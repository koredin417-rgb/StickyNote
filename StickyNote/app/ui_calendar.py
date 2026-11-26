"""The month calendar beside a note (small and big view, period memos)."""
from __future__ import annotations

import calendar as _calendar
import colorsys
from collections import OrderedDict
from copy import deepcopy as _deepcopy
import os
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
import traceback
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageGrab, ImageTk

import calgeom
import geom
from geom import CAL
import holidays
import texts
import perf
import winapi
from icon import draw_icon
from motion import CLICK_THROUGH_ALPHA
from store import (BIN_DAY_CHOICES, CURSOR_COLORS, CUSTOM_COLORS, EMPTY_TITLE, INLINE, LIST_SORTS, MARK_KINDS,
                   PIN_LIMIT_MAX, SNAP_GAPS, STYLES, TIDY_ORDERS, Note, NoteStore, Pad, Prefs)
from texts import tr
from ui_views import *  # noqa: F401,F403  (the parts before this one)


# --------------------------------------------------------------------------- calendar popup
def _dock_side(note, cal) -> str:
    """Which side of the note's box the docked calendar's box is on: by their facing edges,
    else (overlapping) by their centres."""
    if cal[0] >= note[2]:
        return "right"
    if cal[2] <= note[0]:
        return "left"
    if cal[1] >= note[3]:
        return "below"
    if cal[3] <= note[1]:
        return "above"
    (nx, ny), (cx, cy) = geom.center(note), geom.center(cal)
    if abs(cx - nx) >= abs(cy - ny):
        return "right" if cx >= nx else "left"
    return "below" if cy >= ny else "above"


class HolidayCard:
    """The pop-up under a clicked red day: its holiday's name and what it is. Clicks pass
    through it (winapi.set_click_through, after -alpha is below 1.0: Tk layers it), and it takes
    no space (S1)."""

    def __init__(self, cal):
        self.cal, self.top, self._through = cal, None, False

    def _build(self):
        cal = self.cal
        top = self.top = tk.Toplevel(cal.top)
        top.withdraw()
        top.overrideredirect(True)
        top.attributes("-alpha", CLICK_THROUGH_ALPHA)       # before click-through: Tk owns the layering
        top.attributes("-topmost", True)
        self.frame = tk.Frame(top, bd=0)
        self.frame.pack(fill="both", expand=True, padx=1, pady=1)
        self.name = tk.Label(self.frame, font=(UI_BOLD, 9, "bold"), anchor="w", justify="left")
        self.name.pack(fill="x", padx=cal.app.px(10), pady=(cal.app.px(6), 0))
        self.text = tk.Label(self.frame, font=(UI_FONT, 8), anchor="w", justify="left")
        self.text.pack(fill="x", padx=cal.app.px(10), pady=(0, cal.app.px(6)))

    def show(self, iso):
        cal, px = self.cal, self.cal.app.px
        days = holidays.on(date.fromisoformat(iso))
        if not days:
            self.hide()
            return
        if self.top is None:
            self._build()
        c = cal.colors
        top = self.top
        top.configure(bg=c.border)
        self.frame.configure(bg=c.bg)
        self.name.configure(bg=c.bg, fg=c.sunday, text=f"{_date_label(iso)}  {' · '.join(map(texts.holiday_name, days))}")
        self.text.configure(bg=c.bg, fg=c.fg, text="\n".join(map(texts.holiday_detail, days)), wraplength=cal.cell_w * 7)
        top.update_idletasks()
        w, h = top.winfo_reqwidth(), top.winfo_reqheight()
        cell = next(((x0, y0, x1, y1) for x0, y0, x1, y1, d in cal._cells if d.isoformat() == iso), None)
        g = cal.grid
        x = g.winfo_rootx() + (cell[0] if cell else 0)
        y = g.winfo_rooty() + (cell[3] if cell else g.winfo_height()) + px(4)
        left, top_, right, bottom = cal.app.area_of((x, y, x + w, y + h))
        x = min(max(x, left), max(left, right - w))
        y = min(max(y, top_), max(top_, bottom - h))
        top.geometry(f"+{x}+{y}")
        top.deiconify()
        top.update_idletasks()
        if not self._through:                   # after its first map (it has a frame window then)
            winapi.set_click_through(top, True)
            self._through = bool(winapi.hwnd_of(top))
        top.lift()

    def hide(self):
        if self.top is not None:
            try:
                self.top.withdraw()
            except tk.TclError:
                pass


def pill_image(w, h, fill, scale=16, text="", ink="#FFFFFF", font_file=None, size_px=0):
    """A filled pill (fully rounded ends), ``w`` x ``h`` px, as RGBA: drawn ``scale`` times bigger and
    box-averaged down, so each edge pixel's alpha is exactly the share of it the pill covers (256
    levels, no ringing); the colour is the fill's own everywhere (no dark fringe on any cell).
    ``text`` (with ``font_file`` at ``size_px``): drawn on it in ``ink`` with greyscale smoothing (no
    ClearType colour fringes), centred on its own ink, not on the line box."""
    r, g, b = ImageColor.getrgb(fill)[:3]
    big = Image.new("RGBA", (w * scale, h * scale), (r, g, b, 0))
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * scale - 1, h * scale - 1), radius=h * scale // 2,
                                          fill=(r, g, b, 255))
    pill = big.reduce(scale)
    if text and font_file and size_px:
        font = ImageFont.truetype(str(font_file), size_px)
        x0, y0, x1, y1 = font.getbbox(text)
        ImageDraw.Draw(pill).text(((w - (x1 - x0)) / 2 - x0, (h - (y1 - y0)) / 2 - y0), text, font=font, fill=ink)
    return pill


def circle_image(d, fill, scale=4):
    """A filled circle, ``d`` px across, as RGBA: drawn ``scale`` times bigger and shrunk with LANCZOS,
    so its edge is anti-aliased (partial alpha); the corners are transparent and sit on any cell."""
    r, g, b = ImageColor.getrgb(fill)[:3]
    big = Image.new("RGBA", (d * scale, d * scale), (r, g, b, 0))      # (the fill's own colour: no dark fringe)
    ImageDraw.Draw(big).ellipse((0, 0, d * scale - 1, d * scale - 1), fill=(r, g, b, 255))
    return big.resize((d, d), Image.LANCZOS)


