"""Phase 5: what rendering costs. A 500-memo list (scrolled top to bottom), a calendar day pick,
and one keystroke in a 3000-line memo. Runs on a scratch data folder (never %APPDATA%).

    .\\StickyNote\\runtime\\python.exe tools\\render_bench.py [out.json]
"""
import gc
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
winapi.set_app_id("KMH.StickyNote.RenderBench")
from app import App  # noqa: E402
from store import Note  # noqa: E402

MB = 1024 * 1024


def pump(app, seconds, until=None):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        if until is not None and until():
            return
        app.root.update()
        time.sleep(0.002)


def main():
    app = App(Path(tempfile.mkdtemp(prefix="sticky-render-")))
    pump(app, 1.5)
    nw = next(iter(app.windows.values()))
    out = {}

    # ---- the list
    for i in range(500):
        app.add_note(Note(header=f"메모 {i}", body=f"본문 {i} " * 30))
    gc.collect()
    pump(app, 0.5)
    mem0, (gdi0, user0) = winapi.process_memory(), winapi.gui_handles()
    t0 = time.perf_counter()
    nw.show_list()
    app.root.update()
    shown_ms = (time.perf_counter() - t0) * 1000
    lv = nw.list_view
    live, t1 = 0, time.perf_counter()
    for k in range(41):
        lv.area.canvas.yview_moveto(k / 40)
        app.root.update()
        if hasattr(lv, "_build_more"):          # (before Phase 5: cards are made as the list nears its end)
            lv._more_if_near_end()
            app.root.update()
        live = max(live, len(lv.cards))
    scroll_ms = (time.perf_counter() - t1) * 1000
    gc.collect()
    pump(app, 0.3)
    mem1, (gdi1, user1) = winapi.process_memory(), winapi.gui_handles()
    out["list_500"] = {"show_ms": round(shown_ms, 1), "scroll_41_steps_ms": round(scroll_ms, 1),
                       "max_live_cards": live, "user_objects": [user0, user1],
                       "private_mb": round((mem1 - mem0) / MB, 1)}
    nw.show_home()
    pump(app, 0.3)

    # ---- a calendar day pick (mini, then big)
    nw.toggle_calendar()
    pump(app, 1.0, until=lambda: not app.motion.busy())
    pump(app, 0.4)
    cal = nw.calendar
    for view in ("mini", "big"):
        if view == "big":
            cal.click_view("big")
            pump(app, 1.0)
        days = [c[4].isoformat() for c in cal._cells if c[4].month == cal.month[1]]
        ts = []
        for iso in days[:12]:
            t = time.perf_counter()
            cal.pick_day(iso)
            app.root.update()
            ts.append((time.perf_counter() - t) * 1000)
        out[f"calendar_pick_{view}_ms"] = {"p50": round(statistics.median(ts), 1), "max": round(max(ts), 1)}
    nw.close_calendar()
    nw.show_home()
    pump(app, 0.5)

    # ---- one keystroke in a 3000-line memo
    b = nw.body
    lines = "\n".join(("• " if i % 3 == 0 else "☐ " if i % 3 == 1 else "") + f"줄 {i}" for i in range(3000))
    nw._edit(lambda: b.insert("1.0", lines))
    nw._after_edit()
    pump(app, 0.5)
    b.mark_set("insert", "1500.3")
    ts = []
    for _ in range(20):
        t = time.perf_counter()
        b.insert("insert", "가")
        app.root.update()
        ts.append((time.perf_counter() - t) * 1000)
    out["keystroke_3000_lines_ms"] = {"p50": round(statistics.median(ts), 2), "max": round(max(ts), 2)}
    app.quit()
    return out


if __name__ == "__main__":
    result = main()
    text = json.dumps(result, indent=1, ensure_ascii=False)
    print(text)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding="utf-8")
