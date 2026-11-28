"""Backlog item 5 (2026-11-28): the first start, and the tour again from Settings.

The screen the first note is on dims (one window: black at TOUR_DIM, topmost); a hole is cut in it
round what is being shown (winapi.clip_box(holes=...), as the page change does), so that part shows
and takes clicks. A small card beside the hole says what it is, with 다음 / 건너뛰기 (Enter, →, Esc).

New users: the language first (a card: 한국어 / English), then a welcome memo whose one to-do line
("시작합니다. 박스를 체크해 주세요") starts the tour when ticked, then five stops. People updating
never get it; nobody gets it twice (prefs.tour_done). Settings > 일반 > 둘러보기 다시 보기: the five
stops again (no language, no memo)."""
from __future__ import annotations

import tkinter as tk

import anim
import texts
import winapi
from texts import tr
from ui_common import UI_BOLD, UI_FONT, FlatButton, TODO, animate, readable, stop_animation, TEXT_CONTRAST

TOUR_DIM = 0.55                 # how dark the rest of the screen goes
TOUR_HOLE_PAD = 6               # the hole reaches this far round what it shows (px at 100 %)
TOUR_MOVE_MS = anim.BASE        # the hole eases to the next stop this fast
TOUR_START_MS = 400             # after the first start, the dim comes this late (the note has shown)
# the five stops: (what to show, what the card says)
STOPS = (
    ("home", "tour_step1"),
    ("bar", "tour_step2"),
    ("rail", "tour_step3"),
    ("btn_color", "tour_step4"),
    ("btn_more", "tour_step5"),
)