class CalendarPopup:
    """A month view docked beside its note. Click a day to list its memos,
    double-click to start a memo on that day."""

    def __init__(self, nw: NoteWindow):
        self.nw, self.app = nw, nw.app
        px = self.app.px
        today = date.today()
        self.month = (today.year, today.month)
        self.selected: str | None = None
        self._hover: date | None = None
        self._cells: list = []
        self._click_job = None
        self._after_double = False
        pad = nw.pad
        self.docked, self.expanded = pad.calendar_docked, pad.calendar_expanded
        self._chips: list = []          # (x0, y0, x1, y1, note) memo titles in the big view
        self._move = None
        self.tile_size = None               # auto layout: exactly this big (whole tiles, fit_tile)
        self.fit_size = None                # (width or None, height or None) its day cells fill (_fit_cells)
        # what App.space() reads (it measures no window): place() keeps both up to date
        self.least: tuple[int, int] | None = None   # least_size() for the view it shows
        self.target_box = None              # (x0, y0, x1, y1) where it is, or is going; None: not placed yet
        self._dock_offset = None            # docked: target_box's corner less its note's destination
        self._sizes()

        top = self.top = tk.Toplevel(nw.app.root)      # not the note's child: it may go to another note
        top.withdraw()
        top.overrideredirect(True)
        top.protocol("WM_DELETE_WINDOW", lambda: self.nw.close_calendar())     # Alt+F4 on the calendar
        # No top.transient(): after showing it hides the window again, and it does not
        # set a real owner for borderless windows anyway. winapi.set_owner does.
        self.frame = tk.Frame(top, bd=0)
        self.frame.pack(fill="both", expand=True, padx=1, pady=1)
        self._tiles: dict = {}          # rounded day tiles (smooth, drawn with Pillow)
        self._menu_font = tkfont.Font(top, family=UI_FONT, size=9)     # PopupMenu's: for cutting titles

        # like the note: a thin grab strip and a top bar one shade darker than the memo
        self.grab = tk.Canvas(self.frame, width=1, height=px(GRAB_H), bd=0, highlightthickness=0)   # width=1:
        self.grab.pack(fill="x")                    # a Canvas would ask for 10 cm and widen the calendar
        self.grab.bind("<Configure>", lambda e: self._draw_grab())
        head = self.head = tk.Frame(self.frame, bd=0)
        head.pack(fill="x")

        def top_button(glyph, command, tip):        # the same icons, size and height as the note's top bar
            return IconButton(head, self.app, glyph, command, tip, height=TOP_BUTTON_H)
        self.btn_prev = top_button(GLYPH["prev"], self.prev_month, tr("tip_prev_month"))
        self.btn_prev.pack(side="left")
        self.title = tk.Label(head, font=(UI_FONT, 9), bd=0)     # like the note's date: plain, icon gray
        self.title.pack(side="left", padx=px(2))
        self.btn_next = top_button(GLYPH["next"], self.next_month, tr("tip_next_month"))
        self.btn_next.pack(side="left")
        self.btn_close = top_button(GLYPH["close"], lambda: self.nw.close_calendar(), tr("tip_close_calendar"))
        self.btn_close.pack(side="right")
        self.btn_expand = top_button(GLYPH["expand"], self.toggle_expand, tr("tip_cal_expand"))
        self.btn_expand.pack(side="right")
        self.btn_lock = top_button(GLYPH["lock"], self.toggle_lock, tr("tip_cal_locked"))
        self.btn_lock.pack(side="right")
        self.btn_today = top_button(TODAY_GLYPH, self.this_month, tr("tip_today_month"))
        self.btn_today.pack(side="right")
        # the top row moves an undocked calendar; a docked one takes its note (and the notes
        # snapped to it) along
        for w in (self.grab, head, self.title):
            w.configure(cursor="fleur")
            w.bind("<ButtonPress-1>", self._move_start)
            w.bind("<B1-Motion>", self._move_to)
            w.bind("<ButtonRelease-1>", self._move_end)
        self._show_state()

        self.grid = tk.Canvas(self.frame, width=self.cell_w * 7, height=self.head_h + self.cell_h * 6,
                              bd=0, highlightthickness=0, cursor="hand2")
        self.grid.pack(padx=px(4), pady=(px(2), px(4)))
        self.grid.bind("<ButtonRelease-1>", self._click)
        self.grid.bind("<Double-Button-1>", self._double)
        self.grid.bind("<ButtonPress-1>", self._press)          # big view: a memo title can be dragged
        self.grid.bind("<B1-Motion>", self._chip_move)          # onto another day
        self._chip_drag = None
        self.grid.bind("<Motion>", self._motion)
        self.grid.bind("<Leave>", lambda e: (self._set_hover(None), self.hide_peek()))
        self.grid.bind("<MouseWheel>", self._peek_wheel)
        self.grid.bind("<Button-3>", self._context_menu)        # a day's memos: open, to the bin
        self._picked = None                 # the memo title clicked last (outlined): Delete bins it
        for w in (top, self.grid):
            w.bind("<Delete>", self._delete_key)
        self.preview: MemoPreview | None = None     # a day's memo, shown while resting on the day
        self._peek = None                   # (day, its memos, which one) for the preview
        self._peek_key = None
        self._peek_job = None
        self._pointer = None                # a test's pointer for the preview (else the real one)
        self._peek_dropped = None           # the day whose preview has dropped in
        self._peek_spot = None              # (x, y, w, h) where the preview sits
        # what a red day is, shown under the month after clicking it
        self.detail = tk.Frame(self.frame, bd=0)
        self.detail_name = tk.Label(self.detail, font=(UI_BOLD, 9, "bold"), anchor="w", justify="left")
        self.detail_name.pack(fill="x")
        self.detail_text = tk.Label(self.detail, font=(UI_FONT, 8), anchor="w", justify="left",
                                    wraplength=self.cell_w * 7)
        self.detail_text.pack(fill="x")             # (never packed: the HolidayCard shows it)
        self.holiday_card = HolidayCard(self)
        # the big view's bottom-right corner: drag to make its days bigger or smaller
        g = px(12)
        self.grip = tk.Canvas(self.frame, width=g, height=g, bd=0, highlightthickness=0, cursor="size_nw_se")
        self.grip.bind("<ButtonPress-1>", self._resize_start)
        self.grip.bind("<B1-Motion>", self._resize_move)
        self.grip.bind("<ButtonRelease-1>", self._resize_end)
        Tooltip(self.grip, tr("tip_cal_resize"))
        self.grip.bind("<Enter>", lambda e: self.hide_peek(), add="+")
        self._resize = None
        self._rows = 6
        self._show_state()

        self.recolor(self.app.theme_colors())   # the main theme color (Settings), not the memo's
        self._sizes()                       # now that the top bar exists: the days fill its width
        self.detail_text.configure(wraplength=self.cell_w * 7)
        self.draw()
        # as see-through as its note, but solid while the mouse is on it, so the desktop
        # behind does not show through the day numbers and memo titles
        self._pointed = self._closing = False
        top.bind("<Enter>", lambda e: self._point(True), add="+")
        top.bind("<Leave>", lambda e: self.top.after(60, self._check_pointer), add="+")
        top.attributes("-alpha", 0.0)       # built withdrawn: reveal() shows it where its plan put it
        top.update_idletasks()
        self.least = self.least_size()
        self.target_box = None
        self._built = True

    # -- see-through
    def _target_alpha(self):
        """Solid under the mouse; else as see-through as its note, but never past CAL_MIN_ALPHA."""
        return 1.0 if self._pointed else max(self.nw.pad.alpha, CAL_MIN_ALPHA)

    def apply_alpha(self, animated=True):
        """See-through like the note, solid under the mouse; the change fades (HOVER_FADE_MS)."""
        if self._closing or animating(self.top, "slide"):     # the slide fades to the new value itself
            return
        try:
            if animated:
                fade(self.top, "alpha", _alpha(self.top), self._target_alpha(), HOVER_FADE_MS)
            else:
                stop_animation(self.top, "alpha")
                self.top.attributes("-alpha", self._target_alpha())
        except tk.TclError:
            pass

    def _slide(self, opening, done=None):
        """Opening: slide CAL_SLIDE px out from the note's side, fading in. Closing: back
        towards the note, fading out."""
        top = self.top
        stop_animation(top, "alpha")
        x, y = self._xy
        d = self.app.px(CAL_SLIDE) * (-1 if getattr(self, "side", "right") == "right" else 1)
        a0 = _alpha(top)

        def step(k):
            off = round(d * (1 - k)) if opening else round(d * k)
            top.geometry(f"+{x + off}+{y}")
            a1 = self._target_alpha() if opening else 0.0
            top.attributes("-alpha", a0 + (a1 - a0) * k)
        animate(top, "slide", CAL_SHOW_MS, step, done)

    def _point(self, on):
        if self._closing:
            return
        if on != self._pointed:
            self._pointed = on
            self.apply_alpha()

    def _check_pointer(self):
        """After a Leave: still on the calendar (moved onto a child widget)? Else see-through again."""
        try:
            x, y = self.top.winfo_pointerxy()
            t = self.top
            inside = (t.winfo_rootx() <= x < t.winfo_rootx() + t.winfo_width()
                      and t.winfo_rooty() <= y < t.winfo_rooty() + t.winfo_height())
        except tk.TclError:
            return
        self._point(inside)

    # -- size and position
    def _sizes(self):
        px = self.app.px
        if self.expanded:                           # the size the corner grip was dragged to, if any
            cw, ch = self.nw.pad.calendar_big_cell or BIG_CELL
            cw = min(max(cw, BIG_CELL_MIN[0]), BIG_CELL_MAX[0])
            ch = min(max(ch, BIG_CELL_MIN[1]), BIG_CELL_MAX[1])
            self.cell_w, self.cell_h, self.head_h = px(cw), px(ch), px(22)
        else:
            cw, ch = self.nw.pad.calendar_small_cell or SMALL_CELL
            cw = min(max(cw, SMALL_CELL_MIN[0]), SMALL_CELL_MAX[0])
            ch = min(max(ch, SMALL_CELL_MIN[1]), SMALL_CELL_MAX[1])
            self.cell_w, self.cell_h, self.head_h = px(cw), px(ch), px(20)
            head = getattr(self, "head", None)
            if head is not None:                    # the days fill the top bar's width: no empty sides
                head.update_idletasks()
                self.cell_w = max(self.cell_w, -(-(head.winfo_reqwidth() - 2 * px(4)) // 7))

    CARRIED = ("calendar_docked", "calendar_expanded", "calendar_pos", "calendar_big_pos",
               "calendar_big_cell", "calendar_small_cell", "calendar_side", "calendar_auto_big",
               "calendar_hold", "calendar_tile_block", "calendar_setups")    # its settings go with it to a new note

    def _note(self):
        """Its note, shown: a calendar left on its own (the note minimized) brings it back first."""
        nw = self.nw
        if getattr(nw, "minimized", False):
            nw.restore()
        return nw

    def rehome(self, nw):
        """The calendar belongs to ``nw`` from now on: the one calendar icon is on that note,
        days clicked open there and new memos start there; its size and view go along."""
        old = self.nw
        if nw is old:
            return
        for name in self.CARRIED:                   # copies: the two pads never share a list or dict
            setattr(nw.pad, name, _deepcopy(getattr(old.pad, name)))
        old.calendar, old.pad.calendar = None, False
        nw.calendar, nw.pad.calendar = self, True
        self.nw = nw
        self.app.space_changed()
        if self.target_box is not None and self.docked:     # it stays on the side it is on, facing its new note
            self.side = "left" if _dock_side(_pad_box(nw.pad), self.target_box) == "left" else "right"
        winapi.set_owner(self.top, nw.win)
        self.top.attributes("-topmost", nw.pad.pinned)
        self.apply_alpha(animated=False)
        self.app.calendar_buttons()
        self.app.request_save()

    def box(self):
        """Where it is on the screen: (x0, y0, x1, y1)."""
        self.top.update_idletasks()
        x, y = getattr(self, "_xy", None) or (self.top.winfo_rootx(), self.top.winfo_rooty())
        w, h = self._size()
        return x, y, x + w, y + h

    def _size(self):
        """(width, height) on the screen: fit_size where it is given, else what it asks for."""
        self.top.update_idletasks()
        fw, fh = self.fit_size or (None, None)
        return fw or self.top.winfo_reqwidth(), fh or self.top.winfo_reqheight()

    def _fit_cells(self, rows):
        """Day cells that fill fit_size: its width over the 7 days, its height over this
        month's weeks (5 or 6: no empty strip under a short month), within the view's
        smallest and biggest cells."""
        fw, fh = self.fit_size
        px = self.app.px
        lo, hi = (BIG_CELL_MIN, BIG_CELL_MAX) if self.expanded else (SMALL_CELL_MIN, SMALL_CELL_MAX)
        self.top.update_idletasks()
        other_w = self.top.winfo_reqwidth() - self.grid.winfo_reqwidth()
        other_h = self.top.winfo_reqheight() - self.grid.winfo_reqheight() - self._detail_h()
        if fw:
            self.cell_w = min(max((fw - other_w) // 7, px(lo[0])), px(hi[0]))
        if fh:
            self.cell_h = min(max((fh - other_h - self.head_h) // rows, px(lo[1])), px(hi[1]))

    def _detail_h(self):
        return self.detail.winfo_reqheight() + self.app.px(6) if self.detail.winfo_ismapped() else 0

    def _chrome(self, flush=True):
        """(width, height) of all but the day cells (the top bar, the weekday row, margins).
        ``flush``: run the idle tasks first, so a change just made is measured."""
        if flush:
            self.top.update_idletasks()
        return (self.top.winfo_reqwidth() - self.cell_w * 7,
                self.top.winfo_reqheight() - self.cell_h * getattr(self, "_rows", 6) - self._detail_h())

    def least_size(self, flush=True):
        """Its smallest size in this view (the smallest day cells, six week rows): auto layout
        gives it as many whole tiles as that needs. ``flush=False``: measured as Tk last laid it
        out, running no idle tasks (move_to, inside Motion's frame loop)."""
        lo, px = BIG_CELL_MIN if self.expanded else SMALL_CELL_MIN, self.app.px
        other_w, other_h = self._chrome(flush)
        return other_w + 7 * px(lo[0]), other_h + 6 * px(lo[1])

    def most_size(self, flush=True):
        """Its biggest size in this view (the biggest day cells, six week rows): the grip stops there."""
        hi, px = BIG_CELL_MAX if self.expanded else SMALL_CELL_MAX, self.app.px
        other_w, other_h = self._chrome(flush)
        return other_w + 7 * px(hi[0]), other_h + 6 * px(hi[1])

    def fit_tile(self, width, height=None):
        """Auto layout: exactly width x height (whole tiles), its day cells stretched to fill
        it (six week rows: a five-week month leaves a strip at the bottom). None: back to its
        own size."""
        if not width:
            if self.tile_size:
                self.tile_size = self.tile_spot = self.fit_size = None
                self.top.geometry("")
                self._sizes()
                self.draw()
                self.place()
            return
        self.tile_size = self.fit_size = (width, height)
        self._sizes()
        self.detail_text.configure(wraplength=self.cell_w * 7)
        self.draw()
        self.place()

    def place(self):
        """Docked: sit on the saved side of the note again (it moved), at the size it has. Undocked:
        where pad.calendar_pos says. It chooses nothing and never goes to another note; nothing
        before the calendar has a plan (target_box)."""
        b = self.target_box
        if b is None or getattr(self, "_closing", False):
            return
        pad = self.nw.pad
        w, h = b[2] - b[0], b[3] - b[1]
        if self.docked:
            note = _pad_box(pad)
            x, y = calgeom.spot_box(note, pad.calendar_side or _dock_side(note, b), w, h, self.app._gap())[:2]
        else:                                   # (docked: no clamp, the pair slides in as one: settle_drop)
            x, y = pad.calendar_pos or b[:2]
            left, top_, right, bottom = self.app.area_of((int(x), int(y), int(x) + w, int(y) + h))
            x = min(max(int(x), left), max(left, right - w))
            y = min(max(int(y), top_), max(top_, bottom - h))
        x, y = int(x), int(y)
        if (x, y, x + w, y + h) != tuple(b) or (x, y) != getattr(self, "_xy", None):
            self.move_to((x, y, x + w, y + h))
        src = self.app.ring_source              # moving with a group: the line goes around it here
        if src is not None and src._group:
            self.app.ring.move(src._live_ring_boxes())

    def move_to(self, box) -> None:
        """Be exactly ``box`` (a plan's box: the end of a glide, or where one was stopped): its
        geometry, fit_size its size, target_box and least as place() keeps them. It does not
        choose a side or go to another note, and draws nothing: whoever changed its size or
        view drew it already (and set least then). It runs no idle tasks: Motion calls
        it inside its frame loop."""
        if getattr(self, "_closing", False):
            return
        x0, y0, x1, y1 = (int(v) for v in box)
        w, h = x1 - x0, y1 - y0
        top = self.top
        if animating(top, "slide"):
            stop_animation(top, "slide")
            self.apply_alpha(animated=False)
        self.fit_size = (w, h)
        top.geometry(f"{w}x{h}+{x0}+{y0}")
        self._xy = (x0, y0)
        self.target_box = (x0, y0, x1, y1)
        self.least = self.least_size(flush=False)
        pad = self.nw.pad
        note = _pad_box(pad)
        if self.docked:
            self._dock_offset = (x0 - note[0], y0 - note[1])
            self.side = "left" if _dock_side(note, self.target_box) == "left" else "right"
        else:
            self.side = "left" if x0 < pad.x else "right"
        self._place_grip()
        self.app.space_changed()

    def follow_note(self):
        """Its note's destination changed (it glides, or stopped gliding): docked, target_box
        is where it will be beside the note (kept from place())."""
        if self.docked and self._dock_offset is not None and self.target_box is not None:
            nx, ny = _pad_box(self.nw.pad)[:2]
            (ox, oy), b = self._dock_offset, self.target_box
            self.target_box = (nx + ox, ny + oy, nx + ox + b[2] - b[0], ny + oy + b[3] - b[1])
        self.app.space_changed()

    # -- docking: the side, the view and the box, as one plan
    def _least_for(self, view):
        """Its least size in ``view`` ("mini" or "big"), whichever it shows now."""
        big, px = view == "big", self.app.px
        lo = BIG_CELL_MIN if big else SMALL_CELL_MIN
        other_w, other_h = self._chrome()
        other_h += px(22 if big else 20) - self.head_h          # (the weekday row's height is the view's)
        return other_w + 7 * px(lo[0]), other_h + 6 * px(lo[1])

    def _rule(self, side, note, fw, fh, view0):
        """(view, auto_big, hold): the view it shows stays. Only the user's click (click_view) changes
        it: the mini is locked at its size and the big one capped, so a taller or shorter note no
        longer turns it big or mini (that flipped the calendar at every release of a note resize)."""
        return view0, False, None

    def _stretch_rule(self, side, note, fw, fh, view0):
        """The old stretch rule (unused): a mini stretched past STRETCH_UP became big, a big one
        squeezed below STRETCH_DOWN went back to mini."""
        px, gap, pad = self.app.px, self.app._gap(), self.nw.pad
        lens = {v: self._least_for(v) for v in ("mini", "big")}
        lo = BIG_CELL_MIN if view0 == "big" else SMALL_CELL_MIN
        cur = lens[view0]
        _cw, _ch, ratio = calgeom.fit_cells(fw, fh, cur[0] - 7 * px(lo[0]), cur[1] - 6 * px(lo[1]), 6)
        bw, bh = lens["big"]
        beside = side in ("right", "left")
        big_box = calgeom.spot_box(note, side, bw if beside else max(fw, bw), max(fh, bh) if beside else bh, gap)
        big_fits = geom.fits_one(big_box, self.app.usable())
        chrome_w, chrome_h = bw - 7 * px(BIG_CELL_MIN[0]), bh - 6 * px(BIG_CELL_MIN[1])
        can_fill = fh <= chrome_h + 6 * px(BIG_CELL_FILL[1]) if beside else fw <= chrome_w + 7 * px(BIG_CELL_FILL[0])
        return calgeom.stretch_view(ratio, view0, pad.calendar_auto_big, pad.calendar_hold, big_fits, can_fill)

    def _box_for(self, side, note, view):
        """The calendar's box on ``side`` of ``note`` in ``view``: matched to the note along the
        shared edge, at least its least size, the other side just wide (or tall) enough that
        its days are no more than 1.75 times longer than wide."""
        px = self.app.px
        lw, lh = self._least_for(view)
        lo, hi = (BIG_CELL_MIN, BIG_CELL_MAX) if view == "big" else (SMALL_CELL_MIN, SMALL_CELL_MAX)
        mw, mh = calgeom.match_size(side, note[2] - note[0], note[3] - note[1], lw, lh)
        chrome_w, chrome_h = lw - 7 * px(lo[0]), lh - 6 * px(lo[1])
        if side in ("right", "left"):
            cw, _ = calgeom.cap_ratio(px(lo[0]), (mh - chrome_h) / 6, "w")
            w, h = chrome_w + 7 * min(max(cw, px(lo[0])), px(hi[0])), mh
        else:
            _, ch = calgeom.cap_ratio((mw - chrome_w) / 7, px(lo[1]), "h")
            w, h = mw, chrome_h + 6 * min(max(ch, px(lo[1])), px(hi[1]))
        # never past its view's most size: beside a taller (wider) note it stays top (left) aligned
        w, h = min(w, chrome_w + 7 * px(hi[0])), min(h, chrome_h + 6 * px(hi[1]))
        return calgeom.spot_box(note, side, w, h, self.app._gap())

    def plan_dock(self, side: str | None = None, note_box=None, *, view: str | None = None, keep: bool = False):
        """(side, view, cal_box, clear): where the docked calendar goes against ``note_box`` (the
        owner's destination), in which view, and whether that box is free. ``side``: tried
        first (the saved one). ``keep``: stay on it whenever it fits a screen (a resize or view
        switch must not hop sides). ``view``: forced (the user's own click). No side fits any
        screen (G7): (None, "mini", a free spot for the mini, False). Saves calendar_side."""
        app, pad, gap = self.app, self.nw.pad, self.app._gap()
        note = tuple(note_box) if note_box is not None else geom.pad_box(pad)
        areas = app.usable()
        obstacles = [s.box for s in app.space({pad.id, CAL})]
        view0 = "big" if self.expanded else "mini"
        cur = self._least_for(view0)
        fits, sizes = {}, {}
        for s in calgeom.SIDES:
            mw, mh = calgeom.match_size(s, note[2] - note[0], note[3] - note[1], *cur)
            v, auto_big, hold = (view, False, view) if view else self._rule(s, note, mw or cur[0], mh or cur[1], view0)
            b = self._box_for(s, note, v)
            fits[s], sizes[s] = (v, auto_big, hold, b), (b[2] - b[0], b[3] - b[1])
        center = geom.center(self.target_box) if self.target_box is not None else None
        given = side if side in calgeom.SIDES else None
        chosen, clear = None, False
        if given and geom.fits_one(fits[given][3], areas) and (
                keep or geom.is_free(fits[given][3], areas, obstacles, gap)):
            chosen, clear = given, geom.is_free(fits[given][3], areas, obstacles, gap)
        else:
            chosen, clear = calgeom.choose_side(note, center, sizes, areas, obstacles, gap)
            if given and not clear and geom.fits_one(fits[given][3], areas):
                chosen = given
        if chosen is None:                                  # G7: undock at the nearest free spot
            lw, lh = self._least_for("mini")
            origin = calgeom.spot_box(note, "right", lw, lh, gap)[:2]
            b, _how = app.find_spot(lw, lh, origin, exclude=(CAL, pad.id) if note_box is not None else (CAL,),
                                    avoid=(note,) if note_box is not None else ())
            return None, "mini", b, False
        v, auto_big, hold, b = fits[chosen]
        pad.calendar_side = chosen
        self._plan_flags = (auto_big, hold)
        return chosen, v, b, clear

    def set_view(self, view: str) -> None:
        """Both ``expanded`` flags, then what toggle_expand redraws, then least (Global Constraints)."""
        big = view == "big"
        pad = self.nw.pad
        if big == self.expanded:
            pad.calendar_expanded = big
            return
        self.expanded = pad.calendar_expanded = big
        self._sizes()
        self.detail_text.configure(wraplength=self.cell_w * 7)
        self._show_state()
        self.draw()
        self.least = self.least_size()

    def take_plan(self, side, view) -> None:
        """Adopt the view (and its auto-big flag and hold) of a plan_dock result."""
        if side is None:
            return
        pad = self.nw.pad
        pad.calendar_auto_big, pad.calendar_hold = getattr(self, "_plan_flags",
                                                           (pad.calendar_auto_big, pad.calendar_hold))
        self.set_view(view)

    def undock_to(self, cal_box) -> None:
        """G7: it undocks (mini view) at ``cal_box``; the caller moves it there."""
        pad = self.nw.pad
        self.docked = pad.calendar_docked = False
        self.set_view("mini")
        self._dock_offset = None
        self._show_state()
        self.app.space_changed()
        pad.calendar_pos = list(cal_box[:2])

    def _undocked_box(self):
        """Opening undocked: at calendar_pos (else calendar_big_pos, else beside its note), at its own size."""
        pad, app = self.nw.pad, self.app
        self.fit_size = None
        self.top.geometry("")
        w, h = self._size()
        pos = pad.calendar_pos or pad.calendar_big_pos
        if pos is None:
            note, gap, areas = geom.pad_box(pad), app._gap(), app.usable()
            boxes = [calgeom.spot_box(note, s, w, h, gap) for s in calgeom.SIDES]
            box = next((b for b in boxes if geom.fits_one(b, areas)), boxes[0])
            pos = box[:2]
        x, y = int(pos[0]), int(pos[1])
        left, top_, right, bottom = app.area_of((x, y, x + w, y + h))
        x, y = min(max(x, left), max(left, right - w)), min(max(y, top_), max(top_, bottom - h))
        if pad.calendar_pos is None:
            pad.calendar_pos = [x, y]
        return x, y, x + w, y + h

    def open(self, how: str = "user") -> None:
        """Opening (built withdrawn; this plans it and shows it). ``how``: "user" (pushes, offers
        Undo), "start" (docked: one grow; undocked: move_to), "language" (move_to, no push)."""
        app, pad = self.app, self.nw.pad
        label = "calendar_opened" if how == "user" else None
        box = None
        if self.docked:
            side, view, cal_box, _clear = self.plan_dock(side=pad.calendar_side)
            if side is not None:
                self.take_plan(side, view)
                note = geom.pad_box(pad)
                if how == "language":
                    self.move_to(cal_box)
                else:
                    app.grow({pad.id: geom.union([note, cal_box])}, "app", label, by_calendar=True,
                             parts={pad.id: (note, cal_box)})
                self.reveal()
                return
            self.undock_to(cal_box)
            box = cal_box
        if box is None:
            box = self._undocked_box()
        if how == "user":
            app.grow({CAL: box}, "app", label, by_calendar=True)
        else:
            self.move_to(box)
        self.reveal()

    def reveal(self) -> None:
        """Show it where its plan put it (target_box), sliding out and fading in."""
        b = self.target_box
        if b is None or getattr(self, "_closing", False):
            return
        top = self.top
        self.fit_size = (b[2] - b[0], b[3] - b[1])
        self.draw()
        self.move_to(b)
        top.update_idletasks()
        self.least = self.least_size()
        top.attributes("-alpha", 0.0)       # it slides out from beside its note, fading in
        top.deiconify()
        top.update_idletasks()
        winapi.set_owner(top, self.nw.win)
        top.attributes("-topmost", self.nw.pad.pinned)
        top.lift()
        self._place_grip()
        self._slide(opening=True)

    def _show_state(self):
        self.btn_lock.set_glyph(GLYPH["lock" if self.docked else "unlock"])
        self.btn_lock.tooltip.text = tr("tip_cal_locked" if self.docked else "tip_cal_unlocked")
        self.btn_expand.set_glyph(GLYPH["shrink" if self.expanded else "expand"])
        self.btn_expand.tooltip.text = tr("tip_cal_shrink" if self.expanded else "tip_cal_expand")
        self._place_grip()

    def _place_grip(self):
        """The size grip (big view only: the mini is locked at its size): bottom right, or bottom
        left when it is docked on the note's left (that side moves as it grows, so the grip stays
        under the mouse)."""
        grip = getattr(self, "grip", None)
        if grip is None:
            return
        if not self.expanded:
            grip.place_forget()
            return
        on_left = self.docked and getattr(self, "side", "right") == "left"
        if on_left:
            grip.place(relx=0, rely=1, anchor="sw")
        else:
            grip.place(relx=1, rely=1, anchor="se")
        if on_left != getattr(self, "_grip_left", None):
            self._grip_left = on_left
            grip.configure(cursor="size_ne_sw" if on_left else "size_nw_se")
            self._draw_grip()
        tk.Misc.tkraise(grip)

    # -- one plan for the docked pair (a match, a view switch, a resize)
    def _grow_docked(self, note, side, view, cal_box, mode, label) -> None:
        """The docked pair becomes ``note`` and ``cal_box`` (from plan_dock) in one grow. ``side``
        None (G7): the calendar undocks to ``cal_box`` in that same grow."""
        app, pad = self.app, self.nw.pad
        parts = {pad.id: (note, cal_box)}
        if side is None:
            app.grow({pad.id: note, CAL: cal_box}, mode, label, by_calendar=True, parts=parts)
            self.undock_to(cal_box)
            return
        self.take_plan(side, view)
        app.grow({pad.id: geom.union([note, cal_box])}, mode, label, by_calendar=True, parts=parts)

    def refit(self, note, mode="app", label="resized") -> None:
        """Docked: its note is (going to be) ``note``: match it, pick the view, one grow."""
        if not self.docked or self.target_box is None or getattr(self, "_closing", False):
            return
        side, view, cal_box, _clear = self.plan_dock(side=self.nw.pad.calendar_side, note_box=note, keep=True)
        self._grow_docked(tuple(note), side, view, cal_box, mode, label)

    def settle_view(self) -> None:
        """After its note was resized: match it again and pick the view by the stretch rule. In auto
        layout the grid plan decides: it applies ``grid_view`` (set by App's adapter; unset, for
        instance right after set_language rebuilt the calendar: the view stays) and runs no grow."""
        if self.app.prefs.auto_layout:
            view = getattr(self, "grid_view", None)
            if view in ("mini", "big"):
                self.set_view(view)
            return
        if self.docked and self.target_box is not None:
            old, was_big = tuple(self.target_box), self.expanded
            self.refit(geom.pad_box(self.nw.pad))
            if was_big and not self.expanded:       # P4: back to mini gives its room back
                self._gave_room(old)

    def _gave_room(self, old) -> None:
        """P4: it got smaller than ``old`` (its box before): the notes it moved go back."""
        new = self.target_box
        if new is not None and old is not None and (new[2] - new[0] < old[2] - old[0]
                                                    or new[3] - new[1] < old[3] - old[1]):
            self.app.give_back(toward=tuple(new))

    # -- resizing (its corner grip), docked or not, big or small
    def _resize_start(self, event):
        """The grip only shows the new size while it is dragged; the one plan runs at the release."""
        if self.target_box is None or not self.expanded:      # (the mini has no grip: locked at its size)
            return
        self._resize = (event.x_root, event.y_root)
        self._resize_from = tuple(self.target_box)
        self._most = self.most_size()
        self._grip_size = None
        self._resize_job = None

    def _grip_side(self) -> str:
        if self.docked:
            return self.nw.pad.calendar_side or getattr(self, "side", "right")
        return "left" if getattr(self, "_grip_left", False) else "right"

    def _room(self, b, side) -> tuple[int, int]:
        """The most width and height a calendar whose box is ``b`` may have on ``side`` of its note: up to
        the edge of its screen's usable area, on the side it grows towards (left and above grow the other way)."""
        a = self.app.area_of(b)
        return (b[2] - a[0] if side == "left" else a[2] - b[0]), (b[3] - a[1] if side == "above" else a[3] - b[1])

    def _resize_move(self, event):
        if not self._resize:
            return
        x0, y0 = self._resize
        b = self._resize_from
        left = getattr(self, "_grip_left", False)
        dx = (x0 - event.x_root) if left else (event.x_root - x0)
        lw, lh = self.least or (0, 0)
        mw, mh = self._room(b, self._grip_side())      # it stops growing at the screen's edge (the cursor may go on)
        mw, mh = min(mw, self._most[0]), min(mh, self._most[1])     # and at its most size
        w, h = max(min(b[2] - b[0] + dx, mw), lw), max(min(b[3] - b[1] + event.y_root - y0, mh), lh)
        self._grip_size = (w, h)
        self.fit_size = (w, h)
        self.top.geometry(f"{w}x{h}+{b[2] - w if left else b[0]}+{b[1]}")
        if not self._resize_job:                # redraw once per idle moment, not per mouse move
            self._resize_job = self.top.after_idle(self._draw_live)

    def _draw_live(self):
        self._resize_job = None
        if self.top.winfo_exists():
            self.draw()

    def _resize_end(self, _event=None):
        if not self._resize:
            return
        self._resize = None
        if self._resize_job:
            self.top.after_cancel(self._resize_job)
            self._resize_job = None
        size, self._grip_size = self._grip_size, None
        b0 = self._resize_from
        if size is not None and size != (b0[2] - b0[0], b0[3] - b0[1]):
            self._commit_size(*size)
            self._gave_room(b0)
        if not self.app.motion.drives(CAL) and self.target_box is not None:    # (nothing moved it: back as it was)
            tb = self.target_box
            self.fit_size = (tb[2] - tb[0], tb[3] - tb[1])
            self.draw()
            self.move_to(tb)
        self.app.request_save()

    def _commit_size(self, w, h):
        """The grip was let go at ``w`` x ``h``: the shared side takes the note along (unless the
        two sides were unequal: then the calendar alone, until they match), the view follows the
        stretch rule, and it is all one grow (drag mode: it stops at the screen's edge)."""
        app, pad, gap, px = self.app, self.nw.pad, self.app._gap(), self.app.px
        b0 = self._resize_from
        view0 = "big" if self.expanded else "mini"
        if not self.docked:
            fake = (b0[0] - gap, b0[1], b0[0] - gap, b0[1])     # (a note whose right side is at b0's left edge)
            view, auto_big, hold = self._rule("right", fake, w, h, view0)
            pad.calendar_auto_big, pad.calendar_hold = auto_big, hold
            if view != view0:
                lw, lh = self._least_for(view)
                w, h = max(w, lw), max(h, lh)
            self.set_view(view)
            app.grow({CAL: (b0[0], b0[1], b0[0] + w, b0[1] + h)}, "drag", "resized", by_calendar=True)
            return
        note = geom.pad_box(pad)
        side = pad.calendar_side or _dock_side(note, b0)
        if side in ("right", "left"):
            old, now, was = note[3] - note[1], h, b0[3] - b0[1]
        else:
            old, now, was = note[2] - note[0], w, b0[2] - b0[0]
        if was == old or (was > old and now < old) or (was < old and now > old):     # level, or they meet
            if side in ("right", "left"):
                note = (note[0], note[1], note[2], note[1] + max(now, px(MIN_H)))
            else:
                note = (note[0], note[1], note[0] + max(now, px(MIN_W)), note[3])
        view, auto_big, hold = self._rule(side, note, w, h, view0)
        if view != view0:
            lw, lh = self._least_for(view)
            w, h = max(w, lw), max(h, lh)
        cal_box = calgeom.spot_box(note, side, w, h, gap)
        pad.calendar_side = side
        self._plan_flags = (auto_big, hold)
        self._grow_docked(note, side, view, cal_box, "drag", "resized")

    def grip_drag(self, dx, dy) -> None:
        """Test-facing: drag the grip by (dx, dy) with synthetic events and let go."""
        import types

        def ev(a, b):
            return types.SimpleNamespace(x_root=int(a), y_root=int(b), state=0)
        self._resize_start(ev(1000, 1000))
        self._resize_move(ev(1000 + dx, 1000 + dy))
        self._resize_end()

    def _draw_grip(self):
        g, c = self.grip, getattr(self, "colors", None)
        if c is None:
            return
        g.configure(bg=c.bg)
        g.delete("all")
        size = int(g.cget("width"))
        dot = max(2, size // 6)
        step = dot + 1
        left = getattr(self, "_grip_left", False)
        for row in range(3):                 # the same corner dots as the note's (mirrored on the left)
            for col in range(3 - row):
                x, y = size - (col + 1) * step, size - (row + 1) * step
                if left:
                    x = size - dot - x
                g.create_rectangle(x, y, x + dot, y + dot, fill=c.border, outline="")

    def toggle_lock(self):
        """Lock on: the calendar (small or big) sits beside its note and moves with it.
        Off: it stays where it is and can be dragged by its top row."""
        app, pad = self.app, self.nw.pad
        if self.target_box is None:
            return
        if not self.docked:
            owner, toward = self._dock_owner()
            if owner is not self.nw:            # it sits beside another note now: that note takes it
                self.rehome(owner)              # (and its calendar icon: App.calendar_buttons)
                pad = owner.pad
            if toward is not None:              # on the side it is on now, not the one saved before
                pad.calendar_side = toward
            side, view, cal_box, _clear = self.plan_dock(side=pad.calendar_side)
            if side is None:                    # G7: nothing fits, so it stays where it is
                return
            self.take_plan(side, view)
            note = geom.pad_box(pad)
            app.grow({pad.id: geom.union([note, cal_box])}, "app", "calendar_opened", by_calendar=True,
                     parts={pad.id: (note, cal_box)})
            self.docked = pad.calendar_docked = True
            self._dock_offset = (cal_box[0] - note[0], cal_box[1] - note[1])
            self.side = "left" if side == "left" else "right"
        else:
            self.docked = pad.calendar_docked = False
            self._dock_offset = None
            pad.calendar_pos = list(self.target_box[:2])
        self._show_state()
        app.space_changed()
        app.request_save()
        app.arrange_soon()                  # auto layout: a docked calendar takes tiles, a free one not

    def _dock_owner(self):
        """(note, side): locking it again, the shown note it sits beside (left or right of it,
        rows shared, within the magnet's reach) takes it, the nearest one, its own note first
        on a tie; ``side`` is where the calendar is from that note. None beside: its own note,
        on its saved side (side None)."""
        app = self.app
        cb = tuple(self.target_box)
        reach = app.px(SNAP_REACH) + app._gap()
        best = None
        for w in app.windows.values():
            if w._closing or getattr(w, "minimized", False) or w.win.state() != "normal":
                continue
            nb = geom.pad_box(w.pad)
            rows = min(cb[3], nb[3]) - max(cb[1], nb[1])
            if rows <= 0:
                continue
            dx = max(0, nb[0] - cb[2], cb[0] - nb[2])
            if dx > reach:
                continue
            key = (dx, w is not self.nw, -rows)
            if best is None or key < best[0]:
                side = "left" if cb[0] + cb[2] < nb[0] + nb[2] else "right"
                best = (key, w, side)
        return (best[1], best[2]) if best else (self.nw, None)

    def toggle_expand(self):
        """The big month view with each day's memo titles, and back to the small one."""
        self.click_view("mini" if self.expanded else "big")

    def click_view(self, view: str) -> None:
        """The user's own click on a view (option 4, "살짝 사라졌다 나타나기"): the calendar dips out
        (VIEW_DIP_MS), switches while it can't be seen (no half-way frames), then fades back."""
        top = self.top
        try:
            a0 = _alpha(top)
            shown = self.target_box is not None and top.winfo_ismapped() and a0 > 0.05
        except tk.TclError:
            shown = False
        if not shown or getattr(self, "_closing", False):
            self._click_view_now(view)
            return
        stop_animation(top, "alpha")

        def out(k):
            top.attributes("-alpha", a0 * (1 - k))

        def switch():
            self._click_view_now(view)
            if not getattr(self, "_closing", False):
                self.apply_alpha(animated=True)     # back to what it should be (HOVER_FADE_MS)
        animate(top, "dip", VIEW_DIP_MS, out, switch)

    def _click_view_now(self, view: str) -> None:
        """The switch itself: the choice is held (calendar_hold) until the stretch rule agrees with it."""
        self.hide_peek()
        app, pad = self.app, self.nw.pad
        pad.calendar_hold, pad.calendar_auto_big = view, False
        if self.target_box is None:
            self.set_view(view)
            return
        before = tuple(self.target_box)
        if self.docked:
            note = geom.pad_box(pad)
            side, v, cal_box, _clear = self.plan_dock(side=pad.calendar_side, view=view, keep=True)
            if view == "big" and side is not None:         # big goes no further than the room on its side
                rw, rh = self._room(cal_box, side)
                lw, lh = self._least_for("big")
                if lw > rw or lh > rh:                      # not even its least fits: it stays mini
                    pad.calendar_hold = None
                    side, v, cal_box, _clear = self.plan_dock(side=pad.calendar_side, view="mini", keep=True)
                elif cal_box[2] - cal_box[0] > rw or cal_box[3] - cal_box[1] > rh:
                    cal_box = calgeom.spot_box(note, side, min(cal_box[2] - cal_box[0], rw),
                                               min(cal_box[3] - cal_box[1], rh), app._gap())
            self._grow_docked(note, side, v, cal_box, "app", "resized")
        else:
            b = self.target_box
            self.fit_size = None
            self.top.geometry("")
            self.set_view(view)
            w, h = self._size()
            x, y = b[0], b[1]
            left, top_, right, bottom = app.area_of((x, y, x + w, y + h))
            if view == "big":
                lw, lh = self._least_for("big")
                if lw > right - left or lh > bottom - top_:     # not even its least fits: it stays mini
                    pad.calendar_hold = None
                    self.set_view("mini")
                    w, h = self._size()
                else:
                    w, h = min(w, right - left), min(h, bottom - top_)
            x, y = min(max(x, left), max(left, right - w)), min(max(y, top_), max(top_, bottom - h))
            app.grow({CAL: (x, y, x + w, y + h)}, "app", "resized", by_calendar=True)
            pad.calendar_pos = [x, y]
        self._gave_room(before)
        app.request_save()
        app.arrange_soon()                  # auto layout: its column takes its new width

    def _move_start(self, event):
        if self.docked:                     # docked: dragging the calendar drags its note
            self._move = "note"
            self.nw._drag_start(event)
        else:
            self._move = (event.x_root - self.top.winfo_rootx(), event.y_root - self.top.winfo_rooty())
            app = self.app
            b = self.target_box or (self.top.winfo_rootx(), self.top.winfo_rooty(), 0, 0)
            ids = app.drag_group(CAL, bool(event.state & 0x20000)) - {CAL}   # the notes linked to it move along
            self._move_group = [(w, w.pad.x - b[0], w.pad.y - b[1]) for w in app.group_windows(CAL, ids)]
            self._move_places = {}
            self._snap_id = self._snap_hold = None
            app.moving = True
            app.motion.cancel({CAL} | {w.pad.id for w, _dx, _dy in self._move_group})

    def _move_to(self, event):
        if self._move == "note":
            self.nw._drag_move(event)
        elif self._move:
            dx, dy = self._move
            x, y = event.x_root - dx, event.y_root - dy
            if self.target_box is not None:
                app, group = self.app, self._move_group
                b = self.target_box
                self._snap_id = None
                if not event.state & 0x20000:       # Alt held: move freely
                    parts = [(x, y, x + b[2] - b[0], y + b[3] - b[1])] + \
                        [(x + ox, y + oy, x + ox + w.pad.width, y + oy + geom.shown_h(w.pad)) for w, ox, oy in group]
                    shape = geom.union(parts)
                    sx, sy, sid = app.snap(shape, {CAL} | {w.pad.id for w, _ox, _oy in group}, parts=parts)
                    x, y, self._snap_id = app.hold_snap(self, (x, y), (x + sx - shape[0], y + sy - shape[1]), sid)
                self._moved_to = [x, y]
                # its note moving along runs place() (<Configure>), which puts an undocked
                # calendar at calendar_pos: that is here now, not where the drag began
                self.nw.pad.calendar_pos = [x, y]
                self.move_to((x, y, x + b[2] - b[0], y + b[3] - b[1]))     # (target_box follows: space())
                self._move_places = {}
                for w, ox, oy in group:
                    if w.win.winfo_exists():
                        w.win.geometry(f"+{x + ox}+{y + oy}")
                        self._move_places[w] = (x + ox, y + oy)
            else:
                self._moved_to = [x, y]
                self.top.geometry("+%d+%d" % (x, y))

    def _move_end(self, _event=None):
        if self._move == "note":
            self._move = None
            self.nw._drag_end()
        elif self._move:
            self._move = None
            app = self.app
            app.moving = False
            places = {w: xy for w, xy in getattr(self, "_move_places", {}).items() if w.win.winfo_exists()}
            ids = {CAL} | {w.pad.id for w in places}
            snapped, self._snap_id = getattr(self, "_snap_id", None), None
            self._move_places, self._move_group = {}, []
            if app.prefs.auto_layout:               # #3B: it snaps to the nearest block of the grid
                if self.target_box is not None and getattr(self, "_moved_to", None):
                    self.nw.pad.calendar_pos = list(self._moved_to)
                app.arrange()
            elif self.target_box is not None and getattr(self, "_moved_to", None):
                app.settle_drop(ids, places=places)     # back in, clear of the rest (M1, M3)
            where = list(self.target_box[:2]) if self.target_box is not None else (
                getattr(self, "_moved_to", None) or [self.top.winfo_rootx(), self.top.winfo_rooty()])
            self._moved_to = None
            self.nw.pad.calendar_pos = where        # one saved spot for both views (R29)
            if snapped is not None:                     # M2: a snapped drop links to what it snapped to
                app.space_changed()
                app.link_drop(sorted(ids), snapped)
            app.settle_links()
            app.request_save()

    def move_drag(self, dx, dy) -> None:
        """Test-facing: drag the undocked calendar by (dx, dy) with synthetic events and let go."""
        import types
        x, y = self.top.winfo_rootx() + 10, self.top.winfo_rooty() + 3

        def ev(a, b):
            return types.SimpleNamespace(x_root=int(a), y_root=int(b), state=0)
        self._move_start(ev(x, y))
        self._move_to(ev(x + dx, y + dy))
        self._move_end()

    # -- months
    def next_month(self):
        self.hide_peek()
        self.holiday_card.hide()
        self._picked = None
        y, m = self.month
        self._page_to((y + 1, 1) if m == 12 else (y, m + 1))

    def prev_month(self):
        self.hide_peek()
        self.holiday_card.hide()
        self._picked = None
        y, m = self.month
        self._page_to((y - 1, 12) if m == 1 else (y, m - 1))

    def this_month(self):
        self.hide_peek()
        self.holiday_card.hide()
        today = date.today()
        self._page_to((today.year, today.month))

    def _page_to(self, month):
        """Show ``month``: the shown one slides out the way the arrow points and the new one slides
        in beside it (option 1, "밀어내기", MONTH_SLIDE_MS); the weekday row stays. A page still
        sliding is finished at once first. The same month: just a redraw."""
        g = self.grid
        stop_animation(g, "page")
        if getattr(self, "_paging", False):         # (a click during a slide: that slide is done now)
            self._paging = False
            self.draw()
        old = self.month
        self.month = month
        if month == old or not g.winfo_ismapped():
            self.draw()
            return
        way = 1 if month > old else -1
        g.addtag_all("old")
        g.delete("old&&wk")                         # (the weekday row is drawn again, and does not move)
        self.draw(keep="old")
        g.addtag_all("new")
        g.dtag("old", "new")
        g.dtag("wk", "new")
        width = max(g.winfo_width(), self.cell_w * 7)
        g.move("new", way * width, 0)
        g.addtag_withtag("paging", "old")           # both pages move as one (one move a frame)
        g.addtag_withtag("paging", "new")
        self._paging, shift = True, [0]

        def step(k):
            to = round(-way * width * k)
            if to != shift[0]:
                g.move("paging", to - shift[0], 0)
                shift[0] = to

        def done():
            self._paging = False
            self.draw()                             # a clean page at the end (hit boxes, hover)
        animate(g, "page", MONTH_SLIDE_MS, step, done, ease=_ease_out_sine)

    # -- days
    def marked_days(self):
        prefix = "%04d-%02d" % self.month
        return {iso for iso in self._memos_by_day() if iso.startswith(prefix)}

    def pick_day(self, iso):
        self.selected = iso
        self._note().show_list(day=iso)
        self.draw()
        self.show_details(iso)

    def show_details(self, iso):
        """A card under the picked day: what its holiday is (nothing for an ordinary day). It
        takes no space and never moves the calendar or a note (#17A)."""
        if iso:
            self.holiday_card.show(iso)
        else:
            self.holiday_card.hide()

    def new_memo_on(self, iso):
        self.selected = iso
        self._note().new_memo(date=iso)
        self.draw()

    def _date_at(self, x, y):
        for x0, y0, x1, y1, d in self._cells:
            if x0 <= x < x1 and y0 <= y < y1:
                return d
        return None

    def _accent(self):
        """Selection lines in the calendar: the main theme color, a soft step stronger than the
        calendar itself (not the vivid outline color), and never fainter than MARK_CONTRAST. On a
        pale page (a strong theme color) the theme color itself."""
        c = self.colors
        line = c.color if c.tinted else _mix(self.top, accent_color(self.top, c.bg, c.bg), c.bg, 0.4)
        return readable(self.top, line, c.bg, MARK_CONTRAST)

    def _deep(self):
        """The theme color, deep: the selected day's circle and the day count (text: TEXT_CONTRAST)."""
        c = self.colors
        r, g, b = _rgb(self.top, c.bg)
        h, _l, s = colorsys.rgb_to_hls(r, g, b)
        s = 0.0 if s < 0.08 or max(r, g, b) - min(r, g, b) < 0.04 else max(s, 0.55)
        deep = "#%02X%02X%02X" % tuple(round(v * 255) for v in colorsys.hls_to_rgb(h, 0.75 if c.dark else 0.33, s))
        return readable(self.top, deep, c.bg, TEXT_CONTRAST)

    def _mark(self, color):
        """A memo's mark on the calendar (bars under a day, period lines): its color, deep,
        and at least MARK_CONTRAST against the calendar."""
        return readable(self.top, shade(self.top, color, 3), self.colors.bg, MARK_CONTRAST)

    def _count_card(self, event, a, b):
        """While dragging across days: a small theme card by the mouse, "11/10 ~ 11/13 · 4 days"."""
        c, px = self.colors, self.app.px
        top = getattr(self, "_count_top", None)
        if top is None:
            top = self._count_top = tk.Toplevel(self.top)
            top.withdraw()
            top.overrideredirect(True)
            top.configure(bg=TIP_KEY)
            try:
                top.attributes("-transparentcolor", TIP_KEY)
            except tk.TclError:
                pass
            self._count_cv = tk.Canvas(top, bg=TIP_KEY, bd=0, highlightthickness=0)
            self._count_cv.pack()
        cv = self._count_cv
        cv.delete("all")
        pad, pady = px(10), px(6)
        span = f"{_date_label(a.isoformat())} ~ {_date_label(b.isoformat())} · "
        t1 = cv.create_text(pad, pady, anchor="nw", text=span, fill=c.fg, font=(UI_FONT, 9))
        cv.create_text(cv.bbox(t1)[2], pady, anchor="nw", text=tr("period_days", n=(b - a).days + 1),
                       fill=self._deep(), font=(UI_BOLD, 9, "bold"))
        x1, y1 = cv.bbox("all")[2:]
        w, h = x1 + pad, y1 + pady
        self._count_photo = ImageTk.PhotoImage(_rounded_card(w, h, px(7), c.bg, c.border), master=top)
        cv.configure(width=w, height=h)
        cv.tag_lower(cv.create_image(0, 0, anchor="nw", image=self._count_photo))
        top.geometry(f"+{event.x_root + px(16)}+{event.y_root + px(18)}")
        if not top.winfo_ismapped():
            top.deiconify()
            top.attributes("-topmost", True)
        top.lift()

    def _hide_count(self):
        top = getattr(self, "_count_top", None)
        if top is not None:
            top.withdraw()

    def _ring(self, x0, y0, x1, y1, tag, r=None):
        """A thin rounded selection line in the theme color (the shape of the moving-group line)."""
        px = self.app.px
        r = px(6) if r is None else r
        return self.grid.create_polygon(_round_rect(x0, y0, x1, y1, r), smooth=True, fill="",
                                        outline=self._accent(), width=max(1, px(1)), tags=(tag,))

    def _chip_at(self, x, y):
        return next((note for x0, y0, x1, y1, note in self._chips if x0 <= x < x1 and y0 <= y < y1), None)

    # -- dragging a memo title (big view) onto another day
    def _press(self, event):
        """Press on a memo title (big view): it can be dragged to other days. Press on a day:
        dragging across days makes a period memo."""
        self.hide_peek()
        note = self._chip_at(event.x, event.y) if self.expanded else None
        day = self._date_at(event.x, event.y)
        if note is None and day is None:
            self._chip_drag = None
            return
        self._chip_drag = {"note": note, "day": day, "x": event.x, "y": event.y, "moving": False}

    def _chip_move(self, event):
        d, px = self._chip_drag, self.app.px
        if not d:
            return
        if d["note"] is None:               # across days: the period it would make
            self._range_move(event)
            return
        if not d["moving"]:
            if abs(event.x - d["x"]) + abs(event.y - d["y"]) < px(6):
                return
            d["moving"] = True
            self.grid.configure(cursor="fleur")
        g, c, note = self.grid, self.colors, d["note"]
        g.delete("ghost")
        day = self._date_at(event.x, event.y)
        for x0, y0, x1, y1, dd in self._cells:          # the day it would land on: outlined
            if dd == day:
                self._ring(x0 + 2, y0 + 2, x1 - 2, y1 - 2, "ghost")
        w, h = self.cell_w - px(8), px(MEMO_CHIP_H)
        x, y = event.x - w // 2, event.y - h // 2
        nc = Colors.of(self.top, note.color)
        g.create_rectangle(x, y, x + w, y + h, fill=nc.bg, outline=shade(self.top, note.color, 3),
                           tags=("ghost",))
        g.create_text(x + px(4), y + h / 2, anchor="w", text=memo_title(note), font=(UI_FONT, 9),
                      fill=nc.fg, tags=("ghost",))

    def _range_move(self, event):
        d, g, c, px = self._chip_drag, self.grid, self.colors, self.app.px
        day = self._date_at(event.x, event.y)
        if day is None:
            return
        if not d["moving"]:
            if day == d["day"]:
                return
            d["moving"] = True
        d["end"] = day
        a, b = sorted((d["day"], day))
        g.delete("ghost")
        color = self.app.prefs.default_color or self.nw.note.color
        line = self._mark(color)
        days = [cell for cell in self._cells if a <= cell[4] <= b]
        rows: dict = {}
        for x0, y0, x1, y1, dd in days:
            r = rows.setdefault(y0, [x0, x1, y1])
            r[0], r[1] = min(r[0], x0), max(r[1], x1)
        for y0, (x0, x1, y1) in rows.items():       # the days outlined, a band across them
            self._ring(x0 + 2, y0 + 2, x1 - 2, y1 - 2, "ghost")
            by = y0 + (self._big_slot()[2] if self.expanded else round(px(22) * self.cell_h / px(SMALL_CELL[1])))
            if self.expanded:
                g.create_rectangle(x0 + px(4), by, x1 - px(4), by + px(PERIOD_BAND_H),
                                   fill=Colors.of(self.top, color).bg, outline=line, tags=("ghost",))
            else:
                g.create_line(x0 + px(5), by, x1 - px(5), by, width=px(3), fill=line, tags=("ghost",))
        self._count_card(event, a, b)               # how long: a card by the mouse

    def new_period(self, start: date, end: date):
        """A new plain memo from ``start`` to ``end`` (dragged across the days)."""
        nw = self.nw
        note = nw.new_memo(date=start.isoformat())
        note.end_date = end.isoformat() if end > start else None
        if note.style != "plain":           # a period memo starts as a plain one
            note.style = "plain"
            nw._layout()
        self.selected = start.isoformat()
        self._picked = note                 # just made: Delete bins it again (typing here unpicks it)
        nw._touch()
        self.app.refresh_lists()
        nw.body.focus_force()
        return note

    def _drop_chip(self, event):
        d, self._chip_drag = self._chip_drag, None
        g = self.grid
        g.configure(cursor="hand2")
        g.delete("ghost")
        if d["note"] is None:               # dragged across days: a new period memo
            self._hide_count()
            a, b = sorted((d["day"], d.get("end") or d["day"]))
            if a != b:
                self.new_period(a, b)
            return
        day = self._date_at(event.x, event.y)
        note = d["note"]
        # moved by as many days as the mouse went (a period keeps its length)
        shift = (day - d["day"]).days if day is not None and d["day"] is not None else 0
        if not shift:
            return
        old = note.date
        new = (date.fromisoformat(note.date) + timedelta(days=shift)).isoformat()
        self.app.move_note_date(note, new)      # redraws: the title is in its new day
        self._note().show_undo_action(tr("moved_day", day=_date_label(new)),
                                 lambda: self.app.move_note_date(note, old))
        # the title as it was dropped slides into its place in the day (CHIP_SETTLE_MS)
        px = self.app.px
        w, h = self.cell_w - px(8), px(MEMO_CHIP_H)
        x0, y0 = event.x - w // 2, event.y - h // 2
        spot = next(((a, b, r - a, s - b) for a, b, r, s, n in self._chips if n is note), None)
        if spot is None:                    # the day is full ("+ n more"): into the day's top
            spot = next(((a + px(3), b + px(3), w, h) for a, b, _r, _s, dd in self._cells if dd == day),
                        (x0, y0, w, h))
        c = Colors.of(self.top, note.color)
        box = g.create_rectangle(x0, y0, x0 + w, y0 + h, fill=c.bg, outline=shade(self.top, note.color, 3),
                                 tags=("settle",))
        text = g.create_text(x0 + px(4), y0 + h / 2, anchor="w", text=memo_title(note), font=(UI_FONT, 9),
                             fill=c.fg, tags=("settle",))

        def step(k):
            x, y = x0 + (spot[0] - x0) * k, y0 + (spot[1] - y0) * k
            bw, bh = w + (spot[2] - w) * k, h + (spot[3] - h) * k
            g.coords(box, x, y, x + bw, y + bh)
            g.coords(text, x + px(4), y + bh / 2)
        animate(g, "settle", CHIP_SETTLE_MS, step, lambda: g.delete("settle"))

    def _click(self, event):
        if self._chip_drag and self._chip_drag["moving"]:
            self._drop_chip(event)
            return
        self._chip_drag = None
        if self._after_double:          # the release that ends a double-click
            self._after_double = False
            return
        note = self._chip_at(event.x, event.y)
        if note is not None:            # a memo title in the big view: open it in the note, and keep
            self.selected = note.date   # the keys here (outlined: Delete bins it, not the memo's text)
            self._picked = note
            self._note().open_note(note)
            self.draw()
            self.top.after_idle(self.top.focus_force)
            return
        self._picked = None
        d = self._date_at(event.x, event.y)
        if d is None:
            return
        if self._click_job:
            self.grid.after_cancel(self._click_job)
        self._click_job = self.grid.after(DOUBLE_CLICK_MS, lambda: self._single(d))

    def _single(self, d):
        self._click_job = None
        if (d.year, d.month) != self.month:
            self.month = (d.year, d.month)
        self.pick_day(d.isoformat())

    def _double(self, event):
        d = self._date_at(event.x, event.y)
        if d is None or self._chip_at(event.x, event.y) is not None:
            return
        if self._click_job:
            self.grid.after_cancel(self._click_job)
            self._click_job = None
        self._after_double = True
        self.month = (d.year, d.month)
        self.new_memo_on(d.isoformat())

    def _motion(self, event):
        self._set_hover(self._date_at(event.x, event.y))
        self._peek_at(event.x, event.y)

    def _context_menu(self, event):
        """Right-click a day (a memo title in the big view): a new memo on that day, open a
        memo, or move it to the bin (Undo in the note's bottom bar; restored, it is back on
        the calendar)."""
        d = self._date_at(event.x, event.y)
        if d is None:
            return
        chip = self._chip_at(event.x, event.y) if self.expanded else None
        notes = self._memos_by_day().get(d.isoformat(), []) if d.month == self.month[1] else []
        if chip is not None:                # one memo: the title clicked, else the one in the preview
            note = chip
        elif self._peek and self._peek[0] == d:
            note = self._peek[1][self._peek[2]]
        else:
            note = notes[0] if notes else None
        self.hide_peek()
        iso = d.isoformat()
        menu = PopupMenu(self.app, self.grid).add(tr("cal_new_memo"), lambda: self.new_memo_on(iso),
                                                  icon=GLYPH["add"])
        if note is not None:
            title = self._fit(memo_title(note), self.app.px(200), self._menu_font.measure)
            menu.separator()
            menu.add(tr("cal_open", title=title), lambda: self._open_memo(note), icon=GLYPH["open_window"])
            if note.end_date:
                menu.add(tr("cal_one_day"), lambda: self._one_day(note), icon=GLYPH["one_day"])
            menu.add(tr("cal_trash", title=title), lambda: self.trash_memo(note), danger=True,
                     icon=GLYPH["trash"], key="Del")
        menu.popup(event.x_root, event.y_root)

    def unpick(self):
        """The memo title clicked last is not "picked" any more (the note's text was clicked or typed in)."""
        if self._picked is not None:
            self._picked = None
            self.draw()

    def _delete_key(self, _event=None):
        """Delete: the memo title clicked last (big view), else the memo in the preview, to the bin."""
        picked = self._picked               # (a period in the small view has no title to outline)
        note = picked if picked is not None and not picked.deleted and (
            any(c[4] is picked for c in self._chips) or (not self.expanded and picked.end_date)) else None
        if note is None and self.preview is not None:
            note = self.preview.note
        if note is None:
            return "break"
        self._picked = None
        self.hide_peek()
        self.trash_memo(note)
        self.draw()
        return "break"

    def _one_day(self, note):
        """A period memo back to its first day only (Undo puts the period back)."""
        end, note.end_date = note.end_date, None
        self.app.request_save()
        self.app.refresh_lists()
        self._note().show_undo_action(tr("one_day_done"),
                                 lambda: (setattr(note, "end_date", end), self.app.refresh_lists()))

    def _open_memo(self, note):
        self.selected = note.date
        self._note().open_note(note)
        self.draw()

    def trash_memo(self, note):
        """To the bin; the note's bottom bar offers Undo (back on the calendar, the note stays
        on what it shows)."""
        if self.app.trash_note(note.id):
            self._note().show_undo_action(tr("toast_moved"), lambda: self.app.restore_note(note.id))

    # -- resting on a day: its memo beside the calendar; the wheel goes through the day's memos
    def _peek_at(self, x, y):
        if self._chip_drag and self._chip_drag["moving"]:
            return
        d = self._date_at(x, y)
        chip = self._chip_at(x, y) if self.expanded else None
        key = (d, chip.id if chip else None)
        if key == self._peek_key:
            return
        self._pointer = None
        self._peek_key = key
        notes = self._memos_by_day().get(d.isoformat(), []) if d and d.month == self.month[1] else []
        if not notes:
            self.hide_peek()
            return
        self._peek = (d, notes, notes.index(chip) if chip in notes else 0)
        if self.preview is not None:        # already showing one: the new day at once
            self._show_peek()
            return
        self._cancel_peek()
        self._peek_job = self.top.after(PREVIEW_DELAY_MS, self._show_peek)

    def _cancel_peek(self):
        if self._peek_job is not None:
            try:
                self.top.after_cancel(self._peek_job)
            except tk.TclError:
                pass
            self._peek_job = None

    def _show_peek(self):
        self._peek_job = None
        if self._peek is None or self._closing:
            return
        d, notes, i = self._peek
        counter = _span_label(notes[i]) if notes[i].end_date else _date_label(d.isoformat())
        if len(notes) > 1:
            counter = tr("peek_count", day=counter, i=i + 1, n=len(notes))
        if self.preview is None:
            self.preview = MemoPreview(self.nw, notes[i], self._peek_place, wheel=self._peek_step,
                                       counter=counter, alpha=1.0,     # solid, like the calendar under the mouse
                                       click_through=True)            # the pointer's own card never blocks it
        else:
            self.preview.show_note(notes[i], counter)
        if self._peek_dropped != d:         # a new day: it drops into place (the same day: just moves)
            self._peek_dropped = d
            self._drop_peek()

    def _drop_peek(self):
        pv, spot = self.preview, self._peek_spot
        if pv is None or spot is None:
            return
        x, y, w, h = spot
        drop = self.app.px(PEEK_DROP)

        def step(k):
            pv.top.geometry(f"{w}x{h}+{x}+{y - round(drop * (1 - k))}")
        animate(pv.top, "drop", PEEK_DROP_MS, step)

    def peek_day_at_pointer(self, iso, pointer):
        """The hover path as a test can drive it: the day's memo preview by ``pointer``."""
        d = date.fromisoformat(iso)
        notes = self._memos_by_day().get(iso, [])
        if not notes:
            return
        self._pointer = pointer
        self._cancel_peek()
        self._peek = (d, notes, 0)
        self._show_peek()

    def _peek_wheel(self, event):
        self._peek_step(event.delta)
        return "break"

    def _peek_step(self, delta):
        """Wheel up: the day's previous memo; down: the next one (it stops at the first / last)."""
        if self._peek is None or not delta:
            return
        d, notes, i = self._peek
        j = i - 1 if delta > 0 else i + 1
        if 0 <= j < len(notes):
            self._peek = (d, notes, j)
            self._cancel_peek()
            self._show_peek()

    def _peek_place(self, w, h):
        """By the pointer, down and right of it (flipped near the screen's edges), on the
        screen it is on and taking no space."""
        px = self.app.px
        pointer = self._pointer or self.top.winfo_pointerxy()
        area = self.app.area_of((pointer[0], pointer[1], pointer[0] + 1, pointer[1] + 1))
        off = (px(PEEK_OFFSET[0]), px(PEEK_OFFSET[1]))
        x, y = calgeom.peek_spot(pointer, w, h, area, off)
        self._peek_spot = (x, y, w, h)
        return x, y

    def hide_peek(self):
        self._cancel_peek()
        self._peek = self._peek_key = self._peek_dropped = None
        if self.preview is not None:
            self.preview.destroy()
            self.preview = None

    def _set_hover(self, d):
        """Only the two days change (the old one and the new one), not the whole month: a
        month of many memos took ~20 ms to redraw at every day the mouse crossed."""
        if d == self._hover or getattr(self, "_paging", False):
            return
        old, self._hover = self._hover, d
        g, c = self.grid, self.colors
        if self.expanded:
            for day in (old, d):
                if day is not None and g.find_withtag(f"cell{day.isoformat()}"):
                    g.itemconfigure(f"cell{day.isoformat()}", fill=self._big_fill(day, day == d))
            return
        g.delete("hover")
        spot = self._spots.get(d.isoformat()) if d is not None else None
        if spot is not None and d != date.today() and d.isoformat() != self.selected:
            cx, cy, tw, th = spot
            g.create_image(cx, cy, image=self._tile(c.hover, tw, th), tags=("hover",))
            g.tag_lower("hover", f"d{d.isoformat()}")

    # -- drawing
    @perf.timed("calendar_draw")
    def draw(self, keep=None):
        """Draw the month. ``keep``: a tag whose items stay (a page sliding out: _page_to)."""
        c, g, px = self.colors, self.grid, self.app.px
        y, m = self.month
        self.title.configure(text=texts.month_title(y, m))
        g.delete(f"!{keep}" if keep else "all")
        if self.fit_size:                   # filling a given size: the cells for six weeks (C2)
            self._fit_cells(6)
        cw, ch, hh = self.cell_w, self.cell_h, self.head_h
        for i, letter in enumerate(texts.week_letters()):
            color = c.sunday if i == 0 else c.saturday if i == 6 else c.muted
            g.create_text(i * cw + cw / 2, hh / 2, text=letter, fill=color, font=(UI_BOLD, 8, "bold"), tags=("wk",))
        today = date.today()
        red = {d for d in holidays.in_year(y)} | {d for d in holidays.in_year(y - 1 if m == 1 else y + 1)}
        self._cells, self._chips, self._spots = [], [], {}
        weeks = _calendar.Calendar(firstweekday=6).monthdatescalendar(y, m)
        while len(weeks) < 6:               # always six week rows: paging months never changes its size (#17A)
            last = weeks[-1][-1]
            weeks.append([last + timedelta(days=i) for i in range(1, 8)])
        self._rows = 6
        g.configure(width=cw * 7)
        if self.expanded:
            self._draw_big(weeks, today, red)
            return
        by_day = self._memos_by_day(periods=False)
        k = min(cw / px(SMALL_CELL[0]), ch / px(SMALL_CELL[1]))       # a resized small view: all of it bigger
        ky = ch / px(SMALL_CELL[1])
        tw, th = round(px(26) * k), round(px(22) * k)
        size = max(9, round(9 * k))
        period_rows = self._period_rows(weeks)
        for row, week in enumerate(weeks):
            for col, d in enumerate(week):
                x0, y0 = col * cw, hh + row * ch
                cx, cy = x0 + cw // 2, y0 + round(px(13) * ky)
                self._cells.append((x0, y0, x0 + cw, y0 + ch, d))
                in_month = d.month == m
                iso = d.isoformat()
                self._spots[iso] = (cx, cy, tw, th)         # where the hover tile goes (_set_hover)
                if iso == self.selected:
                    g.create_image(cx, cy, image=self._tile(c.select, tw, th), tags=("selected",))
                elif d == self._hover:
                    g.create_image(cx, cy, image=self._tile(c.hover, tw, th), tags=("hover",))
                if d == today:                      # today: a circle in the theme's opposite colour, a bold number
                    fg = self._today_circle(cx, cy, (UI_BOLD, size, "bold"), k, str(d.day))
                elif not in_month:
                    fg = c.border
                elif col == 0 or d in red:
                    fg = c.sunday
                else:
                    fg = c.saturday if col == 6 else c.fg
                g.create_text(cx, cy, text=str(d.day), fill=fg, tags=(f"d{iso}",), font=ui_font(size, d == today),
                              state="hidden" if d == today and self._today_baked else "normal")
                notes = by_day.get(iso, [])[-3:] if in_month else []
                if notes:                           # a dot under the number per memo (up to 3), in its color
                    dot, step, by = max(4, round(px(5) * k)), round(px(7) * k), y0 + round(px(27) * ky)
                    x = cx - step * (len(notes) - 1) // 2
                    for note in reversed(notes):
                        g.create_image(x, by, image=self._dot(self._mark(note.color), dot), tags=("mark",))
                        x += step
            # period memos: a thin line across their days, between the numbers and the dots
            y0 = hh + row * ch
            for note, c0, c1, starts, ends, lane in period_rows[row]:
                if lane > 1:                        # two lines at most in the small view
                    continue
                by = y0 + round(px(22) * ky) + lane * px(3)
                xa = c0 * cw + (px(5) if starts else 0)
                xb = (c1 + 1) * cw - (px(5) if ends else 0)
                g.create_line(xa, by, xb, by, width=px(2), capstyle="round" if starts and ends else "butt",
                              fill=self._mark(note.color), tags=("period",))
        g.configure(height=hh + ch * len(weeks))

    def _memos_by_day(self, periods=True):
        """Day -> its memos: the period memos covering it first (``periods``), then that day's own."""
        by_day: dict = {}
        if periods:
            for n in self._periods():
                d, end = date.fromisoformat(n.date), date.fromisoformat(n.end_date)
                for _ in range(min((end - d).days + 1, 800)):
                    by_day.setdefault(d.isoformat(), []).append(n)
                    d += timedelta(days=1)
        for n in sorted(self.app.notes.values(), key=lambda n: n.modified):
            if not n.is_empty and not n.deleted and n.date and not n.end_date:
                by_day.setdefault(n.date, []).append(n)
        return by_day

    def _periods(self):
        """Period memos; a new one shows (empty) while it is open, before anything is typed."""
        app = self.app
        return sorted((n for n in app.notes.values() if n.end_date and not n.deleted
                       and (not n.is_empty or app.window_for(n.id) is not None)),
                      key=lambda n: (n.date, n.created))

    def _period_rows(self, weeks):
        """Per week row: [(note, first col, last col, starts here, ends here, lane)]. A memo
        keeps one lane (height) through the month so its band lines up across the days."""
        first, last = weeks[0][0].isoformat(), weeks[-1][-1].isoformat()
        lanes, ends = {}, []
        shown = [n for n in self._periods() if not (n.end_date < first or n.date > last)]
        for n in shown:
            for i, e in enumerate(ends):
                if e < n.date:
                    ends[i], lanes[n.id] = n.end_date, i
                    break
            else:
                lanes[n.id] = len(ends)
                ends.append(n.end_date)
        rows = []
        for week in weeks:
            a, b = week[0].isoformat(), week[-1].isoformat()
            segs = []
            for n in shown:
                if n.end_date < a or n.date > b:
                    continue
                c0 = next(i for i, d in enumerate(week) if d.isoformat() >= n.date)
                c1 = max(i for i, d in enumerate(week) if d.isoformat() <= n.end_date)
                segs.append((n, c0, c1, n.date >= a, n.end_date <= b, lanes[n.id]))
            rows.append(segs)
        return rows

    def today_circle_color(self):
        """Today's pill: the theme colour's deep shade (A, "테마 진녹 알약"); white or near-black number on it."""
        return self._deep()

    def _big_fill(self, day, hovered):
        """A big-view day's fill: the picked day a dark tint of the theme (no outline), else the hover
        tint under the mouse, else today's faint wash of the pill's colour (option 3), else the page."""
        c = self.colors
        if day is not None and day.isoformat() == self.selected:
            return _mix(self.top, c.bg, self._deep(), 0.2)
        if hovered:
            return c.hover
        return _mix(self.top, c.bg, self._deep(), 0.09) if day == date.today() else c.bg

    def _dot(self, color, d):
        """A small anti-aliased dot ``d`` px across: a memo's mark under a day in the mini view."""
        key = ("dot", color, d)
        if key not in self._tiles:
            self._tiles[key] = ImageTk.PhotoImage(circle_image(d, color, scale=16), master=self.grid)
        return self._tiles[key]

    def _big_slot(self):
        """The big view's number slot (today's pill size) and where a day's memos start under it:
        (slot w, slot h, top) with 4 px around the slot (option 1, "슬롯 정렬")."""
        px = self.app.px
        w, h = self._today_size((UI_BOLD, 9, "bold"))
        return w, h, px(4) + h + px(4)

    def _today_size(self, font, k=1.0):
        """(w, h) of today's pill: as wide for 1 as for 28, a little taller than the number."""
        px = self.app.px
        h = round(px(16) * k)
        w = max(round(px(26) * k), tkfont.Font(self.top, font=font).measure("88") + px(10))
        return w + w % 2, h + h % 2

    def _today_circle(self, cx, cy, font, k=1.0, text=""):
        """Draw today's smooth pill (an image tagged "todaycircle") centred on (cx, cy); returns the
        number's colour: the white or near-black that reads on it. With the bundled Bold face the
        number ``text`` is drawn into the pill itself (self._today_baked: its Tk text stays hidden,
        kept for its place and colour); otherwise Tk draws it on top."""
        fill = self.today_circle_color()
        ink = ink_for(self.top, fill)
        w, h = self._today_size(font, k)
        face = FONT_DIR / "Pretendard-Bold.ttf"
        baked = bool(text) and font[0] == texts.UI_BOLD_NAME and face.is_file()
        size_px = round(self.top.winfo_fpixels(f"{font[1]}p")) if baked else 0
        number = text if baked else ""
        key = (w, h, fill, number, ink, size_px)
        dots = self.__dict__.setdefault("_dots", {})        # (kept here: Tk's image is not collected)
        if key not in dots:
            try:
                img = pill_image(w, h, fill, text=number, ink=ink, font_file=face if baked else None, size_px=size_px)
            except Exception:                               # (the face can't be read: Tk draws the number)
                img, baked = pill_image(w, h, fill), False
            dots[key] = ImageTk.PhotoImage(img, master=self.grid)
        self.grid.create_image(cx, cy, image=dots[key], tags=("today", "todaycircle"))
        self._today_baked = baked
        return ink

    def _tile(self, color, w, h):
        """A smooth rounded tile (Tk's own shapes have jagged corners)."""
        key = (color, w, h)
        if key not in self._tiles:
            s, r = 4, self.app.px(5)
            img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
            ImageDraw.Draw(img).rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=r * s, fill=color)
            self._tiles[key] = ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS), master=self.grid)
        return self._tiles[key]

    def _draw_grab(self):
        g, bar, px = self.grab, self.bar_colors, self.app.px
        g.delete("all")
        w, h = max(g.winfo_width(), self.cell_w * 7), int(g.cget("height"))
        g.create_line(w / 2 - px(14), h / 2, w / 2 + px(14), h / 2, width=px(2), capstyle="round", fill=bar.border)

    def _draw_big(self, weeks, today, red):
        """The big month: a grid with each day's number, holiday name and memo titles."""
        c, g, px = self.colors, self.grid, self.app.px
        cw, ch, hh = self.cell_w, self.cell_h, self.head_h
        m = self.month[1]
        by_day = self._memos_by_day(periods=False)
        font = (UI_FONT, 9)
        measure = tkfont.Font(self.top, font=font).measure
        band_font = (UI_FONT, 8)
        band_measure = tkfont.Font(self.top, font=band_font).measure
        chip_h, gap, band_h = px(MEMO_CHIP_H), px(2), px(PERIOD_BAND_H)
        period_rows = self._period_rows(weeks)
        bold_font, band_bold = (UI_BOLD, 9, "bold"), (UI_BOLD, 8, "bold")
        sw, sh, head = self._big_slot()
        for row, week in enumerate(weeks):
            segs = period_rows[row]
            lanes = max((s[5] for s in segs), default=-1) + 1
            for col, d in enumerate(week):
                x0, y0 = col * cw, hh + row * ch
                iso, in_month = d.isoformat(), d.month == m
                self._cells.append((x0, y0, x0 + cw, y0 + ch, d))
                is_today = d == today
                g.create_rectangle(x0, y0, x0 + cw, y0 + ch, fill=self._big_fill(d, d == self._hover),
                                   outline=c.line, tags=("cell", f"cell{iso}"))
                nx, ny = x0 + px(4) + sw // 2, y0 + px(4) + sh // 2     # every number: centred in the slot
                name_x = x0 + px(4) + sw + px(4)    # where a holiday name starts
                if is_today:                        # today: the pill fills the slot, a bold number on it
                    fg = self._today_circle(nx, ny, (UI_BOLD, 9, "bold"), 1.0, str(d.day))
                    g.create_text(nx, ny, text=str(d.day), anchor="center", fill=fg, tags=(f"d{iso}",),
                                  font=(UI_BOLD, 9, "bold"), state="hidden" if self._today_baked else "normal")
                else:
                    fg = c.border if not in_month else \
                        c.sunday if col == 0 or d in red else c.saturday if col == 6 else c.fg
                    g.create_text(nx, ny, text=str(d.day), anchor="center", fill=fg, tags=(f"d{iso}",),
                                  font=(UI_FONT, 9, "normal"))
                top = y0 + head + lanes * (band_h + gap)        # under this row's period bands
                names = " · ".join(map(texts.holiday_name, holidays.on(d))) if in_month else ""
                if names:
                    g.create_text(name_x, ny, text=self._fit(names, x0 + cw - name_x - px(4), measure),
                                  anchor="w", fill=c.sunday, font=font)
                notes = by_day.get(iso, []) if in_month else []
                room = max(0, (ch - (top - y0) - px(2)) // (chip_h + gap))
                for i, note in enumerate(notes):
                    if i == room - 1 and len(notes) > room:
                        g.create_text(x0 + px(8), top + chip_h / 2, anchor="w", font=font,
                                      fill=c.muted,
                                      text=tr("calendar_more", n=len(notes) - i))
                        break
                    if i >= room:
                        break
                    nc = Colors.of(self.top, note.color)
                    box = (x0 + px(4), top, x0 + cw - px(4), top + chip_h)     # its left edge under the slot's
                    on = note is self._picked           # clicked (Delete bins it): a shade deeper, bold
                    g.create_rectangle(*box, fill=shade(self.top, nc.bg, 1) if on else nc.bg,
                                       outline=shade(self.top, note.color, 3 if on else 2), tags=("chip",))
                    g.create_text(box[0] + px(4), top + chip_h / 2, anchor="w", fill=nc.fg,
                                  font=bold_font if on else font, tags=("chip",),
                                  text=self._fit(memo_title(note), cw - px(14), measure))
                    self._chips.append((*box, note))
                    top += chip_h + gap
            y0 = hh + row * ch
            for note, c0, c1, starts, ends, lane in segs:       # one band per week row it spans
                yb = y0 + head + lane * (band_h + gap)
                if yb + band_h > y0 + ch - px(2):
                    continue
                xa = c0 * cw + (px(4) if starts else 0)
                xb = (c1 + 1) * cw - (px(4) if ends else 0)
                nc = Colors.of(self.top, note.color)
                on = note is self._picked               # clicked (Delete bins it): a shade deeper, bold
                g.create_rectangle(xa, yb, xb, yb + band_h, fill=shade(self.top, nc.bg, 1) if on else nc.bg,
                                   outline=shade(self.top, note.color, 3 if on else 2), tags=("chip", "period"))
                g.create_text(xa + px(4), yb + band_h / 2, anchor="w", fill=nc.fg,
                              font=band_bold if on else band_font, tags=("chip", "period"),
                              text=self._fit(memo_title(note), xb - xa - px(8), band_measure))
                self._chips.append((xa, yb, xb, yb + band_h, note))
        g.configure(height=hh + ch * len(weeks))

    @staticmethod
    def _fit(text, width, measure):
        """``text`` cut short with "…" so it fits ``width`` pixels."""
        if measure(text) <= width:
            return text
        while text and measure(text + "…") > width:
            text = text[:-1]
        return text + "…"

    def recolor(self, c):
        self.colors = c
        self.top.configure(bg=c.frame)
        bar = self.bar_colors = Colors.of(self.top, c.bar, solid=True)
        for w in (self.frame, self.grid, self.detail, self.detail_name, self.detail_text):
            w.configure(bg=c.bg)
        for w in (self.grab, self.head, self.title):
            w.configure(bg=bar.bg)
        self.title.configure(fg=bar.muted)          # every word on a top bar: the icons' gray
        self._draw_grab()
        self._draw_grip()
        self.detail_name.configure(fg=c.sunday)
        self.detail_text.configure(fg=c.fg)
        for b in (self.btn_prev, self.btn_next, self.btn_today, self.btn_close, self.btn_lock, self.btn_expand):
            b.recolor(bar)
        self.draw()

    def destroy(self, animated=False):
        """Close it; ``animated``: it slides back towards its note, fading out, first."""
        self.hide_peek()
        self._hide_count()
        self.holiday_card.hide()
        if self._click_job:
            self.grid.after_cancel(self._click_job)
            self._click_job = None
        if not animated or self._closing:
            for key in ("slide", "alpha"):
                stop_animation(self.top, key)
            if self.top.winfo_exists():
                self.top.destroy()
            self.app.space_changed()
            return
        self._closing = True
        self.app.space_changed()            # closing: it takes up no space from here on
        try:
            self._xy = (self.top.winfo_x(), self.top.winfo_y())
        except tk.TclError:
            return
        self._slide(opening=False, done=lambda: self.top.winfo_exists() and self.top.destroy())


# every name (underscored ones too) goes on to the next part: see app.py
__all__ = [_n for _n in list(globals()) if not _n.startswith("__")]
