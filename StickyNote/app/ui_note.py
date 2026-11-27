"""One sticky-note window."""
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
from tkinter import colorchooser, filedialog, messagebox

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageGrab, ImageTk

import geom
import holidays
import texts
import perf
import winapi
from icon import draw_icon
from store import (BIN_DAY_CHOICES, CURSOR_COLORS, CUSTOM_COLORS, EMPTY_TITLE, INLINE, LIST_SORTS, MARK_KINDS,
                   PIN_LIMIT_MAX, SNAP_GAPS, STYLES, TIDY_ORDERS, Note, NoteStore, Pad, Prefs)
from texts import tr
from ui_picture import *  # noqa: F401,F403  (the parts before this one)

animate_ = animate                 # (minimize / restore take an ``animate`` argument of their own)


# --------------------------------------------------------------------------- minimized sticker
STICKER_H = 34                  # a minimized note's sticker on the desktop (px at 100 %)
STICKER_W = (96, 180)           # ... its width fits the title, within these (px at 100 %)
STICKER_DRAG = 4                # ... a press that moves this far is a drag, not a click (px at 100 %)
STICKER_FADE_MS = anim.FAST 


class MiniSticker:
    """A minimized note stays on the desktop as a small sticker in its color, where its
    top-left corner was: a click brings the note back (NoteWindow.restore), a drag moves the
    sticker. It has no taskbar button of its own (the minimized note keeps one)."""

    def __init__(self, nw: NoteWindow):
        self.nw = nw
        app, px, win = nw.app, nw.app.px, nw.win
        fill = nw.note.color
        ink = ink_for(win, fill)
        edge = _mix(win, fill, ink, 0.25)
        top = self.top = tk.Toplevel(app.root)
        top.withdraw()
        top.overrideredirect(True)
        top.configure(bg=TIP_KEY)
        try:
            top.attributes("-transparentcolor", TIP_KEY)
        except tk.TclError:
            pass
        font = tkfont.Font(top, font=ui_font(9, True))
        padx, h = px(12), px(STICKER_H)
        lo, hi = px(STICKER_W[0]), px(STICKER_W[1])
        text = memo_title(nw.note).split("\n")[0].strip() or tr("untitled")
        if font.measure(text) > hi - 2 * padx:
            while text and font.measure(text + "…") > hi - 2 * padx:
                text = text[:-1]
            text += "…"
        w = min(max(font.measure(text) + 2 * padx, lo), hi)
        cv = self.cv = tk.Canvas(top, width=w, height=h, bg=TIP_KEY, bd=0, highlightthickness=0,
                                 cursor="hand2")
        cv.pack()
        self._photos = {
            False: ImageTk.PhotoImage(_rounded_card(w, h, px(8), fill, edge), master=top),
            True: ImageTk.PhotoImage(_rounded_card(w, h, px(8), _mix(win, fill, ink, 0.08), edge), master=top),
        }
        self._card = cv.create_image(0, 0, anchor="nw", image=self._photos[False])
        cv.create_text(padx, h // 2, anchor="w", text=text, fill=ink, font=font)
        cv.bind("<Enter>", lambda e: cv.itemconfigure(self._card, image=self._photos[True]))
        cv.bind("<Leave>", lambda e: cv.itemconfigure(self._card, image=self._photos[False]))
        cv.bind("<ButtonPress-1>", self._press)
        cv.bind("<B1-Motion>", self._motion)
        cv.bind("<ButtonRelease-1>", self._release)
        Tooltip(cv, tr("tip_sticker"))
        self._start = None
        self._moved = False

        p = nw.pad
        x = p.x if p.x is not None else win.winfo_rootx()
        y = p.y if p.y is not None else win.winfo_rooty()
        area = app.area_of((x, y, x + w, y + h))
        if area is not None:                # stays on its note's screen
            x = min(max(x, area[0]), area[2] - w)
            y = min(max(y, area[1]), area[3] - h)
        top.geometry(f"{w}x{h}+{x}+{y}")
        top.attributes("-alpha", 0.0)
        top.deiconify()
        top.attributes("-topmost", p.pinned)
        fade(top, "show", 0.0, p.alpha, STICKER_FADE_MS)

    def _press(self, e):
        self._start = (e.x_root, e.y_root, self.top.winfo_x(), self.top.winfo_y())
        self._moved = False

    def _motion(self, e):
        if self._start is None:
            return
        x0, y0, wx, wy = self._start
        dx, dy = e.x_root - x0, e.y_root - y0
        if not self._moved and max(abs(dx), abs(dy)) < self.nw.app.px(STICKER_DRAG):
            return
        self._moved = True
        self.top.geometry(f"+{wx + dx}+{wy + dy}")

    def _release(self, _e):
        clicked = self._start is not None and not self._moved
        self._start = None
        if clicked:
            self.nw.restore()

    def destroy(self):
        try:
            stop_animation(self.top, "show")
            self.top.destroy()
        except tk.TclError:
            pass


# --------------------------------------------------------------------------- note window
TYPING_SYNC_MS = 250            # the stored memo catches up with the typing after this pause


class NoteWindow:
    def __init__(self, app: App, pad: Pad, note: Note, fade_in=False):
        self.app, self.pad, self.note = app, pad, note
        self.look_version = 0               # bumped whenever what it shows changes (its kept picture: shots)
        if perf.ENABLED:
            perf.perf.track_window(self)
        self._closing = False
        self.sticker: MiniSticker | None = None     # shown on the desktop while minimized
        self.minimized = False              # hidden, standing in as its sticker (minimize / restore)
        self._hooked = False               # the taskbar hook is in (show)
        self.rolling = False                # rolling up into the taskbar (or back): its pad waits (_on_configure)
        self.view = "home"
        self.calendar: CalendarPopup | None = None
        self._jobs = {}
        self._drag = self._resize = None
        self._group: list = []          # while dragging: (window, dx, dy) of the notes moving along
        self._loading = False

        px = app.px
        win = self.win = tk.Toplevel(app.root)
        win.withdraw()
        win.overrideredirect(True)
        self.colors = Colors.of(win, note.color)

        # Windows 11: DWM rounds the corners and draws the shadow; else a 1 px border (win's bg)
        self.edge = 0 if winapi.can_round() else 1
        self._rounded = False               # asked DWM once the window is shown (show)
        self.frame = tk.Frame(win, bd=0)
        self._pack_frame()

        # ---- the C look: a rail down the left side with the note's controls, and the date row
        # along the top of the rest (the memo, or the list / settings / bin pages under it)
        rail = self.rail = tk.Frame(self.frame, bd=0, width=px(RAIL_W), cursor="fleur")
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        self.rail_top = tk.Frame(rail, bd=0, cursor="fleur")
        self.rail_top.pack(side="top", fill="x", pady=(px(RAIL_PAD), 0))
        self.rail_sep = tk.Frame(self.rail_top, width=px(16), height=1, bd=0)    # nav | format
        main = self.main = tk.Frame(self.frame, bd=0)
        main.pack(side="left", fill="both", expand=True)

        def rail_button(glyph, command, tip, master=None, **kw):
            return IconButton(master or self.rail_top, app, glyph, command, tip, width=RAIL_BUTTON[0],
                              height=RAIL_BUTTON[1], **kw)
        self.btn_memo = rail_button(GLYPH["add"], self.new_memo, tr("tip_new_memo"))
        self.btn_window = rail_button(GLYPH["note"], lambda: app.new_window(self), tr("tip_new_window"),
                                      overlay=GLYPH["add"])
        self.btn_list = rail_button(GLYPH["list"], self.show_list, tr("tip_list"))
        self.btn_cal = rail_button(GLYPH["calendar"], self.toggle_calendar, tr("tip_calendar"))
        self.btn_pin = rail_button(GLYPH["pin"], self.toggle_pin, tr("tip_pin"))
        self.nav_buttons = (self.btn_memo, self.btn_window, self.btn_list, self.btn_cal, self.btn_pin)
        # the format buttons: in the rail while the memo text has the focus
        self.btn_bold = rail_button(GLYPH["bold"], lambda: self.toggle_format("b"), tr("tip_bold"))
        self.btn_italic = rail_button(GLYPH["italic"], lambda: self.toggle_format("i"), tr("tip_italic"))
        self.btn_underline = rail_button(GLYPH["underline"], lambda: self.toggle_format("u"), tr("tip_underline"))
        self.btn_strike = rail_button(GLYPH["strike"], lambda: self.toggle_format("s"), tr("tip_strike"))
        self.btn_bullets = rail_button(GLYPH["bullets"], self.toggle_bullets, tr("tip_bullets"))
        self.btn_todo = rail_button(GLYPH["todo"], self.toggle_todo, tr("tip_todo"))
        self.btn_picture = rail_button(GLYPH["picture"], self.pick_images, tr("tip_picture"))
        self.format_buttons = (self.btn_bold, self.btn_italic, self.btn_underline, self.btn_strike,
                               self.btn_bullets, self.btn_todo, self.btn_picture)
        self.btn_more = rail_button(GLYPH["more"], self._more_menu, tr("tip_more"), master=rail)
        self.btn_more.pack(side="bottom", pady=(0, px(RAIL_PAD)))
        # a short note gives these up first, in this order: they are in the ⋯ menu then
        self.give_way = (self.btn_pin, self.btn_cal, self.btn_list) + self.format_buttons[::-1] + (self.btn_window,)
        self._rail_state: tuple | None = None   # the rail buttons shown, in order
        self._rail_hidden: tuple = ()           # ... and those that would show if there were room
        self._editing = False                   # the memo text has the focus: the format buttons show
        self._cover = None                      # the picture standing in while a group resizes
        self._clip = None                       # ... and the box it shows while it does (clip_to)

        bar = self.bar = tk.Frame(main, bd=0, height=self._row_h())
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self.btn_back = IconButton(bar, app, GLYPH["back"], self.go_back, tr("tip_back"), width=30,
                                   height=DATE_ROW_H - 2)
        self.btn_close = IconButton(bar, app, GLYPH["close"], self.close, tr("tip_close"), width=30,
                                    height=DATE_ROW_H - 2)
        self.btn_close.pack(side="right", padx=(0, px(4)))
        # minimize, left of the close button (picked option B, 2026-11-27): "Top bar only" folds
        self.btn_min = IconButton(bar, app, GLYPH["minimize"], self.minimize_button, tr("menu_minimize"), width=30,
                                  height=DATE_ROW_H - 2)
        self.btn_min.pack(side="right")
        # today's day, big, with the month and weekday beside it (folded: the memo's lines; on
        # another page: its name), drawn in one canvas: see _draw_row
        self.row = tk.Canvas(bar, width=1, height=1, bd=0, highlightthickness=0, cursor="fleur")
        self.row.pack(side="left", fill="both", expand=True)
        self.row.bind("<Configure>", lambda e: self._draw_row())
        self._num_font = tkfont.Font(win, family=UI_BOLD, size=-px(DATE_NUM_PX), weight="bold")
        self._small_font = tkfont.Font(win, family=UI_FONT, size=-px(DATE_SMALL_PX))
        self._title_font = tkfont.Font(win, family=UI_BOLD, size=-px(DATE_SMALL_PX), weight="bold")
        self._narrow: dict = {}             # font name -> its narrowest glyph's width (fit_text)
        self.date_tip = Tooltip(self.row, tr("tip_date"))
        self.rail_buttons = self.nav_buttons + self.format_buttons + (self.btn_more,)
        self.buttons = self.rail_buttons + (self.btn_back, self.btn_min, self.btn_close)
        # the date row and the rail's empty part move the note (and the notes snapped to it);
        # double-click on the date row folds it up / unfolds it; right-click: the note's menu
        for w in (bar, self.row, rail, self.rail_top):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)
            w.bind("<Button-3>", self._top_menu)
        for w in (bar, self.row):
            w.bind("<Double-Button-1>", lambda e: self.toggle_collapse())

        # ---- pages
        self.views = tk.Frame(self.main, bd=0)
        self.views.pack(fill="both", expand=True)
        self.home = tk.Frame(self.views, bd=0)
        self.header_var = tk.StringVar(win)
        self.header_entry = tk.Entry(self.home, textvariable=self.header_var,
                                     bd=0, relief="flat", highlightthickness=0)
        self.header_sep = tk.Frame(self.home, height=1, bd=0)
        self.viewer = ImageViewer(self)
        self.body = tk.Text(self.home, wrap="word", undo=True, bd=0, relief="flat", height=TEXT_MIN_LINES,
                            highlightthickness=0, padx=px(10), pady=px(6),
                            spacing1=px(1), spacing3=px(1))
        for tag in ("b", "i", "bi", "u", "s", "bullet", "todo", "todo_box", "todo_done"):   # later tags win
            self.body.tag_configure(tag)
        self._pending: set | None = None    # formats picked with nothing selected: for what is typed next
        self._raw = 0                       # > 0 while the app itself edits the text
        _watch_text(self.body, self._text_event)
        # the Korean syllable being typed, drawn at the cursor in the memo's font and colors
        self.preedit = tk.Label(self.body, bd=0, padx=0, pady=0)
        self.body.bind("<KeyPress>", lambda e: self.win.after_idle(self._show_preedit), add="+")
        self.body.bind("<KeyRelease>", lambda e: self._show_preedit(), add="+")
        self.body.bind("<FocusOut>", lambda e: self.preedit.place_forget(), add="+")

        # "+ Add picture" under the text of an image memo: each picture is a new tab
        self.add_bar = tk.Canvas(self.home, height=px(26), bd=0, highlightthickness=0, cursor="hand2")
        self.add_bar.bind("<Configure>", lambda e: self._draw_add_bar())
        self.add_bar.bind("<Enter>", lambda e: self._draw_add_bar(hover=True))
        self.add_bar.bind("<Leave>", lambda e: self._draw_add_bar())
        self.add_bar.bind("<ButtonRelease-1>", lambda e: self.add_inline_pictures())
        self._inline: dict = {}             # embedded image name in the text -> (file name, PhotoImage)
        # a period memo: a thin band like the calendar's, "11/10 ~ 11/13 · 4일" (click: the calendar)
        self.period_band = tk.Canvas(self.home, height=px(18), bd=0, highlightthickness=0, cursor="hand2")
        self.period_band.bind("<Configure>", lambda e: self._draw_period_band())
        self.period_band.bind("<ButtonRelease-1>", lambda e: self.show_period())
        Tooltip(self.period_band, tr("tip_period_band"))
        Tooltip(self.add_bar, tr("tip_add_picture_bar"))
        self.list_view = ListView(self)
        self._settings_view = self._bin_view = None     # made the first time they are opened

        # ---- undo bar, shown for a while after a memo goes to the bin
        self._undo_note: Note | None = None
        self._notice = False
        self.toast = tk.Frame(self.main, bd=0)
        self.toast_text = tk.Label(self.toast, text=tr("toast_moved"), font=(UI_FONT, 9),
                                   padx=px(10), pady=px(5))
        self.toast_text.pack(side="left")
        self._undo_action = None
        self.undo_button = FlatButton(self.toast, "", self._toast_undo)       # an undo icon
        self.undo_button.configure(padx=px(7))
        self.undo_button.pack(side="left", padx=(0, px(4)))
        Tooltip(self.undo_button, tr("undo"))

        # ---- resize grip, bottom-right
        g = px(12)
        self.grip = tk.Canvas(self.frame, width=g, height=g, bd=0, highlightthickness=0, cursor="size_nw_se")
        self._place_grip()
        self.grip.bind("<ButtonPress-1>", self._resize_start)
        self.grip.bind("<B1-Motion>", self._resize_move)
        self.grip.bind("<ButtonRelease-1>", self._drag_end)

        # ---- events
        self._trace_ids = [(self.header_var,       # removed in destroy(): a trace keeps this window alive
                            self.header_var.trace_add("write", lambda *a: self._sync_soon()))]
        self.header_entry.bind("<Return>", lambda e: (self.body.focus_set(), "break")[1])
        self.body.bind("<<Modified>>", self._on_body_modified)
        self.body.bind("<<Selection>>", lambda e: self._update_format_buttons())
        self.body.bind("<Return>", self.newline)
        self.body.bind("<BackSpace>", self.backspace)
        for key, kind in (("b", "b"), ("i", "i"), ("u", "u"), ("t", "s")):     # Windows Sticky Notes keys
            for k in (key, key.upper()):
                self.body.bind(f"<Control-{k}>", lambda e, kind=kind: self.toggle_format(kind))
        self.body.bind("<Control-L>", lambda e: self.toggle_bullets())             # Ctrl+Shift+L
        self.body.bind("<Control-C>", lambda e: self.toggle_todo())                # Ctrl+Shift+C
        # to-do lines: click the box to tick it; the line under the mouse shows undo / remove
        self.body.bind("<Button-1>", self._todo_click, add="+")
        self.body.bind("<Motion>", self._todo_hover, add="+")
        self.body.bind("<Leave>", lambda e: self._later("todo_hover", 80, self._todo_hover_check), add="+")
        self.body.bind("<MouseWheel>", lambda e: self._hide_todo_icons(), add="+")
        self.body_scroll = OverlayScroll(self.body, app, units=3)     # a theme-colored thumb while it scrolls
        self._todo_row = None
        self._body_cursor = "xterm"         # changed only when it must: setting it again makes it flicker
        self.todo_undo = tk.Label(self.body, bd=0, cursor="hand2")
        self.todo_remove = tk.Label(self.body, bd=0, cursor="hand2")
        self.todo_undo.bind("<ButtonRelease-1>", lambda e: self._todo_row and self.set_done(self._todo_row, False))
        self.todo_remove.bind("<ButtonRelease-1>", lambda e: self._todo_row and self.remove_todo(self._todo_row))
        for icon, glyph, mirror in ((self.todo_undo, "undo", True), (self.todo_remove, "remove", False)):
            icon.bind("<Enter>", lambda e, i=icon, g=glyph, m=mirror: paint_glyph(app, i, GLYPH[g], self.colors.fg,
                                                                                   mirror=m))
            icon.bind("<Leave>", lambda e, i=icon, g=glyph, m=mirror: (
                paint_glyph(app, i, GLYPH[g], self.colors.muted, mirror=m), self._later("todo_hover", 80,
                                                                                        self._todo_hover_check)))
        Tooltip(self.todo_undo, tr("tip_todo_undo"))
        Tooltip(self.todo_remove, tr("tip_todo_remove"))
        for w in (self.body, self.header_entry, win):
            w.bind("<Control-d>", lambda e: (self.trash_current() if self.view == "home" else None, "break")[1])
            w.bind("<Control-w>", lambda e: (self.close(), "break")[1])
        for w in (self.body, self.header_entry, win):
            w.bind("<Control-v>", self._paste)
            w.bind("<Control-V>", self._paste)
        for w in (self.body, win):                  # like browser tabs: the previous / next picture
            w.bind("<Control-Prior>", lambda e: (self.step_tab(-1), "break")[1])
            w.bind("<Control-Next>", lambda e: (self.step_tab(1), "break")[1])
        # a memo picked in the calendar (clicked there, nothing typed or clicked here since): Delete
        # bins it even when the keys stayed with this note; any other key or a click here unpicks it
        self.body.bind("<Delete>", self._delete_picked, add="+")
        for seq in ("<Key>", "<ButtonPress-1>"):
            self.body.bind(seq, lambda e: self.calendar.unpick() if self.calendar else None, add="+")
        # Ctrl+Shift+T: reopen the note closed last (in the memo text it wins over Ctrl+T, strikethrough)
        for w in (self.body, win):
            w.bind("<Control-Shift-T>", lambda e: (self.app.reopen_closed(self), "break")[1])
        win.bind("<Control-n>", lambda e: (self.new_memo(), "break")[1])
        win.bind("<Control-N>", lambda e: (app.new_window(self), "break")[1])
        win.bind("<Escape>", lambda e: self.go_back() if self.view != "home" else None)
        win.bind("<MouseWheel>", self._wheel)
        win.bind("<Configure>", self._on_configure)
        win.bind("<FocusIn>", lambda e: setattr(app, "last_note", self), add="+")    # (App._bring_notes)
        win.bind("<FocusIn>", self._focus_in, add="+")     # the format buttons follow the memo's focus
        # Taskbar "Close window" and Alt+F4 send WM_CLOSE. Without this Tk just destroys the
        # window and the app runs on with nothing on screen, blocking the next start.
        win.protocol("WM_DELETE_WINDOW", self.close)
        winapi.hook_ime(win.winfo_id())     # Korean: keep the last syllable, no white IME box
        for w in (self.body, self.header_entry, self.list_view.search_entry):
            _finish_typing_first(w)
            # no white IME box over a picture memo (or anywhere): said again at every focus
            w.bind("<FocusIn>", lambda e: winapi.hide_ime_box(self.win.winfo_id()), add="+")

        win.geometry(f"{pad.width}x{pad.height}+{pad.x}+{pad.y}")
        self._arrange_chrome(pad.width, pad.height)
        tab, open_calendar = pad.tab, pad.calendar
        self._load_note(note)
        self._show_view("home")
        if fade_in:                         # a new or reopened note fades in (OPEN_FADE_MS)
            win.attributes("-alpha", 0.0)
        self.show(focus=False)
        if note.style == "image" and 0 < tab < len(note.images):    # the picture it was showing
            self.switch_tab(tab)
        self._built = True              # (App.open_calendars / set_language open the calendar, once every window is there)
        if pad.collapsed:                   # it was folded up when the app closed
            self._apply_collapsed()
        if fade_in:
            fade(win, "fade", 0.0, self.pad.alpha, OPEN_FADE_MS)

    # ---- pages -----------------------------------------------------------------
    @property
    def settings_view(self) -> SettingsView:
        """The settings page, made the first time it is needed (some 100 widgets each note
        need not have before it is opened)."""
        if self._settings_view is None:
            sv = self._settings_view = SettingsView(self)
            sv.recolor(self.colors)
            for w in (sv.alpha_box.entry, sv.size_box.entry, sv.pin_box.entry):
                _finish_typing_first(w)
                w.bind("<FocusIn>", lambda e: winapi.hide_ime_box(self.win.winfo_id()), add="+")
        return self._settings_view

    @property
    def bin_view(self) -> BinView:
        if self._bin_view is None:
            self._bin_view = BinView(self)
            self._bin_view.recolor(self.colors)
        return self._bin_view

    def _show_view(self, view):
        if self.pad.collapsed and getattr(self, "_built", False):   # e.g. a day clicked in the calendar
            self.toggle_collapse()
        self._end_page_change()
        before = self._page_area_picture() if view != getattr(self, "view", view) else None
        forward = view != "home"
        self.view = view
        PopupMenu.close_current()
        self.list_view.hide_preview()
        for page in (self.list_view, self._settings_view, self._bin_view):
            if page is not None:
                page.frame.pack_forget()
        self.home.pack_forget()
        if view == "home":
            self.btn_back.pack_forget()
            self.home.pack(fill="both", expand=True)
        else:                               # the date row: back, the page's name, close; the rail stays
            if not self.btn_back.winfo_manager():
                self.btn_back.pack(side="left", before=self.row)
            page = {"list": self.list_view, "settings": self.settings_view, "bin": self.bin_view}[view]
            page.frame.pack(fill="both", expand=True)
        self._arrange_chrome()              # (the format buttons are the memo's)
        self.bump_look()
        tk.Misc.tkraise(self.grip)
        self._place_toast()
        if before is not None:
            self._page_change(before, forward)

    # ---- moving between pages: the new one slides in 12 px and fades (picked option D) -------
    def _page_area_picture(self):
        """The page area as it shows now, (image, box in the window), when a page change may be
        animated: built, showing, not folded or frozen or rolling, Animations not Off. Else None."""
        clock = self.app.clock
        try:
            if (not getattr(self, "_built", False) or clock.mode == "off" or self.pad.collapsed
                    or self._cover is not None or getattr(self, "_rolling_cover", None) is not None
                    or not self.win.winfo_ismapped() or self.win.state() != "normal"):
                return None
            v = self.views
            x, y = v.winfo_rootx() - self.win.winfo_rootx(), v.winfo_rooty() - self.win.winfo_rooty()
            box = (x, y, x + v.winfo_width(), y + v.winfo_height())
        except tk.TclError:
            return None
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            return None
        shot = self.app.shots.fresh(self)
        return None if shot is None else (shot.crop(box).convert("RGB"), box)

    def _page_change(self, before, forward):
        """The new page (just laid out) comes in over the old one's picture: a cover over the page
        area blends from the old picture to the new one over PAGE_MS while both slide PAGE_SHIFT px
        (forward: in from the right; back: from the left). Reduced: the fade only."""
        old, box = before
        self.win.update_idletasks()
        after = self._page_area_picture()
        if after is None or after[1] != box:
            return
        new = after[0]
        clock, c = self.app.clock, self.colors
        shift = 0 if clock._instant("move") else self.app.px(PAGE_SHIFT)
        self._page_move = shift if forward else -shift
        w, h = old.size
        photo = ImageTk.PhotoImage(old, master=self.views)
        cover = tk.Canvas(self.views, bd=0, highlightthickness=0, bg=c.bg, width=w, height=h)
        cover.create_image(0, 0, anchor="nw", image=photo)
        cover._photo = photo
        cover.place(x=0, y=0, width=w, height=h)
        tk.Misc.tkraise(cover)
        self._page_cover = cover
        bg = tuple(round(v * 255) for v in _rgb(self.win, c.bg))
        move = self._page_move

        def frame(t):
            s, a = anim.ease_out(t), anim.smoothstep(t)
            a_img = Image.new("RGB", (w, h), bg)
            a_img.paste(old, (round(-move * s), 0))
            b_img = Image.new("RGB", (w, h), bg)
            b_img.paste(new, (round(move * (1 - s)), 0))
            photo.paste(Image.blend(a_img, b_img, a))
        animate(self.views, "page", PAGE_MS, frame, self._end_page_change, ease=lambda t: t, kind="fade")

    def _end_page_change(self):
        cover, self._page_cover = getattr(self, "_page_cover", None), None
        if cover is not None:
            stop_animation(self.views, "page")
            try:
                cover.destroy()
            except tk.TclError:
                pass

    def show_home(self):
        self._show_view("home")
        self.body.focus_set()

    def show_list(self, day=None):
        self.sync_from_widgets()
        self.list_view.day = day
        self.list_view.refresh()
        self._show_view("list")
        self.list_view.search_entry.focus_set()

    def show_bin(self):
        self.sync_from_widgets()
        self.bin_view.refresh()
        self._show_view("bin")

    def go_back(self):
        """Back arrow / Esc: the bin returns to the list, an open setting to the settings
        list, everything else to the memo."""
        if self.view == "settings" and self.settings_view.close():
            return
        if self.view == "bin":
            self.show_list()
        else:
            self.show_home()

    def show_settings(self):
        self.sync_from_widgets()
        self.settings_view.sync()
        self._show_view("settings")
        self.settings_view.reset()

    def toggle_settings(self):
        if self.view == "settings":
            self.show_home()
        else:
            self.show_settings()

    def _wheel(self, event):
        if self.view == "list":
            self.list_view.wheel(event)
        elif self.view == "settings":
            self.settings_view.wheel(event)
        elif self.view == "bin":
            self.bin_view.area.wheel(event)

    # ---- memos -------------------------------------------------------------------
    def _load_note(self, note: Note):
        self._loading = True
        try:
            self.note = note
            self.pad.note_id = note.id
            self.viewer.reset()                     # back to the first picture: its text is note.body
            self.pad.tab = 0
            self._fill_text(note.body, note.marks, note.inline)
            self.header_var.set(note.header)
        finally:
            self._loading = False
        self.win.title(memo_title(note))
        self._layout()
        self.apply_look()
        self._update_format_buttons()

    def _fill_text(self, body, marks, inline=()):
        self.preedit.place_forget()
        self._hide_todo_icons()
        self.body.delete("1.0", "end")          # pictures in the old text go too
        self._inline = {}
        self._pending = None
        _fill_rich_text(self.body, body, marks, inline, self._embed_picture)
        self._refresh_combined()
        self._refresh_bullets()
        self.body.edit_reset()
        self.body.edit_modified(False)

    def _fill_body(self, body, marks, inline=()):
        """Put another text (another picture's tab) in the editor."""
        self._loading = True
        try:
            self._fill_text(body, marks, inline)
        finally:
            self._loading = False
        self._update_format_buttons()

    # ---- picture tabs: every picture of an image memo has its own text ------------
    @property
    def tab(self) -> int:
        return self.viewer.index if self.note.style == "image" and self.note.images else 0

    def switch_tab(self, index):
        if self.note.style != "image" or not 0 <= index < len(self.note.images):
            return
        if index != self.viewer.index:
            self.app.finish_typing()
            self.sync_from_widgets()                # keep what was typed in the tab being left
            self.viewer.index = self.pad.tab = index
            self._fill_body(*self.note.tab_text(index))
            self.app.request_save()
            self.bump_look()
        self.viewer.render(follow=True)

    def step_tab(self, delta):
        if self.view == "home":
            self.switch_tab(self.viewer.index + delta)

    # ---- pictures inside the text ("+ Add picture" under it) ------------------------
    def _inline_width(self):
        px = self.app.px
        width = (self.body.winfo_width() if self.body.winfo_width() > 1
                 else self.pad.width - 2 * self.edge - px(RAIL_W))
        return max(px(60), width - 2 * int(self.body.cget("padx")) - px(6))

    def _inline_photo(self, name):
        photo = _picture_photo(self.app, name, (self._inline_width(), 100_000), self.body)
        if photo is None:                       # missing file: a plain box keeps its place
            photo = ImageTk.PhotoImage(Image.new("RGB", (self.app.px(120), self.app.px(60)), self.colors.well),
                                       master=self.body)
        return photo

    def _embed_picture(self, index, name):
        photo = self._inline_photo(name)
        key = self.body.image_create(index, image=photo, align="top", pady=self.app.px(3))
        self._inline[key] = (name, photo)

    def _rescale_inline(self):
        """The window changed width: fit the pictures in the text to it again."""
        self.bump_look()
        for _key, value, index in self.body.dump("1.0", "end", image=True):
            if value in self._inline:
                name, _old = self._inline[value]
                photo = self._inline_photo(name)
                self.body.image_configure(index, image=photo)
                self._inline[value] = (name, photo)       # the old one is no longer shown: free it

    def _content(self):
        """The text as stored: each picture in it becomes INLINE, and its file name is listed."""
        parts, names = [], []
        for key, value, _index in self.body.dump("1.0", "end-1c", text=True, image=True):
            if key == "text":
                parts.append(value)
            elif key == "image" and value in self._inline:
                parts.append(INLINE)
                names.append(self._inline[value][0])
        return "".join(parts), names

    def add_inline_pictures(self):
        """Put pictures under this tab's text (one per line); typing goes on below them."""
        self._choose_pictures(self.add_inline_picture)

    def add_inline_picture(self, image):
        name = self.app.store.add_image(image)
        b = self.body

        def change():
            last = b.dump("end-2c", "end-1c", text=True, image=True)
            if last and not (last[-1][0] == "text" and last[-1][1].endswith("\n")):
                b.insert("end-1c", "\n", ())
            self._embed_picture("end-1c", name)
            b.insert("end-1c", "\n", ())
        self._edit(change)
        b.mark_set("insert", "end-1c")
        b.see("end")
        self.sync_from_widgets()
        b.focus_set()

    def _show_preedit(self):
        """Show the syllable the Korean IME is putting together right at the cursor, as if it
        were already in the text (the IME's own box is turned off: winapi.hook_ime). While a
        syllable is being typed this checks again a few times a second; otherwise it rests."""
        try:
            typing = self.view == "home" and self.win.focus_get() is self.body
        except (KeyError, tk.TclError):
            typing = False
        text = winapi.composition(self.win.winfo_id()) if typing else ""
        box = self.body.bbox("insert") if text else None
        if not box:
            self.preedit.place_forget()
            return
        c = self.colors
        fmt = self._formats_at_cursor()
        font = self._preedit_font_for("b" in fmt, "i" in fmt)
        self._preedit_font = font
        x, y, _w, h = box
        shown = (text, box, font, c.bg, c.fg)
        if shown != getattr(self, "_preedit_last", None) or not self.preedit.winfo_ismapped():
            self._preedit_last = shown
            self.preedit.configure(text=text, font=font, bg=c.bg, fg=c.fg)
            self.preedit.place(x=x, y=y, height=h, bordermode="ignore")   # bbox counts from the outer edge
        self._later("preedit", 120, self._show_preedit)

    def _preedit_font_for(self, bold: bool, italic: bool) -> tkfont.Font:
        """The underlined font the syllable being typed is shown in, made once per style
        (it was made anew at every key and every 120 ms check)."""
        n = self.note
        key = (n.font_family, n.font_size, bold, italic)
        fonts = self.__dict__.setdefault("_preedit_fonts", {})
        font = fonts.get(key)
        if font is None:
            font = fonts[key] = tkfont.Font(self.win, family=n.font_family, size=n.font_size, underline=True,
                                            weight="bold" if bold else "normal",
                                            slant="italic" if italic else "roman")
        return font

    def _draw_period_band(self):
        self.bump_look()
        cv, c, px, note = self.period_band, self.colors, self.app.px, self.note
        cv.configure(bg=c.bg)
        cv.delete("all")
        if not note.end_date:
            return
        w, h = cv.winfo_width(), int(cv.cget("height"))
        if w <= 1:
            w = self.pad.width - px(18)
        cv.create_rectangle(0, 0, w - 1, h - 1, fill=shade(cv, c.bg, 1), outline=shade(cv, note.color, 2))
        x = px(5)
        if self.app.icons.available:
            self._band_photo = self.app.icons.photo(GLYPH["calendar"], c.fg, px(11))
            cv.create_image(x, h / 2, anchor="w", image=self._band_photo)
            x += px(15)
        days = (date.fromisoformat(note.end_date) - date.fromisoformat(note.date)).days + 1
        self.period_text = f"{_span_label(note)} · {tr('period_days', n=days)}"
        cv.create_text(x, h / 2, anchor="w", text=self.period_text, fill=c.fg, font=(UI_FONT, 8))

    def update_period_band(self):
        """The band shows while the memo is a period (it may become one, or stop, in the calendar)."""
        if bool(self.note.end_date) != bool(self.period_band.winfo_manager()):
            self._layout()
        elif self.note.end_date:
            self._draw_period_band()

    def show_period(self):
        """Click on the band: the calendar at the period's month, the memo picked."""
        note = self.note
        if not note.end_date:
            return
        if self.calendar is None:
            self.toggle_calendar()
        cal = self.calendar
        d = date.fromisoformat(note.date)
        cal.month, cal.selected, cal._picked = (d.year, d.month), note.date, note
        cal.draw()

    def _draw_add_bar(self, hover=False):
        self.bump_look()
        cv, c, px = self.add_bar, self.colors, self.app.px
        cv.configure(bg=c.bg)
        cv.delete("all")
        w, h = cv.winfo_width(), int(cv.cget("height"))
        if w <= 1:
            w = self.pad.width - px(18)
        cv.create_rectangle(1, 1, w - 2, h - 2, dash=(3, 2), outline=c.muted if hover else c.border,
                            fill=c.hover if hover else c.bg)
        cv.create_text(w / 2, h / 2, text=tr("add_picture_bar"), fill=c.fg if hover else c.muted,
                       font=(UI_FONT, 9))

    def open_note(self, note: Note) -> NoteWindow:
        """Show ``note`` here at home. If another window already shows it, bring that one up instead."""
        if note is self.note:
            self.show_home()
            return self
        other = self.app.window_for(note.id)
        if other is not None and other is not self:
            other.show()
            other.show_home()
            return other
        self.sync_from_widgets()
        leaving = self.note
        self._load_note(note)
        self.show_home()
        if leaving.is_empty:
            self.app.discard_note(leaving)
        self.app.request_save()
        self.app.refresh_lists()
        return self

    def new_memo(self, date=None) -> Note:
        """Keep the current memo in the list and start a blank one in this window."""
        self.sync_from_widgets()
        if self.note.is_empty:          # nothing to keep: reuse the blank memo
            if self.note.end_date:      # (a period it was made for is not this one's)
                self.note.end_date = None
            if date and date != self.note.date:
                self.note.date = date
                self._touch()
            self.show_home()
            return self.note
        note = self.app.blank_note(self.note, date=date)
        self.open_note(note)
        return note

    # ---- bin -----------------------------------------------------------------------
    def trash_current(self):
        """Move to the bin (the rail's ⋯, Ctrl+D). A blank memo has nothing to keep, so nothing happens."""
        self.sync_from_widgets()
        if not self.note.is_empty:
            self.trash_note(self.note)

    def trash_note(self, note: Note):
        shot = self._page_picture() if note is self.note else None
        if self.app.trash_note(note.id):
            if shot is not None:
                self._fly_to_bin(*shot)
            self.show_undo(note)

    def _page_picture(self):
        """The memo page as it shows now, for the deletion animation: (image, x, y) in this window's
        pixels, cut from the note's picture (shots: not the screen, so nothing over the note shows
        in it); None off the home page, folded, hidden, or when no picture can be had."""
        try:
            if self.view != "home" or self.pad.collapsed or not self.home.winfo_ismapped():
                return None
            x0 = self.home.winfo_rootx() - self.win.winfo_rootx()
            y0 = self.home.winfo_rooty() - self.win.winfo_rooty()
            w, h = self.home.winfo_width(), self.home.winfo_height()
            if w < 8 or h < 8:
                return None
            shot = self.app.shots.fresh(self)
            if shot is None:
                return None
            return shot.crop((x0, y0, x0 + w, y0 + h)), x0, y0
        except Exception:
            return None

    def _fly_to_bin(self, img, x, y):
        """Deletion (option 1, "휴지통으로 빨려들기"): the memo's picture shrinks into the rail's ⋯
        (where "move to the bin" is), speeding up as it goes (DELETE_FLY_MS), over the next memo
        already in place (only the picture's own box is covered); then ⋯ gives a little bounce."""
        top, btn = self.win, self.btn_more
        try:
            bx = btn.winfo_rootx() - top.winfo_rootx() + btn.winfo_width() / 2
            by = btn.winfo_rooty() - top.winfo_rooty() + btn.winfo_height() / 2
            w0, h0 = img.size
            cv = self._fly_canvas = tk.Canvas(top, bd=0, highlightthickness=0, width=w0, height=h0,
                                              bg=self.colors.bg)     # (the frame its size lags: the page's colour)
            cv._photo = ImageTk.PhotoImage(img, master=cv)      # the one picture every frame pastes into
            pic = cv.create_image(0, 0, anchor="nw", image=cv._photo)
            cv.place(x=x, y=y)
            tk.Misc.tkraise(cv)
        except tk.TclError:
            return
        half = img.resize((max(1, w0 // 2), max(1, h0 // 2)), Image.BOX)   # smaller frames scale from these
        quarter = half.resize((max(1, w0 // 4), max(1, h0 // 4)), Image.BOX)
        sx, sy = x + w0 / 2, y + h0 / 2
        tkphoto = cv._photo._PhotoImage__photo                  # (Tk's photo under it: its size is set)

        def step(t):
            e = t * t                                       # speeds up into the bin
            s = 1 - 0.95 * e
            w, h = max(2, round(w0 * s)), max(2, round(h0 * s))
            cx, cy = sx + (bx - sx) * e, sy + (by - sy) * e
            src = img if s > 0.5 else half if s > 0.25 else quarter
            tkphoto.configure(width=w, height=h)
            cv._photo.paste(src.resize((w, h), Image.BILINEAR))    # (no new PhotoImage a frame)
            cv.configure(width=w, height=h)
            cv.place(x=round(cx - w / 2), y=round(cy - h / 2))

        def done():
            try:
                cv.destroy()
            except tk.TclError:
                return
            self._bin_bounce()
        anim.clock_of(cv).animate(cv, "fly", DELETE_FLY_MS, step, done, ease=lambda t: t)

    def _bin_bounce(self):
        """The rail's ⋯: a little bounce as a memo lands in it."""
        btn = self.btn_more
        base = getattr(btn, "_rest_box", btn.box)
        btn._rest_box = base

        def step(k):
            btn.box = base * (1 + 0.3 * math.sin(math.pi * k)) if k < 1 else base
            btn._draw()
        anim.clock_of(btn).animate(btn, "bounce", anim.FAST, step, ease=lambda t: t)

    def show_undo(self, note: Note):
        self._notice = False
        self._undo_note = note
        self.toast_text.configure(text=tr("toast_moved"))
        self.undo_button.pack(side="left", padx=(0, self.app.px(4)))
        self._place_toast()
        self._later("toast", UNDO_MS, self.hide_undo)

    def show_undo_action(self, text, action):
        """A message in the bottom bar with Undo, which calls ``action``."""
        self._undo_note, self._notice, self._undo_action = None, True, action
        self.toast_text.configure(text=text)
        self.undo_button.pack(side="left", padx=(0, self.app.px(4)))
        self._place_toast()
        self._later("toast", UNDO_MS, self.hide_undo)

    def _toast_undo(self):
        action = self._undo_action
        if action is None:
            self.undo_trash()
            return
        self.hide_undo()
        action()

    def show_notice(self, text):
        """A short message in the bottom bar (no Undo)."""
        self._undo_note, self._notice = None, True
        self.toast_text.configure(text=text)
        self.undo_button.pack_forget()
        self._place_toast()
        self._later("toast", NOTICE_MS, self.hide_undo)

    def _place_toast(self):
        if self._undo_note is None and not self._notice:
            return
        self.bump_look()
        px = self.app.px
        if self.view == "list":
            lift = self.list_view.bin_row.winfo_reqheight() + px(10)
        else:
            lift = 0
        y, toast = -(px(12) + lift), self.toast
        if toast.place_info():              # already showing (e.g. another page): just move it
            stop_animation(toast, "rise")
            toast.place(relx=0.5, rely=1.0, y=y, anchor="s")
        else:                               # rises TOAST_RISE px into place
            rise = px(TOAST_RISE)
            animate(toast, "rise", TOAST_RISE_MS,
                    lambda k: toast.place(relx=0.5, rely=1.0, y=y + round(rise * (1 - k)), anchor="s"))
        tk.Misc.tkraise(toast)

    def hide_undo(self):
        job = self._jobs.pop("toast", None)
        if job is not None:
            self.win.after_cancel(job)
        self._undo_note, self._notice, self._undo_action = None, False, None
        stop_animation(self.toast, "rise")
        if self.toast.place_info():         # (it showed: the look changes)
            self.toast.place_forget()
            self.bump_look()

    def undo_trash(self):
        note = self._undo_note
        self.hide_undo()
        if note is None or self.app.restore_note(note.id) is None:
            return
        if self.view == "home":
            self.open_note(note)

    # ---- visibility --------------------------------------------------------------
    def show(self, focus=True):
        if self.minimized:
            self.restore()                  # unrolls, then the app returns the note to its place
        else:
            self.win.deiconify()
        self.app.space_changed()
        self.win.update_idletasks()
        # no taskbar button of its own: owned by the app's one (App._make_taskbar_proxy), it
        # comes forward with it
        winapi.set_owner(self.win, self.app.proxy)
        if not self._hooked:                # the taskbar's minimize / restore: the app animates them
            self._hooked = True
            winapi.disable_transitions(self.win)
            winapi.hook_syscommand(self.win, self.app._syscommands, self.app.wake_sys)
        if not self._rounded:
            self._rounded = True
            if self.edge == 0 and not winapi.round_corners(self.win):
                self.edge = 1               # DWM said no: square corners and the 1 px border
                self._pack_frame()
        self.win.attributes("-topmost", self.pad.pinned)
        self.win.lift()
        if focus:
            self.body.focus_force()

    def close(self):
        if self._closing:
            return
        self.sync_from_widgets()
        cal = self.calendar
        if cal is not None and not cal.docked:      # an undocked calendar stays, with another note
            heir = self.app.calendar_heir(self) or next(
                (w for w in self.app.windows.values() if w is not self and not w._closing), None)
            if heir is not None:
                cal.rehome(heir)
        self._hand_over_calendar()
        self.app._held_cal.pop(self.pad.id, None)
        self.app.close_window(self)

    def _tile_drop(self, dropped):
        """Auto layout, a note let go after a drag. A plain drag of a tile moved the whole grid
        (#6A, #23A): the grid takes the home it was dropped at, or goes to the screen the pointer
        is on. Alt pulls the note out (free); Ctrl over a tile swaps; a free note let go over a
        tile rejoins (#25A) (App.drop_tile)."""
        app, pad = self.app, self.pad
        pt = getattr(self, "_drag_pt", None) or (pad.x, pad.y)
        xy = (dropped or {}).get(self, (pad.x, pad.y))
        key = getattr(self, "_grid_key", None)
        if key is not None:
            dx, dy = xy[0] - self._drag_from[0], xy[1] - self._drag_from[1]
            if dx == 0 and dy == 0:
                app.arrange()
                return
            keys = app.area_keys()
            if keys[app._screen_index((*pt, *pt))] != key:      # (the pads go back; drop_grid moves them over)
                for w, (x, y) in (dropped or {}).items():
                    w.pad.x, w.pad.y = x - dx, y - dy
                app.space_changed()
                app.drop_grid(key, pt)
                return
            for w, (x, y) in (dropped or {}).items():
                w.pad.x, w.pad.y = x, y
            app.space_changed()
            home0 = self._grid_home0
            app.move_grid(key, (home0[0] + dx, home0[1] + dy), before=self._grid_before)
            return
        mods = set()
        if self._drag_alt:
            mods.add("alt")
        if getattr(self, "_drag_ctrl", False):
            mods.add("ctrl")
        if self._drag_alt or pad.free:      # it stays where it was let go
            pad.x, pad.y = xy
            app.space_changed()
        app.drop_tile(self, pt, mods)

    def set_height(self, h):
        """Make the note ``h`` tall (its docked calendar was resized: they stay level); the
        notes stacked under it (snapped) move along by as much, as when it folds up."""
        p = self.pad
        if p.collapsed or h == p.height:
            return
        group = self.app.group_windows(p.id)
        before = _pad_box(p)
        delta = h - p.height
        p.height = h
        self.win.geometry(f"{p.width}x{h}")
        slack = self.app.px(2)
        for w in group:
            if w is self:
                continue
            l, t, r, b = _pad_box(w.pad)
            if t >= before[3] - slack and min(r, before[2]) - max(l, before[0]) > 0:
                w.pad.y += delta
                w.win.geometry(f"+{w.pad.x}+{w.pad.y}")
        self.app.space_changed()

    def set_size(self, w, h):
        """Make the note ``w`` x ``h`` (the resize path of the grip and the menu): one grow in drag
        mode (its neighbours are pushed, the growth stops at the screen's edge); its docked
        calendar matches it and may change its view in that same plan."""
        p, app, px = self.pad, self.app, self.app.px
        x0, y0 = _pad_box(p)[:2]
        w, h = max(int(w), px(MIN_W)), max(int(h), px(MIN_H))
        note = (x0, y0, x0 + w, y0 + h)
        cal = self.calendar
        if cal is not None and cal.docked and cal.target_box is not None:
            cal.refit(note, mode="drag")
        else:
            app.grow({p.id: note}, "drag", "resized")

    def _hand_over_calendar(self):
        """Closing or minimizing: a note snapped to the docked calendar takes it over (it
        stays where it is); with none, it closes with this note as before."""
        heir = self.app.calendar_heir(self)
        if heir is not None:
            cal = self.calendar
            cal.rehome(heir)
            cal.place()

    def _delete_picked(self, _event=None):
        cal = self.calendar
        if cal is not None and cal._picked is not None:
            return cal._delete_key()
        self.win.after_idle(self._show_preedit)     # what the plain <KeyPress> binding does
        return None

    def fade_out(self, done):
        """Fade the note (and its calendar) out, then ``done()``. It takes no input meanwhile."""
        self._closing = True
        PopupMenu.close_current()
        self.list_view.hide_preview()
        self.hide_hints()
        wins = [self.win]
        if self.calendar:
            cal = self.calendar
            cal._closing = True
            for key in ("slide", "alpha"):
                stop_animation(cal.top, key)
            wins.append(cal.top)
        self.app.space_changed()            # closing: neither takes up space any more
        stop_animation(self.win, "fade")
        starts = [_alpha(w) for w in wins]
        try:
            self.win.attributes("-disabled", True)
        except tk.TclError:
            pass

        clock = anim.clock_of(self.win)
        for w, a in zip(wins, starts):          # (an exit: it speeds up as it goes, no turning back)
            clock.tween(w, "alpha", 0.0, CLOSE_FADE_MS, read=lambda a=a: a,
                        write=lambda v, w=w: w.winfo_exists() and w.attributes("-alpha", v),
                        ease=anim.ease_in, frm=a, done=done if w is self.win else None)

    def bump_look(self):
        """What the note shows changed: its kept picture is no longer current (shots)."""
        self.look_version += 1
        thumb = getattr(self.app, "thumb_soon", None)
        if thumb is not None:
            thumb()                         # (the taskbar preview may show it)
        shots = getattr(self.app, "shots", None)
        if shots is not None:
            shots.stale(self)

    def _pack_frame(self):
        self.frame.pack(fill="both", expand=True, padx=self.edge, pady=self.edge)
        if hasattr(self, "bar"):
            self.bar.configure(height=self._row_h())

    def _place_grip(self):
        """Bottom right; a little in from the corner when DWM rounds it (else the round cuts it)."""
        inset = 0 if self.edge else self.app.px(3)
        self.grip.place(relx=1, rely=1, anchor="se", x=-inset, y=-inset)

    def _row_h(self):
        """The date row's height: with the window's edge, a folded note is DATE_ROW_H tall."""
        return self.app.px(DATE_ROW_H) - 2 * self.edge

    def _roll_geometry(self, h, dy=0):
        p = self.pad
        cover = getattr(self, "_rolling_cover", None)
        if cover is not None and winapi.clip_height(self.win, p.width, round(h)):
            # rolling with its picture: the window stays as big as the picture, its region shows the
            # top h px (the region first, so the window never shows more than h, even as it grows);
            # ``dy`` slides it down (minimize: as it rolls, B5)
            geo = f"{p.width}x{cover.full_h}+{p.x}+{p.y + round(dy)}"
            if getattr(self, "_roll_geo", None) != geo:
                self._roll_geo = geo
                self.win.geometry(geo)
            return
        if getattr(self, "_roll_geo", None) is not None:
            winapi.clip_height(self.win)
            self._roll_geo = None
        self.win.geometry(f"{p.width}x{round(h)}+{p.x}+{p.y + round(dy)}")

    def _shot(self):
        """A picture of the whole note as it shows now (taken now: shots.fresh), or None."""
        return self.app.shots.fresh(self)

    def _kept_shot(self, height):
        """Its kept picture at its own width and ``height`` (the last roll's), if still current."""
        return self.app.shots.peek(self, (self.pad.width, height))

    def _roll_cover(self, img):
        """While it rolls (ROLL_MS), a picture of the whole note stands in, anchored at the top: the
        window only clips it, and nothing inside is laid out again at every frame (a long memo
        made the frames uneven)."""
        if img is None or getattr(self, "_rolling_cover", None) is not None:
            return
        cover = tk.Canvas(self.win, bd=0, highlightthickness=0, bg=self.colors.bg)
        cover._photo = ImageTk.PhotoImage(img, master=cover)
        cover.create_image(0, 0, anchor="nw", image=cover._photo)
        cover.place(x=0, y=0, width=img.width, height=img.height)      # full size: the window just clips it
        cover.full_h = img.height
        tk.Misc.tkraise(cover)
        self.frame.pack_forget()
        self._rolling_cover = cover

    def _drop_roll_cover(self, height=None):
        """The widgets back, the window ``height`` px tall (given: before its region goes)."""
        cover = getattr(self, "_rolling_cover", None)
        if cover is None:
            return
        self._rolling_cover = None
        if height is not None:
            p = self.pad
            self._size_now(p.x, p.y, p.width, round(height))
        if getattr(self, "_roll_geo", None) is not None:
            winapi.clip_height(self.win)
            self._roll_geo = None
        self._pack_frame()
        cover.destroy()

    def _size_now(self, x, y, w, h):
        """The window exactly (x, y, w, h) now, not at Tk's next idle as geometry() does: a window
        region about to go must never show the window bigger than this, even for a frame."""
        hwnd = winapi.hwnd_of(self.win)
        try:
            if hwnd and self.win.winfo_ismapped():
                winapi.defer_move([(hwnd, int(x), int(y), int(w), int(h))])
            self.win.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")    # (Tk's own record of it)
        except tk.TclError:
            pass

    def minimize_button(self):
        """The minimize button. "Top bar only" (Settings): an open note folds up to its top bar
        (as a double-click does); a folded one goes away for real (back from the taskbar)."""
        if self.app.prefs.minimize_style == "bar" and not self.pad.collapsed and not self.rolling:
            self.toggle_collapse()
            return
        self.minimize()

    def minimize(self, animate: bool = True):
        """Roll up to the top bar while (overlapping) it slides down and fades: one MINIMIZE_MS curve, then
        minimize for real. ``rolling`` keeps the pad's saved size out of it (_on_configure)."""
        if self.rolling or self.minimized:
            return
        cal = self.calendar
        if cal is None or cal.docked:       # an undocked calendar stays on its own meanwhile
            self._hand_over_calendar()
            cal = self.calendar
            if cal is not None and cal.target_box is not None:  # C4: the room stays held while it is minimized
                self.app._held_cal[self.pad.id] = tuple(cal.target_box)
            self.close_calendar(remember=True)
        win, p, px = self.win, self.pad, self.app.px
        alpha = p.alpha

        shown = _shown_h(p)                 # (folded: its bar)

        def finish():
            try:
                self._roll_geometry(shown)
                win.withdraw()              # back from the app's one taskbar button, or its sticker
                self.minimized = True
                win.attributes("-alpha", alpha)
            except tk.TclError:
                return
            self._drop_roll_cover(shown)
            self.rolling = False
            if self.app.prefs.minimize_style == "sticker":
                self._show_sticker()
            self.app.note_minimized(self)
            self.app.space_changed()
            self.app.arrange_soon()         # auto layout: the others close up

        mode = self.app.clock.mode          # (B9: Off just goes; Reduced fades, no roll and no picture)
        if not animate or mode == "off":
            self.rolling = True
            finish()
            return
        self.rolling = True
        if mode == "reduced":
            fade(win, "fade", alpha, 0.0, CLOSE_FADE_MS, done=finish, ease=anim.ease_in)
            return
        bar, slide = min(shown, self.collapsed_height()), px(40)
        self._roll_cover(self._shot())

        def step(t):                        # one curve (B5): it rolls up, and from a third of the way
            h = shown + (bar - shown) * anim.ease_out(min(1.0, t / 0.6))    # its bar slides down and
            u = anim.ease_in(max(0.0, (t - 0.35) / 0.65))                   # fades, speeding up as it goes
            self._roll_geometry(h, slide * u)
            win.attributes("-alpha", alpha * (1 - u))
        animate_(win, "roll", MINIMIZE_MS, step, finish, ease=lambda t: t)

    def restore(self, animate: bool = True):
        """The reverse of minimize, one MINIMIZE_MS curve: the bar slides up and fades in while it unrolls; then the app
        returns the note to its place (return_note)."""
        if self.rolling or not self.minimized:
            return
        self._hide_sticker()
        win, p, px = self.win, self.pad, self.app.px
        alpha = p.alpha
        shown = _shown_h(p)
        bar, slide = min(shown, self.collapsed_height()), px(40)
        self.rolling = True

        def finish():
            try:
                self._roll_geometry(shown)
                win.attributes("-alpha", alpha)
                win.attributes("-topmost", p.pinned)
                win.lift()
            except tk.TclError:
                return
            self._drop_roll_cover(shown)
            self.rolling = False
            self.app._held_cal.pop(p.id, None)
            self.app.space_changed()
            self.app.return_note(self, "restore")

        win.attributes("-alpha", 0.0)
        mode = self.app.clock.mode          # (B9: Off just comes back; Reduced fades in, no roll)
        animate = animate and mode != "off"
        if animate and mode == "reduced":
            self._roll_geometry(shown)
            win.deiconify()
            self.minimized = False
            fade(win, "fade", 0.0, alpha, OPEN_FADE_MS, done=finish)
            return
        if animate:                         # its picture from when it went, if it still looks that way
            self._roll_cover(self._kept_shot(shown))
        self._roll_geometry(bar if animate else shown, slide if animate else 0)
        win.deiconify()
        self.minimized = False
        if not animate:
            finish()
            return

        def step(t):                        # one curve (B5): the bar slides up and fades in, and from 40 %
            u = anim.ease_out(min(1.0, t / 0.65))                                # of the way it unrolls
            h = bar + (shown - bar) * anim.ease_out(max(0.0, (t - 0.4) / 0.6))
            self._roll_geometry(h, slide * (1 - u))
            win.attributes("-alpha", alpha * u)
        animate_(win, "roll", MINIMIZE_MS, step, finish, ease=lambda t: t)

    def _show_sticker(self):
        self._hide_sticker()
        try:
            self.sticker = MiniSticker(self)
        except tk.TclError:
            self.sticker = None

    def _hide_sticker(self):
        if self.sticker is not None:
            self.sticker.destroy()
            self.sticker = None

    def destroy(self):
        self._hide_sticker()
        if "sync" in self._jobs and self.win.winfo_exists():    # typed just before: keep it
            self.sync_from_widgets()
        self.close_calendar(remember=True)
        self.list_view.hide_preview()
        self.cancel_jobs()
        stop_animation(self.win, "fade")
        stop_animation(self.win, "roll")
        stop_animation(self.win, "flash")
        self.app.motion.window_gone(self.pad.id)    # a glide in progress: the pad keeps where it got
        anim.clock_of(self.win).drop_owner(self.win)
        self._release()
        if self.win.winfo_exists():
            self.win.destroy()

    def _release(self):
        """Let go of what would keep this window (and its pictures) alive once it is closed:
        variable traces live in Tcl and hold their callbacks, and through them this window."""
        for var, name in self._trace_ids:
            try:
                var.trace_remove("write", name)
            except tk.TclError:
                pass
        self._trace_ids = []
        self.list_view.release()
        self.viewer.release()
        self.app.shots.drop(self)
        self._inline = {}
        if self.app.last_note is self:
            self.app.last_note = None

    def cancel_jobs(self):
        for job in self._jobs.values():
            try:
                self.win.after_cancel(job)
            except tk.TclError:
                pass
        self._jobs.clear()

    def _later(self, key, ms, fn):
        if key in self._jobs:
            self.win.after_cancel(self._jobs[key])
        self._jobs[key] = self.win.after(ms, lambda: (self._jobs.pop(key, None), fn()))

    # ---- calendar ---------------------------------------------------------------------
    def toggle_calendar(self):
        """One calendar at a time: while one is open, the other notes hide their calendar
        icon; opened from here anyway (a shortcut, a menu), it moves over to this note."""
        if self.calendar:
            self.close_calendar()
        else:
            other = self.app.calendar_elsewhere(self)
            if other is not None:
                other.close_calendar()
            self.make_calendar("user")

    def make_calendar(self, how="user"):
        """Open its calendar: built withdrawn, planned and shown by CalendarPopup.open (after
        self.calendar is set, so the plan sees it)."""
        self.calendar = cal = CalendarPopup(self)
        self.pad.calendar = True
        cal.open(how)
        self.app.arrange_soon()             # auto layout: the calendar takes a column
        self.app.request_save()
        self.app.calendar_buttons()

    def _reopen_calendar(self):
        """Restored from minimized with ``pad.calendar`` set: its calendar comes back where the
        note kept its room, pushing nothing."""
        pad, app = self.pad, self.app
        if not pad.calendar or self.calendar is not None:
            return
        self.calendar = cal = CalendarPopup(self)
        if cal.docked:
            side, view, cal_box, _clear = cal.plan_dock(side=pad.calendar_side)
            if side is None:                # G7: no side fits any screen: it comes back undocked
                cal.undock_to(cal_box)
            else:
                cal.set_view(view)
                cal.least = cal.least_size()
            cal.move_to(cal_box)
        else:
            cal.move_to(cal._undocked_box())
        cal.reveal()
        app.space_changed()
        app.request_save()
        app.calendar_buttons()

    def user_moved(self, moved: bool = False) -> None:
        """The user dragged (``moved``), resized or folded this note: what the calendar made it
        give up is its own now (P4), and it leaves its pile. ``own_size`` stays."""
        self.pad.cal_mark = None
        self.pad.stacked = False
        p, app = self.pad, self.app
        if not moved or p.own_size is None:
            return
        # P6: shrunk to fit, it grows back to its own size when the user next moves it, where the
        # new spot has room (a note with a docked calendar keeps what it has)
        if self.calendar is not None and self.calendar.docked:
            return
        x, y = _pad_box(p)[:2]
        ow, oh = p.own_size
        want = (x, y, x + ow, y + (oh if not p.collapsed else _shown_h(p)))
        if (ow, oh) == (p.width, p.height):
            p.own_size = None
            return
        if geom.is_free(want, app.usable(), [s.box for s in app.space({p.id})], app._gap()):
            p.own_size = None
            app.apply({p.id: want})

    def close_calendar(self, remember=False):
        """Close the calendar. The user closing it is remembered; a window closing or the
        app quitting keeps it marked open, so it comes back with the note."""
        if self.calendar:
            last = self.calendar.target_box
            self.calendar.destroy(animated=not remember)    # the user closing it: slides back in
            self.calendar = None
            self.app.space_changed()
            if not remember:
                self.pad.calendar = False
                self.app.request_save()
                if last is not None:
                    self.app.give_back(toward=tuple(last))
            self.app.calendar_buttons()
            self.app.arrange_soon()

    def update_date(self):
        self._draw_row()
        self.bump_look()
        if self.calendar:
            self.calendar.draw()

    def _focus_in(self, event):
        if event.detail in ("NotifyVirtual", "NotifyNonlinearVirtual"):
            return                          # (on its way to the widget that gets it)
        editing = event.widget is self.body
        if editing != self._editing:
            self._editing = editing
            self._arrange_chrome()

    def rail_shown(self) -> tuple:
        """The rail's buttons showing now, top to bottom (⋯ not counted: it always shows)."""
        return self._rail_state or ()

    def rail_hidden(self) -> tuple:
        """The rail's buttons that would show if there were room: in the ⋯ menu instead."""
        return self._rail_hidden

    def _arrange_chrome(self, width=None, height=None):
        """The rail and the date row for the note's size and state. Folded up: no rail, the date
        row is the whole note. Else the rail shows what fits, top to bottom (give_way: the first
        to go into the ⋯ menu), with the format buttons while the memo text has the focus."""
        p, px, win = self.pad, self.app.px, self.win
        if width is None:
            width = win.winfo_width() if win.winfo_width() > 1 else p.width
        if p.collapsed:                     # (no back arrow either: the strip shows the memo)
            if self.rail.winfo_manager():
                self.rail.pack_forget()
            self.btn_back.pack_forget()
            self._rail_state, self._rail_hidden = None, ()
            self._draw_row(width)
            return
        if height is None:                  # the note's own height: the window may not have caught up
            height = p.height               # yet (just unfolded, or a glide setting out)
        if not self.rail.winfo_manager():
            self.rail.pack(side="left", fill="y", before=self.main)
        if self.view != "home" and not self.btn_back.winfo_manager():
            self.btn_back.pack(side="left", before=self.row)
        elsewhere = self.app.calendar_elsewhere(self) is not None      # one calendar at a time
        wanted = [b for b in self.nav_buttons if not (b is self.btn_cal and elsewhere)]
        if self._editing and self.view == "home":
            wanted += self.format_buttons
        bh, gap = px(RAIL_BUTTON[1]), px(RAIL_GAP)
        room = height - 2 * self.edge - 2 * px(RAIL_PAD) - bh          # under the top pad, above ⋯

        def need(bs):
            both = any(b in self.format_buttons for b in bs) and any(b in self.nav_buttons for b in bs)
            return len(bs) * bh + (gap if both else 0)
        show = list(wanted)
        for b in self.give_way:
            if need(show) <= room:
                break
            if b in show and b is not self.btn_memo:
                show.remove(b)
        shown = tuple(show)
        self._rail_hidden = tuple(b for b in wanted if b not in shown)
        if shown != getattr(self, "_rail_seen", None):     # (folding and back: the same look)
            self._rail_seen = shown
            self.bump_look()
        if shown != self._rail_state:
            self._rail_state = shown
            for b in self.nav_buttons + self.format_buttons:
                b.pack_forget()
            self.rail_sep.pack_forget()
            nav = any(b in self.nav_buttons for b in shown)
            for b in shown:
                if b is next((f for f in shown if f in self.format_buttons), None) and nav:
                    self.rail_sep.pack(side="top", pady=((gap - 1) // 2, gap - 1 - (gap - 1) // 2))
                b.pack(side="top")
        self._draw_row(width)

    def _narrowest(self, font):
        name = str(font)
        if name not in self._narrow:
            self._narrow[name] = min(font.measure(c) for c in " i.·l")
        return self._narrow[name]

    def _draw_row(self, width=None):
        """The date row: today's day, big, and the month and weekday beside it, on one baseline.
        Folded up: the day, then what the memo says, cut to fit. On another page: its name (after
        the back arrow). Nothing is ever laid over the close button or cut off mid-letter."""
        cv, px, c, p = self.row, self.app.px, self.colors, self.pad
        if width is None:
            width = self.win.winfo_width() if self.win.winfo_width() > 1 else p.width
        folded = p.collapsed
        page = self.view != "home" and not folded
        room = width - 2 * self.edge - self.btn_close.winfo_reqwidth() - self.btn_min.winfo_reqwidth() - px(4)
        if not folded:
            room -= px(RAIL_W)
        if page:
            room -= self.btn_back.winfo_reqwidth()
        h = self._row_h()
        cv.delete("all")
        if page:
            f = self._title_font
            text = fit_text(tr(f"title_{self.view}"), room - px(6), f.measure, self._narrowest(f))
            cv.create_text(px(2), h / 2, anchor="w", text=text, font=f, fill=c.fg, tags=("text",))
            self.date_tip.text = tr("tip_grab")
            return
        num, small = texts.date_row(date.today())
        nf, sf = self._num_font, self._small_font
        base = round(h / 2 + 0.36 * px(DATE_NUM_PX))       # the digits' ink centred in the row
        x = px(10)                          # in line with the memo's text under it
        cv.create_text(x, base - nf.metrics("ascent"), anchor="nw", text=num, font=nf, fill=c.fg, tags=("text",))
        x += nf.measure(num) + px(6)
        if folded:                          # what the memo says, cut to fit (cached: runs at every resize)
            lines = self._fold_lines()
            full = " · ".join(lines)
            key = (full, room - x, str(sf))
            fit = getattr(self, "_fold_fit", None)
            if fit is None or fit[0] != key:
                fit = self._fold_fit = (key, fit_text(full, room - x, sf.measure, self._narrowest(sf)))
            text, fill = fit[1], c.fg
            shown = "\n".join(lines[:6]) + ("\n…" if len(lines) > 6 else "")
            self.date_tip.text = tr("tip_folded", text=shown)
        else:
            text, fill = fit_text(small, room - x, sf.measure, self._narrowest(sf)), c.muted
            self.date_tip.text = tr("tip_date")
        if text and text != "…":
            cv.create_text(x, base - sf.metrics("ascent"), anchor="nw", text=text, font=sf, fill=fill,
                           tags=("text",))

    def row_texts(self) -> list[str]:
        """What the date row shows, left to right (tests, the perf tools)."""
        return [self.row.itemcget(i, "text") for i in self.row.find_withtag("text")]

    def _fold_lines(self) -> list[str]:
        """The memo's text lines (title, then the rest; pictures counted) for a folded note."""
        n = self.note
        lines = [n.header.strip()] if n.style == "header" and n.header.strip() else []
        for _image, body, _marks, _inline in n.tabs():
            lines += [s for s in (line.replace(INLINE, "").strip() for line in body.split("\n")) if s]
        if n.images and n.style == "image":
            lines.append(tr("folded_pictures", n=len(n.images)))
        return lines or [tr("untitled")]

    # ---- look --------------------------------------------------------------------------
    def apply_look(self):
        n, p = self.note, self.pad
        win = self.win
        c = self.colors = Colors.of(win, n.color)
        # the rail: the note's color a shade toward its ink; a strong color (a pale page) keeps
        # the color itself there, as its top bar did
        rail_bg = c.color if c.tinted else _mix(win, c.bg, c.fg, 0.07)
        rc = self.rail_colors = Colors.of(win, rail_bg, solid=True)
        win.configure(bg=c.frame)           # (seen only as the 1 px border: edge 1)
        for w in (self.frame, self.main, self.views, self.home, self.bar, self.row):
            w.configure(bg=c.bg)
        for w in (self.rail, self.rail_top):
            w.configure(bg=rc.bg)
        self.rail_sep.configure(bg=rc.border)
        for b in self.rail_buttons:
            b.recolor(rc, strong=(b is self.btn_pin and p.pinned))
        self.btn_pin.set_glyph(GLYPH["pinned" if p.pinned else "pin"])
        for b in (self.btn_back, self.btn_min, self.btn_close):
            b.recolor(c)
        self._draw_row()
        cursor = self.app.cursor_color(c.bg)        # the main theme color's opposite
        self.header_entry.configure(bg=c.bg, fg=c.fg, insertbackground=cursor,
                                    selectbackground=c.select, selectforeground=c.fg,
                                    font=(n.font_family, n.font_size + 3, "bold"))
        self.header_sep.configure(bg=c.border)
        self.viewer.recolor(c)
        self.body.configure(bg=c.bg, fg=c.fg, insertbackground=cursor,
                            selectbackground=c.select, selectforeground=c.fg,
                            inactiveselectbackground=c.select, font=(n.font_family, n.font_size))
        self.body_scroll.recolor(c.bg)
        fam, size = n.font_family, n.font_size
        self.body.tag_configure("b", font=(fam, size, "bold"))
        self.body.tag_configure("i", font=(fam, size, "italic"))
        self.body.tag_configure("bi", font=(fam, size, "bold", "italic"))
        self.body.tag_configure("u", underline=True)
        self.body.tag_configure("s", overstrike=True)
        self.body.tag_configure("bullet", lmargin2=tkfont.Font(self.win, font=(fam, size)).measure(BULLET))
        box_font = (BOX_FONT, size + 1)
        self.body.tag_configure("todo", lmargin2=tkfont.Font(self.win, font=box_font).measure(TODO[0])
                                + tkfont.Font(self.win, font=(fam, size)).measure(" "))
        self.body.tag_configure("todo_box", font=box_font, foreground=c.muted)
        self.body.tag_configure("todo_done", overstrike=True, foreground=c.muted)    # done: crossed out, faint
        for icon in (self.todo_undo, self.todo_remove):
            icon.configure(bg=c.bg)
        paint_glyph(self.app, self.todo_undo, GLYPH["undo"], c.muted, mirror=True)
        paint_glyph(self.app, self.todo_remove, GLYPH["remove"], c.muted)
        self._draw_add_bar()
        self._draw_grip()
        for page in (self.list_view, self._settings_view, self._bin_view):
            if page is not None:            # (the others take the colors when they are made)
                page.recolor(c)
        toast_hover = _mix(self.win, c.fg, c.bg, 0.2)
        self.toast.configure(bg=c.fg)
        self.toast_text.configure(bg=c.fg, fg=c.bg)
        self.undo_button._bg, self.undo_button._hover = c.fg, toast_hover
        self.undo_button.configure(bg=c.fg, fg=c.bg)
        paint_glyph(self.app, self.undo_button, GLYPH["undo_action"], c.bg, box=ICON_BOX)
        if self.period_band.winfo_manager():
            self._draw_period_band()
        self.win.attributes("-alpha", p.alpha)
        self.win.attributes("-topmost", p.pinned)
        if self.calendar:
            self.calendar.recolor(self.app.theme_colors())
            self.calendar.apply_alpha()
            self.calendar.top.attributes("-topmost", p.pinned)
        self.bump_look()

    def _draw_grip(self):
        g, c = self.grip, self.colors
        g.configure(bg=c.bg)
        g.delete("all")
        size = int(g.cget("width"))
        dot = max(2, size // 6)
        step = dot + 1
        for row in range(3):                 # a small triangle of dots in the corner
            for col in range(3 - row):
                x, y = size - (col + 1) * step, size - (row + 1) * step
                g.create_rectangle(x, y, x + dot, y + dot, fill=c.border, outline="")

    def set_color(self, color):
        self.note.color = color.upper()
        self._touch()
        self.apply_look()

    def set_font(self, family=None, size=None):
        if family:
            self.note.font_family = family
        if size:
            self.note.font_size = max(6, min(72, int(size)))
        self._touch()
        self.apply_look()

    def set_transparency(self, percent):
        """Transparency is one setting for every note (App.set_transparency)."""
        self.app.set_transparency(percent, source=self)

    def _apply_alpha(self):
        self.win.attributes("-alpha", self.pad.alpha)
        if self.list_view.preview is not None:
            self.list_view.preview.top.attributes("-alpha", self.pad.alpha)
        if self.calendar:
            self.calendar.apply_alpha()

    def toggle_pin(self):
        self.pad.pinned = not self.pad.pinned
        self.app.request_save()
        self.apply_look()

    # ---- styles --------------------------------------------------------------------------
    def set_style(self, style):
        """Change this memo's layout. New memos will use it too, even after a restart."""
        if style not in STYLES:
            return
        self.sync_from_widgets()
        old = self.tab
        self.note.style = style
        self.app.prefs.last_style = style
        if self.tab != old:                         # leaving the picture tabs: show the first text
            self._fill_body(*self.note.tab_text(self.tab))
        self._layout()
        self._touch()

    def _layout(self):
        px = self.app.px
        for w in (self.header_entry, self.header_sep, self.viewer.frame, self.add_bar, self.body,
                  self.period_band):
            w.pack_forget()
        style = self.note.style
        if style == "image" and self.note.images:
            self.add_bar.pack(side="bottom", fill="x", padx=px(8), pady=(px(2), px(6)))
            self._draw_add_bar()
        # packed before the header / picture: when the note is small, they give way, not the text
        self.body.pack(side="bottom", fill="both", expand=True)
        if self.note.end_date:              # above the header / picture
            self.period_band.pack(side="top", fill="x", padx=px(8), pady=(px(4), px(2)))
            self._draw_period_band()
        if style == "header":
            self.header_entry.pack(side="top", fill="x", padx=px(10), pady=(px(2), px(4)))
            self.header_sep.pack(side="top", fill="x", padx=px(10))
        elif style == "image":
            self.viewer.frame.pack(side="top", fill="x", padx=px(8), pady=(px(2), px(4)))
            self.viewer.render(follow=True)
        tk.Misc.tkraise(self.grip)
        self.bump_look()

    def _style_menu(self, x=None, y=None):
        menu = PopupMenu(self.app, self.win, self.colors)
        for style in STYLES:
            menu.add(tr(f"style_{style}"), lambda s=style: self.set_style(s), checked=style == self.note.style)
        if x is None:
            b = self.btn_more
            x, y = b.winfo_rootx() + b.winfo_width(), b.winfo_rooty()
        menu.popup(x, y)

    def _more_menu(self, x=None, y=None) -> PopupMenu:
        """The rail's ⋯: layout, move to the bin, settings, minimize; then the rail buttons a
        short note has no room for, in the rail's order."""
        if x is None:
            b = self.btn_more
            x, y = b.winfo_rootx() + b.winfo_width(), b.winfo_rooty()
        menu = PopupMenu(self.app, self.frame)
        menu.add(tr("menu_style"), lambda: self._style_menu(x, y), icon=GLYPH["style"])
        if self.view == "home":
            menu.add(tr("menu_trash"), self.trash_current, icon=GLYPH["trash"], key="Ctrl+D")
        menu.add(tr("menu_settings"), self.show_settings, icon=GLYPH["gear"])
        menu.add(tr("menu_minimize"), self.minimize_button, icon=GLYPH["minimize"])
        hidden = self.rail_hidden()
        if hidden:
            menu.separator()
        named = {self.btn_window: ("menu_new_window", False), self.btn_list: ("menu_list", False),
                 self.btn_cal: ("menu_calendar", self.calendar is not None),
                 self.btn_pin: ("menu_on_top", self.pad.pinned)}
        for b in hidden:
            key, checked = named.get(b, (None, b.active))
            label = tr(key) if key else b.tooltip.text.split("\n")[0]
            menu.add(label, b._command, checked=checked, icon=GLYPH["note"] if b is self.btn_window else b.glyph)
        menu.popup(x, y)
        return menu

    # ---- images -----------------------------------------------------------------------------
    def add_image(self, image):
        """Store a PIL image as one more picture of this memo and show it. The first
        picture keeps the memo's text; every later one is a new tab with its own text."""
        name = self.app.store.add_image(image)
        self.sync_from_widgets()
        old = self.tab
        self.viewer.index = self.note.add_image(name)
        self.note.style = "image"
        if self.tab != old:
            self._fill_body(*self.note.tab_text(self.tab))
        self._layout()
        self._touch()

    def remove_image(self, index=None):
        """Remove one picture (the shown one by default) and delete its file. Its text
        moves to the tab next to it, so nothing typed is lost."""
        index = self.viewer.index if index is None else index
        if not 0 <= index < len(self.note.images):
            return
        self.sync_from_widgets()
        name = self.note.remove_image(index)
        self.viewer.forget(name)
        self.app.store.remove_image(name)
        if index < self.viewer.index or self.viewer.index >= len(self.note.images):
            self.viewer.index = max(0, self.viewer.index - 1)
        self._fill_body(*self.note.tab_text(self.tab))
        self._layout()
        self._touch()

    def pick_images(self):
        """Add pictures as new tabs (the + tile, the picture button)."""
        self._choose_pictures(self.add_image)

    def _choose_pictures(self, add):
        """Ask for picture files and hand each to ``add`` as a Pillow image."""
        paths = filedialog.askopenfilenames(parent=self.win, title=tr("choose_pictures"),
                                            filetypes=((tr("files_images"), IMAGE_PATTERNS), (tr("files_all"), "*.*")))
        failed = []
        for path in paths:
            try:
                add(_open_image(path))
            except Exception:
                failed.append(os.path.basename(path))
        if failed:
            messagebox.showerror(APP_NAME, tr("could_not_open") + "\n" + "\n".join(failed), parent=self.win)

    def _image_menu(self, event, index=None):
        menu = PopupMenu(self.app, self.win, self.colors)
        menu.add(tr("menu_add_pictures"), self.pick_images, icon=GLYPH["picture"])
        menu.add(tr("menu_paste_picture"), self._paste, icon=GLYPH["paste"], key="Ctrl+V")
        if index is not None:
            menu.add(tr("menu_open_picture"), lambda: self._open_image_file(index), icon=GLYPH["open_window"])
            menu.separator().add(tr("menu_remove_picture"), lambda: self.remove_image(index), danger=True,
                                 icon=GLYPH["remove"])
        menu.popup(event.x_root, event.y_root)

    def _open_image_file(self, index):
        if 0 <= index < len(self.note.images):
            path = self.app.store.image_path(self.note.images[index])
            if path.exists() and hasattr(os, "startfile"):
                os.startfile(path)

    def _paste(self, _event=None):
        if self.note.style != "image" or self.view != "home":
            return None
        image = _clipboard_image()
        if image is None:
            return None
        self.add_image(image)
        return "break"

    # ---- edits ----------------------------------------------------------------------------------
    @perf.timed("body_modified")
    def _on_body_modified(self, _event=None):
        if not self.body.edit_modified():
            return
        self.body.edit_modified(False)
        b = self.body
        count = int(b.index("end-1c").split(".")[0])
        row = int(b.index("insert").split(".")[0])
        lo, hi = row - 1, row + 1                   # the lines around the cursor, and those typed into
        t, self._touched = getattr(self, "_touched", None), None
        if t:
            lo, hi = min(lo, t[0] - 1), max(hi, t[1] + 1)
        before, self._line_count = getattr(self, "_line_count", None), count
        if before is None or abs(count - before) > hi - lo:
            self._refresh_bullets()                 # (more lines came or went than those: an undo, say)
            self._refresh_combined()
        else:
            self._refresh_bullets(max(1, lo), min(count, hi))
        self._sync_soon()

    def _sync_soon(self):
        """While typing, the stored memo catches up once the typing pauses: reading a long
        memo back (some 5 ms for 3000 lines) twice at every key made typing heavy. Whatever
        needs it at once (saving, switching memos, the list, closing) calls sync_from_widgets."""
        self.bump_look()                    # (typed: what it shows changed)
        self._later("sync", TYPING_SYNC_MS, self.sync_from_widgets)

    def sync_from_widgets(self):
        job = self._jobs.pop("sync", None)          # caught up now: no need to wait
        if job is not None:
            self.win.after_cancel(job)
        if self._loading:
            return
        (body, inline), header = self._content(), self.header_var.get()
        changed = self.note.set_tab_text(self.tab, body, self._read_marks(len(body)), inline)
        if header != self.note.header:
            self.note.header, changed = header, True
        if changed:
            self._touch()

    # ---- text formats ---------------------------------------------------------------------------
    def _text_event(self, what, *args):
        if what == "inserted":
            self._typed(*args)
        elif what == "deleted":             # the line it joined at is re-tagged (_on_body_modified)
            row = int(str(args[0]).split(".")[0])
            t = getattr(self, "_touched", None)
            self._touched = (min(row, t[0]), max(row, t[1])) if t else (row, row)
        elif what == "moved" and not self._raw:
            self._pending = None
            self._update_format_buttons()

    def _typed(self, start, end):
        """New text gets the format picked for typing, or the one of the text before it."""
        if self._raw or self._loading:
            return
        fmt = self._pending if self._pending is not None else self._formats_before(start, end)
        for kind in MARK_KINDS:
            (self.body.tag_add if kind in fmt else self.body.tag_remove)(kind, start, end)
        first, last = int(str(start).split(".")[0]), int(str(self.body.index(end)).split(".")[0])
        t = getattr(self, "_touched", None)         # (the lines <<Modified>> re-tags: _on_body_modified)
        self._touched = (min(first, t[0]), max(last, t[1])) if t else (first, last)
        self._refresh_combined(first, last)
        self._update_format_buttons()
        self._sync_soon()

    def _formats_before(self, index, after=None):
        b = self.body
        if b.compare(index, ">", "1.0"):
            names = b.tag_names(f"{index} -1c")
        else:                                       # at the very start: take the text that follows
            names = b.tag_names(after or index)
        return {k for k in MARK_KINDS if k in names}

    def _formats_at_cursor(self):
        if self.body.tag_ranges("sel"):
            return {k for k in MARK_KINDS if self._covered(k, "sel.first", "sel.last")}
        if self._pending is not None:
            return set(self._pending)
        return self._formats_before("insert")

    def _covered(self, kind, start, end):
        """Is every character from ``start`` to ``end`` in ``kind``?"""
        b = self.body
        pos, r = b.index(start), b.tag_ranges(kind)
        if not b.compare(pos, "<", end):
            return False
        for s, e in zip(r[0::2], r[1::2]):
            if b.compare(s, "<=", pos) and b.compare(e, ">", pos):
                pos = b.index(e)
                if b.compare(pos, ">=", end):
                    return True
        return False

    def toggle_format(self, kind):
        """Bold / italic / underline / strikethrough: the selection, or what is typed next."""
        b = self.body
        if self.view != "home":
            return "break"
        if b.tag_ranges("sel"):
            on = not self._covered(kind, "sel.first", "sel.last")
            (b.tag_add if on else b.tag_remove)(kind, "sel.first", "sel.last")
            self._refresh_combined()
            self.sync_from_widgets()
        else:
            self._pending = self._formats_at_cursor() ^ {kind}
        self._update_format_buttons()
        b.focus_set()
        return "break"

    def _tag_spans(self, tag, start, end):
        """``tag``'s ranges cut to start..end (a range that begins before start included)."""
        b, out = self.body, []
        prev = b.tag_prevrange(tag, start)
        if prev and b.compare(prev[1], ">", start):
            out.append((start, prev[1]))
        at = start
        while True:
            r = b.tag_nextrange(tag, at, end)
            if not r:
                break
            out.append(r)
            at = r[1]
        return [(s_, e_ if b.compare(e_, "<", end) else end) for s_, e_ in out]

    def _refresh_combined(self, first=None, last=None):
        """Text that is both bold and italic needs its own font: tag "bi". ``first``..``last``:
        only those lines (typing), else the whole text."""
        b = self.body
        start, end = ("1.0", "end") if first is None else (f"{first}.0", f"{last}.end")
        b.tag_remove("bi", start, end)
        if first is None:
            bold, ital = b.tag_ranges("b"), b.tag_ranges("i")
            bold, ital = list(zip(bold[0::2], bold[1::2])), list(zip(ital[0::2], ital[1::2]))
        else:
            bold, ital = self._tag_spans("b", start, end), self._tag_spans("i", start, end)
        for s1, e1 in bold:
            for s2, e2 in ital:
                s = s1 if b.compare(s1, ">", s2) else s2
                e = e1 if b.compare(e1, "<", e2) else e2
                if b.compare(s, "<", e):
                    b.tag_add("bi", s, e)

    def _refresh_bullets(self, first=None, last=None):
        """Bulleted and to-do lines wrap under their text, not under the mark; a to-do's box
        is drawn in the box font, and a done to-do is crossed out in a faint color.
        ``first``..``last``: only those lines (typing), else every line."""
        b = self.body
        start, end, row0 = ("1.0", "end", 1) if first is None else (f"{first}.0", f"{last}.end", first)
        for tag in ("bullet", "todo", "todo_box", "todo_done"):
            b.tag_remove(tag, start, end)
        text = b.get("1.0", "end-1c") if first is None else b.get(start, end)
        for row, line in enumerate(text.split("\n"), start=row0):
            if line.startswith(BULLET):
                b.tag_add("bullet", f"{row}.0", f"{row}.end")
            elif line.startswith((TODO, DONE)):
                b.tag_add("todo", f"{row}.0", f"{row}.end")
                b.tag_add("todo_box", f"{row}.0", f"{row}.1")
                if line.startswith(DONE):
                    b.tag_add("todo_done", f"{row}.2", f"{row}.end")

    def _line_mark(self, row):
        """The mark a line starts with (BULLET, TODO or DONE), or None."""
        start = self.body.get(f"{row}.0", f"{row}.2")
        return start if start in LINE_MARKS else None

    def _edit(self, change):
        self._raw += 1
        try:
            change()
        finally:
            self._raw -= 1

    def _after_edit(self):
        self._refresh_bullets()
        self._refresh_combined()
        self.sync_from_widgets()
        self._update_format_buttons()

    def _line_rows(self):
        b = self.body
        if not b.tag_ranges("sel"):
            row = int(b.index("insert").split(".")[0])
            return range(row, row + 1)
        first, last = (b.index(i).split(".") for i in ("sel.first", "sel.last"))
        end = int(last[0]) - (last[1] == "0" and int(last[0]) > int(first[0]))
        return range(int(first[0]), end + 1)

    def toggle_bullets(self):
        """Bullets on the cursor's line or the selected lines; off if they all have one."""
        return self._toggle_line_mark(BULLET, (BULLET,))

    def toggle_todo(self):
        """To-do boxes on the cursor's line or the selected lines; off if they all are to-dos."""
        return self._toggle_line_mark(TODO, (TODO, DONE))

    def _toggle_line_mark(self, mark, kind):
        b = self.body
        if self.view != "home":
            return "break"
        rows = self._line_rows()
        has = {r: self._line_mark(r) for r in rows}
        on = not all(has[r] in kind for r in rows)

        def change():
            for r in rows:
                if on and has[r] in kind:
                    continue
                if has[r]:                                   # a bullet becomes a to-do and back
                    b.delete(f"{r}.0", f"{r}.2")
                if on:
                    b.insert(f"{r}.0", mark, ())            # () = no tags: plain, whatever is around it
        self._edit(change)
        self._after_edit()
        b.focus_set()
        return "break"

    # ---- to-do lines ------------------------------------------------------------------------
    def _todo_text(self, row):
        """What a to-do line says, without its box."""
        return self.body.get(f"{row}.2", f"{row}.end").strip()

    def set_done(self, row, done):
        """Tick (or untick) the to-do on line ``row``. An empty to-do cannot be ticked."""
        mark = self._line_mark(row)
        if mark not in (TODO, DONE) or (mark == DONE) == done:
            return
        if done and not self._todo_text(row):
            return
        b = self.body
        self._edit(lambda: (b.delete(f"{row}.0", f"{row}.1"), b.insert(f"{row}.0", (DONE if done else TODO)[0], ())))
        self._after_edit()
        self._show_todo_icons(row)
        if done:                            # dark for a moment, then fading to the done gray
            c = self.colors
            b.tag_remove("done_fade", "1.0", "end")
            b.tag_add("done_fade", f"{row}.2", f"{row}.end")
            b.tag_raise("done_fade")
            animate(b, "done_fade", DONE_FADE_MS,
                    lambda k: b.tag_configure("done_fade", foreground=_mix(b, c.fg, c.muted, k)),
                    lambda: b.tag_remove("done_fade", "1.0", "end"), kind="fade")

    def remove_todo(self, row):
        """Take the to-do line ``row`` out; Undo in the bottom bar puts it back."""
        b = self.body
        if self._line_mark(row) not in (TODO, DONE):
            return
        text = b.get(f"{row}.0", f"{row}.end")
        marks = [[k, s, e] for k, s, e in self._read_marks(10 ** 9)
                 if self._offset(f"{row}.0") <= s < self._offset(f"{row}.end")]
        start = self._offset(f"{row}.0")
        last = b.compare(f"{row}.end", "==", "end-1c")
        first, end = (f"{row}.0 -1c", f"{row}.end") if last and row > 1 else (f"{row}.0", f"{row + 1}.0")
        self._edit(lambda: b.delete(first, end))
        self._hide_todo_icons()
        self._after_edit()
        note, tab = self.note, self.tab

        def put_back():
            if self.note is not note or self.tab != tab:
                return
            at = f"{min(row, int(b.index('end-1c').split('.')[0]) + 1)}.0"
            if b.compare(at, ">", "end-1c"):
                self._edit(lambda: b.insert("end-1c", "\n" + text, ()))
            else:
                self._edit(lambda: b.insert(at, text + "\n", ()))
            base = self._offset(f"{row}.0")
            for kind, s, e in marks:
                b.tag_add(kind, f"1.0+{base + s - start} indices", f"1.0+{base + e - start} indices")
            self._after_edit()
        self.show_undo_action(tr("toast_todo_removed"), put_back)

    def _todo_row_at(self, x, y):
        row = int(self.body.index(f"@{x},{y}").split(".")[0])
        info = self.body.dlineinfo(f"{row}.0")
        last = self.body.bbox(f"{row}.end")
        bottom = (last[1] + last[3]) if last else (info[1] + info[3] if info else 0)
        if info is None or not info[1] <= y < bottom:
            return None
        return row if self._line_mark(row) in (TODO, DONE) else None

    def _on_box(self, row, x):
        box = self.body.bbox(f"{row}.0") if row else None
        return bool(box) and box[0] - 2 <= x <= box[0] + box[2] + 4

    def _todo_click(self, event):
        """A click on a to-do's box ticks or unticks it (and does not move the cursor).
        An empty to-do's box puts the cursor on the line instead, ready to type."""
        row = self._todo_row_at(event.x, event.y)
        if not self._on_box(row, event.x):
            return None
        if self._line_mark(row) == TODO and not self._todo_text(row):
            self.body.mark_set("insert", f"{row}.end")
            self.body.focus_set()
            self._update_format_buttons()
            return "break"
        self.set_done(row, self._line_mark(row) == TODO)
        return "break"

    def _todo_hover(self, event):
        row = self._todo_row_at(event.x, event.y)
        clickable = self._on_box(row, event.x) and (self._line_mark(row) == DONE or bool(self._todo_text(row)))
        cursor = "hand2" if clickable else "xterm"
        if cursor != self._body_cursor:                 # only on a change: setting it again flickers
            self._body_cursor = cursor
            self.body.configure(cursor=cursor)
        if row is None:
            self._hide_todo_icons()
        elif row != self._todo_row:
            self._show_todo_icons(row)

    def _todo_hover_check(self):
        """The mouse left the text: keep the icons only while it is on them."""
        x, y = self.win.winfo_pointerxy()
        under = self.win.winfo_containing(x, y)
        if under not in (self.body, self.todo_undo, self.todo_remove):
            self._hide_todo_icons()

    def _show_todo_icons(self, row):
        """Remove (and, when done, undo) at the right end of the to-do line ``row``."""
        self.bump_look()
        info = self.body.dlineinfo(f"{row}.0")
        if info is None or self._line_mark(row) not in (TODO, DONE):
            self._hide_todo_icons()
            return
        px = self.app.px
        size = px(22)
        y = info[1] + (info[3] - size) // 2
        right = self.body.winfo_width() - px(6) - size
        self.todo_remove.place(x=right, y=y, width=size, height=size, bordermode="ignore")
        if self._line_mark(row) == DONE:
            self.todo_undo.place(x=right - size, y=y, width=size, height=size, bordermode="ignore")
        else:
            self.todo_undo.place_forget()
        self._todo_row = row

    def _hide_todo_icons(self):
        self.bump_look()
        self.todo_undo.place_forget()
        self.todo_remove.place_forget()
        self._todo_row = None

    def newline(self, _event=None):
        """Enter on a bulleted (or to-do) line starts the next one; on an empty one it ends the list."""
        b = self.body
        row = b.index("insert").split(".")[0]
        line = b.get(f"{row}.0", f"{row}.end")
        mark = self._line_mark(row)
        if b.tag_ranges("sel") or not mark or b.compare("insert", "<", f"{row}.2"):
            return None
        if not line[2:].strip() and b.compare("insert", "==", f"{row}.end"):
            self._edit(lambda: b.delete(f"{row}.0", f"{row}.2"))
        else:
            fmt = self._formats_at_cursor()
            nxt = TODO if mark == DONE else mark                # a new to-do starts not done
            self._edit(lambda: b.insert("insert", "\n" + nxt, ()))
            self._pending = fmt
        b.see("insert")
        self._after_edit()
        return "break"

    def backspace(self, _event=None):
        """Backspace right after a bullet (or a to-do box) takes it away."""
        b = self.body
        if b.tag_ranges("sel"):
            return None
        row, col = b.index("insert").split(".")
        if col != "2" or not self._line_mark(row):
            return None
        self._edit(lambda: b.delete(f"{row}.0", f"{row}.2"))
        self._after_edit()
        return "break"

    def _update_format_buttons(self):
        was = tuple(b.active for b in self.format_buttons)
        fmt = self._formats_at_cursor()
        for kind, button in zip(MARK_KINDS, self.format_buttons):
            button.set_active(kind in fmt)
        mark = self._line_mark(self.body.index("insert").split(".")[0])
        self.btn_bullets.set_active(mark == BULLET)
        self.btn_todo.set_active(mark in (TODO, DONE))
        if tuple(b.active for b in self.format_buttons) != was:    # (a caret move alone: the same look)
            self.bump_look()

    def _read_marks(self, length):
        """The formats in the text, as [kind, start, end] character offsets."""
        b, out = self.body, []
        for kind in MARK_KINDS:
            r = b.tag_ranges(kind)
            for s, e in zip(r[0::2], r[1::2]):
                start, end = self._offset(s), min(length, self._offset(e))
                if start < end:
                    out.append([kind, start, end])
        return out

    def _offset(self, index):
        """Position in the stored text: a picture in the text counts as one (INLINE)."""
        return int(self.body.tk.call(self.body._w, "count", "-indices", "1.0", index) or 0)

    def _touch(self):
        self.note.modified = datetime.now().isoformat(timespec="seconds")
        self.win.title(memo_title(self.note))
        self.app.request_save()

    # ---- move / resize ------------------------------------------------------------------------------
    def _drag_start(self, event):
        self.date_tip.hide()
        self.app.moving = True              # docked calendars keep their side while things move
        for w in self.app.group_windows(self.pad.id):
            w.stop_glide()
        self._snap_id = self._snap_hold = None
        self._snap_res, self._snap_mode, self._snap_at, self._snap_done = (0.0, 0.0), (None, None), None, False
        self._snap_shown = (self.pad.x, self.pad.y)                                 # (B8: _ease_snap)
        self._throw = [(time.perf_counter(), event.x_root, event.y_root)]          # (B8: _release_velocity)
        self._drag = (event.x_root - self.win.winfo_rootx(), event.y_root - self.win.winfo_rooty())
        self._pointer = None
        self._drag_from, self._drag_alt = (self.pad.x, self.pad.y), bool(event.state & 0x20000)
        self._drag_ctrl, self._drag_pt, self._grid_key = bool(event.state & 0x4), (event.x_root, event.y_root), None
        # the notes snapped to this one (and to those, and so on) move along, keeping their
        # places around it, like a docked calendar. Alt held, the switch off, or a tile in auto
        # layout: this note alone (App.drag_group).
        ids = self.app.drag_group(self.pad.id, bool(event.state & 0x20000))
        self._group = [(w, w.pad.x - self.pad.x, w.pad.y - self.pad.y)
                       for w in self.app.group_windows(self.pad.id, ids) if w is not self]
        app = self.app
        if app.prefs.auto_layout and not self.pad.free and not self._drag_alt and not self._drag_ctrl:
            i = app._screen_index(_pad_box(self.pad))     # a plain tile drag moves the whole grid (#6A, #23A)
            self._grid_key = key = app.area_keys()[i]
            last = app._grid_last.get(key)
            self._grid_home0 = tuple(last[0].home) if last is not None else (self.pad.x, self.pad.y)
            self._group = [(w, w.pad.x - self.pad.x, w.pad.y - self.pad.y)
                           for w in app._grid_windows(i, shown_only=True) if w is not self]
            self._grid_before = app.layout_of(list(app.windows) + ([CAL] if app._open_calendar() is not None else []))
        # an undocked calendar linked to the group moves along too, as dragging it moves them
        self._cal_along = None
        cal = app._open_calendar()
        if (cal is not None and CAL in ids and not cal.docked and cal.target_box is not None
                and getattr(self, "_grid_key", None) is None and cal.top.winfo_ismapped()):
            app.motion.cancel({CAL})
            b = cal.target_box
            self._cal_along = (cal, b[0] - self.pad.x, b[1] - self.pad.y, b[2] - b[0], b[3] - b[1])
        # docked calendars ride with their notes, in the frame's one window batch (B6): their
        # offsets from where their notes are now
        self._cal_offsets = {}
        for w in [self] + [o for o, _dx, _dy in self._group]:
            c = w.calendar
            if c is not None and c.docked and getattr(c, "_xy", None) and c.top.winfo_ismapped():
                self._cal_offsets[w] = (c._xy[0] - w.pad.x, c._xy[1] - w.pad.y)
        if self._group or self._cal_along:      # moving together: one theme-color line around them
            self.app.ring_source = self
            self.app.ring.show(self._live_ring_boxes(), self.win, self.pad.alpha)

    def _top_menu(self, event):
        """Right-click on the top row: what the icons, double-clicks and Alt do, in one menu."""
        app = self.app
        menu = (PopupMenu(app, self.frame)
                .add(tr("menu_new_memo"), self.new_memo, icon=GLYPH["add"], key="Ctrl+N")
                .add(tr("menu_new_window"), lambda: app.new_window(self), icon=GLYPH["note"]))
        if app.can_reopen():
            menu.add(tr("menu_reopen"), lambda: app.reopen_closed(self), icon=GLYPH["undo_action"],
                     key="Ctrl+Shift+T")
        menu.add(tr("menu_calendar"), self.toggle_calendar, checked=self.calendar is not None,
                 icon=GLYPH["calendar"])
        menu.add(tr("menu_on_top"), self.toggle_pin, checked=self.pad.pinned, icon=GLYPH["pin"])
        if any(w.pad.pinned for w in app.windows.values() if w is not self):
            menu.add(tr("menu_unpin_all"), app.unpin_all, icon=GLYPH["unpin"])
        x, y = event.x_root, event.y_root
        hidden = [(glyph, key, cmd) for glyph, key, cmd, b in (
            (GLYPH["list"], "menu_list", self.show_list, self.btn_list),
            (GLYPH["gear"], "menu_settings", self.show_settings, None),
            (GLYPH["style"], "menu_style", lambda: self._style_menu(x, y), None),
            (GLYPH["trash"], "menu_trash", self.trash_current, None),
            (GLYPH["minimize"], "menu_minimize", self.minimize, None))
            if (b is None or b not in self.rail_shown()) and (key != "menu_trash" or self.view == "home")]
        menu.separator()                    # what the rail does not show (its ⋯ has it too)
        for glyph, key, cmd in hidden:
            menu.add(tr(key), cmd, icon=glyph)
        menu.separator()
        menu.add(tr("menu_expand" if self.pad.collapsed else "menu_collapse"), self.toggle_collapse,
                 icon=GLYPH["fold_down" if self.pad.collapsed else "fold_up"], key=tr("key_double_click"))
        shown_notes = [w for w in app.windows.values() if w.win.state() == "normal"]
        if any(not w.pad.collapsed for w in shown_notes) and len(shown_notes) > 1:
            menu.add(tr("menu_fold_all"), lambda: app.fold_all(True), icon=GLYPH["fold_up"])
        if any(w.pad.collapsed for w in shown_notes):
            menu.add(tr("menu_unfold_all"), lambda: app.fold_all(False), icon=GLYPH["fold_down"])
        menu.add(tr("menu_tidy"), lambda: self._tidy_menu(x, y), icon=GLYPH["tidy"])
        size = [self.pad.width, self.pad.height]
        menu.add(tr("menu_default_size"), lambda: app.set_note_size(self), checked=app.prefs.note_size == size,
                 icon=GLYPH["fit"])
        menu.separator()
        menu.add(tr("menu_group_drag"), app.toggle_group_drag, checked=app.prefs.group_drag, icon=GLYPH["link"])
        if len(app.group_of(self.pad.id)) > 1:
            menu.add(tr("menu_detach"), lambda: app.detach(self), icon=GLYPH["cut"])
        menu.add(tr("menu_hints"), self.show_hints, icon=GLYPH["info"])
        menu.popup(x, y)

    def _tidy_menu(self, x, y):
        """"Tidy up notes…": every note on this screen into neat columns, in one of the sizes."""
        app = self.app
        menu = PopupMenu(app, self.frame)
        for key in ("small", "medium", "large"):
            menu.add(tr(f"tidy_{key}"), lambda k=key: app.tidy(self, k), icon=("size", key))
        if app.prefs.note_size:
            menu.add(tr("tidy_default"), lambda: app.tidy(self, "default"), icon=GLYPH["note"])
        menu.add(tr("tidy_keep"), lambda: app.tidy(self, "keep"), icon=GLYPH["tidy"])
        menu.separator()

        def order(o):                       # pick the order, then the size (the menu comes back)
            app.prefs.tidy_order = o
            app.request_save()
            self._tidy_menu(x, y)
        for o in TIDY_ORDERS:
            menu.add(tr(f"tidy_order_{o}"), lambda o=o: order(o), checked=app.prefs.tidy_order == o)
        menu.popup(x, y)

    # ---- the one-time hint about controls that are easy to miss ------------------------
    def show_hints(self):
        self.hide_hints()
        c, px = self.app.theme_colors(), self.app.px          # the main theme color, like menus and tips
        box = self.hints = tk.Frame(self.main, bg=c.border, bd=0)
        inner = tk.Frame(box, bg=c.bg, bd=0)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        width = max(px(180), (self.main.winfo_width() if self.main.winfo_width() > 1
                              else self.pad.width - px(RAIL_W)) - px(28))
        tk.Label(inner, text=tr("hint_title"), bg=c.bg, fg=c.fg, anchor="w",
                 font=(UI_BOLD, 10, "bold")).pack(fill="x", padx=px(12), pady=(px(10), px(4)))
        tk.Label(inner, text=tr("hint_lines"), bg=c.bg, fg=c.muted, anchor="w", justify="left",
                 wraplength=width - px(26), font=(UI_FONT, 9)).pack(fill="x", padx=px(12))
        ok = FlatButton(inner, tr("hint_ok"), self.close_hints)
        ok.recolor(c)
        ok.configure(font=(UI_BOLD, 9, "bold"))
        ok.pack(anchor="e", padx=px(10), pady=(px(6), px(10)))
        y, drop = self._row_h() + px(8), px(HINT_DROP)
        animate(box, "drop", HINT_DROP_MS,         # drops HINT_DROP px into place
                lambda k: box.place(relx=0.5, y=y - round(drop * (1 - k)), anchor="n", width=width))
        tk.Misc.tkraise(box)
        self.bump_look()

    def hide_hints(self):
        box = getattr(self, "hints", None)
        if box is not None:
            stop_animation(box, "drop")
            box.destroy()
            self.hints = None
            self.bump_look()

    def close_hints(self):
        self.hide_hints()
        self.app.prefs.hints_seen = True
        self.app.request_save()

    def _live_ring_boxes(self):
        """Each moving note's box where the drag put it, and its docked calendar's where that
        is now: on whichever side it went (it changes side near the screen's edge)."""
        dropped = getattr(self, "_dropped", None) or {}
        boxes = []
        for w in [self] + [o for o, _dx, _dy in getattr(self, "_group", ())]:
            if not w.win.winfo_exists():
                continue
            x, y = dropped.get(w, (w.pad.x, w.pad.y))
            boxes.append((x, y, x + w.pad.width, y + _shown_h(w.pad)))
            cal = w.calendar
            if cal is not None and cal.docked and getattr(cal, "_xy", None) and cal.top.winfo_ismapped():
                off = getattr(self, "_cal_offsets", {}).get(w)
                ox, oy = off or (cal._xy[0] - w.pad.x, cal._xy[1] - w.pad.y)    # placed from the same pad
                cw, ch = cal.top.winfo_width(), cal.top.winfo_height()
                boxes.append((x + ox, y + oy, x + ox + cw, y + oy + ch))
        along = getattr(self, "_cal_along", None)
        if along is not None and along[0].target_box is not None:
            boxes.append(tuple(along[0].target_box))
        return boxes

    def _drag_shape_box(self, x, y, group):
        """The box of everything that moves with the drag, were this note at (x, y): the notes
        of the group, and their docked calendars where they are placed from the same pads."""
        return geom.union(self._drag_parts(x, y, group))

    def _drag_parts(self, x, y, group):
        """Each piece that moves with the drag, were this note at (x, y): the notes, their
        docked calendars, and an undocked calendar that came along."""
        boxes = []
        for w, ox, oy in [(self, 0, 0)] + list(group):
            if not w.win.winfo_exists():
                continue
            bx, by = x + ox, y + oy
            boxes.append((bx, by, bx + w.pad.width, by + _shown_h(w.pad)))
            cal = w.calendar
            if cal is not None and cal.docked and getattr(cal, "_xy", None) and cal.top.winfo_ismapped():
                cx, cy = bx + cal._xy[0] - w.pad.x, by + cal._xy[1] - w.pad.y
                boxes.append((cx, cy, cx + cal.top.winfo_width(), cy + cal.top.winfo_height()))
        along = getattr(self, "_cal_along", None)
        if along is not None:
            _cal, ox, oy, cw, ch = along
            boxes.append((x + ox, y + oy, x + ox + cw, y + oy + ch))
        return boxes

    def _snapped(self, x, y, group):
        """(x, y) after the magnet (App.snap) for the whole dragged shape; the id it snapped
        to is kept in ``_snap_id`` (the drop links to it)."""
        parts = self._drag_parts(x, y, group)
        shape = geom.union(parts)
        ids = {self.pad.id} | {w.pad.id for w, _dx, _dy in group}
        if getattr(self, "_cal_along", None) is not None:
            ids.add(CAL)
        sx, sy, sid = self.app.snap(shape, ids, parts=parts)
        nx, ny, sid = self.app.hold_snap(self, (x, y), (x + sx - shape[0], y + sy - shape[1]), sid)
        self._snap_id = sid
        return nx, ny

    def _drag_move(self, event):
        """The pointer moved: noted, and applied once at the next display frame (_apply_drag)."""
        if self._drag:
            self._pointer = (event.x_root, event.y_root, event.state)
            now = time.perf_counter()
            throw = getattr(self, "_throw", [])
            throw.append((now, event.x_root, event.y_root))
            while len(throw) > 2 and now - throw[0][0] > THROW_WINDOW_S:
                throw.pop(0)
            self._throw = throw
            self.app.clock.request(self._apply_drag)

    def _flush_gesture(self):
        """Let go before the next frame came: the last pointer is applied now, and its window moves
        are done (the drop reads where they are). A snap still easing in lands there now (B8)."""
        clock = self.app.clock
        for fn in (self._apply_drag, self._apply_resize):
            if clock.take(fn):
                fn()
        if self._drag and getattr(self, "_pointer", None) is not None and any(getattr(self, "_snap_res", ())):
            self._snap_done = True
            self._apply_drag()
        clock.flush_moves()

    def _ease_snap(self, raw, target):
        """B8: where the drag shows the note, the magnet's changes eased. ``target`` is where the
        pointer puts it (``raw``), snapped. On an axis whose snap changes (it engages, lets go,
        or lines up with something else) the note goes on from where it showed, and the rest
        (shown - target) eases away on a first-order lag (SNAP_TAU_S: 90 % in 65 ms, no
        overshoot). The pointer's own motion is never lagged: a free drag follows it exactly and
        a held snap holds still. While a rest is left it asks for the next frame itself (the
        pointer may be still); let go, the rest goes at once (_snap_done)."""
        now = time.perf_counter()
        if self._snap_done:
            self._snap_res = (0.0, 0.0)
        else:
            at, prev = self._snap_at, self._snap_shown
            k = math.exp(-max(0.0, (now - at) if at is not None else self.app.clock._period()) / SNAP_TAU_S)
            res, modes = [], []
            for i in (0, 1):
                mode = target[i] if target[i] != raw[i] else None      # (snapped on this axis, to there)
                r = self._snap_res[i]
                if mode != self._snap_mode[i] and prev is not None:
                    r = float(prev[i] - target[i])          # (on from where it showed)
                r *= k
                res.append(0.0 if abs(r) < 0.5 else r)
                modes.append(mode)
            self._snap_res, self._snap_mode = tuple(res), tuple(modes)
        self._snap_at = now
        shown = (target[0] + round(self._snap_res[0]), target[1] + round(self._snap_res[1]))
        self._snap_shown = shown
        if any(self._snap_res):
            self.app.clock.request(self._apply_drag)
        return shown

    def _release_velocity(self, samples=None):
        """The pointer's speed at the release (px/s): over its last THROW_WINDOW_S; none when that
        is shorter than THROW_MIN_S (a still hand, or a click)."""
        if samples is None:                 # (now, where it last was: a hand held still is no throw)
            samples = list(getattr(self, "_throw", []))
            if samples:
                samples.append((time.perf_counter(),) + tuple(samples[-1][1:]))
        samples = list(samples)
        if len(samples) < 2:
            return 0.0, 0.0
        t1, x1, y1 = samples[-1]
        first = next((s for s in samples if t1 - s[0] <= THROW_WINDOW_S + 1e-9), samples[0])
        t0, x0, y0 = first
        span = t1 - t0
        if span < THROW_MIN_S:
            return 0.0, 0.0
        return (x1 - x0) / span, (y1 - y0) / span

    @perf.timed("drag_move")
    def _apply_drag(self):
        """Once a frame: the dragged note (and those moving with it) where the last pointer puts
        it, snapped; all of them in the frame's one window batch."""
        if not self._drag or getattr(self, "_pointer", None) is None:
            return
        px_, py_, state = self._pointer
        dx, dy = self._drag
        x, y = px_ - dx, py_ - dy
        group = getattr(self, "_group", [])
        self._snap_id = None
        self._drag_pt = (px_, py_)
        raw = (x, y)
        if not state & 0x20000 and getattr(self, "_grid_key", None) is None:     # Alt held: move freely
            x, y = self._snapped(x, y, group)
        if getattr(self, "_snap_res", None) is not None:
            x, y = self._ease_snap(raw, (x, y))   # (a snap eases in and out: B8)
        clock = self.app.clock
        clock.move(self.win, x, y)
        self._dropped = {self: (x, y)}              # where the drag put each (winfo_rootx can lag behind)
        for w, ox, oy in group:
            if w.win.winfo_exists():
                clock.move(w.win, x + ox, y + oy)
                self._dropped[w] = (x + ox, y + oy)
        for w, (ox, oy) in getattr(self, "_cal_offsets", {}).items():
            if w in self._dropped and w.calendar is not None and w.calendar.docked:
                wx, wy = self._dropped[w]
                w.calendar.ride(wx + ox, wy + oy)   # (in this batch: <Configure> then finds it there)
        along = getattr(self, "_cal_along", None)
        if along is not None:
            cal, ox, oy, cw, ch = along
            cal.nw.pad.calendar_pos = [x + ox, y + oy]    # (place() puts an undocked one there)
            cal.move_to((x + ox, y + oy, x + ox + cw, y + oy + ch))
        if group or along is not None:
            self.app.ring.move(self._live_ring_boxes())

    def _place(self, nw, x, y, w=None, h=None):
        """Tell Windows only what changed (each change redraws that note), in the frame's one batch."""
        box = (x, y, w, h)
        if self._geometries.get(nw) != box:
            self._geometries[nw] = box
            self.app.clock.move(nw.win, x, y, w, h)

    def _resize_start(self, event):
        self._resize = (event.x_root, event.y_root, self.win.winfo_width(), self.win.winfo_height())
        self._pointer = None
        self._resize_area = self.app.area_of(_pad_box(self.pad))
        self._geometries = {}
        self.app.moving = True
        for w in self.app.group_windows(self.pad.id):
            w.stop_glide()
        # snapped notes keep the layout: the same row takes the new height, the same column
        # the new width, and the notes beyond are pushed along (no gaps, no overlaps).
        # Alt held (or the menu switch off, or a tile in auto layout): this note alone.
        ids = self.app.drag_group(self.pad.id, bool(event.state & 0x20000))
        self._resize_box = _pad_box(self.pad)
        self._resize_group = [(w, _pad_box(w.pad)) for w in self.app.group_windows(self.pad.id, ids)
                              if w is not self]
        # the boxes at the start: what Undo goes back to, and what the one plan at the release is made from
        self._resize_before = self.app.layout_of([i for i, w in self.app.windows.items() if not w._closing])
        self._resize_shapes = self.app.space()
        self._now = {}                      # id -> the box the drag has put it at (the pads follow later)
        self._live = {}                     # notes the drag moves along live (pushed in line): window -> box at start
        cal = self.calendar
        self._resize_solo = (not self._resize_group and not self.app.prefs.auto_layout
                             and not (cal is not None and cal.docked))
        if self._resize_solo:
            self.app.outlines()             # (its window is made now, at the press: not inside a frame)
        if self._resize_group:              # the same line as when they move together
            self.app.ring.show([self._resize_box] + [b for _w, b in self._resize_group], self.win, self.pad.alpha)
            self.freeze()                   # (smooth: see freeze; the text wraps when let go)
            a0, b0, a1, b1 = self._resize_box
            for o, (l, t, r, b) in self._resize_group:  # those in its row or column will change size: their
                if min(r, a1) - max(l, a0) > 0 or min(b, b1) - max(t, b0) > 0:     # pictures go in now, at
                    o.freeze()              # the press, where nothing moves yet (not at the first frame)

    def _resize_move(self, event):
        """The pointer moved: noted, and applied once at the next display frame (_apply_resize)."""
        if self._resize:
            self._pointer = (event.x_root, event.y_root, event.state)
            self.app.clock.request(self._apply_resize)

    @perf.timed("resize_move")
    def _apply_resize(self):
        """Once a frame: the note as big as the last pointer makes it; the notes resized or pushed
        along (a group), or the live plan (one note), in the frame's one window batch."""
        if self._resize and getattr(self, "_pointer", None) is not None:
            x0, y0, w0, h0 = self._resize
            px = self.app.px
            w = max(px(MIN_W), w0 + self._pointer[0] - x0)
            h = max(px(MIN_H), h0 + self._pointer[1] - y0)
            dw, dh = w - w0, h - h0
            a0, b0, a1, b1 = self._resize_box
            slack = px(2)
            group = getattr(self, "_resize_group", ())
            if group and (dw > 0 or dh > 0):    # the group may not grow bigger than the screen
                left, top, right, bottom = self._resize_area        # (let go, it slides back in)
                boxes = [self._resize_box] + [bx for _o, bx in group]
                room_w = (right - left) - (max(bx[2] for bx in boxes) - min(bx[0] for bx in boxes))
                room_h = (bottom - top) - (max(bx[3] for bx in boxes) - min(bx[1] for bx in boxes))
                dw, dh = min(dw, max(0, room_w)), min(dh, max(0, room_h))
                w, h = w0 + dw, h0 + dh
            if getattr(self, "_resize_solo", False):
                w, h = self._follow_live(a0, b0, w, h)
            self._place(self, a0, b0, w, h)
            boxes = [(a0, b0, a0 + w, b0 + h)]
            self._now[self.pad.id] = boxes[0]
            for o, (l, t, r, b) in group:
                if not o.win.winfo_exists():
                    continue
                x, y, ow, oh = l, t, r - l, b - t
                if min(r, a1) - max(l, a0) > 0:         # same column: the same width
                    ow += dw
                elif l >= a1 - slack:                   # right of it: pushed along
                    x += dw
                if min(b, b1) - max(t, b0) > 0:         # same row: the same height
                    if not o.pad.collapsed:
                        oh += dh
                elif t >= b1 - slack:                   # under it: pushed along
                    y += dh
                ow = max(px(MIN_W), ow)
                if o.pad.collapsed:
                    o.pad.width = ow
                else:
                    oh = max(px(MIN_H), oh)
                if (ow, oh) != (r - l, b - t) or o._cover is not None:
                    o.freeze()                  # its size changes: a picture is redrawn, not its widgets
                if o._cover is not None:
                    o.clip_to(x, y, ow, oh)     # (shown through a region: no resize each frame, B3)
                else:
                    self._place(o, x, y, ow, oh)
                boxes.append((x, y, x + ow, y + (_shown_h(o.pad) if o.pad.collapsed else oh)))
                self._now[o.pad.id] = (x, y, x + ow, y + oh)
            if group:
                self.app.ring.move(boxes)
                self.app.space_changed()        # (a folded one's width is set on its pad)

    def _finish_resize(self, members):
        """The release of a resize: the new size is the notes' own (no grow-back), and everything
        runs as one grow in drag mode against the boxes at the start (Undo: back to those)."""
        app = self.app
        if getattr(app, "_outlines", None) is not None:
            app._outlines.hide()
        start, changes = self._resize_before, {}
        for pid, b in self._now.items():    # the pads take where the drag put each (Configure may lag behind)
            nw = app.windows.get(pid)
            if nw is not None:
                p = nw.pad
                p.x, p.y, p.width = b[0], b[1], b[2] - b[0]
                if not p.collapsed:
                    p.height = b[3] - b[1]
                p.target = None
        app.space_changed()
        for w in members:
            b = _pad_box(w.pad)
            s0 = start.get(w.pad.id)
            if s0 is not None and (s0[2] - s0[0], s0[3] - s0[1]) != (b[2] - b[0], b[3] - b[1]):
                w.pad.own_size = None
            changes[w.pad.id] = b
        if len(members) > 1:
            label = "resized_together" if app.prefs.resize_hint_seen else "resized_alt_hint"
            app.prefs.resize_hint_seen = True
        else:
            label = "resized"
        app.grow(changes, "drag", label, shapes=self._resize_shapes, before=start, offer=len(members) > 1)

    def _follow_live(self, a0, b0, w, h):
        """A single note's resize, live (P2, P3): the plan for this size, from the boxes at the
        start. The notes pushed in line follow at once; what the plan would relocate or squeeze
        shows as an outline until the release. Returns the size the edge allows."""
        app = self.app
        shapes = self._resize_shapes
        plan = app.plan_resize({self.pad.id: (a0, b0, a0 + w, b0 + h)}, shapes)
        allowed = plan.allowed.get(self.pad.id)
        if allowed is not None:
            w, h = allowed[2] - a0, allowed[3] - b0
        by_id = {s.id: s for s in shapes}
        outlines, still = [], set()
        for sid, nb in plan.boxes.items():
            s, nw = by_id.get(sid), self.app.windows.get(sid)
            if sid == self.pad.id or s is None:
                continue
            same_size = (nb[2] - nb[0], nb[3] - nb[1]) == (s.box[2] - s.box[0], s.box[3] - s.box[1])
            if (nw is not None and s.kind == "note" and same_size and sid not in plan.relocated
                    and nw.win.winfo_exists()):
                self._live[nw] = s.box
                still.add(nw)
                self._now[sid] = nb
                self._place(nw, nb[0], nb[1])
            elif nb != s.box:
                outlines.append(nb)
        for nw, start in list(self._live.items()):          # no longer pushed: back to where it was
            if nw not in still:
                del self._live[nw]
                self._now.pop(nw.pad.id, None)
                if nw.win.winfo_exists():
                    self._place(nw, start[0], start[1])
        if outlines:
            app.outlines().show(outlines)
        else:
            app.outlines().hide()
        app.space_changed()
        return w, h

    def _drag_end(self, _event=None):
        self._flush_gesture()               # (the last pointer, if its frame had not come yet)
        dropped = getattr(self, "_dropped", None) if self._drag else None   # (off the screen: back in)
        if dropped:                         # the pads take where the drag put them now: the windows'
            for w, (x, y) in dropped.items():   # <Configure> may come later, and the links made at the
                if w.win.winfo_exists() and not w.rolling and not self.app.motion.drives(w.pad.id):
                    w.pad.x, w.pad.y = x, y     # drop (and the check that prunes them) read the pads
            self.app.space_changed()
        along, self._cal_along = getattr(self, "_cal_along", None), None
        if along is not None:               # the calendar that came along keeps its new spot
            cal = along[0]
            if cal.target_box is not None and cal.nw is not None:
                cal.nw.pad.calendar_pos = list(cal.target_box[:2])
                cal.place()                     # (back inside its screen, if it went past the edge)
                self.app.space_changed()
        if self._group or along is not None:
            self.app.ring.hide()
        resized = getattr(self, "_resize_group", None) if self._resize else None
        if resized:                         # a group resize: off the screen now? back in, like a drag
            members = [self] + [w for w, _b in resized if w.win.winfo_exists()]
            for w in members:
                w.thaw()
            self.app.ring.hide()
            self.win.update_idletasks()
            dropped = {w: (w.pad.x, w.pad.y) for w in members}
            before = self._resize_before
        if self._resize and not resized:    # one note resized past the screen's edge: back in
            self.win.update_idletasks()
            dropped = {self: (self.pad.x, self.pad.y)}
        tiles = self.app.prefs.auto_layout and (self._drag or self._resize) and not resized
        if tiles and self._resize and not self.pad.collapsed:   # resized: the tiles take its size
            self.app.prefs.auto_cell = [self.pad.width, self.pad.height]
        if self._drag and not self._resize and getattr(self, "_dropped", None) and not tiles:
            places = {w: xy for w, xy in self._dropped.items() if w.win.winfo_exists()}
            # let go over a calendar (not their own): beside it, like snapped there (3B)
            if self.app.off_calendars(places):
                dropped = None              # they glide there, on the screen already
        was_drag = bool(self._drag)
        note_resized = bool(self._resize) and not resized and not tiles
        moved_ids = [self.pad.id] + [w.pad.id for w, _dx, _dy in self._group]     # the dragged shape
        if was_drag and getattr(self, "_drag_from", None) != (self.pad.x, self.pad.y):
            for i in moved_ids:             # the user moved them: P4 no longer gives their room back
                if i in self.app.windows:
                    self.app.windows[i].user_moved(moved=True)
        elif self._resize:
            for w in [self] + [w for w, _b in (resized or ())]:
                w.user_moved(moved=False)
        plain_members = None                # a resize (single or group) with no docked calendar: one grow
        if self._resize and not tiles:
            plain_members = [self] + [w for w, _b in (resized or ()) if w.win.winfo_exists()]
            if any(w.calendar is not None and w.calendar.docked for w in plain_members):
                plain_members = None
        snapped_to, self._snap_id = getattr(self, "_snap_id", None), None
        push = None                         # a group let go: what it overlaps slides out, as soon as it lands (B5)
        if was_drag and (self._group or along is not None) and not tiles:
            ids = set(moved_ids)
            push = lambda: self.app.push_clear(ids)     # noqa: E731
        self._drag = self._resize = None
        self._group, self._dropped, self._resize_group = [], None, []
        self.app.ring_source = None
        self.app.moving = False
        for w in self.app.windows.values():     # now they may pick the side clear of other notes
            if w.calendar is not None and w.calendar.docked and not self.app.motion.drives(w.pad.id):
                w.calendar.place()
        if note_resized and self.calendar is not None and self.calendar.docked:
            self.calendar.settle_view()     # a resized note: its calendar matches it, the view by the stretch rule
        if tiles:                           # auto layout: into the tiles (a drag: swap places)
            if was_drag:
                self._tile_drop(dropped)
            else:
                self.pad.own_size = None
                self.app.arrange()
        elif plain_members:                 # P1-P3: pushes and the edge, from the boxes at the start
            self._finish_resize(plain_members)
        elif dropped:                       # notes of the group left off the screen glide back in
            places = {w: xy for w, xy in dropped.items() if w.win.winfo_exists()}
            if was_drag:                    # a user drag unstacks it (P5)
                for w in places:
                    w.pad.stacked = False
            ids = {w.pad.id for w in places} | ({CAL} if along is not None else set())   # (it came along)
            throw = self._release_velocity() if was_drag else None
            self.app.settle_drop(ids, places=places, anchor=self, velocity=throw if throw and any(throw) else None)
        if resized and not plain_members and self.app.layout_of([w.pad.id for w in members]) != before:  # Undo (after any bring_back, an apply); the first time also how to avoid it
            prefs = self.app.prefs
            label = "resized_together" if prefs.resize_hint_seen else "resized_alt_hint"
            prefs.resize_hint_seen = True
            self.app.offer_undo(before, label, self)
        if was_drag and snapped_to is not None and not tiles:   # M2: a snapped drop links to what it snapped to
            self.win.update_idletasks()     # (the pads take where the windows are)
            self.app.space_changed()
            self.app.link_drop(moved_ids, snapped_to)
        self.app.settle_links()             # (links that no longer touch break: Alt, a drag to somewhere else)
        self.app.request_save()
        if push is not None:
            self.app.motion.when_still(push)

    # ---- group resize: a picture stands in for the widgets ---------------------------
    def freeze(self):
        """Resized along with a group, a note would redraw its ~30 widgets at every step of
        the mouse (some 25 ms each; six notes made the resize lag). Instead a picture of it
        stands in, drawn at the new size: the rail down the left (its buttons at the top, ⋯ at the
        bottom), the date row's day at the left and × at the right, the text where it was, the grip
        in the corner. thaw() brings the widgets back (the text wraps to the new size then)."""
        if self._cover is not None or not self.win.winfo_ismapped():
            return
        shot = self.app.shots.shot(self)        # (taken ahead for linked notes: no wait at the first frame)
        if shot is None:
            return
        w, h = shot.size
        e = self.edge
        img = shot.crop((e, e, w - e, h - e))
        fw, fh = img.size
        fx, fy = self.frame.winfo_rootx(), self.frame.winfo_rooty()

        def box(wd):
            x, y = wd.winfo_rootx() - fx, wd.winfo_rooty() - fy
            return x, y, x + wd.winfo_width(), y + wd.winfo_height()
        rail = self.rail.winfo_width() if self.rail.winfo_ismapped() else 0
        row = box(self.bar)[3]
        close = (box(self.btn_min)[0] if self.btn_min.winfo_ismapped()      # (- and x: the right-hand piece)
                 else box(self.btn_close)[0] if self.btn_close.winfo_ismapped() else fw)
        more = box(self.btn_more)[1] if rail else fh
        grip = box(self.grip) if self.grip.winfo_ismapped() else (fw, fh, fw, fh)
        cover = tk.Canvas(self.win, bd=0, highlightthickness=0, bg=self.colors.bg)
        bars = []
        if rail:
            bars.append((cover.create_rectangle(0, 0, 0, 0, width=0, fill=self.rail.cget("bg"), tags=("rail",)),
                         lambda W, H: (0, 0, rail, H)))
        photos, pieces = [], []

        def piece(crop, where, tag=()):
            if crop[2] - crop[0] > 0 and crop[3] - crop[1] > 0:
                photos.append(ImageTk.PhotoImage(img.crop(crop), master=cover))
                pieces.append((cover.create_image(0, 0, anchor="nw", image=photos[-1], tags=tag), where))
        piece((rail, row, fw, fh), lambda W, H: (rail, row))                        # the text
        piece((rail, 0, close, row), lambda W, H: (rail, 0))                        # the date
        piece((close, 0, fw, row), lambda W, H: (W - (fw - close), 0), ("close",))  # ×
        piece((0, 0, rail, more), lambda W, H: (0, 0))                              # the rail's buttons
        piece((0, more, rail, fh), lambda W, H: (0, H - (fh - more)))               # ... and its ⋯
        piece(grip, lambda W, H: (W - (fw - grip[0]), H - (fh - grip[1])))         # the resize grip

        def lay(W, H):
            for item, where in bars + pieces:
                cover.coords(item, *where(W, H))
        cover.bind("<Configure>", lambda e: lay(e.width, e.height))
        lay(fw, fh)
        cover.lay = lay
        self._cover, self._cover_photos = cover, photos
        cover.place(x=e, y=e, relwidth=1, relheight=1, width=-2 * e, height=-2 * e)
        self.frame.pack_forget()

    def clip_to(self, x, y, w, h):
        """Frozen in a group resize (B3): show the box (x, y, w, h) without resizing the window
        at every frame (each resize costs Tk a layout and a repaint of the whole note: a group of
        16 ran at 36 fps). The window keeps its size and a window region shows w x h of it; it
        grows only when it must, RING_SLACK px at a time. The pad says the box shown (a docked
        calendar follows it). thaw() makes the window that box again."""
        cover = self._cover
        if cover is None:
            self.app.clock.move(self.win, x, y, w, h)
            return
        clock = self.app.clock
        real = getattr(self, "_clip_real", None) or (self.win.winfo_width(), self.win.winfo_height())
        if w > real[0] or h > real[1]:
            slack = self.app.px(GroupRing.RING_SLACK)
            real = (max(real[0], w + slack), max(real[1], h + slack))
            clock.move(self.win, x, y, real[0], real[1])
        else:
            clock.move(self.win, x, y)
        self._clip_real = real
        if self._clip is None:                  # the cover stays as big as the window (nothing in it is
            cover.unbind("<Configure>")         # laid out again): only its pieces move, to the size shown
        if self._clip is None or tuple(self._clip[2:]) != (w, h):
            winapi.clip_box(self.win, w, h, self.app.px(8))     # (the region first: never more shows)
            e = self.edge
            cover.lay(w - 2 * e, h - 2 * e)
            self._sized_late = True             # (laid out for its size when thawed)
        self._clip = (x, y, w, h)
        p = self.pad
        p.x, p.y, p.width = x, y, w
        if not p.collapsed:
            p.height = h
        self.app.space_changed()
        if self.calendar is not None and self.calendar.docked:
            self.calendar.place()

    def thaw(self):
        if self._cover is None:
            return
        clip, self._clip, self._clip_real = self._clip, None, None
        if clip is not None:                    # the window that box again, then no region (the
            x, y, w, h = clip                   # region last: it never shows the big window)
            self._size_now(x, y, w, h)
            winapi.clip_height(self.win)
        self._pack_frame()
        self._cover.destroy()
        self._cover = self._cover_photos = None
        if getattr(self, "_sized_late", False):     # resized while frozen: laid out for its size now
            self._sized_late = False
            self._sized(self.pad.width)

    # ---- folding up to the top bar --------------------------------------------------
    def collapsed_height(self):
        """A folded note is its date row: DATE_ROW_H, its edge included (= PILE_STEP)."""
        return self.app.px(DATE_ROW_H)

    def _apply_collapsed(self, shoot=False, geometry=True):
        """Show the folded / unfolded state (pad.collapsed) without moving other notes. ``shoot``:
        a fold of a note that shows (not one built folded) first takes its picture, as it is
        painted, for the unfold to roll. ``geometry`` False: the window keeps its height (it is
        rolling there: the roll's end calls this again)."""
        p = self.pad
        if p.collapsed and shoot:
            try:
                painted = (self.win.winfo_ismapped() and self.win.state() == "normal" and self._cover is None
                           and getattr(self, "_rolling_cover", None) is None
                           and self.win.winfo_height() == p.height)
            except tk.TclError:
                painted = False
            if painted:
                self.app.shots.fresh(self)
        if p.collapsed:
            self.hide_hints()
            self.hide_undo()
            self.list_view.hide_preview()
            self.views.pack_forget()
            self.grip.place_forget()
            p.shown_height = self.collapsed_height()
            if geometry:
                self.win.geometry(f"{p.width}x{p.shown_height}")
        else:
            self.views.pack(fill="both", expand=True)
            self._place_grip()
            tk.Misc.tkraise(self.grip)
            if geometry:
                self.win.geometry(f"{p.width}x{p.height}")
        self.app.space_changed()            # folded: as tall as its date row
        self._arrange_chrome(p.width)
        if self.calendar and geometry:          # (rolling: placed when the roll ends, not over it)
            self.calendar.place()

    def toggle_collapse(self, instant=False):
        """Fold the note up to its top bar, or unfold it. The notes stacked under it (snapped)
        move up to close the gap, and back down when it unfolds. ``instant``: they jump
        (folding many at once)."""
        p = self.pad
        if self._closing or self.win.state() != "normal":
            return
        if self.app.prefs.auto_layout and not p.free:    # the tiles close up / make room
            p.collapsed = not p.collapsed
            self._apply_collapsed(shoot=True)
            self.app.request_save()
            self.app.arrange_soon()
            return
        self.user_moved(moved=False)
        if self.rolling:
            return
        if instant or not self.win.winfo_ismapped() or self.app.clock.mode != "full":   # (B9: no roll)
            self.app.set_folded([self], not p.collapsed)     # one plan: closes up linked / pushes (no Undo)
            self.app.request_save()
        elif not p.collapsed:
            self._fold_rolling()
        else:
            self._unfold_rolling()

    def _fold_rolling(self):
        """Fold up: the note rolls up to its top bar (ROLL_MS) while the plan runs (the notes
        under it close up at the same time: one motion, B5). A note the plan moves itself just
        folds."""
        p, win = self.pad, self.win
        bar = self.collapsed_height()
        full = p.height
        self.rolling = True
        self._roll_cover(self._shot())
        stop_animation(win, "roll")
        self.app.set_folded([self], True, rolling=True)

        def done():
            self._drop_roll_cover(bar)
            self.rolling = False
            self._apply_collapsed()
            self.app.request_save()
        if self.app.motion.drives(p.id):
            done()
            return
        animate(win, "roll", ROLL_MS, lambda k: self._roll_geometry(full + (bar - full) * k), done)

    def _unfold_rolling(self):
        """Unfold: the plan first (what is under it makes room), then the note rolls down from
        its top bar to its height. A note the plan moves (not enough room under it) just opens."""
        p, win = self.pad, self.win
        bar = win.winfo_height()
        img = self._kept_shot(p.height)         # taken as it showed, when it folded (none: the widgets roll)
        self.rolling = True
        self._roll_cover(img)
        self._roll_geometry(bar)                # (with the picture: only the bar shows, whatever comes)
        self.app.set_folded([self], False)
        if self.app.motion.drives(p.id):        # moved by the plan: it just opens
            self._drop_roll_cover(p.height)
            self.rolling = False
            self.app.request_save()
            return
        self._roll_geometry(bar)

        def done():
            self._drop_roll_cover(p.height)
            self.rolling = False
            self.app.request_save()
        animate(win, "roll", ROLL_MS, lambda k: self._roll_geometry(bar + (p.height - bar) * k), done)

    def glide_to(self, x, y, ms=None, start_at=None):
        """Move the note to (x, y) smoothly (ease-out), its docked calendar following: one item
        of app.motion, on its one clock. ``start_at``: where it starts, when the window is not
        there now (a new note sliding out from behind its parent)."""
        p = self.pad
        self.app.motion.run({p.id: (x, y, x + p.width, y + _shown_h(p))}, ms=ms,
                            starts=None if start_at is None else {p.id: tuple(start_at)})

    def stop_glide(self):
        """Stop sliding where it is now (the user takes hold of it); its docked calendar too."""
        self.app.motion.cancel({self.pad.id})

    def flash(self):
        """"Here it is" (a new or reopened note): the date row starts in the main theme color
        and fades back to the note's own (FLASH_MS). The rail keeps its shade."""
        win, c = self.win, self.colors
        start = _mix(win, accent_color(win, self.app.theme_colors().bg, c.bg), c.bg, 0.15)
        plain = (self.bar, self.row)
        buttons = (self.btn_back, self.btn_min, self.btn_close)

        last = [None]

        def step(t):                        # smoothstep: stays colored a little, lets go, settles (B7)
            color = _mix(win, start, c.bg, anim.smoothstep(t))
            if color != last[0]:            # (the last stretch is often the same color: no configure)
                last[0] = color
                for w in plain + buttons:
                    w.configure(bg=color)

        def done():
            for w in plain:
                w.configure(bg=c.bg)
            for b in buttons:
                b.configure(bg=b._rest())
        animate(win, "flash", FLASH_MS, step, done, ease=lambda t: t, kind="fade")

    def _on_configure(self, event):
        if event.widget is not self.win:
            return
        # moved or resized, also by Windows (minimized from the taskbar, or shown again): no
        # <Map>/<Unmap> binding for that, as ShowWindow (winapi.minimize) runs those at once,
        # inside a ctypes call that let go of the GIL
        self.app.space_changed()
        if self._clip is not None:              # a group resize shows it through a region: the pad
            return                              # is what clip_to says, not the window's real size
        if self.win.state() != "normal":
            return
        if self.app.screens_pending and not self.app.moving:
            # the monitors changed and are not taken in yet: what Windows did to the window is not
            # saved. A drag or resize by the user is (its docked calendar follows it): the flag can
            # stay up a while at start, as the taskbar and monitors settle, and the calendar would
            # stay behind while its outline went along with the note
            return
        if self.app.motion.drives(self.pad.id) or self.rolling:
            return                          # moved by a plan: Motion writes the pad (and moves the calendar)
        p = self.pad
        geo = (self.win.winfo_rootx(), self.win.winfo_rooty(),
               self.win.winfo_width(), self.win.winfo_height())
        if p.collapsed:                     # folded up: the height kept is the unfolded one
            geo = geo[:3] + (p.height,)
        if geo == (p.x, p.y, p.width, p.height):
            return
        resized = (geo[2], geo[3]) != (p.width, p.height)
        p.x, p.y, p.width, p.height = geo
        if not self.app.moving:             # (a drag or resize saves once, when it lets go)
            self.app.request_save()
        if self.calendar:                   # a docked calendar follows its note, also mid-drag
            self.calendar.place()
        if resized:
            if self._cover is not None:     # a picture stands in: laid out once, when thawed
                self._sized_late = True
            else:
                self._sized(geo[2])

    def _sized(self, width):
        """Its size changed (resized, or a glide got there): the date fits again, and the grab
        strip, picture and inline pictures are drawn for it."""
        self._arrange_chrome(width)
        if self.note.style == "image":
            self._later("image", 120, self.viewer.render)
        if self._inline:
            self._later("inline", 200, self._rescale_inline)


# every name (underscored ones too) goes on to the next part: see app.py
__all__ = [_n for _n in list(globals()) if not _n.startswith("__")]
