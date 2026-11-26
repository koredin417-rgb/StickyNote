"""Phase 3: capture the C look for a side-by-side check with the mockups.

Opens the app on a scratch data folder (never %APPDATA%\\StickyNote), sets up a few notes and
the calendar, captures each window with PrintWindow and pastes them onto one neutral "desktop"
per state. Writes PNGs to docs/perf/look-*.png (git-ignored), or to the folder given.

    .\\StickyNote\\runtime\\python.exe tools\\look_capture.py [out folder] [ko|en]
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "StickyNote" / "app"))

import winapi  # noqa: E402

winapi.set_dpi_aware()
winapi.set_app_id("KMH.StickyNote.LookCapture")
from PIL import Image  # noqa: E402

from app import App  # noqa: E402
from ui_common import MIN_H, MIN_W  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "perf"
LANG = sys.argv[2] if len(sys.argv) > 2 else None
OUT.mkdir(parents=True, exist_ok=True)
DATA = Path(tempfile.mkdtemp(prefix="sticky-look-"))
app = App(DATA)
root = app.root
log: list[str] = []
if LANG:
    app.set_language(LANG)


def fill(nw, header, body, color=None):
    nw.set_style("header")
    nw.header_var.set(header)
    nw.body.delete("1.0", "end")
    nw.body.insert("1.0", body)
    nw.sync_from_widgets()
    if color:
        nw.set_color(color)


def snap(tag, only=None):
    """Every shown window (or ``only``) pasted onto one picture at its screen place."""
    shots = []
    tops = only if only is not None else [root] + list(root.winfo_children())
    for t in tops:
        try:
            if not hasattr(t, "wm_state") or t.wm_state() != "normal":
                continue
            r = winapi.snapshot(t)
        except Exception as e:                  # (a window going away meanwhile)
            log.append(f"snap: {e!r}")
            continue
        if not r:
            continue
        w, h, raw = r
        if w < 40 or h < 30 or abs(t.winfo_rootx()) > 20000 or abs(t.winfo_rooty()) > 20000:
            continue
        img = Image.frombuffer("RGB", (w, h), raw, "raw", "BGRX", 0, 1).copy()
        shots.append((t.winfo_rootx(), t.winfo_rooty(), img))
    if not shots:
        log.append(f"{tag}: nothing to capture")
        return
    x0, y0 = min(s[0] for s in shots), min(s[1] for s in shots)
    x1, y1 = max(s[0] + s[2].width for s in shots), max(s[1] + s[2].height for s in shots)
    desk = Image.new("RGB", (x1 - x0 + 48, y1 - y0 + 48), (92, 104, 120))
    for x, y, img in sorted(shots, key=lambda s: s[2].width * s[2].height, reverse=True):
        desk.paste(img, (x - x0 + 24, y - y0 + 24))
    desk.save(OUT / f"look-{tag}.png")
    log.append(f"{tag}: {len(shots)} windows")


def steps():
    a = next(iter(app.windows.values()))
    a.close_hints()
    fill(a, "이번 주 할 일" if app.prefs.language != "en" else "This week",
         "• 디자인 시안 정리\n☐ 회의록 보내기\n☑ 장보기\n☐ 치과 예약 (목 3시)")
    yield 400
    b = app.new_window(from_window=a)
    yield 700
    fill(b, "아이디어" if app.prefs.language != "en" else "Ideas", "프레임 타이머 하나로 정리", "#CFE6FF")
    b.win.focus_force()
    yield 500
    snap("notes")
    a.toggle_calendar()
    yield 900
    a.win.focus_force()
    yield 300
    snap("calendar")
    a.body.focus_force()                        # typing: the format buttons in the rail
    yield 300
    snap("typing", only=[a.win])
    b.show_list()
    yield 500
    snap("list", only=[b.win])
    b.go_back()
    b.toggle_collapse(instant=True)
    yield 600
    snap("folded")
    a.calendar.click_view("big")
    yield 900
    snap("calendar-big")
    a.close_calendar()
    yield 600
    a.set_size(app.px(MIN_W), app.px(MIN_H))   # the smallest note, typing: the rail gives way to ⋯
    yield 700
    a.body.focus_force()
    yield 300
    snap("small", only=[a.win])


def run(gen):
    try:
        delay = next(gen)
    except StopIteration:
        (OUT / "look-log.txt").write_text("\n".join(log), encoding="utf-8")
        app.quit()
        return
    except Exception as e:
        log.append(f"step: {e!r}")
        (OUT / "look-log.txt").write_text("\n".join(log), encoding="utf-8")
        app.quit()
        return
    root.after(delay, lambda: run(gen))


root.after(1200, lambda: run(steps()))
root.after(30000, root.destroy)
root.mainloop()
