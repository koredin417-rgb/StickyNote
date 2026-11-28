"""The note's sub pages: memo list (+ memo preview), settings, bin."""
from __future__ import annotations

import calendar as _calendar
import colorsys
from collections import OrderedDict
import os
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
import traceback
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import NamedTuple
from tkinter import colorchooser, filedialog, messagebox

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageGrab, ImageTk

import holidays
import texts
import perf
import version
import winapi
from icon import draw_icon
from store import (BIN_DAY_CHOICES, CURSOR_COLORS, CUSTOM_COLORS, EMPTY_TITLE, INLINE, LIST_SORTS, MARK_KINDS,
                   PIN_LIMIT_MAX, SNAP_GAPS, STYLES, TIDY_ORDERS, Note, NoteStore, Pad, Prefs)
from texts import tr
from ui_common import *  # noqa: F401,F403  (the parts before this one)


# --------------------------------------------------------------------------- list page
CARD_GUESS, HEAD_GUESS = 96, 28    # a row's height (px at 100 %) until it is made and measured
KEEP_SCREENS = 1                 # rows this many screens above and below the view are made too ...
BUILD_PER_PASS = 2               # ... a couple at a time (the rows in view at once): a far jump stays quick
BUILD_AGAIN_MS = 15              # ... the next couple this much later
DROP_PER_PASS, DROP_AGAIN_MS = 3, 40   # rows let go of are hidden at once, destroyed a few at a time later


class _Row:
    """One row of the memo list: a part head, a memo card or the empty page. Only the rows near
    the view have a widget; the others are just their height (measured once made, else guessed)."""
    __slots__ = ("kind", "key", "make", "y", "height", "widget")

    def __init__(self, kind, key, make, height):
        self.kind, self.key, self.make, self.height = kind, key, make, height
        self.y, self.widget = 0, None
SEARCH_DELAY_MS = 120            # the search runs once the typing pauses this long


# ---- list cards (Phase 9, 2026-11-28): title first, paper lift, the current memo in its own tone
CARD_LEVELS = CAL_HOVER_STEPS    # a card lifts through this many colours (0 rest .. 5 lit), like a calendar day
CARD_LIFT_IN_MS, CARD_LIFT_OUT_MS = CAL_HOVER_IN_MS, CAL_HOVER_OUT_MS
CARD_RISE_AT = 3                 # ... and rises 1 px at this level (a 1 px step has no in-between)
SHADOW_REST = (0.10, 0.06, 0.03)         # the strips under a card: the page toward black (paper lift)
SHADOW_LIT = (0.14, 0.10, 0.06, 0.03)    # ... a step deeper under a lifted card
SHADOW_DARK = 3.0                # ... these many times as strong on a dark page
CARD_MIN_TINT = 1.12             # a lifted card differs from its rest colour at least this much (pale colours too)
CARD_ON_PAGE = (0.45, 0.08)      # a card the page's own colour is mixed this far toward white (light, dark page)
CARD_EDGE_CONTRAST = 2.2         # the current memo's edge on its card
CARD_GAP = 4                     # px at 100 % between one card's shadow and the next card


class CardColors(NamedTuple):
    rest: str               # the card at rest
    lit: str                # ... under the mouse or picked with the arrow keys
    fg: str
    muted: str              # dates and the done to-dos (readable on ``lit`` too)
    edge: str               # the current memo's edge: a mid tone of its own colour
    label: str              # "현재 메모": that colour's readable dark (or light) shade
    rest_strips: tuple      # the four 1 px strips under the card (the last one is the page)
    lit_strips: tuple
    ramp: list              # level -> (card colour, strips), 0 .. CARD_LEVELS


CARD_HOVER = "D"                 # a card under the mouse: "A" a half-step tint, "D" the same fill and a ring
CARD_ICON_PAD = 4                # a card's pin and bin: room round each (px at 100 %) ...
CARD_ICON_GAP = 6                # ... and between them (the user: "too close together")
CARD_LIT_K = 0.5                 # a card under the mouse / picked: this much of the full step (option A)
_CARD_COLORS: dict = {}          # (memo colour, page colour) -> CardColors: cards are built while scrolling


def card_colors(widget, note_color, page_bg) -> CardColors:
    """A list card's colours (cached: the same few colour pairs come back at every scroll)."""
    key = (str(note_color).upper(), str(page_bg).upper())
    k = _CARD_COLORS.get(key)
    if k is None:
        if len(_CARD_COLORS) > 256:
            _CARD_COLORS.clear()
        k = _CARD_COLORS[key] = _card_colors(widget, note_color, page_bg)
    return k


def _card_colors(widget, note_color, page_bg) -> CardColors:
    """A list card's colours, worked out once: all from the memo's own colour and the page."""
    c = Colors.of(widget, note_color)
    rest = c.bg
    if str(rest).upper() == str(page_bg).upper():           # it would vanish into the page
        rest = _mix(widget, rest, "#FFFFFF", CARD_ON_PAGE[1] if c.dark else CARD_ON_PAGE[0])
    lit, steps = shade(widget, rest, 1), 1
    while contrast(widget, rest, lit) < CARD_MIN_TINT and steps < 8:
        steps += 1
        lit = shade(widget, rest, steps)
    lit = rest if CARD_HOVER == "D" else _mix(widget, rest, lit, CARD_LIT_K)   # (A: half the step; D: no tint)
    base = c.color if c.tinted else shade(widget, rest, 4)
    edge = readable(widget, base, rest, CARD_EDGE_CONTRAST)
    label = readable(widget, edge, lit, TEXT_CONTRAST)
    muted = readable(widget, c.muted, lit, TEXT_CONTRAST)
    k = SHADOW_DARK if luminance(widget, page_bg) < 0.18 else 1.0
    rest_strips = tuple(_mix(widget, page_bg, "#000000", min(1.0, w * k)) for w in SHADOW_REST) + (page_bg,)
    lit_strips = tuple(_mix(widget, page_bg, "#000000", min(1.0, w * k)) for w in SHADOW_LIT)
    n = CARD_LEVELS
    ramp = [(rest, rest_strips)]
    for i in range(1, n):
        ramp.append((_mix(widget, rest, lit, i / n),
                     tuple(_mix(widget, a, b, i / n) for a, b in zip(rest_strips, lit_strips))))
    ramp.append((lit, lit_strips))
    return CardColors(rest, lit, c.fg, muted, edge, label, rest_strips, lit_strips, ramp)


class CardLift:
    """A list card's lift, level 0 (rest) .. CARD_LEVELS (lit): its colour deepens one step, the
    shadow deepens to four strips, and at CARD_RISE_AT it rises 1 px (a spacer moves from above
    the card to below it, so the row's height never changes). The pin and trash show while lifted."""

    def __init__(self, app, card, colors, top_gap, bottom_gap, strips, icons, edge=None, title=None):
        self.app, self.card, self.colors = app, card, colors
        self.top_gap, self.bottom_gap, self.strips = top_gap, bottom_gap, strips
        self.icons = icons                  # [(label, glyph, colour, colour under the mouse, always shown)]
        self.edge, self.title = edge, title
        self.level, self.risen, self.icons_shown = 0, False, None
        self.pointed = set()                # the icons under the mouse (it may reach one before the lift)
        self._painted = None                # the widgets the card's colour goes on (found at first use)
        self._show_icons(False)
        for label, *_ in icons:
            label.bind("<Enter>", lambda e, lb=label: self.point(lb, True), add="+")
            label.bind("<Leave>", lambda e, lb=label: self.point(lb, False), add="+")

    def point(self, label, on):
        (self.pointed.add if on else self.pointed.discard)(label)
        self._paint_icon(label)

    def _paint_icon(self, label):
        for lb, glyph, color, hover, always in self.icons:
            if lb is not label:
                continue
            if self.icons_shown or always:
                paint_glyph(self.app, lb, glyph, hover if lb in self.pointed else color)
            elif self.app.icons.available:
                lb.configure(image=_blank_icon(self.app))
            else:
                lb.configure(text=" ")

    def _show_icons(self, on):
        if on == self.icons_shown:
            return
        self.icons_shown = on
        for label, *_ in self.icons:
            self._paint_icon(label)

    def _widgets(self):
        if self._painted is None:
            out = []

            def walk(w):
                if w.winfo_class() in ("Frame", "Label") and not getattr(w, "keep_bg", False):
                    out.append(w)
                for ch in w.winfo_children():
                    walk(ch)
            walk(self.card)
            self._painted = out
        return self._painted

    def set(self, level):
        level = max(0, min(CARD_LEVELS, level))
        bg, strips = self.colors.ramp[level]
        try:
            for w in self._widgets():
                w.configure(bg=bg)
            if CARD_HOVER == "D":           # the ring comes in with the lift (the fill stays)
                ring = _mix(self.card, self.colors.rest, self.colors.edge, level / CARD_LEVELS)
                self.card.configure(highlightbackground=ring, highlightcolor=ring)
            for s, color in zip(self.strips, strips):
                s.configure(bg=color)
            rise = level >= CARD_RISE_AT
            if rise != self.risen:
                self.risen = rise
                gap = self.app.px(CARD_GAP)
                if rise:
                    self.top_gap.pack_forget()
                    self.bottom_gap.configure(height=gap + int(self.top_gap.cget("height")))
                else:
                    self.top_gap.pack(fill="x", before=self.card)
                    self.bottom_gap.configure(height=gap)
        except tk.TclError:
            return
        self.level = level
        self._show_icons(level > 0)

    def to(self, target, fade=True):
        """Lift (target CARD_LEVELS) or settle (0), from wherever it is now."""
        target = max(0, min(CARD_LEVELS, target))
        stop_animation(self.card, "lift")
        start = self.level
        if target == start:
            return
        if not fade:
            self.set(target)
            return
        up = target > start
        ms = (CARD_LIFT_IN_MS if up else CARD_LIFT_OUT_MS) * abs(target - start) / CARD_LEVELS

        def step(k):
            level = round(start + (target - start) * k)
            if level != self.level:
                self.set(level)
        animate(self.card, "lift", max(1, round(ms)), step, lambda: self.set(target),
                ease=anim.ease_out if up else anim.ease_in, kind="fade")


def _blank_icon(app):
    """A see-through picture the size of a list icon: a hidden icon keeps its room (one per size)."""
    size = app.px(SMALL_ICON_BOX)
    made = app.__dict__.setdefault("_blank_icons", {})
    if size not in made:
        real = app.icons.photo(GLYPH["trash"], "#000000", size)
        made[size] = tk.PhotoImage(master=app.root, width=real.width(), height=real.height())
    return made[size]


