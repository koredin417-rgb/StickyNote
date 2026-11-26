"""Phase 6: what an idle app costs. Counts the timer callbacks Tk runs in 10 s of idle with 5 notes
(each is a wakeup of the process), times a save with nothing changed, and reports the biggest
picture the taskbar preview allocates. Scratch data folder (never %APPDATA%).

    .\\StickyNote\\runtime\\python.exe tools\\idle_bench.py [out.json]
"""
import json
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "StickyNote" / "app"))

import winapi  # noqa: E402

winapi.set_dpi_aware()
winapi.set_app_id("KMH.StickyNote.IdleBench")
from PIL import Image  # noqa: E402

fired = []
_after, _after_idle = tk.Misc.after, tk.Misc.after_idle


def _counted(fn):
    def run(*a):
        fired.append((time.perf_counter(), getattr(fn, "__name__", "?")))
        return fn(*a)
    return run


tk.Misc.after = lambda self, ms, func=None, *args: (_after(self, ms, _counted(func), *args) if func is not None
                                                    else _after(self, ms))
tk.Misc.after_idle = lambda self, func, *args: _after_idle(self, _counted(func), *args)

from app import App  # noqa: E402


def main():
    app = App(Path(tempfile.mkdtemp(prefix="sticky-idle-")))
    root = app.root

    def pump(seconds):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            root.update()
            time.sleep(0.005)
    pump(1.5)
    last = next(iter(app.windows.values()))
    last.close_hints()
    for _ in range(4):
        last = app.new_window(from_window=last)
        pump(0.6)
    pump(4.0)                               # settled (and the idle work of the clock done once)
    fired.clear()
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 10:
        root.tk.dooneevent(0)               # (as mainloop: waits for the next event)
    names = {}
    for _t, n in fired:
        names[n] = names.get(n, 0) + 1
    out = {"idle_wakeups_10s": len(fired), "by_callback": names}
    app.save_now()
    ts = []
    for _ in range(20):
        t = time.perf_counter()
        app.save_now()
        ts.append((time.perf_counter() - t) * 1000)
    out["save_no_change_ms"] = round(sorted(ts)[10], 3)
    sizes = []
    real_new = Image.new
    Image.new = lambda mode, size, *a, **k: (sizes.append(tuple(size)), real_new(mode, size, *a, **k))[1]
    real_send = winapi.set_iconic_thumbnail
    winapi.set_iconic_thumbnail = lambda win, pic: 0
    try:
        app._send_thumbnail((240, 160))
    finally:
        Image.new, winapi.set_iconic_thumbnail = real_new, real_send
    big = max(sizes, key=lambda s: s[0] * s[1]) if sizes else (0, 0)
    out["thumbnail_biggest_image"] = list(big)
    out["thumbnail_biggest_mb"] = round(big[0] * big[1] * 4 / 1024 / 1024, 2)
    app.quit()
    return out


if __name__ == "__main__":
    result = main()
    text = json.dumps(result, indent=1)
    print(text)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding="utf-8")
