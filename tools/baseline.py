"""Drive Sticky Note through fixed scenarios and record perf numbers.

    $env:STICKY_PERF='1'; .\\StickyNote\\runtime\\python.exe tools\\baseline.py <label>

Runs on a scratch data folder under %TEMP% (never %APPDATA%\\StickyNote) and the real
monitors. Writes docs/perf/<label>.json and prints one summary line per scenario.
"""
from __future__ import annotations

import gc
import json
import shutil
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import winapi

winapi.set_dpi_aware()
winapi.set_app_id("KMH.StickyNote.Baseline")

import perf  # noqa: E402
from app import App  # noqa: E402
from store import Note  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MB = 1024 * 1024


class Driver:
    def __init__(self, folder: Path):
        self.app = App(folder)
        self.root = self.app.root
        self.results: dict = {}

    # ---- waiting -----------------------------------------------------------------------
    def pump(self, seconds: float, until=None) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            if until is not None and until():
                return
            self.root.update()
            time.sleep(0.004)

    def settle(self) -> None:
        """Until nothing glides, then 300 ms more (fades, saves)."""
        self.pump(5.0, until=lambda: not self.app.motion.busy())
        self.pump(0.3)

    def first(self):
        return next(iter(self.app.windows.values()))

    # ---- one scenario -------------------------------------------------------------------
    def scenario(self, name: str, fn) -> None:
        self.settle()
        gc.collect()
        perf.perf.reset()
        before = perf.perf.sample()
        t0 = time.perf_counter()
        extra = fn() or {}
        self.settle()
        wall = (time.perf_counter() - t0) * 1000
        gc.collect()
        self.results[name] = {"perf": perf.perf.report(), "before": before, "after": perf.perf.sample(),
                              "wall_ms": round(wall, 1), **extra}

    @staticmethod
    def event(x, y):
        return SimpleNamespace(x_root=int(x), y_root=int(y), x=0, y=0, widget=None, state=0)

    # ---- the scenarios ------------------------------------------------------------------
    def open_20(self):
        last = self.first()
        for _ in range(19):
            last = self.app.new_window(from_window=last)
            self.pump(0.05)

    def tidy(self):
        self.app.tidy(self.first(), "keep")

    def group_drag(self):
        nw = self.first()
        lbl = nw.date_label
        x, y = lbl.winfo_rootx() + lbl.winfo_width() // 2, lbl.winfo_rooty() + lbl.winfo_height() // 2
        group = len(self.app.group_windows(nw.pad.id))
        nw._drag_start(self.event(x, y))
        for i in range(1, 61):
            nw._drag_move(self.event(x + 5 * i, y + 2 * i))
            self.pump(0.016)
        nw._drag_end(self.event(x + 300, y + 120))
        return {"group_size": group}

    def resize(self):
        nw = self.first()
        g = nw.grip
        x, y = g.winfo_rootx() + 2, g.winfo_rooty() + 2
        nw._resize_start(self.event(x, y))
        for i in range(1, 61):
            nw._resize_move(self.event(x + 3 * i, y + 3 * i))
            self.pump(0.016)
        nw._drag_end(self.event(x + 180, y + 180))

    def calendar_paging(self):
        nw = self.first()
        if nw.calendar is None:
            nw.toggle_calendar()
        self.pump(0.5)
        for _ in range(6):
            nw.calendar.next_month()
            self.pump(0.35)

    def typing(self):
        nw = self.first()
        nw.body.focus_force()
        text = ("가나다라마바사 abc ☐ 할 일\n" * 20)[:300]
        for ch in text:
            nw.body.insert("insert", ch)
            self.pump(0.016)

    def list_500(self):
        for i in range(500):
            self.app.add_note(Note(header=f"메모 {i}", body="본문 " * 30))
        nw = self.first()
        t0 = time.perf_counter()
        nw.show_list()
        built = 0
        while nw.list_view._build_more():
            built += 1
            self.root.update()
        return {"list_build_ms": round((time.perf_counter() - t0) * 1000, 1), "batches": built}

    def open_close_50(self):
        first = self.first()
        for _ in range(50):
            nw = self.app.new_window(from_window=first)
            self.pump(0.2)
            pid = nw.pad.id
            self.app.close_window(nw)
            del nw
            self.pump(2.0, until=lambda: pid not in self.app.windows)
            self.pump(0.3)
        gc.collect()
        return {"open_windows": len(self.app.windows), "live_windows": perf.perf.live_windows()}

    def run(self) -> dict:
        self.settle()
        for name in ("open_20", "tidy", "group_drag", "resize", "calendar_paging", "typing",
                     "list_500", "open_close_50"):
            self.scenario(name, getattr(self, name))
        return self.results


def summary(results: dict) -> list[str]:
    lines = []
    for name, r in results.items():
        fr = ", ".join(f"{k} p95 {v['p95']:.1f}/max {v['max']:.1f}" for k, v in r["perf"]["frames"].items()) or "-"
        sp = ", ".join(f"{k} p95 {v['p95']:.1f} (n={v['n']})" for k, v in r["perf"]["spans"].items()) or "-"
        dmem = (r["after"]["private_bytes"] - r["before"]["private_bytes"]) / MB
        dgdi = r["after"]["gdi"] - r["before"]["gdi"]
        lines.append(f"{name:16} wall {r['wall_ms']:7.0f} ms | Δmem {dmem:+6.1f} MB | Δgdi {dgdi:+4d} | "
                     f"live {r['after']['live_windows']:3d} | frames: {fr} | spans: {sp}")
    return lines


def main() -> int:
    if not perf.ENABLED:
        print("set STICKY_PERF=1 first", file=sys.stderr)
        return 2
    label = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    folder = Path(tempfile.mkdtemp(prefix=f"sticky-{label}-"))
    try:
        d = Driver(folder)
        results = d.run()
        try:
            d.app.quit()
        except tk.TclError:
            pass
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    out = ROOT / "docs" / "perf" / f"{label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n".join(summary(results)))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
