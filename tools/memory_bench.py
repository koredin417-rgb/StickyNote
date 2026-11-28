"""What memory a session holds, and whether it grows. Five notes; then one cycle of what the user
does most (the rail hides and shows, Settings in and out, the list, the calendar opened, expanded and
closed, a note folded and unfolded, a new note closed), three times over. After each step: the
process's private bytes, its working set, the Tk pictures and windows alive, and Python's own
allocated bytes. A cycle that leaves more than the one before is a leak. Scratch data folder
(never %APPDATA%).

    .\\StickyNote\\runtime\\python.exe tools\\hidden_tests.py --script tools\\memory_bench.py [out.json]
"""
import ctypes
import gc
import json
import sys
import tempfile
import time
import tracemalloc
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "StickyNote" / "app"))

import winapi  # noqa: E402

winapi.set_dpi_aware()
winapi.set_app_id("KMH.StickyNote.MemoryBench")

from app import App  # noqa: E402

MB = 1024 * 1024


class _Counters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]


def _process():
    c = _Counters()
    c.cb = ctypes.sizeof(c)
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.K32GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD)
    k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return c.PrivateUsage, c.WorkingSetSize


def main(out_path=None):
    tracemalloc.start()
    app = App(Path(tempfile.mkdtemp(prefix="sticky-mem-")))
    app.prefs.tips_seen = list(getattr(sys.modules["store"], "TIPS", ()))
    app.prefs.tour_done = True
    root = app.root

    def pump(seconds=0.3):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            root.update()
            time.sleep(0.004)

    def settle(extra=0.3):
        end = time.perf_counter() + 4
        while time.perf_counter() < end and (app.motion.busy() or app.clock.busy):
            root.update()
            time.sleep(0.004)
        pump(extra)

    rows = []

    def mark(label):
        gc.collect()
        settle(0.1)
        private, ws = _process()
        rows.append({"step": label, "private_mb": round(private / MB, 2), "working_set_mb": round(ws / MB, 2),
                     "tk_images": len(root.tk.call("image", "names")),
                     "toplevels": sum(1 for w in root.winfo_children() if w.winfo_class() == "Toplevel")
                     + len(app.windows),
                     "py_mb": round(tracemalloc.get_traced_memory()[0] / MB, 2)})

    settle(1.5)
    last = next(iter(app.windows.values()))
    for _ in range(4):
        last = app.new_window(from_window=last)
        settle(0.4)
    mark("start, 5 notes")
    nw = next(iter(app.windows.values()))
    for cycle in range(1, 4):
        for _ in range(3):
            nw.rail_calm._swap(True)
            settle(0.2)
            nw.rail_calm._swap(False)
            settle(0.2)
        mark(f"c{cycle} rail x3")
        nw.show_settings()
        settle(0.4)
        nw.go_back()
        settle(0.3)
        mark(f"c{cycle} settings")
        nw.show_list()
        settle(0.4)
        nw.go_back()
        settle(0.3)
        mark(f"c{cycle} list")
        nw.toggle_calendar()
        settle(0.6)
        if nw.calendar is not None:
            nw.calendar.toggle_expand()
            settle(0.8)
            nw.calendar.toggle_expand()
            settle(0.8)
        nw.toggle_calendar()
        settle(0.6)
        mark(f"c{cycle} calendar")
        nw.toggle_collapse()
        settle(0.5)
        nw.toggle_collapse()
        settle(0.5)
        mark(f"c{cycle} fold")
        extra = app.new_window(from_window=nw)
        settle(0.5)
        extra.close()
        settle(0.8)
        mark(f"c{cycle} new+close")
    snap = tracemalloc.take_snapshot()
    top = [{"where": str(s.traceback[0]), "kb": round(s.size / 1024, 1), "count": s.count}
           for s in snap.statistics("lineno")[:15]]
    out = {"rows": rows, "py_top": top}
    for r in rows:
        print(f"{r['step']:<18} private {r['private_mb']:>7} MB  ws {r['working_set_mb']:>7} MB  "
              f"tk images {r['tk_images']:>4}  toplevels {r['toplevels']:>3}  python {r['py_mb']:>6} MB")
    print("python top lines:")
    for t in top:
        print(f"  {t['kb']:>8} KB  {t['count']:>6}  {t['where']}")
    if out_path:
        Path(out_path).write_text(json.dumps(out, indent=1), encoding="utf-8")
    app.root.destroy()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
