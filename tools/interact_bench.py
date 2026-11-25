"""Phase 4: main-thread work per display frame while dragging and resizing with 20 notes.

A fast mouse sends several motion events per display frame. This queues EVENTS_PER_FRAME
B1-Motion events through Tk's real bindings, runs the event loop until they (and anything the
clock owes) are done, and records the time that took: the work one display frame had to do.
Frames whose work goes over the display period are frames the screen misses.

Runs on a scratch data folder (never %APPDATA%\\StickyNote).

    .\\StickyNote\\runtime\\python.exe tools\\interact_bench.py [out.json]
"""
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "StickyNote" / "app"))

import winapi  # noqa: E402

winapi.set_dpi_aware()
winapi.set_app_id("KMH.StickyNote.InteractBench")
from app import App  # noqa: E402

EVENTS_PER_FRAME = 8            # a 500-1000 Hz mouse against a 60-72 Hz display
FRAMES = 60


class Bench:
    def __init__(self):
        self.app = App(Path(tempfile.mkdtemp(prefix="sticky-bench-")))
        self.root = self.app.root
        timing = winapi.composition_timing()
        self.period = timing[1] * 1000 if timing else 1000 / 60

    def pump(self, seconds, until=None):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            if until is not None and until():
                return
            self.root.update()
            time.sleep(0.002)

    def settle(self):
        self.pump(5.0, until=lambda: not self.app.motion.busy())
        self.pump(0.4)

    def open_20(self):
        last = next(iter(self.app.windows.values()))
        last.close_hints()
        for _ in range(19):
            last = self.app.new_window(from_window=last)
            self.pump(0.05)
        self.settle()

    def gesture(self, widget, press_xy, step, alt=False):
        """Press on ``widget``, FRAMES frames of EVENTS_PER_FRAME motions each, release.
        Returns each frame's work in ms."""
        x, y = press_xy
        state = 0x20000 if alt else 0
        widget.event_generate("<ButtonPress-1>", x=1, y=1, rootx=x, rooty=y, state=state)
        self.root.update()
        works = []
        for f in range(1, FRAMES + 1):
            for e in range(EVENTS_PER_FRAME):
                k = (f - 1) * EVENTS_PER_FRAME + e + 1
                dx, dy = step(k)
                widget.event_generate("<B1-Motion>", x=1, y=1, rootx=x + dx, rooty=y + dy, state=state | 0x100,
                                      when="tail")
            t0 = time.perf_counter()
            self.root.update()                      # the events, and whatever they ask the clock for
            work = time.perf_counter() - t0
            clock = self.app.clock
            while (clock._requests or clock._moves) and time.perf_counter() - t0 < 0.1:
                time.sleep(0.0005)                  # (waiting for the frame is not work)
                t1 = time.perf_counter()
                self.root.update()
                work += time.perf_counter() - t1
            works.append(work * 1000)
            rest = self.period / 1000 - (time.perf_counter() - t0)
            if rest > 0:
                time.sleep(rest)
        dx, dy = step(FRAMES * EVENTS_PER_FRAME)
        widget.event_generate("<ButtonRelease-1>", x=1, y=1, rootx=x + dx, rooty=y + dy, state=state | 0x100)
        self.settle()
        return works

    @staticmethod
    def stats(works, period):
        s = sorted(works)
        return {"n": len(s), "p50": round(statistics.median(s), 1), "p95": round(s[int(len(s) * 0.95) - 1], 1),
                "max": round(s[-1], 1), "over_period": sum(1 for w in s if w > period),
                "over_2x": sum(1 for w in s if w > 2 * period)}

    def run(self):
        self.settle()
        self.open_20()
        app = self.app
        out = {"period_ms": round(self.period, 2), "events_per_frame": EVENTS_PER_FRAME}
        nw = next(iter(app.windows.values()))
        out["group_size"] = len(app.group_windows(nw.pad.id))
        row = nw.row
        xy = (row.winfo_rootx() + 60, row.winfo_rooty() + 10)
        out["group_drag"] = self.stats(self.gesture(row, xy, lambda k: (k // 2, k // 4)), self.period)
        g = nw.grip                         # one note (Alt): the live plan pushes the notes in line
        xy = (g.winfo_rootx() + 4, g.winfo_rooty() + 4)
        out["solo_resize"] = self.stats(self.gesture(g, xy, lambda k: (k // 4, k // 5), alt=True), self.period)
        xy = (g.winfo_rootx() + 4, g.winfo_rooty() + 4)   # the linked group: their covers resize
        out["group_resize"] = self.stats(self.gesture(g, xy, lambda k: (-(k // 4), -(k // 5))), self.period)
        app.quit()
        return out


if __name__ == "__main__":
    result = Bench().run()
    text = json.dumps(result, indent=1)
    print(text)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding="utf-8")
