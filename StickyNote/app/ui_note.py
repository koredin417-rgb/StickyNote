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
STICKER_FADE_MS = 140


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

        self.frame = tk.Frame(win, bd=0)
        self.frame.pack(fill="both", expand=True, padx=1, pady=1)

        # ---- grab strip: a handle along the top for moving the note
        self.grab = tk.Canvas(self.frame, height=px(GRAB_H), bd=0, highlightthickness=0, cursor="fleur")
        self.grab.pack(fill="x")
        self.grab.bind("<Configure>", lambda e: self._draw_grab())
        self.grab.bind("<Enter>", lambda e: self._draw_grab(hover=True))
        self.grab.bind("<Leave>", lambda e: self._draw_grab())
        Tooltip(self.grab, tr("tip_grab"))

        # ---- top bars
        self.bar = tk.Frame(self.frame, bd=0)
        self.bar.pack(fill="x")
        hb = self.home_bar = tk.Frame(self.bar, bd=0)

        def top_button(master, glyph, command, tip, **kw):
            return IconButton(master, app, glyph, command, tip, height=TOP_BUTTON_H, **kw)
        self.btn_memo = top_button(hb, GLYPH["add"], self.new_memo, tr("tip_new_memo"))
        self.btn_window = top_button(hb, GLYPH["note"], lambda: app.new_window(self),
                                     tr("tip_new_window"), overlay=GLYPH["add"])
        self.btn_list = top_button(hb, GLYPH["list"], self.show_list, tr("tip_list"))
        self.btn_cal = top_button(hb, GLYPH["calendar"], self.toggle_calendar, tr("tip_calendar"))
        self.btn_close = top_button(hb, GLYPH["close"], self.close, tr("tip_close"))
        self.btn_min = top_button(hb, GLYPH["minimize"], self.minimize_button, tr("tip_minimize"))
        self.btn_gear = top_button(hb, GLYPH["gear"], self.toggle_settings, tr("tip_settings"))
        self.btn_pin = top_button(hb, GLYPH["pin"], self.toggle_pin, tr("tip_pin"))
        self.btn_style = top_button(hb, GLYPH["style"], self._style_menu, tr("tip_style"))
        self.btn_trash = top_button(hb, GLYPH["trash"], self.trash_current, tr("tip_trash", days=BIN_DAYS))
        self.btn_unfold = top_button(hb, GLYPH["fold"], lambda: self.toggle_collapse(), tr("tip_unfold"))
        self.left_buttons = (self.btn_memo, self.btn_window, self.btn_list, self.btn_cal)
        self.right_buttons = (self.btn_close, self.btn_min, self.btn_gear, self.btn_pin, self.btn_style,
                              self.btn_trash)
        # a narrow note gives up these first (in this order) so the date keeps its place; they
        # are in the top row's right-click menu then
        self.spare_buttons = (self.btn_style, self.btn_min, self.btn_trash)
        self._bar_state = None
        self._cover = None                  # the picture standing in while a group resizes
        for b in self.left_buttons:
            b.pack(side="left")
        for b in self.right_buttons:
            b.pack(side="right")
        self._date_font = tkfont.Font(win, family=UI_FONT, size=9)
        # placed over the middle of the note (see _fit_date), not packed between the icons
        self.date_label = tk.Label(hb, text=today_label(date.today()), font=self._date_font, cursor="fleur", bd=0)
        # double-click: fold up / unfold, like the rest of the top bar (the calendar is its icon)
        self.date_label.bind("<Double-Button-1>", lambda e: self.toggle_collapse())
        self.date_tip = Tooltip(self.date_label, tr("tip_date"))

        sb = self.sub_bar = tk.Frame(self.bar, bd=0)
        self.btn_back = top_button(sb, GLYPH["back"], self.go_back, tr("tip_back"))
        self.btn_back.pack(side="left")
        self.sub_title = tk.Label(sb, font=(UI_FONT, 9), bd=0)     # like the date: plain, icon gray
        self.sub_title.pack(side="left", padx=px(2))
        self.btn_close2 = top_button(sb, GLYPH["close"], self.close, tr("tip_close_short"))
        self.btn_min2 = top_button(sb, GLYPH["minimize"], self.minimize_button, tr("tip_minimize"))
        self.btn_close2.pack(side="right")
        self.btn_min2.pack(side="right")
        self.buttons = (self.btn_memo, self.btn_window, self.btn_list, self.btn_cal, self.btn_style,
                        self.btn_trash, self.btn_pin, self.btn_gear, self.btn_min, self.btn_close,
                        self.btn_back, self.btn_min2, self.btn_close2, self.btn_unfold)
        for w in (self.grab, self.bar, hb, sb, self.sub_title, self.date_label):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)
            w.bind("<Button-3>", self._top_menu)    # the hidden controls, as a menu
        for w in (self.grab, self.bar, hb, sb, self.sub_title):     # the date too (below)
            w.bind("<Double-Button-1>", lambda e: self.toggle_collapse())

        # ---- pages
        self.views = tk.Frame(self.frame, bd=0)
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

        # ---- format bar under the memo, like Windows Sticky Notes
        fb = self.format_bar = tk.Frame(self.home, bd=0)
        self.format_line = tk.Frame(fb, height=1, bd=0)
        self.format_line.pack(fill="x")
        self.format_row = tk.Frame(fb, bd=0)
        self.format_row.pack(fill="x", padx=px(6))

        def fmt_button(glyph, command, tip):
            return IconButton(self.format_row, app, GLYPH[glyph], command, tr(tip), width=FORMAT_BUTTON_W)
        self.btn_bold = fmt_button("bold", lambda: self.toggle_format("b"), "tip_bold")
        self.btn_italic = fmt_button("italic", lambda: self.toggle_format("i"), "tip_italic")
        self.btn_underline = fmt_button("underline", lambda: self.toggle_format("u"), "tip_underline")
        self.btn_strike = fmt_button("strike", lambda: self.toggle_format("s"), "tip_strike")
        self.btn_bullets = fmt_button("bullets", self.toggle_bullets, "tip_bullets")
        self.btn_todo = fmt_button("todo", self.toggle_todo, "tip_todo")
        self.btn_picture = fmt_button("picture", self.pick_images, "tip_picture")
        self.format_buttons = (self.btn_bold, self.btn_italic, self.btn_underline, self.btn_strike,
                               self.btn_bullets, self.btn_todo, self.btn_picture)
        for b in self.format_buttons:
            b.pack(side="left", padx=(0, px(4)))
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
        self.toast = tk.Frame(self.frame, bd=0)
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
        self.grip.place(relx=1, rely=1, anchor="se")
        self.grip.bind("<ButtonPress-1>", self._resize_start)
        self.grip.bind("<B1-Motion>", self._resize_move)
        self.grip.bind("<ButtonRelease-1>", self._drag_end)

        # ---- events
        self._trace_ids = [(self.header_var,       # removed in destroy(): a trace keeps this window alive
                            self.header_var.trace_add("write", lambda *a: self.sync_from_widgets()))]
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
        # Taskbar "Close window" and Alt+F4 send WM_CLOSE. Without this Tk just destroys the
        # window and the app runs on with nothing on screen, blocking the next start.
        win.protocol("WM_DELETE_WINDOW", self.close)
        winapi.hook_ime(win.winfo_id())     # Korean: keep the last syllable, no white IME box
        for w in (self.body, self.header_entry, self.list_view.search_entry):
            _finish_typing_first(w)
            # no white IME box over a picture memo (or anywhere): said again at every focus
            w.bind("<FocusIn>", lambda e: winapi.hide_ime_box(self.win.winfo_id()), add="+")

        win.geometry(f"{pad.width}x{pad.height}+{pad.x}+{pad.y}")
        self._fit_date(pad.width)
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
            animate(win, "fade", OPEN_FADE_MS, lambda k: win.attributes("-alpha", self.pad.alpha * k))

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
        self.view = view
        PopupMenu.close_current()
        self.list_view.hide_preview()
        for page in (self.list_view, self._settings_view, self._bin_view):
            if page is not None:
                page.frame.pack_forget()
        self.home.pack_forget()
        if view == "home":
            self.sub_bar.pack_forget()
            self.home_bar.pack(fill="x")
            self.home.pack(fill="both", expand=True)
        else:
            self.home_bar.pack_forget()
            self.sub_bar.pack(fill="x")
            page = {"list": self.list_view, "settings": self.settings_view, "bin": self.bin_view}[view]
            self.sub_title.configure(text=tr(f"title_{view}"))
            page.frame.pack(fill="both", expand=True)
        tk.Misc.tkraise(self.grip)
        self._place_toast()

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
        self.viewer.render(follow=True)

    def step_tab(self, delta):
        if self.view == "home":
            self.switch_tab(self.viewer.index + delta)

    # ---- pictures inside the text ("+ Add picture" under it) ------------------------
    def _inline_width(self):
        px = self.app.px
        width = self.body.winfo_width() if self.body.winfo_width() > 1 else self.pad.width - 2
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
        n, c = self.note, self.colors
        fmt = self._formats_at_cursor()
        style = [s for s, k in (("bold", "b"), ("italic", "i")) if k in fmt]
        font = tkfont.Font(self.win, family=n.font_family, size=n.font_size, underline=True,
                           weight="bold" if "bold" in style else "normal",
                           slant="italic" if "italic" in style else "roman")
        self._preedit_font = font
        x, y, _w, h = box
        self.preedit.configure(text=text, font=font, bg=c.bg, fg=c.fg)
        self.preedit.place(x=x, y=y, height=h, bordermode="ignore")   # bbox counts from the outer edge
        self._later("preedit", 120, self._show_preedit)

    def _draw_period_band(self):
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
        """Bin icon on the home bar. A blank memo has nothing to keep, so nothing happens."""
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
        pixels; None off the home page, folded, hidden, or when the screen can't be read."""
        try:
            if self.view != "home" or self.pad.collapsed or not self.home.winfo_ismapped():
                return None
            x0, y0, w = self.home.winfo_rootx(), self.home.winfo_rooty(), self.home.winfo_width()
            fb = self.format_bar
            y1 = fb.winfo_rooty() if fb.winfo_ismapped() else y0 + self.home.winfo_height()
            if w < 8 or y1 - y0 < 8:
                return None
            img = ImageGrab.grab((x0, y0, x0 + w, y1), all_screens=True)
            return img, x0 - self.win.winfo_rootx(), y0 - self.win.winfo_rooty()
        except Exception:
            return None

    def _fly_to_bin(self, img, x, y):
        """Deletion (option 1, "휴지통으로 빨려들기"): the memo's picture shrinks into the bin icon on
        the top bar, speeding up as it goes (DELETE_FLY_MS), over the next memo already in place
        (only the picture's own box is covered); then the icon gives a little bounce."""
        top, btn = self.win, self.btn_trash
        try:
            bx = btn.winfo_rootx() - top.winfo_rootx() + btn.winfo_width() / 2
            by = btn.winfo_rooty() - top.winfo_rooty() + btn.winfo_height() / 2
            w0, h0 = img.size
            cv = tk.Canvas(top, bd=0, highlightthickness=0, width=w0, height=h0)
            cv._photo = ImageTk.PhotoImage(img, master=cv)
            pic = cv.create_image(0, 0, anchor="nw", image=cv._photo)
            cv.place(x=x, y=y)
            tk.Misc.tkraise(cv)
        except tk.TclError:
            return
        half = img.resize((max(1, w0 // 2), max(1, h0 // 2)), Image.BOX)   # small frames scale from this
        sx, sy, start = x + w0 / 2, y + h0 / 2, time.perf_counter()

        def frame():
            try:
                t = min(1.0, (time.perf_counter() - start) * 1000 / DELETE_FLY_MS)
                e = t * t                                       # speeds up into the bin
                s = 1 - 0.95 * e
                w, h = max(2, round(w0 * s)), max(2, round(h0 * s))
                cx, cy = sx + (bx - sx) * e, sy + (by - sy) * e
                cv._photo = ImageTk.PhotoImage((img if s > 0.5 else half).resize((w, h), Image.BILINEAR), master=cv)
                cv.itemconfigure(pic, image=cv._photo)
                cv.configure(width=w, height=h)
                cv.place(x=round(cx - w / 2), y=round(cy - h / 2))
                if t < 1.0:
                    cv.after(FRAME_MS, frame)
                    return
                cv.destroy()
            except tk.TclError:
                return
            self._bin_bounce()
        frame()

    def _bin_bounce(self):
        """The top bar's bin icon: a little bounce as a memo lands in it."""
        btn = self.btn_trash
        base = btn.box
        for i, f in enumerate((1.3, 1.12, 1.0)):
            def step(f=f):
                if btn.winfo_exists():
                    btn.box = base * f if f != 1.0 else base
                    btn._draw()
            self.win.after(i * 60, step)

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
        px = self.app.px
        if self.view == "list":
            lift = self.list_view.bin_row.winfo_reqheight() + px(10)
        elif self.view == "home":
            lift = self.format_bar.winfo_reqheight()        # above the format bar, not over it
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
        self.toast.place_forget()

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
            winapi.hook_syscommand(self.win, self.app._syscommands)
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

        def step(k):
            for w, a in zip(wins, starts):
                if w.winfo_exists():
                    w.attributes("-alpha", a * (1 - k))
        animate(self.win, "fade", CLOSE_FADE_MS, step, done)

    def _roll_geometry(self, h, dy=0):
        p = self.pad
        cover = getattr(self, "_rolling_cover", None)
        if cover is not None and not dy and winapi.clip_height(self.win, p.width, round(h)):
            # rolling with its picture: the window stays as big as the picture, its region shows the
            # top h px (the region first, so the window never shows more than h, even as it grows)
            geo = f"{p.width}x{cover.full_h}+{p.x}+{p.y}"
            if getattr(self, "_roll_geo", None) != geo:
                self._roll_geo = geo
                self.win.geometry(geo)
            return
        if getattr(self, "_roll_geo", None) is not None:
            winapi.clip_height(self.win)
            self._roll_geo = None
        self.win.geometry(f"{p.width}x{round(h)}+{p.x}+{p.y + round(dy)}")

    def _shot(self):
        """A picture of the whole note as it shows now (PrintWindow), or None."""
        try:
            shot = winapi.snapshot(self.win) if self.win.winfo_ismapped() else None
        except tk.TclError:
            return None
        if shot is None:
            return None
        w, h, data = shot
        img = Image.frombuffer("RGB", (w, h), data, "raw", "BGRX", 0, 1).copy()
        self._roll_shot = ((self.pad.width, h, self.note.color), img)      # kept: the way back rolls it too
        return img

    def _kept_shot(self, height):
        """The picture kept from the last roll, if the note still looks that way (same size and color)."""
        kept = getattr(self, "_roll_shot", None)
        return kept[1] if kept and kept[0] == (self.pad.width, height, self.note.color) else None

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
            self.win.geometry(f"{p.width}x{round(height)}+{p.x}+{p.y}")
        if getattr(self, "_roll_geo", None) is not None:
            winapi.clip_height(self.win)
            self._roll_geo = None
        self.frame.pack(fill="both", expand=True, padx=1, pady=1)
        cover.destroy()

    def minimize_button(self):
        """The minimize button. "Top bar only" (Settings): an open note folds up to its top bar
        (as a double-click does); a folded one goes away for real (back from the taskbar)."""
        if self.app.prefs.minimize_style == "bar" and not self.pad.collapsed and not self.rolling:
            self.toggle_collapse()
            return
        self.minimize()

    def minimize(self, animate: bool = True):
        """Roll up to the top bar (ROLL_MS), slide it down while fading (DOCK_SLIDE_MS), then
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

        if not animate:
            self.rolling = True
            finish()
            return
        self.rolling = True
        bar, slide = min(shown, px(GRAB_H + TOP_BUTTON_H)), px(40)
        self._roll_cover(self._shot())

        def slide_down():
            def step(k):
                self._roll_geometry(bar, slide * k)
                win.attributes("-alpha", alpha * (1 - k))
            animate_(win, "roll", DOCK_SLIDE_MS, step, finish)

        animate_(win, "roll", ROLL_MS, lambda k: self._roll_geometry(shown + (bar - shown) * k), slide_down)

    def restore(self, animate: bool = True):
        """The reverse of minimize: the bar slides up and fades in, then unrolls; then the app
        returns the note to its place (return_note)."""
        if self.rolling or not self.minimized:
            return
        self._hide_sticker()
        win, p, px = self.win, self.pad, self.app.px
        alpha = p.alpha
        shown = _shown_h(p)
        bar, slide = min(shown, px(GRAB_H + TOP_BUTTON_H)), px(40)
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
        if animate:
            self._roll_cover(self._kept_shot(shown))
        self._roll_geometry(bar if animate else shown, slide if animate else 0)
        win.deiconify()
        self.minimized = False
        if not animate:
            finish()
            return

        def unroll():
            animate_(win, "roll", ROLL_MS, lambda k: self._roll_geometry(bar + (shown - bar) * k), finish)

        def slide_up():
            def step(k):
                self._roll_geometry(bar, slide * (1 - k))
                win.attributes("-alpha", alpha * k)
            animate_(win, "roll", DOCK_SLIDE_MS, step, unroll)

        slide_up()

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
        self._roll_shot = None
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
        self._fit_date()
        if self.calendar:
            self.calendar.draw()

    def _arrange_bar(self, inner):
        """Which top-bar icons show. Folded up: unfold, minimize and close (the title gets the
        room). Narrow: the spare ones go, one by one, until the short date fits."""
        if self.pad.collapsed:              # (minimize too: a folded note can still go away)
            shown = (self.btn_unfold, self.btn_min, self.btn_close)
        else:
            px = self.app.px
            need = self._date_font.measure(texts.day_label(date.today(), short=True)) + px(8)
            hidden = []
            for b in (None,) + self.spare_buttons:
                if b is not None:
                    hidden.append(b)
                used = sum(x.winfo_reqwidth() for x in self.left_buttons + self.right_buttons if x not in hidden)
                if inner - used >= need:
                    break
            shown = tuple(b for b in self.left_buttons + self.right_buttons if b not in hidden)
            if self.app.calendar_elsewhere(self) is not None:     # one calendar at a time
                shown = tuple(b for b in shown if b is not self.btn_cal)
        state = (self.pad.collapsed, shown)
        if state == self._bar_state:
            return
        self._bar_state = state
        for b in self.left_buttons + self.right_buttons + (self.btn_unfold,):
            b.pack_forget()
        for b in (self.btn_unfold,) + self.left_buttons:
            if b in shown:
                b.pack(side="left")
        for b in self.right_buttons:
            if b in shown:
                b.pack(side="right")

    def _fit_date(self, width=None):
        """Put the date in the middle of the note. When the icons leave too little room
        there, it moves toward the free side; if it still does not fit it is shortened
        ("11/21") or hidden, never cut off or laid over an icon."""
        if width is None:
            width = self.win.winfo_width() if self.win.winfo_width() > 1 else self.pad.width
        px = self.app.px
        inner = width - 2                                   # the 1 px frame on each side
        self._arrange_bar(inner)
        shown = [b for b in self.left_buttons + (self.btn_unfold,) if b in self._bar_state[1]]
        lo = sum(b.winfo_reqwidth() for b in shown) + px(2)
        hi = inner - sum(b.winfo_reqwidth() for b in self.right_buttons if b in self._bar_state[1]) - px(2)
        d = date.today()
        choices = (texts.day_label(d), texts.day_label(d, short=True))
        if self.pad.collapsed:              # folded up: what the memo says, left-aligned, cut to fit
            lines = self._fold_lines()
            full = " · ".join(lines)
            text, room = full, max(0, hi - lo - px(8))
            while text and self._date_font.measure(text + "…") > room:
                text = text[:-1]
            text = full if text == full else text.rstrip(" ·") + "…"
            self.date_label.configure(text=text, anchor="w")
            self.date_label.place(x=lo + px(2), y=0, relheight=1, width=max(1, hi - lo - px(2)))
            shown = "\n".join(lines[:6]) + ("\n…" if len(lines) > 6 else "")
            self.date_tip.text = tr("tip_folded", text=shown)
            return
        self.date_label.configure(anchor="center")
        self.date_tip.text = tr("tip_date")
        for text in choices:
            w = self._date_font.measure(text) + px(4)
            if w <= hi - lo:
                x = min(max(round(inner / 2 - w / 2), lo), hi - w)
                self.date_label.configure(text=text)
                self.date_label.place(x=x, y=0, relheight=1, width=w)
                return
        self.date_label.configure(text="")
        self.date_label.place_forget()

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
        c = self.colors = Colors.of(self.win, n.color)
        top = self.bar_colors = Colors.of(self.win, c.bar, solid=True)   # the grab strip and top bar share one shade
        self.win.configure(bg=c.frame)
        for w in (self.frame, self.views, self.home):
            w.configure(bg=c.bg)
        for w in (self.bar, self.home_bar, self.sub_bar, self.grab):
            w.configure(bg=top.bg)
        self._draw_grab()
        for b in self.buttons:
            b.recolor(top, strong=(b is self.btn_pin and p.pinned))
        self.btn_pin.set_glyph(GLYPH["pinned" if p.pinned else "pin"])
        self.date_label.configure(bg=top.bg, fg=top.muted)    # the icons' color
        self.sub_title.configure(bg=top.bg, fg=top.muted)
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
        for w in (self.format_bar, self.format_row):
            w.configure(bg=c.bg)
        self.format_line.configure(bg=c.line)
        for b in self.format_buttons:
            b.recolor(c)
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

    def _draw_grab(self, hover=False):
        g, c, px = self.grab, self.bar_colors, self.app.px
        g.delete("all")
        w, h = g.winfo_width(), int(g.cget("height"))
        if w <= 1:
            w = self.pad.width
        if hover:                           # double-click folds up (^) / unfolds (v)
            up = not self.pad.collapsed
            s, k = px(5), px(2)
            y0, y1 = (h / 2 + k, h / 2 - k) if up else (h / 2 - k, h / 2 + k)
            g.create_line(w / 2 - s, y0, w / 2, y1, w / 2 + s, y0, width=px(2), capstyle="round",
                          joinstyle="round", fill=c.muted)
            return
        half = px(18)
        g.create_line(w / 2 - half, h / 2, w / 2 + half, h / 2, width=px(2), capstyle="round", fill=c.border)

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
        for w in (self.header_entry, self.header_sep, self.viewer.frame, self.format_bar, self.add_bar,
                  self.body, self.period_band):
            w.pack_forget()
        self.format_bar.pack(side="bottom", fill="x")
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

    def _style_menu(self, x=None, y=None):
        menu = PopupMenu(self.app, self.win, self.colors)
        for style in STYLES:
            menu.add(tr(f"style_{style}"), lambda s=style: self.set_style(s), checked=style == self.note.style)
        b = self.btn_style
        if x is None:
            x, y = b.winfo_rootx(), b.winfo_rooty() + b.winfo_height()
        menu.popup(x, y)

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
        self._refresh_bullets()
        self._sync_soon()

    def _sync_soon(self):
        """While typing, the stored memo catches up once the typing pauses: reading a long
        memo back (some 5 ms for 3000 lines) twice at every key made typing heavy. Whatever
        needs it at once (saving, switching memos, the list, closing) calls sync_from_widgets."""
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
        self._refresh_combined()
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

    def _refresh_combined(self):
        """Text that is both bold and italic needs its own font: tag "bi"."""
        b = self.body
        b.tag_remove("bi", "1.0", "end")
        bold, ital = b.tag_ranges("b"), b.tag_ranges("i")
        for s1, e1 in zip(bold[0::2], bold[1::2]):
            for s2, e2 in zip(ital[0::2], ital[1::2]):
                s = s1 if b.compare(s1, ">", s2) else s2
                e = e1 if b.compare(e1, "<", e2) else e2
                if b.compare(s, "<", e):
                    b.tag_add("bi", s, e)

    def _refresh_bullets(self):
        """Bulleted and to-do lines wrap under their text, not under the mark; a to-do's box
        is drawn in the box font, and a done to-do is crossed out in a faint color."""
        b = self.body
        for tag in ("bullet", "todo", "todo_box", "todo_done"):
            b.tag_remove(tag, "1.0", "end")
        for row, line in enumerate(b.get("1.0", "end-1c").split("\n"), start=1):
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
                    lambda: b.tag_remove("done_fade", "1.0", "end"))

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
        fmt = self._formats_at_cursor()
        for kind, button in zip(MARK_KINDS, self.format_buttons):
            button.set_active(kind in fmt)
        mark = self._line_mark(self.body.index("insert").split(".")[0])
        self.btn_bullets.set_active(mark == BULLET)
        self.btn_todo.set_active(mark in (TODO, DONE))

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
        self._drag = (event.x_root - self.win.winfo_rootx(), event.y_root - self.win.winfo_rooty())
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
        shown = self._bar_state[1] if self._bar_state else ()
        hidden = [(b, key, cmd) for b, key, cmd in (
            (self.btn_list, "menu_list", self.show_list), (self.btn_gear, "menu_settings", self.show_settings),
            (self.btn_style, "menu_style", lambda: self._style_menu(x, y)),
            (self.btn_trash, "menu_trash", self.trash_current), (self.btn_min, "menu_minimize", self.minimize))
            if b not in shown]
        if hidden:                          # the icons a narrow or folded note does not show
            menu.separator()
            for b, key, cmd in hidden:
                menu.add(tr(key), cmd, icon=b.glyph)
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
        box = self.hints = tk.Frame(self.frame, bg=c.border, bd=0)
        inner = tk.Frame(box, bg=c.bg, bd=0)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        width = max(px(180), (self.win.winfo_width() if self.win.winfo_width() > 1 else self.pad.width)
                    - px(28))
        tk.Label(inner, text=tr("hint_title"), bg=c.bg, fg=c.fg, anchor="w",
                 font=(UI_BOLD, 10, "bold")).pack(fill="x", padx=px(12), pady=(px(10), px(4)))
        tk.Label(inner, text=tr("hint_lines"), bg=c.bg, fg=c.muted, anchor="w", justify="left",
                 wraplength=width - px(26), font=(UI_FONT, 9)).pack(fill="x", padx=px(12))
        ok = FlatButton(inner, tr("hint_ok"), self.close_hints)
        ok.recolor(c)
        ok.configure(font=(UI_BOLD, 9, "bold"))
        ok.pack(anchor="e", padx=px(10), pady=(px(6), px(10)))
        y, drop = px(GRAB_H + TOP_BUTTON_H + 8), px(HINT_DROP)
        animate(box, "drop", HINT_DROP_MS,         # drops HINT_DROP px into place
                lambda k: box.place(relx=0.5, y=y - round(drop * (1 - k)), anchor="n", width=width))
        tk.Misc.tkraise(box)

    def hide_hints(self):
        box = getattr(self, "hints", None)
        if box is not None:
            stop_animation(box, "drop")
            box.destroy()
            self.hints = None

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
                ox, oy = cal._xy[0] - w.pad.x, cal._xy[1] - w.pad.y       # placed from the same pad
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

    @perf.timed("drag_move")
    def _drag_move(self, event):
        if self._drag:
            dx, dy = self._drag
            x, y = event.x_root - dx, event.y_root - dy
            group = getattr(self, "_group", [])
            self._snap_id = None
            self._drag_pt = (event.x_root, event.y_root)
            if not event.state & 0x20000 and getattr(self, "_grid_key", None) is None:     # Alt held: move freely
                x, y = self._snapped(x, y, group)
            self.win.geometry(f"+{x}+{y}")
            self._dropped = {self: (x, y)}          # where the drag put each (winfo_rootx can lag behind)
            for w, ox, oy in group:
                if w.win.winfo_exists():
                    w.win.geometry(f"+{x + ox}+{y + oy}")
                    self._dropped[w] = (x + ox, y + oy)
            along = getattr(self, "_cal_along", None)
            if along is not None:
                cal, ox, oy, cw, ch = along
                cal.nw.pad.calendar_pos = [x + ox, y + oy]    # (place() puts an undocked one there)
                cal.move_to((x + ox, y + oy, x + ox + cw, y + oy + ch))
            if group or along is not None:
                self.app.ring.move(self._live_ring_boxes())

    def _set_geometry(self, nw, geometry):
        """Tell Tk only what changed (each change redraws that note)."""
        if self._geometries.get(nw) != geometry:
            self._geometries[nw] = geometry
            nw.win.geometry(geometry)

    def _resize_start(self, event):
        self._resize = (event.x_root, event.y_root, self.win.winfo_width(), self.win.winfo_height())
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
        if self._resize_group:              # the same line as when they move together
            self.app.ring.show([self._resize_box] + [b for _w, b in self._resize_group], self.win, self.pad.alpha)
            self.freeze()                   # (smooth: see freeze; the text wraps when let go)

    @perf.timed("resize_move")
    def _resize_move(self, event):
        if self._resize:
            x0, y0, w0, h0 = self._resize
            px = self.app.px
            w = max(px(MIN_W), w0 + event.x_root - x0)
            h = max(px(MIN_H), h0 + event.y_root - y0)
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
            self._set_geometry(self, f"{w}x{h}")
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
                self._set_geometry(o, f"{ow}x{oh}+{x}+{y}")
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
                self._set_geometry(nw, f"+{nb[0]}+{nb[1]}")
            elif nb != s.box:
                outlines.append(nb)
        for nw, start in list(self._live.items()):          # no longer pushed: back to where it was
            if nw not in still:
                del self._live[nw]
                self._now.pop(nw.pad.id, None)
                if nw.win.winfo_exists():
                    self._set_geometry(nw, f"+{start[0]}+{start[1]}")
        if outlines:
            app.outlines().show(outlines)
        else:
            app.outlines().hide()
        app.space_changed()
        return w, h

    def _drag_end(self, _event=None):
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
        if was_drag and (self._group or along is not None) and not tiles:
            ids = set(moved_ids)
            self.app.root.after(GLIDE_MS + 40, lambda: self.app.push_clear(ids))
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
            self.app.settle_drop(ids, places=places, anchor=self)
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

    # ---- group resize: a picture stands in for the widgets ---------------------------
    def freeze(self):
        """Resized along with a group, a note would redraw its ~30 widgets at every step of
        the mouse (some 25 ms each; six notes made the resize lag). Instead a picture of it
        stands in, drawn at the new size: the top bar's icons stay at the two edges, the date
        in the middle, the bottom bar at the left, the text where it was. thaw() brings the
        widgets back (the text wraps to the new size then)."""
        if self._cover is not None or not self.win.winfo_ismapped():
            return
        shot = winapi.snapshot(self.win)
        if shot is None:
            return
        w, h, data = shot
        img = Image.frombuffer("RGB", (w, h), data, "raw", "BGRX", 0, 1).crop((1, 1, w - 1, h - 1))
        fw, fh = img.size
        fx, fy = self.frame.winfo_rootx(), self.frame.winfo_rooty()

        def box(wd):
            x, y = wd.winfo_rootx() - fx, wd.winfo_rooty() - fy
            return x, y, x + wd.winfo_width(), y + wd.winfo_height()

        buttons = []

        def walk(wd):
            for ch in wd.winfo_children():
                if ch.winfo_ismapped():
                    if isinstance(ch, IconButton):
                        buttons.append(box(ch))
                    else:
                        walk(ch)
        walk(self.bar)
        grab_h, top = box(self.grab)[3], box(self.bar)[3]
        left = max([b[2] for b in buttons if b[0] + b[2] < fw], default=0)
        right = min([b[0] for b in buttons if b[0] + b[2] >= fw], default=fw)
        bottom = fh - box(self.format_bar)[1] if self.format_bar.winfo_ismapped() else 0
        g = self.grip.winfo_width() if self.grip.winfo_ismapped() else 0
        cover = tk.Canvas(self.win, bd=0, highlightthickness=0, bg=self.body.cget("bg"))
        bars = [(cover.create_rectangle(0, 0, 0, 0, width=0, fill=self.grab.cget("bg")),
                 lambda W, H: (0, 0, W, grab_h)),
                (cover.create_rectangle(0, 0, 0, 0, width=0, fill=self.home_bar.cget("bg")),
                 lambda W, H: (0, grab_h, W, top))]
        if bottom:
            bars.append((cover.create_rectangle(0, 0, 0, 0, width=0, fill=self.format_bar.cget("bg")),
                         lambda W, H: (0, H - bottom, W, H)))
        photos, pieces = [], []

        def piece(crop, where):
            if crop[2] - crop[0] > 0 and crop[3] - crop[1] > 0:
                photos.append(ImageTk.PhotoImage(img.crop(crop), master=cover))
                pieces.append((cover.create_image(0, 0, anchor="nw", image=photos[-1]), where))
        piece((0, top, fw, fh - bottom), lambda W, H: (0, top))                   # the text
        piece((0, fh - bottom, fw - g, fh), lambda W, H: (0, H - bottom))         # bottom bar
        piece((left, grab_h, right, top), lambda W, H: (left + (W - fw) / 2, grab_h))  # the date
        piece((0, grab_h, left, top), lambda W, H: (0, grab_h))                   # left icons
        piece((right, grab_h, fw, top), lambda W, H: (W - (fw - right), grab_h))  # right icons
        hw = self.app.px(24)
        piece((fw // 2 - hw, 0, fw // 2 + hw, grab_h), lambda W, H: (W // 2 - hw, 0))   # the handle
        piece((fw - g, fh - g, fw, fh), lambda W, H: (W - g, H - g))              # the resize grip

        def lay(W, H):
            for item, where in bars + pieces:
                cover.coords(item, *where(W, H))
        cover.bind("<Configure>", lambda e: lay(e.width, e.height))
        lay(fw, fh)
        self._cover, self._cover_photos = cover, photos
        cover.place(x=1, y=1, relwidth=1, relheight=1, width=-2, height=-2)
        self.frame.pack_forget()

    def thaw(self):
        if self._cover is None:
            return
        self.frame.pack(fill="both", expand=True, padx=1, pady=1)
        self._cover.destroy()
        self._cover = self._cover_photos = None

    # ---- folding up to the top bar --------------------------------------------------
    def collapsed_height(self):
        self.win.update_idletasks()
        return self.grab.winfo_reqheight() + self.bar.winfo_reqheight() + 2

    def _apply_collapsed(self):
        """Show the folded / unfolded state (pad.collapsed) without moving other notes."""
        p = self.pad
        if p.collapsed:
            self.hide_hints()
            self.hide_undo()
            self.list_view.hide_preview()
            self.views.pack_forget()
            self.grip.place_forget()
            p.shown_height = self.collapsed_height()
            self.win.geometry(f"{p.width}x{p.shown_height}")
        else:
            self.views.pack(fill="both", expand=True)
            self.grip.place(relx=1, rely=1, anchor="se")
            tk.Misc.tkraise(self.grip)
            self.win.geometry(f"{p.width}x{p.height}")
        self.app.space_changed()            # folded: as tall as its top bar
        self._fit_date(p.width)
        if self.calendar:
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
            self._apply_collapsed()
            self._draw_grab()
            self.app.request_save()
            self.app.arrange_soon()
            return
        self.user_moved(moved=False)
        if self.rolling:
            return
        if instant or not self.win.winfo_ismapped():
            self.app.set_folded([self], not p.collapsed)     # one plan: closes up linked / pushes (no Undo)
            self.app.request_save()
        elif not p.collapsed:
            self._fold_rolling()
        else:
            self._unfold_rolling()

    def _fold_rolling(self):
        """Fold up: the note rolls up to its top bar (ROLL_MS), then the plan runs (the notes
        under it close up)."""
        p, win = self.pad, self.win
        bar = self.collapsed_height()
        self.rolling = True
        self._roll_cover(self._shot())
        stop_animation(win, "roll")

        def done():
            self._drop_roll_cover(bar)
            self.rolling = False
            self.app.set_folded([self], True)
            self.app.request_save()
        animate(win, "roll", ROLL_MS, lambda k: self._roll_geometry(p.height + (bar - p.height) * k), done)

    def _unfold_rolling(self):
        """Unfold: the plan first (what is under it makes room), then the note rolls down from
        its top bar to its height. A note the plan moves (not enough room under it) just opens."""
        p, win = self.pad, self.win
        bar = win.winfo_height()
        img = self._kept_shot(p.height)
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

    def glide_to(self, x, y, ms=GLIDE_MS, start_at=None):
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
        """"Here it is" (a new or reopened note): the top bar starts in the main theme color
        and fades back to its own shade (FLASH_MS)."""
        win, top = self.win, self.bar_colors
        start = _mix(win, accent_color(win, self.app.theme_colors().bg, top.bg), top.bg, 0.15)
        plain = (self.grab, self.bar, self.home_bar, self.sub_bar, self.date_label, self.sub_title)

        def step(k):                        # k * k: stays colored a little longer, then lets go
            color = _mix(win, start, top.bg, k * k)
            for w in plain + self.buttons:
                w.configure(bg=color)

        def done():
            for w in plain:
                w.configure(bg=top.bg)
            for b in self.buttons:
                b.configure(bg=b._rest())
        animate(win, "flash", FLASH_MS, step, done)

    def _on_configure(self, event):
        if event.widget is not self.win:
            return
        # moved or resized, also by Windows (minimized from the taskbar, or shown again): no
        # <Map>/<Unmap> binding for that, as ShowWindow (winapi.minimize) runs those at once,
        # inside a ctypes call that let go of the GIL
        self.app.space_changed()
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
        self.app.request_save()
        if self.calendar:
            self.calendar.place()
        if resized:
            self._sized(geo[2])

    def _sized(self, width):
        """Its size changed (resized, or a glide got there): the date fits again, and the grab
        strip, picture and inline pictures are drawn for it."""
        self._fit_date(width)
        self._later("grab", 60, self._draw_grab)
        if self.note.style == "image":
            self._later("image", 120, self.viewer.render)
        if self._inline:
            self._later("inline", 200, self._rescale_inline)


# every name (underscored ones too) goes on to the next part: see app.py
__all__ = [_n for _n in list(globals()) if not _n.startswith("__")]
