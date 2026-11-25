"""Spike S2: can several Tk toplevels be moved in one BeginDeferWindowPos/EndDeferWindowPos
batch while Tk's own geometry bookkeeping (winfo_rootx/rooty, <Configure>) stays right?

    .\\StickyNote\\runtime\\python.exe tools\\spikes\\s2_defer_window_pos.py
"""
from __future__ import annotations

import ctypes
import sys
import time
import tkinter as tk
from ctypes import wintypes

import winapi

winapi.set_dpi_aware()

user32 = ctypes.WinDLL("user32")
user32.BeginDeferWindowPos.argtypes = (ctypes.c_int,)
user32.BeginDeferWindowPos.restype = wintypes.HANDLE
user32.DeferWindowPos.argtypes = (wintypes.HANDLE, wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT)
user32.DeferWindowPos.restype = wintypes.HANDLE
user32.EndDeferWindowPos.argtypes = (wintypes.HANDLE,)
user32.EndDeferWindowPos.restype = wintypes.BOOL
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010
FLAGS = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE


def batch_move(wins, pos):
    h = user32.BeginDeferWindowPos(len(wins))
    for w, (x, y) in zip(wins, pos):
        h = user32.DeferWindowPos(h, winapi.hwnd_of(w), None, x, y, 0, 0, FLAGS)
        if not h:
            return False
    return bool(user32.EndDeferWindowPos(h))


def main() -> int:
    root = tk.Tk()
    root.withdraw()
    wins, configs = [], []
    for i in range(4):
        t = tk.Toplevel(root, bg=("#FFF4A3", "#CFE6FF", "#CDEFC4", "#FFD6E7")[i])
        t.overrideredirect(True)
        t.geometry(f"160x120+{200 + i * 180}+300")
        n = [0]
        t.bind("<Configure>", lambda e, n=n: n.__setitem__(0, n[0] + 1))
        wins.append(t)
        configs.append(n)
    root.update()
    ok = True

    # 1. one batch of +37/+23
    start = [(w.winfo_rootx(), w.winfo_rooty()) for w in wins]
    for n in configs:
        n[0] = 0
    want = [(x + 37, y + 23) for x, y in start]
    r = batch_move(wins, want)
    root.update_idletasks()
    root.update()
    got = [(w.winfo_rootx(), w.winfo_rooty()) for w in wins]
    pos_ok = got == want
    cfg_ok = all(n[0] >= 1 for n in configs)
    print(f"single batch: EndDeferWindowPos={r} positions {'PASS' if pos_ok else 'FAIL'} "
          f"configure {'PASS' if cfg_ok else 'FAIL'} ({[n[0] for n in configs]})")
    ok &= r and pos_ok and cfg_ok

    # 2. a 2 s glide of 120 batches, 16 ms apart
    drift, base = 0, want
    for k in range(1, 121):
        target = [(x + 2 * k, y + (k % 7)) for x, y in base]
        batch_move(wins, target)
        root.update()
        drift = max(drift, max(abs(a - c) + abs(b - d) for (a, b), (c, d) in
                               zip(target, [(w.winfo_rootx(), w.winfo_rooty()) for w in wins])))
        time.sleep(0.016)
    print(f"120-frame glide: max drift {drift} px {'PASS' if drift == 0 else 'FAIL'}")
    ok &= drift == 0

    # 3. across a monitor boundary, if there is a second monitor
    mons = winapi.monitors()
    if len(mons) > 1:
        (mx0, my0, mx1, my1), _work = mons[1]
        target = [(mx0 + 50 + i * 170, my0 + 80) for i in range(4)]
        batch_move(wins, target)
        root.update()
        got = [(w.winfo_rootx(), w.winfo_rooty()) for w in wins]
        across = got == target
        print(f"second monitor ({mx0},{my0})-({mx1},{my1}): positions {'PASS' if across else 'FAIL'} got={got}")
        ok &= across
    else:
        print("second monitor: SKIPPED (one monitor)")
    root.destroy()
    print("VERDICT:", "batch OK" if ok else "keep geometry()")
    return 0


if __name__ == "__main__":
    sys.exit(main())
