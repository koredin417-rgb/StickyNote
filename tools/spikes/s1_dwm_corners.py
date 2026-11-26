"""Spike S1: do Windows 11's rounded corners and shadow apply to Tk's borderless
(overrideredirect) windows, opaque and layered (-alpha < 1)?

    .\\StickyNote\\runtime\\python.exe tools\\spikes\\s1_dwm_corners.py

For each method x alpha it shows a yellow 'note' over a grey backdrop, grabs that region
(only this script's own windows), checks a corner pixel (rounded?) and a pixel just below
the note (shadow?), prints the matrix and saves docs/perf/s1-<method>-<alpha>.png.
"""
from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

import winapi

winapi.set_dpi_aware()
from PIL import ImageGrab  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "docs" / "perf"
BACK, NOTE = "#5B6676", "#FFF4A3"
BACK_RGB = (0x5B, 0x66, 0x76)
W, H, PAD = 220, 160, 40

dwm = ctypes.WinDLL("dwmapi")
dwm.DwmSetWindowAttribute.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
dwm.DwmExtendFrameIntoClientArea.argtypes = (wintypes.HWND, ctypes.c_void_p)
user32 = ctypes.WinDLL("user32")
user32.GetClassLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
user32.GetClassLongPtrW.restype = ctypes.c_size_t
user32.SetClassLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_size_t)
user32.SetClassLongPtrW.restype = ctypes.c_size_t
DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
GCL_STYLE, CS_DROPSHADOW = -26, 0x00020000


class MARGINS(ctypes.Structure):
    _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]


def lum(rgb):
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def cell(root, method, alpha, x, y):
    back = tk.Toplevel(root, bg=BACK)
    back.overrideredirect(True)
    back.attributes("-topmost", True)
    back.geometry(f"{W + 2 * PAD}x{H + 2 * PAD}+{x}+{y}")
    note = tk.Toplevel(root, bg=NOTE)
    note.overrideredirect(True)
    note.attributes("-topmost", True)
    note.geometry(f"{W}x{H}+{x + PAD}+{y + PAD}")
    if alpha < 1:
        note.attributes("-alpha", alpha)
    root.update()
    hwnd = winapi.hwnd_of(note)
    pref = ctypes.c_int(DWMWCP_ROUND)
    hr = dwm.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref), 4)
    extra = ""
    if method == "extend":
        m = MARGINS(1, 1, 1, 1)
        extra = f" extend_hr={dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m)) & 0xFFFFFFFF:#x}"
    elif method == "dropshadow":
        style = user32.GetClassLongPtrW(hwnd, GCL_STYLE)
        user32.SetClassLongPtrW(hwnd, GCL_STYLE, style | CS_DROPSHADOW)
        note.withdraw()
        root.update()
        note.deiconify()                    # the class shadow is drawn when the window is shown
        note.overrideredirect(True)
        note.geometry(f"{W}x{H}+{x + PAD}+{y + PAD}")
    root.update()
    note.lift()
    root.after(600)
    root.update()
    nx, ny = note.winfo_rootx(), note.winfo_rooty()
    img = ImageGrab.grab(bbox=(nx - PAD, ny - PAD, nx + W + PAD, ny + H + PAD), all_screens=True).convert("RGB")
    corner = img.getpixel((PAD + 1, PAD + 1))
    below = img.getpixel((PAD + W // 2, PAD + H + 6))
    rounded = all(abs(a - b) <= 10 for a, b in zip(corner, BACK_RGB))
    shadow = lum(BACK_RGB) - lum(below) > 8
    name = f"s1-{method}-{'layered' if alpha < 1 else 'opaque'}.png"
    img.save(OUT / name)
    back.destroy()
    note.destroy()
    root.update()
    return rounded, shadow, f"corner_hr={hr & 0xFFFFFFFF:#x}{extra} corner_px={corner} below_px={below}"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Windows build {sys.getwindowsversion().build}")
    root = tk.Tk()
    root.withdraw()
    rows = []
    for method in ("plain", "extend", "dropshadow"):          # dropshadow last: it changes the window class
        for alpha in (1.0, 0.92):
            r, s, info = cell(root, method, alpha, 200, 200)
            rows.append((method, alpha, r, s))
            print(f"{method:10} alpha={alpha:<4} rounded={r!s:5} shadow={s!s:5}  {info}")
    root.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
