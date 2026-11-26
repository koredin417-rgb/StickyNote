"""Spike S3: can DwmGetCompositionTimingInfo give the display's refresh period and vblank
times, and how close do Tk after() callbacks land to a vblank-based target with the
1 ms timer held? Compared against a plain 16.67 ms grid.

    .\\StickyNote\\runtime\\python.exe tools\\spikes\\s3_frame_timing.py
"""
from __future__ import annotations

import ctypes
import math
import sys
import time
import tkinter as tk
from ctypes import wintypes

import winapi

winapi.set_dpi_aware()

U32, U64 = ctypes.c_uint32, ctypes.c_uint64


class DWM_TIMING_INFO(ctypes.Structure):
    _pack_ = 1                          # dwmapi.h wraps its structs in pshpack1.h
    _fields_ = [("cbSize", U32), ("rateRefresh_num", U32), ("rateRefresh_den", U32),
                ("qpcRefreshPeriod", U64), ("rateCompose_num", U32), ("rateCompose_den", U32),
                ("qpcVBlank", U64), ("cRefresh", U64), ("cDXRefresh", U32), ("qpcCompose", U64),
                ("cFrame", U64), ("cDXPresent", U32), ("cRefreshFrame", U64), ("cFrameSubmitted", U64),
                ("cDXPresentSubmitted", U32), ("cFrameConfirmed", U64), ("cDXPresentConfirmed", U32),
                ("cRefreshConfirmed", U64), ("cDXRefreshConfirmed", U32), ("cFramesLate", U64),
                ("cFramesOutstanding", U32), ("cFrameDisplayed", U64), ("qpcFrameDisplayed", U64),
                ("cRefreshFrameDisplayed", U64), ("cFrameComplete", U64), ("qpcFrameComplete", U64),
                ("cFramePending", U64), ("qpcFramePending", U64), ("cFramesDisplayed", U64),
                ("cFramesComplete", U64), ("cFramesPending", U64), ("cFramesAvailable", U64),
                ("cFramesDropped", U64), ("cFramesMissed", U64), ("cRefreshNextDisplayed", U64),
                ("cRefreshNextPresented", U64), ("cRefreshesDisplayed", U64), ("cRefreshesPresented", U64),
                ("cRefreshStarted", U64), ("cPixelsReceived", U64), ("cPixelsDrawn", U64),
                ("cBuffersEmpty", U64)]


dwm = ctypes.WinDLL("dwmapi")
dwm.DwmGetCompositionTimingInfo.argtypes = (wintypes.HWND, ctypes.POINTER(DWM_TIMING_INFO))
dwm.DwmGetCompositionTimingInfo.restype = ctypes.c_long
k32 = ctypes.WinDLL("kernel32")
FREQ = ctypes.c_int64()
k32.QueryPerformanceFrequency(ctypes.byref(FREQ))
N = 300


def timing():
    info = DWM_TIMING_INFO()
    info.cbSize = ctypes.sizeof(info)
    hr = dwm.DwmGetCompositionTimingInfo(None, ctypes.byref(info))
    return (hr == 0), info


def stats(values):
    s = sorted(values)
    pick = lambda p: s[min(len(s) - 1, math.ceil(len(s) * p / 100) - 1)]  # noqa: E731
    return f"p50 {pick(50):6.2f}  p95 {pick(95):6.2f}  max {s[-1]:6.2f} ms"


def run(root, next_target):
    """Schedule N callbacks; each aims at next_target(now) and records how late it ran (ms)."""
    late, done = [], []

    def step(target):
        now = time.perf_counter()
        late.append((now - target) * 1000)
        if len(late) >= N:
            done.append(True)
            return
        arm()

    def arm():
        now = time.perf_counter()
        target = next_target(now)
        root.after(max(1, round((target - now) * 1000)), step, target)

    arm()
    while not done:
        root.update()
        time.sleep(0.0005)
    return late


def main() -> int:
    ok, info = timing()
    print(f"DwmGetCompositionTimingInfo: {'OK' if ok else 'FAILED'} (cbSize {ctypes.sizeof(info)})")
    qpc = ctypes.c_int64()
    k32.QueryPerformanceCounter(ctypes.byref(qpc))
    offset = time.perf_counter() - qpc.value / FREQ.value
    print(f"perf_counter - QPC/freq offset: {offset * 1000:.3f} ms")
    root = tk.Tk()
    root.withdraw()
    winapi.fine_timer(True)
    try:
        if ok and info.qpcRefreshPeriod:
            period = info.qpcRefreshPeriod / FREQ.value
            print(f"refresh period {period * 1000:.3f} ms ({1 / period:.1f} Hz)")

            def vblank_target(now):
                _ok, ti = timing()
                vb = ti.qpcVBlank / FREQ.value + offset
                p = ti.qpcRefreshPeriod / FREQ.value or period
                k = math.ceil((now + 0.004 - vb) / p)          # first vblank at least 4 ms away
                return vb + k * p - 0.002
            print("vblank-2ms targets:", stats(run(root, vblank_target)))
        t0 = time.perf_counter()
        grid = 1 / 60

        def grid_target(now):
            return t0 + math.ceil((now - t0 + 0.001) / grid) * grid
        print("16.67 ms grid:     ", stats(run(root, grid_target)))
    finally:
        winapi.fine_timer(False)
        root.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