class ListView:
    """Every memo as a card, like the Windows Sticky Notes list."""

    def __init__(self, nw: NoteWindow):
        self.nw, self.app = nw, nw.app
        px = self.app.px
        self.day: str | None = None
        self._order: list[str] = []
        self.frame = tk.Frame(nw.views, bd=0)

        self.search_box = tk.Frame(self.frame, bd=0)
        self.search_box.pack(fill="x", padx=px(10), pady=(px(2), px(6)))
        self.search_icon = tk.Label(self.search_box, bd=0)
        self.search_icon.pack(side="left", padx=(px(6), px(2)))
        self.search = tk.StringVar(nw.win)
        self.search_entry = tk.Entry(self.search_box, textvariable=self.search, bd=0,
                                     relief="flat", highlightthickness=0, font=(UI_FONT, 10))
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=px(4), padx=(0, px(6)))
        self.select_btn = tk.Label(self.search_box, bd=0, cursor="hand2")     # select mode (backlog 4)
        self.select_btn.pack(side="right", padx=(0, px(6)))
        self.select_btn.bind("<ButtonRelease-1>", lambda e: self.toggle_select())
        Tooltip(self.select_btn, tr("list_select"))
        self.selecting, self.ticked, self.checks = False, set(), {}
        self._last_tick = None
        for k in ("a", "Lock-A"):         # select mode: Ctrl+A ticks every memo shown
            self.search_entry.bind(f"<Control-{k}>", lambda e: (self.select_all(), "break")[1] if self.selecting
                                   else None)
        self.search_entry.bind("<Escape>", lambda e: (self.toggle_select(), "break")[1] if self.selecting
                               else None)
        # typing a search: the list is made again once the typing pauses, not at every letter
        self._search_trace = self.search.trace_add(
            "write", lambda *a: self.nw._later("search", SEARCH_DELAY_MS, self.refresh))
        # keyboard: ↑↓ pick a memo card, Enter opens it (the first one if none is picked)
        self.search_entry.bind("<Down>", lambda e: (self.step_pick(1), "break")[1])
        self.search_entry.bind("<Up>", lambda e: (self.step_pick(-1), "break")[1])
        self.search_entry.bind("<Return>", lambda e: (self.open_picked(), "break")[1])
        self._picked: str | None = None     # note id picked with the arrow keys
        self._painters: dict = {}           # note id -> function(lit) repainting its card

        self.filter_row = tk.Frame(self.frame, bd=0)
        self.filter_text = tk.Label(self.filter_row, font=(UI_BOLD, 9, "bold"))
        self.filter_text.pack(side="left")
        self.filter_holiday = tk.Label(self.filter_row, font=(UI_FONT, 9))   # red-day name, if any
        self.filter_clear = FlatButton(self.filter_row, tr("show_all"), self.clear_day)
        self.filter_clear.pack(side="right")

        self.bin_row = tk.Frame(self.frame, bd=0, cursor="hand2")      # the way into the bin page
        self.bin_row.pack(side="bottom", anchor="w", padx=px(10), pady=(px(4), px(6)))   # (not the list's width:
                                                                    # only the icon and its count are the button)
        self.bin_glyph = tk.Label(self.bin_row, bd=0)         # the icon, a red dot on it while memos are in the bin
        self.bin_glyph.pack(side="left", padx=(px(4), px(4)))
        for w in (self.bin_row, self.bin_glyph):
            w.bind("<ButtonRelease-1>", lambda e: self.nw.show_bin())
            w.bind("<Enter>", lambda e: self._bin_hover(True))
            w.bind("<Leave>", lambda e: self._bin_hover(False))
        self.bin_tip = Tooltip(self.bin_glyph, tr("tip_bin_link", days=BIN_DAYS))     # (_bin_badge adds the count)
        self.select_bar = tk.Frame(self.frame, bd=0)     # select mode: in the bin row's place
        self.select_count = tk.Label(self.select_bar, font=(UI_FONT, 9), anchor="w")
        self.select_count.pack(side="left", padx=(px(4), px(8)))
        self.select_trash = FlatButton(self.select_bar, tr("select_trash"), self.trash_ticked, danger=True)
        self.select_trash.pack(side="right")
        self.select_every = FlatButton(self.select_bar, tr("select_all"), self._all_or_none)
        self.select_every.pack(side="right", padx=(0, px(4)))
        self.bin_icons: dict = {}       # card -> its bin icon

        self.area = ScrollArea(self.frame, self.app)
        self.area.canvas.pack(fill="both", expand=True)
        self.area.canvas.bind("<Configure>", self._on_resize, add="+")
        self.area.listen(self._sync_soon)       # scrolled: the rows near the view are made
        self.area.fine_steps(px(24))            # (to the pixel: the view follows a row being measured)
        self.area.scroll.wheel_to = self.wheel  # (the wheel over the thumb: as over the list)
        self.area.inner.unbind("<Configure>")   # (its scroll room is set here, from the rows' heights)
        self.rows: list[_Row] = []
        self._heights: dict = {}                # (kind, key, width) -> its height, measured
        self._total = 0
        self._sync_job = None
        self._trash: list = []                  # rows' widgets let go of, destroyed a few at a time
        self._trash_job = None
        self._width = 0
        self.cards: dict = {}           # note id -> (outer frame, card frame)
        self.pin_icons: dict = {}       # note id -> its pin icon
        self.preview: MemoPreview | None = None
        self._preview_job = self._hide_job = None

    # -- data
    def memos(self):
        query = self.search.get().strip().casefold()
        notes = [n for n in reversed(list(self.app.notes.values())) if not n.is_empty and not n.deleted]
        if self.day:
            notes = [n for n in notes if n.covers(self.day)]
        if query:
            notes = [n for n in notes if query in n.search_text.casefold()]
        # pinned memos in the order they were pinned, whatever the sort; the others by date
        # (the memo's day, newest first; the same day: last edited first) or as added (newest first)
        pinned = sorted((n for n in notes if n.pinned), key=lambda n: n.pinned)
        others = [n for n in notes if not n.pinned]
        newest = not self.app.prefs.list_oldest
        if self.app.prefs.list_sort == "added":
            others.sort(key=lambda n: (n.created, n.id), reverse=newest)
        else:
            others.sort(key=lambda n: (n.date or "", n.created), reverse=newest)
        return pinned + others

    def titles(self):
        return [self.app.notes[i].title for i in self._order if i in self.app.notes]

    def clear_day(self):
        self.day = None
        if self.nw.calendar:
            self.nw.calendar.selected = None
            self.nw.calendar.draw()
            self.nw.calendar.show_details(None)
        self.refresh()

    # -- drawing
    def release(self):
        """The window is closing: the search trace (held by Tcl) would keep it alive; the list's
        own waiting passes go too."""
        for job in (self._sync_job, self._trash_job):
            if job is not None:
                try:
                    self.frame.after_cancel(job)
                except tk.TclError:
                    pass
        self._sync_job = self._trash_job = None
        self._trash = []
        name, self._search_trace = self._search_trace, None
        if name is not None:
            try:
                self.search.trace_remove("write", name)
            except tk.TclError:
                pass

    @perf.timed("list_refresh")
    def refresh(self):
        c = self.nw.colors
        px = self.app.px
        if self.day:
            self.filter_text.configure(text=tr("memos_on", day=_date_label(self.day)))
            names = " · ".join(map(texts.holiday_name, holidays.on(date.fromisoformat(self.day))))
            self.filter_holiday.configure(text=names, bg=c.bg, fg=c.sunday)
            if names:
                self.filter_holiday.pack(side="left", padx=(px(6), 0), after=self.filter_text)
            else:
                self.filter_holiday.pack_forget()
            self.filter_row.pack(fill="x", padx=px(10), pady=(0, px(6)), before=self.area.canvas)
        else:
            self.filter_row.pack_forget()
        self.hide_preview()
        job = self.nw._jobs.pop("search", None)         # made now: a pending search refresh is not needed
        if job is not None:
            self.nw.win.after_cancel(job)
        for child in self.area.inner.winfo_children():
            child.destroy()
        self._trash = []                    # (destroyed with the rest)
        self.bin_icons, self.cards, self.pin_icons = {}, {}, {}
        self.sections, self.sort_switch = {}, None
        self._picked, self._painters = None, {}
        notes = self.memos()
        self._order = [n.id for n in notes]
        px, rows = self.app.px, []

        def row(kind, key, make, guess):
            rows.append(_Row(kind, key, make, self._heights.get((kind, key, self._width), px(guess))))
        if not notes:
            row("empty", None, lambda parent: self._empty_state(c, parent), 160)
        pinned = [n for n in notes if n.pinned]
        others = [n for n in notes if not n.pinned]
        searching = bool(self.search.get().strip())        # a search shows what it found, folded or not
        folded = set() if searching else set(self.app.prefs.list_collapsed)
        if pinned:
            args = ("pinned", tr("pinned_head", n=len(pinned), limit=self.app.prefs.pin_limit),
                    len(pinned), "pinned" in folded, c)
            row("head", "pinned", lambda parent, a=args: self._section(*a, icon=GLYPH["pinned"], parent=parent),
                HEAD_GUESS)
            if "pinned" not in folded:
                for note in pinned:
                    row("card", note.id, lambda parent, n=note: self._card(n, parent), CARD_GUESS)
        if notes:                       # the memos' head is always there: it holds the sort switch
            args = ("others", tr("others_head"), len(others), "others" in folded, c)
            row("head", "others", lambda parent, a=args: self._section(*a, sort=True, parent=parent), HEAD_GUESS)
            if "others" not in folded:
                for note in others:
                    row("card", note.id, lambda parent, n=note: self._card(n, parent), CARD_GUESS)
        self.rows, self._total = rows, -1
        self._bin_badge()
        self.area.to_top()
        self._sync_window()

    def live_cards(self) -> int:
        """How many memo cards exist now (the rest of the list is only heights)."""
        return len(self.cards)

    def _sync_soon(self):
        if self._sync_job is None:
            self._sync_job = self.frame.after_idle(self._sync_later)

    def _sync_later(self):
        self._sync_job = None
        self._sync_window()

    def _sync_window(self):
        """Make the rows within KEEP_SCREENS of the view and let go of the others; each row sits
        where the rows above it end (a row made is measured, and the ones under it move)."""
        if self._sync_job is not None:
            try:
                self.frame.after_cancel(self._sync_job)
            except tk.TclError:
                pass
            self._sync_job = None
        if getattr(self, "_syncing", False):    # (asked again while making a row: once this one is done)
            self._resync = True
            return
        self._syncing = True
        try:
            self._sync_rows()
        finally:
            self._syncing = False
        if getattr(self, "_resync", False):
            self._resync = False
            self._sync_soon()

    def _sync_rows(self):
        cv = self.area.canvas
        try:
            view = cv.winfo_height() if cv.winfo_height() > 1 else self.nw.pad.height
            top = cv.canvasy(0)
        except tk.TclError:
            return
        # the row at the top of the view stays put on the screen while rows above it are made and
        # measured (their heights were guesses): the view follows it
        anchor = next((r for r in self.rows if r.y + r.height > top), None)
        offset = top - anchor.y if anchor is not None else 0
        lo, hi = top - view * KEEP_SCREENS, top + view * (1 + KEEP_SCREENS)
        y, budget, more, made = 0, BUILD_PER_PASS, False, []
        for r in self.rows:                 # what is near the view is made (unmeasured yet) ...
            near = y < hi and y + r.height > lo
            if near and r.widget is None:
                seen = y < top + view and y + r.height > top
                if seen or budget > 0:
                    budget -= 0 if seen else 1
                    self._make_row(r, y)
                    made.append(r)
                else:
                    more = True
            elif not near and r.widget is not None:
                self._drop_row(r)
            y += r.height
        if made:                            # ... and measured together: one layout pass, not one a row
            self.area.inner.update_idletasks()
            for r in made:
                h = r.widget.winfo_reqheight()
                more = more or h < r.height     # (shorter than guessed: more rows may come near)
                r.height = self._heights[(r.kind, r.key, self._width)] = h
        y = 0
        for r in self.rows:                 # each row where the rows above it end
            if r.y != y:
                r.y = y
                if r.widget is not None:
                    r.widget.place_configure(y=y)
            y += r.height
        if y != self._total:
            self._total = y
            self.area.inner.configure(height=max(1, y))
            cv.configure(scrollregion=(0, 0, max(1, cv.winfo_width()), max(1, y)))
        if anchor is not None and anchor.y + offset != top and y > 0:
            cv.yview_moveto((anchor.y + offset) / y)
        if more:
            self._sync_job = self.frame.after(BUILD_AGAIN_MS, self._sync_later)

    def _make_row(self, r, y):
        box = tk.Frame(self.area.inner, bg=self.nw.colors.bg, bd=0)
        box.place(x=0, y=y, relwidth=1)
        r.widget = box
        r.make(box)
        if r.kind == "card" and r.key == self._picked and r.key in self._painters:
            self._painters[r.key](True)

    def _drop_row(self, r):
        box, r.widget = r.widget, None
        if r.kind == "card":
            entry = self.cards.pop(r.key, None)
            if entry is not None:
                self.bin_icons.pop(entry[0], None)
            self.pin_icons.pop(r.key, None)
            self._painters.pop(r.key, None)
        elif r.kind == "head":
            self.sections.pop(r.key, None)
            if r.key == "others":
                self.sort_switch = None
        try:
            box.place_forget()              # (out of sight now; destroying ~10 cards took a frame)
        except tk.TclError:
            return
        self._trash.append(box)
        if self._trash_job is None:
            self._trash_job = self.frame.after(DROP_AGAIN_MS, self._empty_trash)

    def _empty_trash(self):
        self._trash_job = None
        batch, self._trash = self._trash[:DROP_PER_PASS], self._trash[DROP_PER_PASS:]
        for box in batch:
            try:
                box.destroy()
            except tk.TclError:
                pass
        if self._trash:
            try:
                self._trash_job = self.frame.after(DROP_AGAIN_MS, self._empty_trash)
            except tk.TclError:
                self._trash = []

    def _bin_badge(self):
        """The way into the bin: its icon with a red dot on its corner while the bin holds memos (badge
        option 5: how many is in its tooltip), or faint when the bin is empty."""
        c = self.nw.colors
        count = sum(1 for n in self.app.notes.values() if n.deleted)
        self.bin_count = count
        fg = c.fg if count else _mix(self.frame, c.muted, c.bg, 0.45)
        photo = bin_photo(self.app, fg, c.danger if count else None)
        if photo is not None:
            self.bin_glyph.configure(image=photo, text="")
        else:                                   # no icon font: the plain glyph
            paint_glyph(self.app, self.bin_glyph, GLYPH["trash"], fg, box=BIN_ICON_BOX)
        keep = tr("tip_bin_link", days=BIN_DAYS)
        self.bin_tip.text = f"{tr('bin_count', count=count)}\n{keep}" if count else keep

    def _bin_hover(self, on):
        c = self.nw.colors
        for w in (self.bin_row, self.bin_glyph):
            w.configure(bg=c.hover if on else c.bg)

    def _empty_state(self, c, parent=None):
        px = self.app.px
        inner = parent or self.area.inner
        if self.day:
            glyph, text = GLYPH["calendar"], tr("none_on")       # (short: the bar above says the day)
        elif self.search.get().strip():
            glyph, text = GLYPH["search"], tr("none_found")
        else:
            glyph, text = GLYPH["empty_note"], tr("none_yet")
        self.empty_text = text
        empty_page(self.app, inner, c, glyph, text)
        tk.Frame(inner, bg=c.bg, height=px(6)).pack()
        if self.day:
            b = FlatButton(inner, tr("new_on_day"),
                           lambda d=self.day: self.nw.new_memo(date=d))
            b.recolor(c)
            if self.app.icons.available:            # the add icon before the words (option C)
                b.configure(image=self.app.icons.photo(GLYPH["add"], c.fg, px(SMALL_ICON_BOX)), compound="left")
            else:
                b.configure(text="+ " + tr("new_on_day"))
            b.pack()

    def _section(self, key, text, count, folded, c, sort=False, icon=None, parent=None):
        """A part's head: ▾ / ▸ and its name (click: fold / unfold); the memos' head also
        has the sort switch on the right (click: by date ↔ as added). ``icon`` stands before
        the name (the pinned part: a pin and "2 / 5")."""
        px = self.app.px
        row = tk.Frame(parent or self.area.inner, bg=c.bg, bd=0, cursor="hand2")
        row.pack(fill="x", padx=(px(10), px(12)), pady=(px(2), px(3)))
        chevron = tk.Label(row, bg=c.bg, bd=0)
        chevron.pack(side="left", padx=(0, px(3)))
        glyph = GLYPH["unfold" if folded else "fold"]
        pic = None
        if icon:
            pic = tk.Label(row, bg=c.bg, bd=0)
            pic.pack(side="left", padx=(0, px(3)))
        label = tk.Label(row, text=tr("folded_count", head=text, n=count) if folded and not icon else text,
                         bg=c.bg, fg=c.muted_text, anchor="w", font=(UI_FONT, 9), bd=0)
        label.pack(side="left")
        parts = (row, chevron, label) + ((pic,) if pic else ())

        def tint(fg):
            label.configure(fg=fg)
            paint_glyph(self.app, chevron, glyph, fg, box=SECTION_ICON_BOX)
            if pic:
                paint_glyph(self.app, pic, icon, fg, box=SECTION_ICON_BOX + 1)
        tint(c.muted_text)
        for w in parts:
            w.bind("<ButtonRelease-1>", lambda e, k=key: self.app.toggle_list_section(k))
            w.bind("<Enter>", lambda e: tint(c.fg))
            w.bind("<Leave>", lambda e: tint(c.muted_text))
        Tooltip(label, tr("tip_section"))
        self.sections[key] = row
        if not sort:
            return
        prefs = self.app.prefs
        switch = tk.Frame(row, bg=c.bg, bd=0, cursor="hand2")
        switch.pack(side="right")
        word = tk.Label(switch, text=tr(f"sort_{prefs.list_sort}_{'old' if prefs.list_oldest else 'new'}"),
                        bg=c.bg, fg=c.muted_text, font=(UI_FONT, 9), bd=0)
        word.pack(side="left")
        icon = tk.Label(switch, bg=c.bg, bd=0)
        icon.pack(side="left", padx=(px(3), 0))

        def tint_switch(fg):
            word.configure(fg=fg)
            paint_glyph(self.app, icon, GLYPH["sort"], fg, box=SECTION_ICON_BOX)
        tint_switch(c.muted_text)

        def menu(_event):
            app = self.app
            (PopupMenu(app, self.frame)
             .add(tr("sort_by_date"), lambda: app.set_list_sort("date"), checked=prefs.list_sort == "date")
             .add(tr("sort_by_added"), lambda: app.set_list_sort("added"), checked=prefs.list_sort == "added")
             .separator()
             .add(tr("sort_newest"), lambda: app.set_list_oldest(False), checked=not prefs.list_oldest)
             .add(tr("sort_oldest"), lambda: app.set_list_oldest(True), checked=prefs.list_oldest)
             .popup(switch.winfo_rootx(), switch.winfo_rooty() + switch.winfo_height() + self.app.px(2)))
        for w in (switch, word, icon):
            w.bind("<ButtonRelease-1>", menu)
            w.bind("<Enter>", lambda e: tint_switch(c.fg))
            w.bind("<Leave>", lambda e: tint_switch(c.muted_text))
        Tooltip(word, tr("tip_sort"))
        self.sort_switch = word

    def _card(self, note: Note, parent=None):
        """A memo card (Phase 9, layout B): the title first, up to 3 lines, a quiet footer. No border
        or band: it rests on the page with a paper-lift shadow, and lifts under the mouse or when
        picked with the arrow keys (CardLift). The current memo has an edge in its own colour."""
        px = self.app.px
        c = Colors.of(self.frame, note.color)
        page = self.nw.colors.bg
        k = card_colors(self.frame, note.color, page)
        current = note is self.nw.note
        shown_elsewhere = (w := self.app.window_for(note.id)) is not None and w is not self.nw
        width = max(px(120), (self._width or self.nw.pad.width) - px(24))

        outer = tk.Frame(parent or self.area.inner, bg=page, bd=0)
        outer.pack(fill="x", padx=px(10))
        top_gap = tk.Frame(outer, bg=page, height=px(1), bd=0)
        top_gap.pack(fill="x")
        card = tk.Frame(outer, bg=k.rest, bd=0, highlightthickness=px(1) if CARD_HOVER == "D" else 0,
                        highlightbackground=k.rest, highlightcolor=k.rest)    # (D: the ring's room, unseen at rest)
        card.pack(fill="x")
        strips = []
        for color in k.rest_strips:
            s = tk.Frame(outer, bg=color, height=px(1), bd=0)
            s.pack(fill="x")
            strips.append(s)
        bottom_gap = tk.Frame(outer, bg=page, height=px(CARD_GAP), bd=0)
        bottom_gap.pack(fill="x")
        self.cards[note.id] = (outer, card)

        row = tk.Frame(card, bg=k.rest, bd=0)
        row.pack(fill="x", padx=(px(8), px(6)), pady=(px(6), 0))
        headed = note.style == "header" and note.header.strip()
        font = (note.font_family, 10, "bold")
        room = width - px(16) - 2 * (px(SMALL_ICON_BOX) + 2 * px(CARD_ICON_PAD)) - px(CARD_ICON_GAP)
        text = note.header.strip() if headed else memo_title(note)
        empty = not headed and note.title == EMPTY_TITLE         # "(빈 메모)": in the muted ink, not a title
        title = tk.Label(row, text=self._fit_line(text, font, room), bg=k.rest, fg=k.muted if empty else k.fg,
                         anchor="w",
                         font=font, bd=0, padx=0)
        if self.selecting:                  # select mode: a round check before the title (its row's height kept)
            check = tk.Canvas(row, width=px(16), height=px(16), bd=0, highlightthickness=0, bg=k.rest)
            check.pack(side="left", padx=(0, px(6)))     # (packed first: before the title)
            check._k = k
            self.checks[note.id] = check
            self._draw_check(note.id)
        title.pack(side="left", fill="x", expand=True)
        self.card_preview(card, note, c, width, title=False, bg=k.rest, muted=k.muted)

        foot = tk.Frame(card, bg=k.rest, bd=0)
        foot.pack(fill="x", padx=px(8), pady=(px(3), px(7)))
        small = (UI_FONT, 9)
        if current:
            tk.Label(foot, text=tr("current"), bg=k.rest, fg=k.label, font=(UI_BOLD, 9, "bold"),
                     bd=0, padx=0).pack(side="left")
            tk.Label(foot, text=" · ", bg=k.rest, fg=k.muted, font=small, bd=0, padx=0).pack(side="left")
        elif shown_elsewhere:
            there = tk.Label(foot, bg=k.rest, bd=0)
            paint_glyph(self.app, there, GLYPH["open_window"], k.muted)
            there.pack(side="left", padx=(0, px(3)))
            tk.Label(foot, text=tr("open_elsewhere"), bg=k.rest, fg=k.muted, font=small,
                     bd=0, padx=0).pack(side="left")
            tk.Label(foot, text=" · ", bg=k.rest, fg=k.muted, font=small, bd=0, padx=0).pack(side="left")
        tk.Label(foot, text=_span_label(note), bg=k.rest, fg=k.muted, font=small, bd=0, padx=0).pack(side="left")

        edge = None
        if current:                         # a mid tone of its own colour, not ink (picked 2026-11-28)
            edge = tk.Frame(card, bg=k.edge, bd=0)
            edge.keep_bg = True
            edge.place(x=0, y=0, width=px(3), relheight=1)

        state = {"hover": False}

        def lift(fade=True):
            card.lifts.to(CARD_LEVELS if state["hover"] or self._picked == note.id else 0, fade)

        def hover(on):
            state["hover"] = on
            lift()
            if on:
                self._rest_on(note, outer)
            else:
                self._left_card()

        def leave(event):
            under = outer.winfo_containing(event.x_root, event.y_root)
            if under is None or not str(under).startswith(str(outer)):
                hover(False)

        _bind_tree(outer, "<ButtonRelease-1>", lambda e, n=note: self.card_click(n, shift=bool(e.state & 0x1)))
        _bind_tree(outer, "<Button-3>", lambda e, n=note: self._card_menu(e, n))
        _bind_tree(outer, "<Enter>", lambda e: hover(True))
        _bind_tree(outer, "<Leave>", leave)
        for w in [outer, *outer.winfo_children()]:
            w.configure(cursor="hand2")

        # made after the card's bindings, so clicking the bin or the pin does not open the memo
        icons = []
        trash = tk.Label(row, bg=k.rest, cursor="hand2", padx=px(CARD_ICON_PAD), bd=0)
        trash.pack(side="right", before=title)
        danger = readable(self.frame, c.danger, k.lit, MARK_CONTRAST)
        trash.bind("<ButtonRelease-1>", lambda e, n=note: card.lifts.icons_shown and self.nw.trash_note(n))
        Tooltip(trash, tr("tip_card_trash"))
        self.bin_icons[outer] = trash
        icons.append((trash, GLYPH["trash"], k.muted, danger, False))

        glyph = GLYPH["pinned" if note.pinned else "pin"]
        pin = tk.Label(row, bg=k.rest, cursor="hand2", padx=px(CARD_ICON_PAD), bd=0)
        pin_rest = k.fg if note.pinned else k.muted
        if self.app.prefs.pin_limit or note.pinned:
            pin.pack(side="right", after=trash, padx=(0, px(CARD_ICON_GAP)))    # (packed after: left of the trash)
            icons.append((pin, glyph, pin_rest, k.fg, note.pinned))
        pin.bind("<ButtonRelease-1>", lambda e, n=note: (card.lifts.icons_shown or n.pinned) and self.toggle_pin(n))
        Tooltip(pin, tr("tip_card_unpin" if note.pinned else "tip_card_pin"))
        self.pin_icons[note.id] = pin

        card.lifts = CardLift(self.app, card, k, top_gap, bottom_gap, strips, icons, edge=edge, title=title)

        def picked(on):                     # picked with the arrow keys: the same lift as the mouse
            lift()
        self._painters[note.id] = picked

    def _fit_line(self, text, font, room):
        """``text`` on one line, cut with "…" to fit ``room`` px."""
        text = " ".join(str(text).split())
        fonts = self.__dict__.setdefault("_fit_fonts", {})
        f = fonts.get(font)
        if f is None:
            f = fonts[font] = tkfont.Font(self.frame, font=font)
        if f.measure(text) <= room:
            return text
        lo, hi = 0, len(text)
        while lo < hi:                      # the longest start that fits with "…"
            mid = (lo + hi + 1) // 2
            if f.measure(text[:mid].rstrip() + "…") <= room:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + "…"

    # -- keyboard
    def shown_ids(self) -> list[str]:
        """The memo cards on the page, top to bottom (not those in a folded part), made or not."""
        return [r.key for r in self.rows if r.kind == "card"]

    def step_pick(self, delta):
        ids = self.shown_ids()
        if not ids:
            return
        if self._picked in ids:
            index = max(0, min(len(ids) - 1, ids.index(self._picked) + delta))
        else:
            index = 0 if delta > 0 else len(ids) - 1
        self.pick(ids[index])

    def pick(self, note_id):
        old, self._picked = self._picked, note_id
        if old in self._painters:
            self._painters[old](False)
        row = next((r for r in self.rows if r.kind == "card" and r.key == note_id), None)
        if row is None:
            return
        for _ in range(2):                  # (made and measured on the way: its height may change)
            self._reveal(row)
        if note_id in self._painters:
            self._painters[note_id](True)

    def _reveal(self, row):
        """Scroll just enough that ``row`` is fully seen, and make it."""
        cv = self.area.canvas
        self.area.stop_glide()
        total, view, first = max(1, self._total), cv.winfo_height(), cv.canvasy(0)
        if row.y < first:
            cv.yview_moveto(row.y / total)
        elif row.y + row.height > first + view:
            cv.yview_moveto(max(0, row.y + row.height - view) / total)
        self._sync_window()

    def open_picked(self):
        ids = self.shown_ids()
        target = self._picked if self._picked in ids else (ids[0] if ids else None)
        if target is not None and target in self.app.notes:
            self.nw.open_note(self.app.notes[target])

    # -- pins
    def toggle_pin(self, note: Note):
        if note.pinned:
            self.app.unpin_note(note)
        elif not self.app.pin_note(note):
            limit = self.app.prefs.pin_limit
            self.nw.show_notice(tr("pin_full", n=limit) if limit else tr("pin_off"))
        self.refresh()

    # -- preview of the whole memo, after resting on a card
    def _rest_on(self, note, outer):
        self._cancel(hide=True)
        if self.preview is not None and self.preview.note is note:
            return
        self._cancel(show=True)
        self._preview_job = self.nw.win.after(PREVIEW_DELAY_MS, lambda: self._show_preview(note, outer))

    def _left_card(self):
        self._cancel(show=True)
        if self.preview is not None and self._hide_job is None:
            self._hide_job = self.nw.win.after(PREVIEW_HIDE_MS, self._hide_unless_pointed)

    def _hide_unless_pointed(self):
        self._hide_job = None
        if self.preview is not None and not self.preview.pointed():
            self.hide_preview()

    def _show_preview(self, note, outer):
        self._preview_job = None
        if self.nw.view != "list" or not outer.winfo_exists() or not outer.winfo_ismapped():
            return
        self.hide_preview()
        nw, px = self.nw, self.app.px

        def place(width, height):           # beside the note, level with the card, on the note's screen (S1)
            area = self.app.area_of(_pad_box(nw.pad))
            x = nw.win.winfo_rootx() + nw.win.winfo_width() + px(6)
            if x + width > area[2]:
                x = nw.win.winfo_rootx() - width - px(6)
            return x, min(max(outer.winfo_rooty(), area[1]), area[3] - height)
        self.preview = MemoPreview(nw, note, place, on_enter=lambda: self._cancel(hide=True),
                                   on_leave=self._left_card)

    def _cancel(self, show=False, hide=False):
        for attr, wanted in (("_preview_job", show), ("_hide_job", hide)):
            job = getattr(self, attr)
            if wanted and job is not None:
                try:
                    self.nw.win.after_cancel(job)
                except tk.TclError:
                    pass
                setattr(self, attr, None)

    def hide_preview(self):
        self._cancel(show=True, hide=True)
        if self.preview is not None:
            self.preview.destroy()
            self.preview = None

    def wheel(self, event):
        """The wheel scrolls an open preview first; when it has nothing more to show,
        the list scrolls and the preview closes."""
        if self.preview is not None and self.preview.scroll(event.delta):
            return
        self.hide_preview()
        self.area.wheel(event)

    def card_preview(self, card, note, c, width, title=True, bg=None, muted=None):
        """Header, pictures and the first lines of a memo, inside a card. ``title`` False: the card
        shows the title itself (the list). Done to-dos are dimmed and struck, as in the note."""
        px = self.app.px
        bg, muted = bg or c.bg, muted or c.muted
        headed = note.style == "header" and note.header.strip()
        if headed and title:
            tk.Label(card, text=note.header.strip(), bg=bg, fg=c.fg, anchor="w", justify="left",
                     wraplength=width, font=(note.font_family, 10, "bold")).pack(fill="x", padx=px(8))
        if note.style == "image" and note.images:
            self._pictures(card, note, c, width, bg)
        lines = note.preview_lines(4)
        if lines and not headed:            # no header: the first line reads as the title
            first = lines.pop(0)
            if title:
                tk.Label(card, text=first, bg=bg, fg=c.fg, anchor="w", justify="left",
                         wraplength=width, font=(note.font_family, 10, "bold")).pack(fill="x", padx=px(8))
        for i, line in enumerate(lines[:4 if headed and title else 3]):    # (the bin: a header and 4 lines)
            done = line.startswith("☑")
            tk.Label(card, text=line, bg=bg, fg=muted if done else c.fg, anchor="w", justify="left",
                     wraplength=width, bd=0,
                     font=(note.font_family, 9, "overstrike") if done else (note.font_family, 9)
                     ).pack(fill="x", padx=px(8), pady=(px(2) if i == 0 else 0, 0))
        query = self.search.get().strip()
        if query:
            self._match_line(card, note, c, query, width, bg)

    def _match_line(self, card, note, c, query, width, bg=None):
        """Searching: the line where the words were found, the found part marked like a
        highlighter, so it is clear why the memo is in the results."""
        px = self.app.px
        bg = bg or c.bg
        found = next((ln for ln in note.search_text.splitlines() if query.casefold() in ln.casefold()), None)
        if found is None:
            return
        found = found.strip()
        at = found.casefold().index(query.casefold())
        before, hit, after = found[:at], found[at:at + len(query)], found[at + len(query):]
        font = tkfont.Font(self.frame, font=(note.font_family, 9))
        room = max(px(40), width - font.measure(hit) - px(4))
        def cut_left(s, limit):                     # "…end of the text before"
            if font.measure(s) <= limit:
                return s
            while s and font.measure("…" + s) > limit:
                s = s[1:]
            return "…" + s

        def cut_right(s, limit):                    # "start of the text after…"
            if font.measure(s) <= limit:
                return s
            while s and font.measure(s + "…") > limit:
                s = s[:-1]
            return s + "…"
        before = cut_left(before, room // 2)         # one line: both sides cut with "…" to fit
        after = cut_right(after, room - font.measure(before))
        row = tk.Frame(card, bg=bg, bd=0)
        row.pack(fill="x", padx=px(8), pady=(px(3), 0))
        mark = _mix(self.frame, bg, "#FFD233", 0.75)      # a yellow highlighter on the memo's color
        for text, color, weight in ((before, bg, "normal"), (hit, mark, "bold"), (after, bg, "normal")):
            if text:
                lbl = tk.Label(row, text=text, bg=color, fg=c.fg, bd=0, padx=0, font=(note.font_family, 9, weight))
                lbl.pack(side="left")
                lbl.keep_bg = color is mark            # the highlighter stays when the card is lit

    def _pictures(self, card, note, c, width, bg=None):
        """One picture fills the card's width; several sit side by side, then "+N"."""
        px = self.app.px
        bg = bg or c.bg
        row = tk.Frame(card, bg=bg)
        row.pack(fill="x", padx=px(8), pady=(px(2), 0))
        box = (width, px(70)) if len(note.images) == 1 else (px(64), px(52))
        used = 0
        for i, name in enumerate(note.images):
            thumb = self._thumb(name, box)
            if thumb is None:
                continue
            if used and used + thumb.width() > width:
                tk.Label(row, text=f"+{len(note.images) - i}", bg=bg, fg=c.muted_text,
                         font=(UI_BOLD, 9, "bold")).pack(side="left", padx=px(2))
                break
            pic = tk.Label(row, image=thumb, bg=bg, bd=0)
            pic.image = thumb               # (held by its label: let go of with the card)
            pic.pack(side="left", padx=(0, px(4)))
            used += thumb.width() + px(4)

    def _thumb(self, name, box):
        return self.app.picture(name, box)

    def _card_menu(self, event, note):
        self.hide_preview()
        (PopupMenu(self.app, self.frame, Colors.of(self.frame, note.color))
         .add(tr("menu_open"), lambda: self.nw.open_note(note), icon=GLYPH["note"])
         .add(tr("menu_open_new_window"), lambda: self.app.open_in_new_window(note, self.nw),
              icon=GLYPH["open_window"])
         .add(tr("menu_unpin" if note.pinned else "menu_pin"), lambda: self.toggle_pin(note),
              icon=GLYPH["unpin" if note.pinned else "pin"])
         .separator()
         .add(tr("menu_move_to_bin"), lambda: self.nw.trash_note(note), danger=True, icon=GLYPH["trash"])
         .popup(event.x_root, event.y_root))

    def _on_resize(self, event):
        self._sync_soon()                                   # shown (or taller): fill the screen
        if abs(event.width - self._width) > 4:
            self._width = event.width
            if self.nw.view == "list":
                self.nw._later("list", 150, self.refresh)

    def recolor(self, c):
        self.frame.configure(bg=c.bg)
        self.search_box.configure(bg=c.well)
        self.search_icon.configure(bg=c.well)
        paint_glyph(self.app, self.search_icon, GLYPH["search"], c.muted)
        self.search_entry.configure(bg=c.well, fg=c.fg, insertbackground=self.app.cursor_color(c.well),
                                    selectbackground=c.select, selectforeground=c.fg)
        self.filter_row.configure(bg=c.bg)
        self.filter_text.configure(bg=c.bg, fg=c.fg)
        self.filter_clear.recolor(c)
        self.bin_row.configure(bg=c.bg)
        self.bin_glyph.configure(bg=c.bg)
        self._bin_badge()
        self.select_btn.configure(bg=c.well)
        paint_glyph(self.app, self.select_btn, GLYPH["select"], c.fg if self.selecting else c.muted)
        self.select_bar.configure(bg=c.bg)
        self.select_count.configure(bg=c.bg, fg=c.fg)
        for b in (self.select_trash, self.select_every):
            b.recolor(c)
        self.area.recolor(c.bg)
        page, self._page_bg = getattr(self, "_page_bg", c.bg), c.bg
        if page != c.bg:                    # the cards' colours are worked out from the page: once idle, and
            self.frame.after_idle(self._refresh_if_shown)   # only if still shown (opening a memo leaves)

    # -- select mode (backlog 4): tick memos, move them to the bin at once, one Undo
    def toggle_select(self):
        self.selecting = not self.selecting
        self.ticked, self._last_tick, self.checks = set(), None, {}
        px = self.app.px
        if self.selecting:
            self.bin_row.pack_forget()
            self.select_bar.pack(side="bottom", fill="x", padx=px(10), pady=(px(4), px(6)), before=self.area.canvas)
        else:
            self.select_bar.pack_forget()
            self.bin_row.pack(side="bottom", anchor="w", padx=px(10), pady=(px(4), px(6)), before=self.area.canvas)
        self.recolor(self.nw.colors)
        self._sync_select()
        self.refresh()

    def card_click(self, note, shift=False):
        """A card clicked: select mode ticks it (Shift: the run from the last one), else it opens."""
        if not self.selecting:
            self.nw.open_note(note)
            return
        ids = self.shown_ids()
        if shift and self._last_tick in ids and note.id in ids:
            a, b = sorted((ids.index(self._last_tick), ids.index(note.id)))
            self.ticked |= set(ids[a:b + 1])
        elif note.id in self.ticked:
            self.ticked.discard(note.id)
        else:
            self.ticked.add(note.id)
        self._last_tick = note.id
        for i in list(self.checks):
            self._draw_check(i)
        self._sync_select()

    def select_all(self):
        """Every memo shown (a search counts: what you can see)."""
        self.ticked = set(self.shown_ids())
        for i in list(self.checks):
            self._draw_check(i)
        self._sync_select()

    def _all_or_none(self):
        if self.ticked and self.ticked >= set(self.shown_ids()):
            self.ticked = set()
            for i in list(self.checks):
                self._draw_check(i)
            self._sync_select()
        else:
            self.select_all()

    def _sync_select(self):
        n = len(self.ticked)
        self.select_count.configure(text=tr("list_selected", n=n))
        every = bool(self.ticked) and self.ticked >= set(self.shown_ids())
        self.select_every.configure(text=tr("select_none" if every else "select_all"))
        self.select_trash.configure(cursor="hand2" if n else "")

    def _draw_check(self, note_id):
        cv = self.checks.get(note_id)
        if cv is None:
            return
        try:
            k, s = cv._k, int(cv.cget("width"))
            cv.delete("all")
            on = note_id in self.ticked
            ring = readable(cv, k.muted, k.rest, MARK_CONTRAST)
            cv._photo = dot_photo(self.app, k.fg if on else k.rest, k.fg if on else ring, s, self.app.px(1),
                                  k.rest if on else None)          # (smooth: no jagged oval)
            cv.create_image(s // 2, s // 2, image=cv._photo)
        except tk.TclError:
            self.checks.pop(note_id, None)

    def trash_ticked(self):
        """Every ticked memo to the bin at once; one notice, one Undo for the lot."""
        ids = [i for i in self.shown_ids() if i in self.ticked] + [i for i in self.ticked if i not in self.shown_ids()]
        if not ids:
            return
        self.toggle_select()                # (leaves select mode first: the list is made once more after)
        gone = self.app.trash_notes(ids)
        if gone:
            self.nw.show_undo_action(tr("toast_trashed_n", n=len(gone)), lambda g=gone: self.app.restore_notes(g),
                                     tip=tr("undo"))

    def _refresh_if_shown(self):
        if self.nw.view == "list":          # (show_list refreshes on the way back anyway)
            try:
                self.refresh()
            except tk.TclError:             # (the note closed meanwhile)
                pass


class MemoPreview:
    """The whole memo, in its own colors, in a small window: beside the note for a card
    in the list (the wheel scrolls it), beside the calendar for a day (the wheel goes to
    the day's previous / next memo, ``show_note``). ``place(width, height)`` says where."""

    WIDTH = 260
    MAX_HEIGHT = 380

    def __init__(self, nw: NoteWindow, note: Note, place, on_enter=None, on_leave=None, wheel=None,
                 counter="", alpha=None, click_through=False):
        self.nw, self.app, self._place = nw, nw.app, place
        px = self.app.px
        self._photos = []
        top = self.top = tk.Toplevel(nw.win)
        top.withdraw()
        top.overrideredirect(True)
        # "11/27 (Fri) · 2 / 3": which of the day's memos this is (calendar)
        self.counter = tk.Label(top, anchor="w", font=(UI_FONT, 9), padx=px(10), pady=px(3), bd=0)
        self.text = tk.Text(top, wrap="word", bd=0, highlightthickness=0, padx=px(10), pady=px(8),
                            cursor="arrow", width=1, height=1, spacing1=px(1), spacing3=px(1))
        self.text.pack(side="bottom", fill="both", expand=True, padx=1, pady=(0, 1))
        for w in (top, self.text, self.counter):
            w.bind("<MouseWheel>", lambda e: ((wheel or self.scroll)(e.delta), "break")[1])
            if on_enter:
                w.bind("<Enter>", lambda e: on_enter())
            if on_leave:
                w.bind("<Leave>", lambda e: on_leave())
        top.geometry(f"{px(self.WIDTH)}x{px(40)}+-10000+-10000")
        self.show_note(note, counter)
        top.attributes("-alpha", 0.0)
        top.deiconify()
        end = nw.pad.alpha if alpha is None else alpha
        if click_through:                   # Tk must own the layering: stay below 1.0 (set_click_through)
            from motion import CLICK_THROUGH_ALPHA
            end = min(end, CLICK_THROUGH_ALPHA)
        fade(top, "show", 0.0, end, TIP_FADE_MS)
        top.attributes("-topmost", True)
        winapi.set_owner(top, nw.win)
        if click_through:
            top.update_idletasks()
            winapi.set_click_through(top, True)

    def show_note(self, note: Note, counter=""):
        """Show ``note`` (in its colors and font), resized to it and placed again."""
        self.note = note
        nw, app, px, top, text = self.nw, self.app, self.app.px, self.top, self.text
        c = Colors.of(nw.win, note.color)
        top.configure(bg=_mix(nw.win, note.color, c.fg, 0.3))
        fam, size = note.font_family, max(8, note.font_size - 1)
        text.configure(state="normal", bg=c.bg, fg=c.fg, font=(fam, size))
        text.delete("1.0", "end")           # images out first: Tk 9 dislikes freeing them under use
        self._photos.clear()
        text.tag_configure("head", font=(fam, size + 2, "bold"))
        text.tag_configure("b", font=(fam, size, "bold"))
        text.tag_configure("i", font=(fam, size, "italic"))
        text.tag_configure("u", underline=True)
        text.tag_configure("s", overstrike=True)
        text.tag_configure("gap", font=(fam, 4))
        width = px(self.WIDTH)
        if note.style == "header" and note.header.strip():
            text.insert("end", note.header.strip() + "\n", ("head",))
        for i, (image, body, marks, inline) in enumerate(note.tabs()):
            if i:
                text.insert("end", "\n", ("gap",))
            if image and note.style == "image":
                photo = self._photo(app, image, width - px(24))
                if photo is not None:
                    text.image_create("end", image=photo)
                    text.insert("end", "\n")
            _fill_rich_text(text, body.rstrip(), marks, inline,
                            lambda index, name: self._embed(app, index, name, width - px(24)))
            text.insert("end", "\n")
        text.configure(state="disabled")
        text.yview_moveto(0)
        if counter:
            self.counter.configure(text=counter, bg=c.bar, fg=readable(top, c.muted, c.bar, TEXT_CONTRAST))
            self.counter.pack(side="top", fill="x", padx=1, pady=(1, 0))
        else:
            self.counter.pack_forget()
        top.update_idletasks()
        try:
            content = int(text.count("1.0", "end", "update", "ypixels") or 0) + px(18)
        except (tk.TclError, TypeError):
            content = px(self.MAX_HEIGHT)
        if counter:
            content += self.counter.winfo_reqheight()
        height = max(px(40), min(px(self.MAX_HEIGHT), content))
        x, y = self._place(width, height)
        top.geometry(f"{width}x{height}+{x}+{y}")

    def _photo(self, app, name, width):
        photo = app.picture(name, (width, round(width * 0.75)))
        if photo is not None:
            self._photos.append(photo)
        return photo

    def _embed(self, app, index, name, width):
        """A picture inside the text; a space if it cannot be read (it still takes one place)."""
        photo = self._photo(app, name, width)
        if photo is not None:
            self.text.image_create(index, image=photo)
        else:
            self.text.insert(index, " ")

    def pointed(self) -> bool:
        x, y = self.top.winfo_pointerxy()
        under = self.top.winfo_containing(x, y)
        return under is not None and under.winfo_toplevel() is self.top

    def scroll(self, delta) -> bool:
        """Scroll by one wheel notch. False when there is nothing more that way."""
        first, last = self.text.yview()
        if (delta > 0 and first <= 0) or (delta < 0 and last >= 1) or not delta:
            return False
        self.text.yview_scroll(-3 if delta > 0 else 3, "units")
        return True

    def destroy(self):
        try:
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")         # images out first: Tk 9 dislikes freeing them under use
            self.top.destroy()
        except tk.TclError:
            pass
        self._photos.clear()


# --------------------------------------------------------------------------- settings page
SETTING_GROUPS = (
    ("grp_memo", ("set_color", "set_font")),
    ("grp_look", ("set_default_color", "set_theme_color", "set_cursor", "set_transparency")),
    ("grp_place", ("set_snap", "set_auto_layout", "set_rail_hide", "set_minimize", "set_motion")),
    ("grp_general", ("set_language", "set_date_format", "set_pin_limit", "set_bin_days", "set_keys", "set_tour",
                     "set_folder", "set_update")),
)
# Keys and gestures (U1): (the key, what it does) and (the gesture, what it does)
KEY_ROWS = (
    ("Ctrl+N", "keys_new_memo"), ("Ctrl+Shift+N", "keys_new_window"), ("Ctrl+W", "keys_close"),
    ("Ctrl+Shift+T", "keys_reopen"), ("Ctrl+D", "keys_trash"), ("Ctrl+B · I · U · T", "keys_format"),
    ("Ctrl+Shift+L", "keys_bullets"), ("Ctrl+Shift+C", "keys_todo"), ("Ctrl+V", "keys_paste"),
    ("Ctrl+PgUp · PgDn", "keys_pictures"), ("Esc", "keys_back"), ("↑↓ · Enter", "keys_list_pick"),
)
GESTURE_ROWS = (
    ("gest_fold", "keys_fold"), ("gest_menu", "keys_menu"), ("gest_text_menu", "keys_text_menu"),
    ("gest_alt", "keys_alt"), ("gest_snap_resize", "keys_snap_resize"), ("gest_cal_click", "keys_cal_click"),
    ("gest_cal_day", "keys_cal_day"), ("gest_cal_span", "keys_cal_span"), ("gest_cal_move", "keys_cal_move"),
    ("gest_color", "keys_color"),
)
SETTING_HELP = {
    "set_color": "help_color", "set_font": "help_font", "set_default_color": "help_default_color",
    "set_theme_color": "help_theme_color", "set_cursor": "help_cursor", "set_transparency": "help_transparency",
    "set_snap": "help_snap", "set_auto_layout": "help_auto_layout", "set_rail_hide": "help_rail_hide", "set_minimize": "tip_minimize_style", "set_motion": "help_motion",
    "set_language": "help_language", "set_date_format": "help_date_format", "set_pin_limit": "help_pin_limit",
    "set_bin_days": "help_bin_days", "set_keys": "help_keys", "set_tour": "help_tour", "set_folder": "help_folder",
    "set_update": "help_update",
}
# Settings C (2026-11-28): each row's icon (Segoe Fluent), and the rows whose choice is in the row
SETTING_ICONS = {
    "set_color": "\ue790", "set_font": "\ue8d2", "set_default_color": "\ue771", "set_theme_color": "\ue7a1",
    "set_cursor": "\ue933", "set_transparency": "\ue746", "set_snap": "\ue71b", "set_auto_layout": "\ue8a9",
    "set_minimize": "\ue921", "set_motion": "\ue9f3", "set_language": "\ue775", "set_date_format": "\ue787",
    "set_pin_limit": "\ue718", "set_bin_days": "\ue74d", "set_keys": "\ue765", "set_folder": "\ue8b7",
    "set_update": "\ue896", "set_rail_hide": "\ue8a0", "set_tour": "\ue897",
}
QUICK = ("set_language", "set_cursor", "set_motion", "set_bin_days", "set_auto_layout", "set_rail_hide")
# Settings, clear cards (2026-11-28, the user's pick): every card reads on any note colour
SET_CARD_LIFT = (0.62, 0.08)     # a card: the page mixed this far toward white (light page, dark page)
SET_CARD_EDGE = 0.16             # ... ringed 1 px in the page mixed this far toward its ink
SET_ROW_HOVER = 0.06             # a row under the mouse: the card this far toward its ink
SET_CHOICE_LIFT = (0.75, 0.16)   # the choice in use: a raised chip, the card toward white (light, dark)
EXPORT_GLYPH = ""           # (Segoe Fluent: Export) the Memos card's export row
UPDATE_NOTE_LINES = 12           # the release notes on the Update page: longer ones are cut with …
SETTING_COLORS = {"set_color": "memo", "set_default_color": "default", "set_theme_color": "theme"}
SETTING_SLIDE_MS = anim.LONG     # a setting's page slides in over the list
SETTING_SLIDE_BACK = 0.28        # ... and the list steps back this much of its width


class Switch(tk.Label):
    """An on/off switch (Settings C: auto layout). A click calls ``command(not on)``; ``set`` shows a
    state (the picture comes from switch_photo's cache)."""

    def __init__(self, master, app, command):
        super().__init__(master, bd=0, cursor="hand2")
        self.app, self.command, self.on = app, command, False
        self.bind("<ButtonRelease-1>", lambda e: self.command(not self.on))

    def set(self, on, ink, pale, bg):
        """On: an ``ink`` track with a ``pale`` knob. Off: a ``pale`` track ringed in ``ink`` with an
        ``ink`` knob (an off switch never reads as on: Windows' own look)."""
        self.on = bool(on)
        photo = (switch_photo(self.app, True, ink, pale) if self.on
                 else switch_photo(self.app, False, pale, ink, outline=ink))
        self.configure(bg=bg, image=photo)


class SettingsView:
    def __init__(self, nw: NoteWindow):
        self.nw, self.app = nw, nw.app
        px = self.app.px
        self._syncing = False
        self.frame = tk.Frame(nw.views, bd=0)
        # two pages over each other: the list of settings, and one setting opened from it
        self.list_area = ScrollArea(self.frame, self.app)
        self.list_area.canvas.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.detail_area = ScrollArea(self.frame, self.app)
        self.area = self.list_area
        self.opened: str | None = None          # the setting open now (a SETTING_ROWS key)
        self._page_u = 0.0                      # 0: the list shows, 1: a setting's page (_slide_page)
        self.labels, self.flat, self.muted = [], [], []
        self.key_chips = []                     # the keys on the Keys and gestures page
        self.pages: dict = {}                   # key -> its page in detail_area
        self.list_rows: dict = {}               # key -> (row, name, value, dot, chevron)
        self.row_icons: dict = {}               # key -> its icon (Settings C)
        self.quick: dict = {}                   # key -> the choice in its row (QUICK)
        self.cards: list = []                   # (card, its strips): one a group
        self.segs: list = []                    # the quick choices' wells
        self.lines = []                         # thin lines under the rows
        pad = dict(padx=px(14))

        def page(key):
            """The page of one setting: its name on top, its controls, then what it does."""
            p = tk.Frame(self.detail_area.inner, bd=0)
            self.rows.append(p)
            self.pages[key] = p
            title = tk.Label(p, text=tr(key), font=(UI_BOLD, 10, "bold"), anchor="w", justify="left")
            title.pack(fill="x", pady=(px(12), px(8)), **pad)
            title.bind("<Configure>", lambda e, w=title: w.configure(wraplength=max(px(120), e.width)))
            self.labels.append(title)
            return p

        self.rows, self.palettes, self.warnings = [], {}, {}
        body = page("set_color")
        self._palette(body, "memo", px(24), pad)
        body = page("set_default_color")
        self._palette(body, "default", px(24), pad)
        body = page("set_theme_color")
        self._palette(body, "theme", px(24), pad)

        body = page("set_transparency")
        row = tk.Frame(body, bd=0)
        row.pack(fill="x", **pad)
        self.rows.append(row)
        self.alpha_unit = tk.Label(row, text="%", font=(UI_FONT, 9))
        self.alpha_unit.pack(side="right")
        self.alpha_box = NumberBox(row, self.app, 0, 90, self._alpha_typed)      # type the percent
        self.alpha_box.pack(side="right", padx=(px(6), px(2)))
        self.alpha = Slider(row, self.app, 0, 90, self._alpha_moved)
        self.alpha.pack(side="left", fill="x", expand=True)

        body = page("set_font")
        row = tk.Frame(body, bd=0)
        row.pack(fill="x", **pad)
        self.rows.append(row)
        self.font_picker = FontPicker(row, self.app, lambda fam: self.nw.set_font(family=fam))
        self.font_picker.pack(side="left", fill="x", expand=True)
        self.size_box = NumberBox(row, self.app, 8, 48, lambda v: self.nw.set_font(size=v))
        self.size_box.pack(side="left", padx=(px(6), 0))

        body = page("set_pin_limit")
        row = tk.Frame(body, bd=0)
        row.pack(fill="x", **pad)
        self.rows.append(row)
        self.pin_box = NumberBox(row, self.app, 0, PIN_LIMIT_MAX, self.app.set_pin_limit)
        self.pin_box.pack(side="left")
        self.pin_var = self.pin_box.var

        body = page("set_date_format")
        box = tk.Frame(body, bd=0)
        box.pack(fill="x", **pad)
        self.rows.append(box)
        self.date_buttons = {}
        today = date.today()
        for i, fmt in enumerate(texts.DATE_FORMATS):     # each shows today in that format
            b = FlatButton(box, texts.day_label(today, fmt), lambda f=fmt: self.app.set_date_format(f))
            b.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, px(6)), pady=(0, px(4)))
            self.date_buttons[fmt] = b
            self.flat.append(b)

        body = page("set_snap")
        row = tk.Frame(body, bd=0)
        row.pack(fill="x", **pad)
        self.rows.append(row)
        self.snap_buttons = {}
        for gap in (None, *SNAP_GAPS):
            b = FlatButton(row, tr("snap_off") if gap is None else f"{gap}", lambda g=gap: self.app.set_snap_gap(g))
            b.pack(side="left", padx=(0, px(4)))
            self.snap_buttons[gap] = b
            self.flat.append(b)
        self.snap_unit = tk.Label(row, text="px", font=(UI_FONT, 9))
        self.snap_unit.pack(side="left", padx=(px(2), 0))

        body = page("set_minimize")
        row = tk.Frame(body, bd=0)
        row.pack(fill="x", **pad)
        self.rows.append(row)
        self.min_buttons = {}
        for i, style in enumerate(("bar", "fold", "sticker")):     # the default first
            b = FlatButton(row, tr(f"min_{style}"), lambda s=style: self.app.set_minimize_style(s))
            b.grid(row=i, column=0, sticky="w", pady=(0, px(4)))      # one a line: the names are long
            self.min_buttons[style] = b
            self.flat.append(b)

        body = page("set_folder")              # where the memos are, and Open folder (Q8)
        self.folder_path = tk.Label(body, text=str(self.app.store.folder), font=(UI_FONT, 9), anchor="w",
                                    justify="left")
        self.folder_path.pack(fill="x", pady=(0, px(6)), **pad)
        self.folder_path.bind("<Configure>", lambda e, w=self.folder_path: w.configure(
            wraplength=max(px(120), e.width)))
        self.labels.append(self.folder_path)
        row = tk.Frame(body, bd=0)
        row.pack(fill="x", **pad)
        self.rows.append(row)
        b = FlatButton(row, tr("open_folder"), self.app.open_folder)
        b.pack(side="left")
        self.flat.append(b)

        self._keys_page(page("set_keys"), pad)   # every key and gesture (U1; also from ⋯)
        self._build_update(page("set_update"), pad)

        # under each setting's controls: what it does, in words (the tooltips of the old long page)
        for key, p in self.pages.items():
            words = tk.Label(p, text=tr(SETTING_HELP[key]), font=(UI_FONT, 9), anchor="w", justify="left")
            words.pack(fill="x", pady=(px(12), px(16)), **pad)
            words.bind("<Configure>", lambda e, w=words: w.configure(wraplength=max(px(120), e.width)))
            self.muted.append(words)

        # ---- the list: a row per setting with its value now, in four groups
        body = self.list_area.inner
        for group, keys in SETTING_GROUPS:       # Settings C: a paper card a group, like the list's
            cap = tk.Label(body, text=tr(group), font=ui_font(9, True), anchor="w")
            cap.pack(fill="x", pady=(px(14), px(5)), **pad)
            self.muted.append(cap)
            card = tk.Frame(body, bd=0)
            card.pack(fill="x", **pad)
            strips = []
            for _ in range(3):                  # the paper lift: 1 px strips under it
                strip = tk.Frame(body, height=1, bd=0)
                strip.pack(fill="x", **pad)
                strips.append(strip)
            self.cards.append((card, strips))
            for i, key in enumerate(keys):
                if i:
                    line = tk.Frame(card, height=1, bd=0)
                    line.pack(fill="x", padx=px(10))
                    self.lines.append(line)
                self._list_row(card, key)

        # the memos: export and this memo to the bin, as rows on a card of their own (clear cards)
        cap = tk.Label(body, text=tr("grp_memos"), font=ui_font(9, True), anchor="w")
        cap.pack(fill="x", pady=(px(14), px(5)), **pad)
        self.muted.append(cap)
        card = tk.Frame(body, bd=0)
        card.pack(fill="x", **pad)
        strips = []
        for _ in range(3):
            strip = tk.Frame(body, height=1, bd=0)
            strip.pack(fill="x", **pad)
            strips.append(strip)
        self.cards.append((card, strips))
        self.action_rows = []
        self._action_row(card, tr("set_export"), EXPORT_GLYPH, self._export, tip=tr("tip_backups"))
        line = tk.Frame(card, height=1, bd=0)
        line.pack(fill="x", padx=px(10))
        self.lines.append(line)
        self._action_row(card, tr("set_trash"), GLYPH["trash"], self._delete, danger=True)
        tk.Frame(body, height=px(14), bd=0).pack(fill="x")      # (room under the last card)
        self.rule = None

    # -- Update: the installed version, Check, and what the last check or download says
    def _build_update(self, body, pad):
        """Its status part is redrawn from the app's one Updater (_sync_update, a listener of
        it), so every note's page shows the same check."""
        px = self.app.px

        def wrapped(master, muted=False):
            lbl = tk.Label(master, font=(UI_FONT, 9), anchor="w", justify="left")
            lbl.bind("<Configure>", lambda e, w=lbl: w.configure(wraplength=max(px(120), e.width)))
            (self.muted if muted else self.labels).append(lbl)
            return lbl
        installed = wrapped(body)
        installed.configure(text=tr("upd_installed", v=version.VERSION))
        installed.pack(fill="x", **pad)
        row = tk.Frame(body, bd=0)
        row.pack(fill="x", pady=(px(8), 0), **pad)
        self.rows.append(row)
        self.update_check = FlatButton(row, tr("upd_check"), self.app.update_check)
        self.update_check.pack(side="left")
        self.flat.append(self.update_check)
        self.update_box = tk.Frame(body, bd=0)
        self.update_box.pack(fill="x", **pad)
        self.rows.append(self.update_box)
        self.update_status = wrapped(self.update_box)
        self.update_notes = wrapped(self.update_box, muted=True)
        self.update_buttons = tk.Frame(self.update_box, bd=0)
        self.rows.append(self.update_buttons)
        self.update_now = FlatButton(self.update_buttons, tr("upd_now"), self.app.update_install)
        self.update_now.pack(side="left", padx=(0, px(6)))
        self.update_later = FlatButton(self.update_buttons, tr("upd_later"), lambda: self.app.updater.dismiss())
        self.update_later.pack(side="left")
        self.flat += [self.update_now, self.update_later]
        self.update_elsewhere = wrapped(self.update_box, muted=True)
        self.update_elsewhere.configure(text=tr("upd_elsewhere"))
        self._updater = self.app.updater
        self._updater.listeners.append(self._sync_update)

    def _sync_update(self):
        u, px = self.app.updater, self.app.px
        for w in self.update_box.winfo_children():
            w.pack_forget()
        release = u.release
        status = {"checking": lambda: tr("upd_checking"), "latest": lambda: tr("upd_latest"),
                  "error": lambda: tr(u.error, e=u.error_detail) if u.error else "",
                  "available": lambda: tr("upd_new", v=release.version) if release else "",
                  "downloading": lambda: tr("upd_downloading", pct=round(u.progress * 100)),
                  "installing": lambda: tr("upd_installing")}.get(u.state, lambda: "")()
        if status:
            self.update_status.configure(text=status)
            self.update_status.pack(fill="x", pady=(px(10), 0))
        if u.state == "available" and release is not None:
            lines = release.notes.split("\n") if release.notes else []
            if len(lines) > UPDATE_NOTE_LINES:
                lines = lines[:UPDATE_NOTE_LINES] + ["…"]
            if lines:
                self.update_notes.configure(text="\n".join(lines))
                self.update_notes.pack(fill="x", pady=(px(4), 0))
            if u.can_install:
                self.update_buttons.pack(anchor="w", pady=(px(8), 0))
            else:                               # (a run from the repo or an unzipped folder)
                self.update_elsewhere.pack(fill="x", pady=(px(8), 0))
        busy = u.state in ("checking", "downloading", "installing")     # Check does nothing then
        self.update_check.configure(fg=self.nw.colors.muted if busy else self.nw.colors.fg,
                                    cursor="" if busy else "hand2")

    def _keys_page(self, body, pad):
        """Keys: the key in a tinted chip, what it does beside it. Mouse: the gesture, what it
        does under it (the gestures are too long to sit beside the words in a small note)."""
        px = self.app.px

        def wrap(w):
            w.bind("<Configure>", lambda e: w.configure(wraplength=max(px(60), e.width)))
        for head, rows in (("keys_keyboard", KEY_ROWS), ("keys_mouse", GESTURE_ROWS)):
            cap = tk.Label(body, text=tr(head), font=(UI_FONT, 9), anchor="w")
            cap.pack(fill="x", pady=(px(8), px(4)), **pad)
            self.muted.append(cap)
            for first, words in rows:
                row = tk.Frame(body, bd=0)
                row.pack(fill="x", pady=(0, px(6)), **pad)
                self.rows.append(row)
                if head == "keys_keyboard":
                    chip = tk.Label(row, text=first, font=(UI_BOLD, 9, "bold"), padx=px(5), pady=0)
                    chip.pack(side="left", anchor="n")
                    self.key_chips.append(chip)
                    text = tk.Label(row, text=tr(words), font=(UI_FONT, 9), anchor="w", justify="left")
                    text.pack(side="left", fill="x", expand=True, padx=(px(8), 0))
                    self.labels.append(text)
                else:
                    name = tk.Label(row, text=tr(first), font=(UI_BOLD, 9, "bold"), anchor="w", justify="left")
                    name.pack(fill="x")
                    wrap(name)
                    self.labels.append(name)
                    text = tk.Label(row, text=tr(words), font=(UI_FONT, 9), anchor="w", justify="left")
                    text.pack(fill="x")
                    self.muted.append(text)
                wrap(text)

    def release(self):
        """The window closes: the Updater must not keep this page (and its window) alive."""
        try:
            self._updater.listeners.remove(self._sync_update)
        except ValueError:
            pass

    # -- the list and opening one setting
    def _list_row(self, card, key):
        """One setting on its group's card: its icon, its name, then its value and › (a click opens
        its page) or, for QUICK, its choice right there (on a second line when the row is narrow)."""
        px = self.app.px
        quick = key in QUICK
        row = tk.Frame(card, bd=0, cursor="" if quick else "hand2")
        row.pack(fill="x", padx=px(10))
        row.columnconfigure(1, weight=1)
        icon = tk.Label(row, bd=0, cursor=row.cget("cursor"))
        icon.grid(row=0, column=0, sticky="w", padx=(0, px(8)), pady=px(7))
        name = tk.Label(row, text=tr(key).split(" (")[0] if key != "set_language" else tr(key),
                        font=(UI_FONT, 9), anchor="w", cursor=row.cget("cursor"))
        name.grid(row=0, column=1, sticky="w")
        value = tk.Label(row, font=(UI_FONT, 9), anchor="e", cursor="hand2")
        chevron = tk.Label(row, bd=0, cursor="hand2")
        dot = None
        self.row_icons[key] = icon
        self.list_rows[key] = (row, name, value, dot, chevron)
        if quick:
            self.quick[key] = control = self._quick_control(row, key)
            control.grid(row=0, column=2, columnspan=3, sticky="e")
            control._stacked = False
            name.tooltip = Tooltip(name, tr(SETTING_HELP[key]))      # (what its page said)
            Tooltip(icon, tr(SETTING_HELP[key]))
            row.bind("<Configure>", lambda e, k=key: self._fit_quick(k), add="+")
            return
        if key in SETTING_COLORS:
            dot = tk.Canvas(row, width=px(11), height=px(11), bd=0, highlightthickness=0, cursor="hand2")
            dot.grid(row=0, column=2, padx=(0, px(5)))
            self.list_rows[key] = (row, name, value, dot, chevron)
        value.grid(row=0, column=3, sticky="e")
        chevron.grid(row=0, column=4, padx=(px(4), 0))
        name._full = name.cget("text")
        name.tooltip = Tooltip(name, "")    # (the full name, only while it is cut)
        row.bind("<Configure>", lambda e, k=key: self._fit_name(k), add="+")
        parts = [w for w in (row, icon, name, value, dot, chevron) if w is not None]

        def hover(on):
            k = self._card_colors()
            for w in parts:
                w.configure(bg=k.lit if on else k.rest)
        for w in parts:
            w.bind("<Enter>", lambda e: hover(True))
            w.bind("<Leave>", lambda e: hover(row.winfo_containing(e.x_root, e.y_root) in parts))
            w.bind("<ButtonRelease-1>", lambda e, k=key: self.open(k))

    def _action_row(self, card, text, glyph, command, danger=False, tip=None):
        """A row that does something at once (no page): its icon and its words, red for the bin."""
        px = self.app.px
        row = tk.Frame(card, bd=0, cursor="hand2")
        row.pack(fill="x", padx=px(10))
        icon = tk.Label(row, bd=0, cursor="hand2")
        icon.pack(side="left", padx=(0, px(8)), pady=px(7))
        name = tk.Label(row, text=text, font=(UI_FONT, 9), anchor="w", cursor="hand2")
        name.pack(side="left", fill="x", expand=True)
        parts = (row, icon, name)
        self.action_rows.append((parts, glyph, danger))
        if tip:
            Tooltip(name, tip)

        def hover(on):
            k = self._card_colors()
            for w in parts:
                w.configure(bg=k.lit if on else k.rest)
        for w in parts:
            w.bind("<Enter>", lambda e: hover(True))
            w.bind("<Leave>", lambda e: hover(row.winfo_containing(e.x_root, e.y_root) in parts))
            w.bind("<ButtonRelease-1>", lambda e: command())

    def _fit_name(self, key):
        """The name cut with … to the room its row leaves (English names run longer): never under
        the value; the whole name on hover then."""
        row, name, value, dot, chevron = self.list_rows[key]
        icon, px = self.row_icons[key], self.app.px
        try:
            room = (row.winfo_width() - icon.winfo_reqwidth() - px(8) - value.winfo_reqwidth()
                    - (dot.winfo_reqwidth() + px(5) if dot is not None else 0) - chevron.winfo_reqwidth() - px(12))
            f = tkfont.Font(font=name.cget("font"))
        except tk.TclError:
            return
        full = name._full
        text = fit_text(full, room, f.measure, f.measure(".")) if room > 0 else "…"
        if text != name.cget("text"):
            name.configure(text=text)
        name.tooltip.text = full if text != full else ""

    def _quick_control(self, row, key):
        """A QUICK setting's choice: a small well of choices (the one in use stands out: sync), or the
        auto layout switch."""
        px = self.app.px
        if key == "set_auto_layout":
            self.auto_switch = Switch(row, self.app, self.app.set_auto_layout)
            return self.auto_switch
        if key == "set_rail_hide":
            self.rail_switch = Switch(row, self.app, self.app.set_rail_hide)
            return self.rail_switch
        seg = tk.Frame(row, bd=0, padx=px(2), pady=px(2))
        self.segs.append(seg)
        options = {
            "set_language": [(code, name, lambda c=code: self._choose_language(c)) for code, name in texts.LANGUAGES],
            "set_cursor": [(m, tr(f"cursor_{m}"), lambda m=m: self.app.set_cursor_mode(m)) for m in ("opposite", "text")],
            "set_motion": [(m, tr(f"motion_{m}"), lambda m=m: self.app.set_motion(m)) for m in ("full", "reduced", "off")],
            "set_bin_days": [(d, tr("bin_day_choice", n=d), lambda d=d: self.app.set_bin_days(d))
                             for d in BIN_DAY_CHOICES],
        }[key]
        buttons = {}
        for value, label, command in options:
            b = FlatButton(seg, label, command)
            b.configure(padx=px(6), pady=px(1))
            b.pack(side="left")
            buttons[value] = b
            self.flat.append(b)
        setattr(self, {"set_language": "lang_buttons", "set_cursor": "cursor_buttons", "set_motion": "motion_buttons",
                       "set_bin_days": "bin_buttons"}[key], buttons)
        return seg

    def _refit_quick(self):
        try:
            for key in self.quick:
                self._fit_quick(key)
        except tk.TclError:                 # (the window went away meanwhile)
            pass

    def _fit_quick(self, key):
        """The choice beside the name when the row has room, else on a second line under the name."""
        row, name, *_ = self.list_rows[key]
        control, icon, px = self.quick[key], self.row_icons[key], self.app.px
        need = icon.winfo_reqwidth() + px(8) + name.winfo_reqwidth() + px(12) + control.winfo_reqwidth()
        stacked = row.winfo_width() < need
        if stacked != control._stacked:
            control._stacked = stacked
            if stacked:
                control.grid(row=1, column=1, columnspan=4, sticky="w", pady=(0, px(8)))
            else:
                control.grid(row=0, column=2, columnspan=3, sticky="e", pady=0)

    def _well(self, c, k):
        """The quick choices' well: the card a step toward its ink (on a dark card too)."""
        return _mix(self.frame, k.rest, c.fg, 0.09)

    def _card_colors(self):
        """The cards' colours (clear cards): a surface a set step off the page with a 1 px edge, so a
        card reads on a pale note too (the list's recipe left 1.05:1 on yellow), and a hover tint."""
        c = self.nw.colors
        key = ("settings", str(c.bg).upper(), str(c.fg).upper())
        k = _CARD_COLORS.get(key)
        if k is None:
            base = card_colors(self.frame, self.nw.note.color, c.bg)
            dark = luminance(self.frame, c.bg) < 0.18
            rest = _mix(self.frame, c.bg, "#FFFFFF", SET_CARD_LIFT[1] if dark else SET_CARD_LIFT[0])
            lit = _mix(self.frame, rest, c.fg, SET_ROW_HOVER)
            muted = readable(self.frame, c.muted, lit, TEXT_CONTRAST)
            edge = _mix(self.frame, c.bg, c.fg, SET_CARD_EDGE)
            k = _CARD_COLORS[key] = base._replace(rest=rest, lit=lit, muted=muted, edge=edge)
        return k

    def _choice_colors(self, c, track):
        """A choice row's colours: (track, the chosen chip, its 1 px edge). The one in use is raised: a
        lighter chip with an edge on the darker track (it read as pressed when it was darker)."""
        dark = luminance(self.frame, track) < 0.18
        chip = _mix(self.frame, track, "#FFFFFF", SET_CHOICE_LIFT[1] if dark else SET_CHOICE_LIFT[0])
        return track, chip, _mix(self.frame, track, c.fg, 0.22)

    def _paint_choices(self, buttons, now, track):
        c = self.nw.colors
        track, chip, edge = self._choice_colors(c, track)
        for value, b in buttons.items():
            chosen = value == now
            b._bg = chip if chosen else track
            b.configure(bg=b._bg, font=ui_font(9, chosen), highlightthickness=self.app.px(1),
                        highlightbackground=edge if chosen else track, highlightcolor=edge if chosen else track)

    def _value_text(self, key) -> str:
        n, p, prefs = self.nw.note, self.nw.pad, self.app.prefs
        if key in SETTING_COLORS:
            color = self._shown_color(SETTING_COLORS[key])
            name = next((nm for nm, c in PALETTE if c.upper() == color), None)
            return tr(f"color_{name.lower()}") if name else color
        return {
            "set_font": lambda: f"{n.font_family} {n.font_size}",
            "set_cursor": lambda: tr(f"cursor_{prefs.cursor_color}"),
            "set_transparency": lambda: f"{p.transparency}%",
            "set_snap": lambda: tr("snap_off") if prefs.snap_gap is None else f"{prefs.snap_gap}px",
            "set_auto_layout": lambda: tr("auto_on" if prefs.auto_layout else "auto_off"),
            "set_minimize": lambda: tr(f"min_{prefs.minimize_style}"),
            "set_motion": lambda: tr(f"motion_{self.app.clock.mode}"),
            "set_language": lambda: dict(texts.LANGUAGES).get(texts.language(), ""),
            "set_date_format": lambda: texts.day_label(date.today(), texts.date_format()),
            "set_pin_limit": lambda: str(prefs.pin_limit),
            "set_bin_days": lambda: tr("bin_day_choice", n=prefs.bin_days),
            "set_keys": lambda: "",
            "set_tour": lambda: "",
            "set_rail_hide": lambda: "",
            "set_folder": lambda: Path(self.app.store.folder).name,
            "set_update": lambda: f"v{version.VERSION}",
        }[key]()

    def _shown_color(self, which):
        """The color in use: no theme color chosen means the default memo color (App.theme_colors)."""
        prefs = self.app.prefs
        if which == "theme":
            return (prefs.theme_color or prefs.default_color or PALETTE[0][1]).upper()
        return self._current(which) or PALETTE[0][1].upper()

    def _sync_rows(self):
        c = self.nw.colors
        for key, (_row, _name, value, dot, _chev) in self.list_rows.items():
            value.configure(text=self._value_text(key))
            if dot is not None:             # a smooth round dot, never a hollow square (read as a checkbox)
                color = self._shown_color(SETTING_COLORS[key])
                size = int(dot.cget("width"))
                dot.delete("all")
                k = self._card_colors()
                ring = readable(dot, Colors.of(dot, color, solid=True).border, k.rest, MARK_CONTRAST)
                dot._ring = ring
                dot._photo = dot_photo(self.app, color, ring, size, 1)     # (a ring: shows on its own colour)
                dot.create_image(size // 2, size // 2, image=dot._photo)

    def open(self, key, animated=True):
        """One setting's page slides in from the right over the list, which steps back a little
        (``animated`` False: it is just there, as from ⋯ > Keys and gestures)."""
        if key == "set_tour":                # (an action, no page: the tour again, on the memo)
            self.nw.show_home()
            self.app.start_tour(replay=True)
            return
        if self.opened is not None or key not in self.pages:
            return
        self.opened = key
        for k, p in self.pages.items():
            if k != key:
                p.pack_forget()
        self.pages[key].pack(fill="x")
        self.detail_area.to_top()
        lst, det = self.list_area.canvas, self.detail_area.canvas
        u = self._page_u                        # (a close still sliding: it turns back from there)
        det.place(relx=1 - u, rely=0, relwidth=1, relheight=1)
        lst.place(relx=-SETTING_SLIDE_BACK * u, rely=0, relwidth=1, relheight=1)
        tk.Misc.tkraise(det)
        if not animated:
            anim.clock_of(self.frame).stop(self.frame, "place:settings")
            self._page_u = 1.0
            det.place_configure(relx=0)
            lst.place_forget()
            return
        self._slide_page(1.0, lambda: lst.place_forget())

    def _slide_page(self, to, done):
        """The page's place, ``u`` from 0 (the list) to 1 (a setting): one tween, so a click the
        other way while it slides turns it back from where it is."""
        lst, det = self.list_area.canvas, self.detail_area.canvas

        def write(u):
            self._page_u = u
            det.place_configure(relx=1 - u)
            lst.place_configure(relx=-SETTING_SLIDE_BACK * u)
        anim.clock_of(self.frame).tween(self.frame, "place:settings", to, SETTING_SLIDE_MS,
                                        read=lambda: self._page_u, write=write, done=done)

    def close(self, animated=True):
        """Back to the list (the back arrow, Esc). True if a setting was open."""
        if self.opened is None:
            return False
        self.opened = None
        self._sync_rows()
        lst, det = self.list_area.canvas, self.detail_area.canvas
        u = self._page_u if animated else 0.0
        lst.place(relx=-SETTING_SLIDE_BACK * u, rely=0, relwidth=1, relheight=1)
        tk.Misc.tkraise(det)
        if animated:
            self._slide_page(0.0, lambda: det.place_forget())
        else:
            anim.clock_of(self.frame).stop(self.frame, "place:settings")
            self._page_u = 0.0
            det.place_forget()
        return True

    def reset(self):
        """The list, from its top: how the page opens."""
        self.close(animated=False)
        lst = self.list_area.canvas
        anim.clock_of(self.frame).stop(self.frame, "place:settings")
        self._page_u = 0.0
        lst.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.detail_area.canvas.place_forget()
        self.list_area.to_top()

    def wheel(self, event):
        (self.detail_area if self.opened else self.list_area).wheel(event)

    # -- palettes: 10 colors and 4 personal ones
    def _palette(self, body, which, size, pad):
        px = self.app.px
        box = tk.Frame(body, bd=0)
        box.pack(fill="x", **pad)
        self.rows.append(box)
        gap = px(5) if size > px(20) else px(4)
        basic, custom = [], []
        for i, (name, color) in enumerate(PALETTE):
            cv = tk.Canvas(box, width=size, height=size, highlightthickness=0, bd=0, cursor="hand2")
            cv.grid(row=i // 5, column=i % 5, padx=(0, gap), pady=(0, gap))
            cv.bind("<ButtonRelease-1>", lambda e, c=color: self._pick(which, c))
            Tooltip(cv, tr(f"color_{name.lower()}"))
            basic.append((cv, color))
        box.grid_columnconfigure(5, minsize=px(6))
        for i in range(CUSTOM_COLORS):
            cv = tk.Canvas(box, width=size, height=size, highlightthickness=0, bd=0, cursor="hand2")
            cv.grid(row=i // 2, column=6 + i % 2, padx=(0, gap), pady=(0, gap))
            cv.bind("<ButtonRelease-1>", lambda e, i=i: self.custom_click(which, i))
            cv.bind("<Button-3>", lambda e, i=i: self._custom_menu(e, which, i))
            Tooltip(cv, tr("tip_custom_color"))
            custom.append(cv)
        self.palettes[which] = (basic, custom)
        # under it, for a color too strong for text: what happens (a pale page) and a way to keep it solid
        warn = tk.Frame(body, bd=0)
        self.rows.append(warn)
        words = tk.Label(warn, font=(UI_FONT, 9), anchor="w", justify="left")
        words.pack(fill="x")
        words.bind("<Configure>", lambda e, w=words: w.configure(wraplength=max(px(120), e.width)))
        switch = FlatButton(warn, tr("keep_solid"), lambda: self._toggle_solid(which))
        switch.pack(anchor="w", pady=(px(3), px(2)))
        self.flat.append(switch)
        self.warnings[which] = (warn, words, switch, Tooltip(words, ""), box, pad)

    def _sync_warning(self, which):
        warn, words, switch, tip, box, pad = self.warnings[which]
        color = self._current(which)
        if not color or not needs_tint(self.frame, color):
            warn.pack_forget()
            return
        kept = color in Colors.solid
        words.configure(text=tr("solid_kept" if kept else "solid_tinted"))
        switch.configure(text=tr("use_tint" if kept else "keep_solid"))
        tip.text = tr("tip_solid", ratio=f"{text_contrast(self.frame, color):.1f}")
        warn.pack(fill="x", after=box, pady=(0, self.app.px(4)), **pad)

    def _toggle_solid(self, which):
        color = self._current(which)
        if color:
            self.app.keep_solid_color(color, keep=color not in Colors.solid)

    def _current(self, which):
        prefs = self.app.prefs
        color = {"memo": self.nw.note.color, "default": prefs.default_color, "theme": prefs.theme_color}[which]
        return (color or "").upper()

    def _pick(self, which, color):
        if which == "memo":
            self.nw.set_color(color)
        elif which == "theme":
            self.app.set_theme_color(color)
        else:
            self.app.set_default_color(color)

    def _ask(self, color):
        _rgb, hexv = colorchooser.askcolor(color=color or PALETTE[0][1], parent=self.nw.win,
                                           title=tr("set_custom_color"))
        return hexv.upper() if hexv else None

    def custom_click(self, which, i):
        """A personal-color square: the + box adds a color (in order, up to four); a
        filled one is used; clicking the one in use again changes it to a new color."""
        colors = self.app.prefs.custom_colors
        if i < len(colors):
            if colors[i] != self._current(which):
                self._pick(which, colors[i])
                return
            new = self._ask(colors[i])
            if new:
                self.app.replace_custom_color(i, new)
                self._pick(which, new)
            return
        new = self._ask(self._current(which))
        if new and self.app.add_custom_color(new) is not None:
            self._pick(which, new)

    def _custom_menu(self, event, which, i):
        if i >= len(self.app.prefs.custom_colors):
            return

        def change():
            new = self._ask(self.app.prefs.custom_colors[i])
            if new:
                self.app.replace_custom_color(i, new)
                self._pick(which, new)
        (PopupMenu(self.app, self.frame, self.nw.colors)
         .add(tr("menu_change_color"), change)
         .add(tr("menu_remove_color"), lambda: self.app.remove_custom_color(i), danger=True)
         .popup(event.x_root, event.y_root))

    def _sync_palette(self, which):
        basic, custom = self.palettes[which]
        current = self._current(which)
        for cv, color in basic:
            self._draw_swatch(cv, color, color.upper() == current)
        colors = self.app.prefs.custom_colors
        for i, cv in enumerate(custom):
            if i < len(colors):
                self._draw_swatch(cv, colors[i], colors[i] == current)
                cv.configure(cursor="hand2")
            else:
                self._draw_empty(cv, add=i == len(colors))
        self._sync_warning(which)

    def _draw_empty(self, cv, add):
        """An empty round slot (smooth, as the swatches); the next one to fill has a + in it."""
        c = self.nw.colors
        cv.delete("all")
        size = int(cv.cget("width"))
        cv._photo = dot_photo(self.app, c.bg, c.muted if add else c.border, size, 1)
        cv.create_image(size // 2, size // 2, image=cv._photo)
        if add:
            m, arm = size // 2, max(3, size // 5)
            cv.create_line(m - arm, m, m + arm + 1, m, fill=c.muted)
            cv.create_line(m, m - arm, m, m + arm + 1, fill=c.muted)
        cv.configure(cursor="hand2" if add else "")

    def sync(self):
        n, p = self.nw.note, self.nw.pad
        self._syncing = True
        try:
            for which in self.palettes:
                self._sync_palette(which)
            self.alpha.set(p.transparency)
            self.alpha_box.set(p.transparency)
            self.font_picker.set(n.font_family)
            self.size_box.set(n.font_size)
            self.pin_box.set(self.app.prefs.pin_limit)
            c = self.nw.colors
            prefs = self.app.prefs
            k = self._card_colors()
            well = self._well(c, k)             # (on a card: its well; on a page: the page's)
            for buttons, now, track in ((self.lang_buttons, texts.language(), well),
                                        (self.cursor_buttons, prefs.cursor_color, well),
                                        (self.bin_buttons, prefs.bin_days, well),
                                        (self.motion_buttons, self.app.clock.mode, well),
                                        (self.date_buttons, texts.date_format(), c.well),
                                        (self.snap_buttons, prefs.snap_gap, c.well),
                                        (self.min_buttons, prefs.minimize_style, c.well)):
                self._paint_choices(buttons, now, track)
            accent = readable(self.frame, accent_color(self.frame, self.app.theme_colors().color, k.rest),
                              k.rest, MARK_CONTRAST)    # on: the theme's colour (the ink read as off)
            white = contrast(self.frame, accent, "#FFFFFF") >= MARK_CONTRAST     # (Windows' own: a white knob
            knob = "#FFFFFF" if white else "#202020"                             # on the accent, where it reads)
            off = readable(self.frame, c.muted, k.rest, MARK_CONTRAST)     # off: a quieter ring and knob
            for switch, on in ((self.auto_switch, prefs.auto_layout), (self.rail_switch, bool(prefs.rail_hide))):
                switch.set(on, ink=accent if on else off, pale=knob if on else k.rest, bg=k.rest)
            self._sync_rows()
            self._sync_update()
            self.frame.after_idle(self._refit_quick)     # (a bold choice is wider: it may not fit now)
        finally:
            self._syncing = False

    def _draw_swatch(self, cv, color, selected):
        """A round swatch (smooth, like the colour menu's): the colour itself, never its pale page,
        ringed so it shows on its own colour; the one in use has a tick and a stronger ring."""
        c = Colors.of(cv, color, solid=True)
        page = self.nw.colors.bg
        cv.delete("all")
        size = int(cv.cget("width"))
        ring = readable(cv, c.fg if selected else c.border, page, MARK_CONTRAST if selected else 1.4)
        cv._photo = dot_photo(self.app, color, ring, size, 2 if selected else 1,
                              check=c.fg if selected else None)
        cv.create_image(size // 2, size // 2, image=cv._photo)
        if selected:
            cv.create_text(size / 2, size / 2, text=GLYPH["check"], fill=c.fg,
                           font=(self.app.icon_font, 8 if size > self.app.px(20) else 7))

    def recolor(self, c):
        self.frame.configure(bg=c.bg)
        self.list_area.recolor(c.bg)
        self.detail_area.recolor(c.bg)
        for w in self.rows:
            w.configure(bg=c.bg)
        for lbl in self.labels:
            lbl.configure(bg=c.bg, fg=c.fg)
        for lbl in self.muted:
            lbl.configure(bg=c.bg, fg=c.muted_text)
        for chip in self.key_chips:
            chip.configure(bg=c.hover, fg=c.fg)
        for line in self.lines:
            line.configure(bg=c.line)
        k = self._card_colors()
        words = k.muted                                     # (readable on the hovered row, k.lit, too)
        ink = readable(self.frame, readable(self.frame, c.muted, k.rest, MARK_CONTRAST), k.lit, MARK_CONTRAST)
        for card, strips in self.cards:     # (clear cards: a 1 px edge round each)
            card.configure(bg=k.rest, highlightthickness=self.app.px(1), highlightbackground=k.edge,
                           highlightcolor=k.edge)
            for strip, color in zip(strips, k.rest_strips):
                strip.configure(bg=color)
        danger = readable(self.frame, c.danger, k.lit, TEXT_CONTRAST)
        for parts, glyph, is_danger in getattr(self, "action_rows", ()):
            for w in parts:
                w.configure(bg=k.rest)
            parts[2].configure(fg=danger if is_danger else c.fg)
            paint_glyph(self.app, parts[1], glyph, danger if is_danger else ink, box=ICON_BOX)
        for key, (row, name, value, dot, chevron) in self.list_rows.items():
            for w in (row, name, value, chevron, dot, self.row_icons[key]):
                if w is not None:
                    w.configure(bg=k.rest)
            name.configure(fg=c.fg)
            value.configure(fg=words)
            paint_glyph(self.app, chevron, GLYPH["unfold"], ink, box=SECTION_ICON_BOX)
            paint_glyph(self.app, self.row_icons[key], SETTING_ICONS[key], ink, box=ICON_BOX)
        for seg in self.segs:
            seg.configure(bg=self._well(c, k))
        for b in self.flat:
            b.recolor(c)
        for basic, custom in self.palettes.values():
            for cv in [cv for cv, _ in basic] + custom:
                cv.configure(bg=c.bg)
        for _warn, words, *_rest in self.warnings.values():
            words.configure(bg=c.bg, fg=c.muted_text)
        self.alpha_unit.configure(bg=c.bg, fg=c.muted_text)
        self.snap_unit.configure(bg=c.bg, fg=c.muted_text)
        self.alpha.recolor(c)
        for box in (self.alpha_box, self.size_box, self.pin_box):
            box.recolor(c)
        self.font_picker.recolor(c)
        if self.rule is not None:
            self.rule.configure(bg=c.border)
        self.sync()

    def _alpha_moved(self, value):
        if not self._syncing:
            self.nw.set_transparency(value)
            self.alpha_box.set(self.nw.pad.transparency)

    def _alpha_typed(self, value):
        if not self._syncing:
            self.nw.set_transparency(value)
            self.alpha.set(self.nw.pad.transparency)

    def _delete(self):
        self.nw.show_home()
        self.nw.trash_current()

    def _export(self):
        name = f"{tr('export_name')}-{date.today().isoformat()}.txt"
        path = filedialog.asksaveasfilename(parent=self.nw.win, title=tr("export_title"), initialfile=name,
                                            defaultextension=".txt",
                                            filetypes=[(tr("files_text"), "*.txt"), (tr("files_all"), "*.*")])
        if not path:
            return
        self.app.export_text(path, self.nw)

    def _choose_language(self, code):
        # after_idle: switching rebuilds this window, including the button being clicked
        self.app.root.after_idle(lambda: self.app.set_language(code))


# --------------------------------------------------------------------------- bin page
class BinView:
    """Memos moved to the bin, newest first. Each can be restored or deleted for good;
    after BIN_DAYS days they are deleted automatically."""

    def __init__(self, nw: NoteWindow):
        self.nw, self.app = nw, nw.app
        px = self.app.px
        self._order: list[str] = []
        self._armed: dict = {}          # key -> (after job, button, its colors, label, its text and color)
        self.notices: dict = {}         # note id -> the card's "n days left" label (says "click again" when armed)
        self.buttons: dict = {}         # note id -> (restore button, delete button)
        self.frame = tk.Frame(nw.views, bd=0)
        self.head = tk.Frame(self.frame, bd=0)
        self.head.pack(fill="x", padx=px(10), pady=(px(2), px(6)))
        self.info = tk.Label(self.head, text=tr("bin_info", days=BIN_DAYS),
                             font=(UI_FONT, 9), anchor="w")
        self.info.pack(side="left")
        self.empty_btn = IconButton(self.head, self.app, GLYPH["trash"], self.empty_bin, tr("bin_empty_button"),
                                    height=24)
        self.area = ScrollArea(self.frame, self.app)
        self.area.canvas.pack(fill="both", expand=True)

    def memos(self):
        return sorted((n for n in self.app.notes.values() if n.deleted), key=lambda n: n.deleted, reverse=True)

    def titles(self):
        return [self.app.notes[i].title for i in self._order if i in self.app.notes]

    def refresh(self):
        c, px = self.nw.colors, self.app.px
        self._disarm_all()
        for child in self.area.inner.winfo_children():
            child.destroy()
        self.buttons = {}
        notes = self.memos()
        self._order = [n.id for n in notes]
        self.notices = {}
        if notes:
            self.empty_btn.pack(side="right")
        else:
            self.empty_btn.pack_forget()
            empty_page(self.app, self.area.inner, c, GLYPH["trash"], tr("bin_is_empty"))
        for note in notes:
            self._card(note)
        self.area.to_top()

    @staticmethod
    def time_left(note) -> str:
        try:
            gone = datetime.fromisoformat(note.deleted) + timedelta(days=BIN_DAYS)
        except (TypeError, ValueError):
            return ""
        days = max(0, math.ceil((gone - datetime.now()).total_seconds() / 86400))
        return texts.days_left(days)

    def _card(self, note):
        px = self.app.px
        c = Colors.of(self.frame, note.color)
        avail = self.area.canvas.winfo_width()
        if avail <= 1:                  # page not shown yet: use the window's width
            avail = (self.nw.win.winfo_width() if self.nw.win.winfo_width() > 1 else self.nw.pad.width) - 2
        width = max(px(120), avail - px(24))
        outer = tk.Frame(self.area.inner, bg=c.border, bd=0)
        outer.pack(fill="x", padx=px(10), pady=(0, px(6)))
        card = tk.Frame(outer, bg=c.bg, bd=0)
        card.pack(fill="both", expand=True, padx=1, pady=1)
        meta = readable(self.frame, c.muted, c.bar, TEXT_CONTRAST)     # on the strip: readable words (Q9)
        top = tk.Frame(card, bg=c.bar)
        top.pack(fill="x")
        left = tk.Label(top, text=self.time_left(note), bg=c.bar, fg=c.fg, font=(UI_FONT, 9))
        left.pack(side="left", padx=(px(8), 0), pady=px(3))
        self.notices[note.id] = left
        tk.Label(top, text=_span_label(note), bg=c.bar, fg=meta,
                 font=(UI_FONT, 9)).pack(side="right", padx=(0, px(8)))
        tk.Frame(card, bg=c.bg, height=px(4)).pack(fill="x")
        self.nw.list_view.card_preview(card, note, c, width)
        row = tk.Frame(card, bg=c.bg)
        row.pack(fill="x", padx=px(6), pady=(px(2), px(4)))
        delete = IconButton(row, self.app, GLYPH["trash"], lambda n=note: self.delete_forever(n),
                            tr("delete_forever"), height=24)
        restore = IconButton(row, self.app, GLYPH["restore"], lambda n=note: self.restore(n), tr("restore"),
                             height=24)
        restore.recolor(c, strong=True)
        _danger_icon(delete, c)
        delete.pack(side="right")
        restore.pack(side="right", padx=(0, px(2)))
        self.buttons[note.id] = (restore, delete)

    def restore(self, note):
        self.app.restore_note(note.id)

    def delete_forever(self, note):
        button = self.buttons.get(note.id, (None, None))[1]
        if self._confirm(("delete", note.id), button, self.notices.get(note.id), tr("confirm_delete")):
            self.app.delete_forever(note.id)

    def empty_bin(self):
        if self._confirm(("empty",), self.empty_btn, self.info, tr("confirm_empty")):
            self.app.empty_bin()

    def _confirm(self, key, button, label, text) -> bool:
        """First click arms the button for CONFIRM_MS: it fills red, and ``label`` says
        "click again"; a second click within that time confirms."""
        if key in self._armed:
            self._disarm(key)
            return True
        job = self.frame.after(CONFIRM_MS, lambda: self._disarm(key))
        colors = (button._bg, button._hover, button._fg) if button is not None else None
        said = (label.cget("text"), label.cget("fg")) if label is not None else None
        self._armed[key] = (job, button, colors, label, said)
        danger = self.nw.colors.danger
        if button is not None:
            button._bg = button._hover = danger
            button._fg = "#FFFFFF"
            button.configure(bg=danger)
            button._draw()
        if label is not None:
            label.configure(text=text, fg=danger)
        return False

    def _disarm(self, key):
        job, button, colors, label, said = self._armed.pop(key, (None, None, None, None, None))
        if job is not None:
            try:
                self.frame.after_cancel(job)
            except tk.TclError:
                pass
        if button is not None and button.winfo_exists() and colors:
            button._bg, button._hover, button._fg = colors
            button.configure(bg=button._bg)
            button._draw()
        if label is not None and label.winfo_exists() and said:
            label.configure(text=said[0], fg=said[1])

    def _disarm_all(self):
        for key in list(self._armed):
            self._disarm(key)

    def recolor(self, c):
        for w in (self.frame, self.head):
            w.configure(bg=c.bg)
        self.info.configure(bg=c.bg, fg=c.muted_text)
        _danger_icon(self.empty_btn, c)
        self.area.recolor(c.bg)


def _danger_icon(button, c):
    """An icon button for deleting: drawn in the red of the colors ``c``."""
    button.recolor(c)
    button._fg = button.ink_color = c.danger
    button._draw()


# every name (underscored ones too) goes on to the next part: see app.py
__all__ = [_n for _n in list(globals()) if not _n.startswith("__")]