class FirstStart:
    def __init__(self, app, replay=False):
        self.app = app
        self.step = None                # "language", "welcome", 1..5
        self.hole = None                # the hole now (x0, y0, x1, y1), the dim's pixels
        nw = self.nw()
        x0, y0, x1, y1 = app.area_of(_box(nw.win))
        self.area = (x0, y0, x1 - x0, y1 - y0)
        dim = self.dim = tk.Toplevel(app.root)
        dim.withdraw()
        dim.overrideredirect(True)
        dim.configure(bg="#000000")
        dim.geometry(f"{x1 - x0}x{y1 - y0}+{x0}+{y0}")
        dim.attributes("-alpha", 0.0)
        dim.attributes("-topmost", True)
        dim.bind("<ButtonRelease-1>", lambda e: self.skip())        # a click on the dim: skip
        dim.deiconify()
        animate(dim, "alpha", anim.LONG, lambda k: dim.attributes("-alpha", TOUR_DIM * k), kind="fade")
        self.card = None
        if replay:
            self._go(1)
        else:
            self._language()

    # -- helpers
    def nw(self):
        wins = [w for w in self.app.windows.values() if not w._closing]
        return wins[0] if wins else None

    def target_box(self, i):
        """Stop ``i``'s box in the dim's pixels, padded."""
        nw = self.nw()
        w = getattr(nw, STOPS[i - 1][0])
        x0, y0, x1, y1 = _box(w)
        p = self.app.px(TOUR_HOLE_PAD)
        ax, ay = self.area[0], self.area[1]
        return (x0 - ax - p, y0 - ay - p, x1 - ax + p, y1 - ay + p)

    def _set_hole(self, box):
        self.hole = tuple(round(v) for v in box) if box else None
        w, h = self.area[2], self.area[3]
        winapi.clip_box(self.dim, w, h, 0, redraw=True, holes=[self.hole] if self.hole else ())

    def _move_hole(self, box):
        stop_animation(self.dim, "hole")
        start = self.hole
        if start is None:
            self._set_hole(box)
            return
        animate(self.dim, "hole", TOUR_MOVE_MS,
                lambda k: self._set_hole([a + (b - a) * k for a, b in zip(start, box)]), kind="move")
        self.hole = tuple(round(v) for v in box)        # (where it is going: the tests, the next card)

    def _card(self, lines, buttons, near=None):
        """The card: ``lines`` (the first bold), ``buttons`` [(label, command, danger)], beside ``near``
        (a box in the dim's pixels) or in the middle of the screen."""
        if self.card is not None:
            self.card.destroy()
        app, px = self.app, self.app.px
        c = app.theme_colors()
        top = self.card = tk.Toplevel(app.root)
        top.withdraw()
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=c.border)
        body = tk.Frame(top, bg=c.bg, bd=0)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        for i, line in enumerate(lines):
            tk.Label(body, text=line, bg=c.bg, fg=c.fg if i == 0 else readable(top, c.muted, c.bg, TEXT_CONTRAST),
                     font=(UI_BOLD, 10, "bold") if i == 0 else (UI_FONT, 9), anchor="w", justify="left",
                     wraplength=px(240)).pack(fill="x", padx=px(14), pady=(px(12) if i == 0 else px(2), 0))
        row = tk.Frame(body, bg=c.bg, bd=0)
        row.pack(fill="x", padx=px(10), pady=(px(10), px(10)))
        for label, command, danger in buttons:
            b = FlatButton(row, label, command, danger=danger)
            b.recolor(c)
            b.pack(side="right", padx=(px(4), 0))
        top.bind("<Escape>", lambda e: self.skip())
        top.bind("<Return>", lambda e: self.next())
        top.bind("<Right>", lambda e: self.next())
        top.update_idletasks()
        w, h = top.winfo_reqwidth(), top.winfo_reqheight()
        ax, ay, aw, ah = self.area
        if near is None:
            x, y = ax + (aw - w) // 2, ay + (ah - h) // 2
        else:
            gap = px(12)
            x0, y0, x1, y1 = near
            if ax + x1 + gap + w <= ax + aw:                 # right of the hole, else left, else below
                x, y = ax + x1 + gap, ay + y0
            elif x0 - gap - w >= 0:
                x, y = ax + x0 - gap - w, ay + y0
            else:
                x, y = ax + x0, ay + y1 + gap
            x = min(max(x, ax), ax + aw - w)
            y = min(max(y, ay), ay + ah - h)
        top.geometry(f"+{x}+{y}")
        top.deiconify()
        top.lift()
        top.focus_force()

    # -- the steps
    def _language(self):
        self.step = "language"
        self._card([tr("tour_language")],
                   [(tr("tour_skip"), self.skip, False)] + [(name, (lambda c=code: self.choose_language(c)), False)
                                                           for code, name in reversed(texts.LANGUAGES)])

    def choose_language(self, code):
        self.app.set_language(code)         # (rebuilds the windows: the tour keeps to the app, not one)
        self._welcome()

    def _welcome(self):
        """The welcome memo: one to-do line; ticking it (NoteWindow.set_done) starts the tour."""
        self.step = "welcome"
        nw = self.nw()
        if nw is None:
            self.finish()
            return
        b = nw.body
        if not b.get("1.0", "end").strip():
            b.insert("1.0", tr("welcome_todo"))
            b.mark_set("insert", "1.0")
            nw.toggle_todo()
            nw.sync_from_widgets()
        self._move_hole(self._padded(_box(nw.win)))
        self._card([tr("tour_welcome")], [(tr("tour_skip"), self.skip, False)], near=self.hole)

    def _padded(self, box):
        p = self.app.px(TOUR_HOLE_PAD)
        ax, ay = self.area[0], self.area[1]
        return (box[0] - ax - p, box[1] - ay - p, box[2] - ax + p, box[3] - ay + p)

    def ticked(self, nw):
        if self.step == "welcome":
            self._go(1)

    def _go(self, i):
        self.step = i
        nw = self.nw()
        if nw is None:
            self.finish()
            return
        if nw.view != "home":
            nw.show_home()
        self._move_hole(self.target_box(i))
        key = STOPS[i - 1][1]
        lines = tr(key).split("\n")
        if key == "tour_step3" and self.app.prefs.rail_hide:
            lines.append(tr("tour_step3_calm"))
        last = i == len(STOPS)
        self._card(lines + [f"{i} / {len(STOPS)}"],
                   [(tr("tour_end" if last else "tour_next"), self.next, False), (tr("tour_skip"), self.skip, False)],
                   near=self.hole)

    def next(self):
        if self.step == "language":
            return
        if self.step == "welcome":
            self._go(1)
        elif isinstance(self.step, int) and self.step < len(STOPS):
            self._go(self.step + 1)
        else:
            self.finish()

    def skip(self):
        self.finish()

    def finish(self):
        """The dim fades out; the note has the keyboard, ready to type. Never again (tour_done)."""
        app = self.app
        app.prefs.tour_done = True
        app.request_save()
        if app.tour is self:
            app.tour = None
        if self.card is not None:
            self.card.destroy()
            self.card = None
        dim = self.dim
        stop_animation(dim, "hole")
        a0 = float(dim.attributes("-alpha"))
        animate(dim, "alpha", anim.LONG, lambda k: dim.attributes("-alpha", a0 * (1 - k)), dim.destroy, kind="fade")
        nw = self.nw()
        if nw is not None:
            try:
                nw.body.focus_force()
            except tk.TclError:
                pass


def _box(w):
    x, y = w.winfo_rootx(), w.winfo_rooty()
    return (x, y, x + w.winfo_width(), y + w.winfo_height())
