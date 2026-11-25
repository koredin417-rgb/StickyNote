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
from tkinter import colorchooser, filedialog, messagebox

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageGrab, ImageTk

import holidays
import texts
import perf
import winapi
from icon import draw_icon
from store import (BIN_DAY_CHOICES, CURSOR_COLORS, CUSTOM_COLORS, EMPTY_TITLE, INLINE, LIST_SORTS, MARK_KINDS,
                   PIN_LIMIT_MAX, SNAP_GAPS, STYLES, TIDY_ORDERS, Note, NoteStore, Pad, Prefs)
from texts import tr
from ui_common import *  # noqa: F401,F403  (the parts before this one)


# --------------------------------------------------------------------------- list page
LIST_BATCH = 20                  # memo cards made at a time (the list makes more as it is scrolled)
SEARCH_DELAY_MS = 120            # the search runs once the typing pauses this long


class ListView:
    """Every memo as a card, like the Windows Sticky Notes list."""

    def __init__(self, nw: NoteWindow):
        self.nw, self.app = nw, nw.app
        px = self.app.px
        self.day: str | None = None
        self._order: list[str] = []
        self._shown: list = []          # pictures on the cards now (cached in App.picture)
        self.frame = tk.Frame(nw.views, bd=0)

        self.search_box = tk.Frame(self.frame, bd=0)
        self.search_box.pack(fill="x", padx=px(10), pady=(px(2), px(6)))
        self.search_icon = tk.Label(self.search_box, bd=0)
        self.search_icon.pack(side="left", padx=(px(6), px(2)))
        self.search = tk.StringVar(nw.win)
        self.search_entry = tk.Entry(self.search_box, textvariable=self.search, bd=0,
                                     relief="flat", highlightthickness=0, font=(UI_FONT, 10))
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=px(4), padx=(0, px(6)))
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
        self.bin_icons: dict = {}       # card -> its bin icon

        self.area = ScrollArea(self.frame, self.app)
        self.area.canvas.pack(fill="both", expand=True)
        self.area.canvas.bind("<Configure>", self._on_resize, add="+")
        self._width = 0
        self.cards: dict = {}           # note id -> (outer frame, card frame)
        self.pin_icons: dict = {}       # note id -> its pin icon
        self.preview: MemoPreview | None = None
        self._preview_job = self._hide_job = None
        self._queue, self._next = [], 0     # parts of the list not made yet (see _build_more)

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
        """The window is closing: the search trace (held by Tcl) would keep it alive."""
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
        self._shown = []
        self.bin_icons, self.cards, self.pin_icons = {}, {}, {}
        self.sections, self.sort_switch = {}, None
        self._picked, self._painters = None, {}
        notes = self.memos()
        self._order = [n.id for n in notes]
        if not notes:
            self._empty_state(c)
        pinned = [n for n in notes if n.pinned]
        others = [n for n in notes if not n.pinned]
        searching = bool(self.search.get().strip())        # a search shows what it found, folded or not
        folded = set() if searching else set(self.app.prefs.list_collapsed)
        queue = []
        if pinned:
            queue.append(("head", ("pinned", tr("pinned_head", n=len(pinned), limit=self.app.prefs.pin_limit),
                                   len(pinned), "pinned" in folded, c), {"icon": GLYPH["pinned"]}))
            if "pinned" not in folded:
                queue += [("card", note, None) for note in pinned]
        if notes:                       # the memos' head is always there: it holds the sort switch
            queue.append(("head", ("others", tr("others_head"), len(others), "others" in folded, c), {"sort": True}))
            if "others" not in folded:
                queue += [("card", note, None) for note in others]
        self._queue, self._next = queue, 0
        self._build_more()
        self._bin_badge()
        self.area.to_top()
        self.frame.after_idle(self._more_if_near_end)

    def _build_more(self, cards=LIST_BATCH) -> bool:
        """Make the next ``cards`` memo cards (and the part heads on the way). Hundreds of
        cards took seconds to make at once; the first ones show at once, the rest as the
        list is scrolled (or walked with the arrow keys) toward them."""
        made = 0
        while self._next < len(self._queue) and made < cards:
            kind, what, options = self._queue[self._next]
            self._next += 1
            if kind == "head":
                self._section(*what, **options)
            else:
                self._card(what)
                made += 1
        return made > 0

    def _more_if_near_end(self):
        """Less than a screen of cards left below what shows: make the next cards. (Measured
        on the cards themselves: the scroll room is only updated later.)"""
        try:
            cv = self.area.canvas
            if self._next >= len(self._queue) or not cv.winfo_ismapped():
                return
            self.area.inner.update_idletasks()
            seen = cv.canvasy(cv.winfo_height())        # the bottom of what shows, in the list's pixels
            if self.area.inner.winfo_reqheight() - seen < cv.winfo_height() and self._build_more():
                self.frame.after_idle(self._more_if_near_end)
        except tk.TclError:
            pass

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

    def _empty_state(self, c):
        px = self.app.px
        if self.day:
            glyph, text = GLYPH["calendar"], tr("none_on", day=_date_label(self.day))
        elif self.search.get().strip():
            glyph, text = GLYPH["search"], tr("none_found")
        else:
            glyph, text = GLYPH["empty_note"], tr("none_yet")
        self.empty_text = text
        empty_page(self.app, self.area.inner, c, glyph, text)
        tk.Frame(self.area.inner, bg=c.bg, height=px(6)).pack()
        if self.day:
            b = FlatButton(self.area.inner, tr("new_on_day"),
                           lambda d=self.day: self.nw.new_memo(date=d))
            b.recolor(c)
            b.pack()

    def _section(self, key, text, count, folded, c, sort=False, icon=None):
        """A part's head: ▾ / ▸ and its name (click: fold / unfold); the memos' head also
        has the sort switch on the right (click: by date ↔ as added). ``icon`` stands before
        the name (the pinned part: a pin and "2 / 5")."""
        px = self.app.px
        row = tk.Frame(self.area.inner, bg=c.bg, bd=0, cursor="hand2")
        row.pack(fill="x", padx=(px(10), px(12)), pady=(px(2), px(3)))
        chevron = tk.Label(row, bg=c.bg, bd=0)
        chevron.pack(side="left", padx=(0, px(3)))
        glyph = GLYPH["unfold" if folded else "fold"]
        pic = None
        if icon:
            pic = tk.Label(row, bg=c.bg, bd=0)
            pic.pack(side="left", padx=(0, px(3)))
        label = tk.Label(row, text=tr("folded_count", head=text, n=count) if folded and not icon else text,
                         bg=c.bg, fg=c.muted, anchor="w", font=(UI_FONT, 8), bd=0)
        label.pack(side="left")
        parts = (row, chevron, label) + ((pic,) if pic else ())

        def tint(fg):
            label.configure(fg=fg)
            paint_glyph(self.app, chevron, glyph, fg, box=SECTION_ICON_BOX)
            if pic:
                paint_glyph(self.app, pic, icon, fg, box=SECTION_ICON_BOX + 1)
        tint(c.muted)
        for w in parts:
            w.bind("<ButtonRelease-1>", lambda e, k=key: self.app.toggle_list_section(k))
            w.bind("<Enter>", lambda e: tint(c.fg))
            w.bind("<Leave>", lambda e: tint(c.muted))
        Tooltip(label, tr("tip_section"))
        self.sections[key] = row
        if not sort:
            return
        prefs = self.app.prefs
        switch = tk.Frame(row, bg=c.bg, bd=0, cursor="hand2")
        switch.pack(side="right")
        word = tk.Label(switch, text=tr(f"sort_{prefs.list_sort}_{'old' if prefs.list_oldest else 'new'}"),
                        bg=c.bg, fg=c.muted, font=(UI_FONT, 8), bd=0)
        word.pack(side="left")
        icon = tk.Label(switch, bg=c.bg, bd=0)
        icon.pack(side="left", padx=(px(3), 0))

        def tint_switch(fg):
            word.configure(fg=fg)
            paint_glyph(self.app, icon, GLYPH["sort"], fg, box=SECTION_ICON_BOX)
        tint_switch(c.muted)

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
            w.bind("<Leave>", lambda e: tint_switch(c.muted))
        Tooltip(word, tr("tip_sort"))
        self.sort_switch = word

    def _card(self, note: Note):
        px = self.app.px
        c = Colors.of(self.frame, note.color)
        current = note is self.nw.note
        shown_elsewhere = (w := self.app.window_for(note.id)) is not None and w is not self.nw
        width = max(px(120), (self._width or self.nw.pad.width) - px(24))
        # each card is a small copy of a note: a strip in the note's top bar color over its page.
        # The current memo's strip is a step darker; the card under the mouse lights a step.
        rest, lit = c.bg, shade(self.frame, c.bg, 1)
        head_rest = shade(self.frame, c.bar, 1) if current else c.bar
        head_lit = shade(self.frame, head_rest, 1)
        meta = readable(self.frame, c.muted, head_lit, MARK_CONTRAST)      # date and icons on the strip

        outer = tk.Frame(self.area.inner, bg=_mix(self.frame, note.color, c.fg, 0.3 if current else 0.22), bd=0)
        outer.pack(fill="x", padx=px(10), pady=(0, px(8)))
        card = tk.Frame(outer, bg=c.bg, bd=0)
        card.pack(fill="both", expand=True, padx=1, pady=1)
        self.cards[note.id] = (outer, card)

        top = tk.Frame(card, bg=head_rest)
        top.pack(fill="x")
        heads = [top]
        date_lbl = tk.Label(top, text=_span_label(note), bg=head_rest, fg=meta, font=(UI_FONT, 8))
        date_lbl.pack(side="right", padx=(0, px(8)), pady=px(3))
        heads.append(date_lbl)
        if shown_elsewhere:                 # a window icon (the words in its tooltip)
            there = tk.Label(top, bg=head_rest, bd=0)
            paint_glyph(self.app, there, GLYPH["open_window"], meta)
            there.pack(side="left", padx=(px(8), 0))
            Tooltip(there, tr("open_elsewhere"))
            heads.append(there)
        elif current:
            heads.append(tk.Label(top, text=tr("current"), bg=head_rest, fg=c.fg, font=(UI_FONT, 8)))
            heads[-1].pack(side="left", padx=(px(8), 0))
        for w in heads:
            w.keep_bg = True                # the strip lights on its own (hover)

        tk.Frame(card, bg=c.bg, height=px(4)).pack(fill="x")
        self.card_preview(card, note, c, width)
        tk.Frame(card, bg=c.bg, height=px(8)).pack(fill="x")

        def paint(widget, bg):
            if widget.winfo_class() in ("Frame", "Label") and not getattr(widget, "keep_bg", False):
                widget.configure(bg=bg)
            for child in widget.winfo_children():
                paint(child, bg)

        def paint_head(on):
            for w in heads:
                w.configure(bg=head_lit if on else head_rest)

        def hover(on):
            paint_head(on or self._picked == note.id)
            paint(card, lit if on or self._picked == note.id else rest)
            if on:
                self._rest_on(note, outer)
            else:
                self._left_card()

        def leave(event):
            under = outer.winfo_containing(event.x_root, event.y_root)
            if under is None or not str(under).startswith(str(outer)):
                hover(False)

        _bind_tree(outer, "<ButtonRelease-1>", lambda e, n=note: self.nw.open_note(n))
        _bind_tree(outer, "<Button-3>", lambda e, n=note: self._card_menu(e, n))
        _bind_tree(outer, "<Enter>", lambda e: hover(True))
        _bind_tree(outer, "<Leave>", leave)
        for w in [outer, *outer.winfo_children()]:
            w.configure(cursor="hand2")

        # made after the card's click binding, so clicking the bin does not open the memo
        trash = tk.Label(top, bg=head_rest, cursor="hand2", padx=px(2), bd=0)
        trash.keep_bg = True
        heads.append(trash)
        paint_glyph(self.app, trash, GLYPH["trash"], meta)
        trash.pack(side="right", padx=(0, px(6)), before=date_lbl)
        date_lbl.pack_configure(padx=(0, px(4)))
        danger = readable(self.frame, c.danger, head_lit, MARK_CONTRAST)
        trash.bind("<Enter>", lambda e: paint_glyph(self.app, trash, GLYPH["trash"], danger))
        trash.bind("<Leave>", lambda e: paint_glyph(self.app, trash, GLYPH["trash"], meta))
        trash.bind("<ButtonRelease-1>", lambda e, n=note: self.nw.trash_note(n))
        Tooltip(trash, tr("tip_card_trash"))
        self.bin_icons[outer] = trash

        glyph = GLYPH["pinned" if note.pinned else "pin"]
        pin = tk.Label(top, bg=head_rest, cursor="hand2", padx=px(2), bd=0)
        pin.keep_bg = True
        heads.append(pin)
        paint_glyph(self.app, pin, glyph, c.fg if note.pinned else meta)
        if self.app.prefs.pin_limit or note.pinned:
            pin.pack(side="right", padx=(px(4), px(4)), before=date_lbl)
        pin.bind("<ButtonRelease-1>", lambda e, n=note: self.toggle_pin(n))
        pin.bind("<Enter>", lambda e: paint_glyph(self.app, pin, glyph, c.fg))
        pin.bind("<Leave>", lambda e: paint_glyph(self.app, pin, glyph, c.fg if note.pinned else meta))
        Tooltip(pin, tr("tip_card_unpin" if note.pinned else "tip_card_pin"))
        self.pin_icons[note.id] = pin
        paint(card, rest)
        line = outer.cget("bg")

        def picked(on):                 # picked with the arrow keys: lit, with a dark outline
            paint_head(on)
            paint(card, lit if on else rest)
            outer.configure(bg=c.fg if on else line)
        self._painters[note.id] = picked

    # -- keyboard
    def shown_ids(self) -> list[str]:
        """The memo cards on the page now, top to bottom (not those in a folded part)."""
        return [i for i in self._order if i in self.cards]

    def step_pick(self, delta):
        ids = self.shown_ids()
        if delta > 0 and ids and self._picked == ids[-1] and self._build_more():
            ids = self.shown_ids()              # walked past the last card made: make more
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
        if note_id in self._painters:
            self._painters[note_id](True)
            self.area.show(self.cards[note_id][0])

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
        self._more_if_near_end()

    def card_preview(self, card, note, c, width):
        """Header, pictures and the first lines of a memo, inside a card."""
        px = self.app.px
        headed = note.style == "header" and note.header.strip()
        if headed:
            tk.Label(card, text=note.header.strip(), bg=c.bg, fg=c.fg, anchor="w", justify="left",
                     wraplength=width, font=(note.font_family, 10, "bold")).pack(fill="x", padx=px(8))
        if note.style == "image" and note.images:
            self._pictures(card, note, c, width)
        lines = note.preview_lines(4)
        if lines and not headed:            # no header: the first line reads as the title
            tk.Label(card, text=lines.pop(0), bg=c.bg, fg=c.fg, anchor="w", justify="left",
                     wraplength=width, font=(note.font_family, 10, "bold")).pack(fill="x", padx=px(8))
            lines = lines[:3]
        if lines:
            tk.Label(card, text="\n".join(lines), bg=c.bg, fg=c.fg, anchor="w", justify="left",
                     wraplength=width, font=(note.font_family, 9)).pack(fill="x", padx=px(8), pady=(px(2), 0))
        query = self.search.get().strip()
        if query:
            self._match_line(card, note, c, query, width)

    def _match_line(self, card, note, c, query, width):
        """Searching: the line where the words were found, the found part marked like a
        highlighter, so it is clear why the memo is in the results."""
        px = self.app.px
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
        row = tk.Frame(card, bg=c.bg, bd=0)
        row.pack(fill="x", padx=px(8), pady=(px(3), 0))
        mark = _mix(self.frame, c.bg, "#FFD233", 0.75)      # a yellow highlighter on the memo's color
        for text, bg, weight in ((before, c.bg, "normal"), (hit, mark, "bold"), (after, c.bg, "normal")):
            if text:
                lbl = tk.Label(row, text=text, bg=bg, fg=c.fg, bd=0, padx=0, font=(note.font_family, 9, weight))
                lbl.pack(side="left")
                lbl.keep_bg = bg is mark            # the highlighter stays when the card is lit

    def _pictures(self, card, note, c, width):
        """One picture fills the card's width; several sit side by side, then "+N"."""
        px = self.app.px
        row = tk.Frame(card, bg=c.bg)
        row.pack(fill="x", padx=px(8), pady=(px(2), 0))
        box = (width, px(70)) if len(note.images) == 1 else (px(64), px(52))
        used = 0
        for i, name in enumerate(note.images):
            thumb = self._thumb(name, box)
            if thumb is None:
                continue
            if used and used + thumb.width() > width:
                tk.Label(row, text=f"+{len(note.images) - i}", bg=c.bg, fg=c.muted,
                         font=(UI_BOLD, 9, "bold")).pack(side="left", padx=px(2))
                break
            tk.Label(row, image=thumb, bg=c.bg, bd=0).pack(side="left", padx=(0, px(4)))
            used += thumb.width() + px(4)

    def _thumb(self, name, box):
        photo = self.app.picture(name, box)
        if photo is not None:
            self._shown.append(photo)       # keep it while a card shows it
        return photo

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
        self.frame.after_idle(self._more_if_near_end)      # shown (or taller): fill the screen
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
        self.area.recolor(c.bg)


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
        self.counter = tk.Label(top, anchor="w", font=(UI_FONT, 8), padx=px(10), pady=px(3), bd=0)
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
            self.counter.configure(text=counter, bg=c.bar, fg=c.muted)
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
    ("grp_place", ("set_snap", "set_auto_layout", "set_minimize")),
    ("grp_general", ("set_language", "set_date_format", "set_pin_limit", "set_bin_days")),
)
SETTING_HELP = {
    "set_color": "help_color", "set_font": "help_font", "set_default_color": "help_default_color",
    "set_theme_color": "help_theme_color", "set_cursor": "help_cursor", "set_transparency": "help_transparency",
    "set_snap": "help_snap", "set_auto_layout": "help_auto_layout", "set_minimize": "tip_minimize_style",
    "set_language": "help_language", "set_date_format": "help_date_format", "set_pin_limit": "help_pin_limit",
    "set_bin_days": "help_bin_days",
}
SETTING_COLORS = {"set_color": "memo", "set_default_color": "default", "set_theme_color": "theme"}
SETTING_SLIDE_MS = anim.LONG     # a setting's page slides in over the list
SETTING_SLIDE_BACK = 0.28        # ... and the list steps back this much of its width


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
        self.pages: dict = {}                   # key -> its page in detail_area
        self.list_rows: dict = {}               # key -> (row, name, value, dot, chevron)
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

        body = page("set_cursor")
        row = tk.Frame(body, bd=0)
        row.pack(fill="x", **pad)
        self.rows.append(row)
        self.cursor_buttons = {}
        for mode in ("opposite", "text"):
            b = FlatButton(row, tr(f"cursor_{mode}"), lambda m=mode: self.app.set_cursor_mode(m))
            b.pack(side="left", padx=(0, px(6)))
            self.cursor_buttons[mode] = b
            self.flat.append(b)

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

        body = page("set_language")
        row = tk.Frame(body, bd=0)
        row.pack(fill="x", **pad)
        self.rows.append(row)
        self.lang_buttons = {}
        for code, name in texts.LANGUAGES:      # each name in its own language
            b = FlatButton(row, name, lambda c=code: self._choose_language(c))
            b.pack(side="left", padx=(0, px(6)))
            self.lang_buttons[code] = b
            self.flat.append(b)

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

        body = page("set_auto_layout")
        row = tk.Frame(body, bd=0)
        row.pack(fill="x", **pad)
        self.rows.append(row)
        self.auto_buttons = {}
        for on in (False, True):
            b = FlatButton(row, tr("auto_on" if on else "auto_off"), lambda v=on: self.app.set_auto_layout(v))
            b.pack(side="left", padx=(0, px(4)))
            self.auto_buttons[on] = b
            self.flat.append(b)

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

        body = page("set_bin_days")
        row = tk.Frame(body, bd=0)
        row.pack(fill="x", **pad)
        self.rows.append(row)
        self.bin_buttons = {}
        for days in BIN_DAY_CHOICES:
            b = FlatButton(row, tr("bin_day_choice", n=days), lambda d=days: self.app.set_bin_days(d))
            b.pack(side="left", padx=(0, px(4)))
            self.bin_buttons[days] = b
            self.flat.append(b)

        # under each setting's controls: what it does, in words (the tooltips of the old long page)
        for key, p in self.pages.items():
            words = tk.Label(p, text=tr(SETTING_HELP[key]), font=(UI_FONT, 9), anchor="w", justify="left")
            words.pack(fill="x", pady=(px(12), px(16)), **pad)
            words.bind("<Configure>", lambda e, w=words: w.configure(wraplength=max(px(120), e.width)))
            self.muted.append(words)

        # ---- the list: a row per setting with its value now, in four groups
        body = self.list_area.inner
        for group, keys in SETTING_GROUPS:
            cap = tk.Label(body, text=tr(group), font=(UI_FONT, 8), anchor="w")
            cap.pack(fill="x", pady=(px(12), 0), **pad)
            self.muted.append(cap)
            for key in keys:
                self._list_row(body, key, pad)

        row = tk.Frame(body, bd=0)
        row.pack(fill="x", pady=(px(16), 0), **pad)
        self.rows.append(row)
        export = FlatButton(row, tr("set_export"), self._export)
        export.pack(side="left")
        Tooltip(export, tr("tip_backups"))
        self.flat.append(export)

        self.rule = tk.Frame(body, height=1, bd=0)
        self.rule.pack(fill="x", pady=px(12), **pad)
        delete = FlatButton(body, tr("set_trash"), self._delete, danger=True)
        delete.pack(anchor="w", pady=(0, px(14)), **pad)
        self.flat.append(delete)

    # -- the list and opening one setting
    def _list_row(self, body, key, pad):
        px = self.app.px
        row = tk.Frame(body, bd=0, cursor="hand2")
        row.pack(fill="x", **pad)
        name = tk.Label(row, text=tr(key).split(" (")[0] if key != "set_language" else tr(key),
                        font=(UI_FONT, 9), anchor="w", cursor="hand2")
        name.pack(side="left", pady=px(8))
        chevron = tk.Label(row, bd=0, cursor="hand2")
        chevron.pack(side="right", padx=(px(4), 0))
        value = tk.Label(row, font=(UI_FONT, 8), anchor="e", cursor="hand2")
        value.pack(side="right")
        dot = None
        if key in SETTING_COLORS:
            dot = tk.Canvas(row, width=px(11), height=px(11), bd=0, highlightthickness=0, cursor="hand2")
            dot.pack(side="right", padx=(0, px(5)))
        line = tk.Frame(body, height=1, bd=0)
        line.pack(fill="x", **pad)
        self.lines.append(line)
        self.list_rows[key] = (row, name, value, dot, chevron)
        parts = [w for w in (row, name, value, dot, chevron) if w is not None]

        def hover(on):
            c = self.nw.colors
            for w in parts:
                w.configure(bg=c.hover if on else c.bg)
        for w in parts:
            w.bind("<Enter>", lambda e: hover(True))
            w.bind("<Leave>", lambda e: hover(row.winfo_containing(e.x_root, e.y_root) in parts))
            w.bind("<ButtonRelease-1>", lambda e, k=key: self.open(k))

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
            "set_language": lambda: dict(texts.LANGUAGES).get(texts.language(), ""),
            "set_date_format": lambda: texts.day_label(date.today(), texts.date_format()),
            "set_pin_limit": lambda: str(prefs.pin_limit),
            "set_bin_days": lambda: tr("bin_day_choice", n=prefs.bin_days),
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
            if dot is not None:
                color = self._shown_color(SETTING_COLORS[key])
                size = int(dot.cget("width"))
                dot.delete("all")
                dot.create_rectangle(0, 0, size - 1, size - 1, fill=color,
                                     outline=Colors.of(dot, color, solid=True).border)

    def open(self, key):
        """One setting's page slides in from the right over the list, which steps back a little."""
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
        words = tk.Label(warn, font=(UI_FONT, 8), anchor="w", justify="left")
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
        """A dashed square; the next one to fill has a + in it."""
        c = self.nw.colors
        cv.delete("all")
        size = int(cv.cget("width"))
        cv.create_rectangle(1, 1, size - 2, size - 2, outline=c.muted if add else c.border, dash=(2, 2))
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
            for code, b in self.lang_buttons.items():
                chosen = code == texts.language()
                b._bg = c.select if chosen else c.well
                b.configure(bg=b._bg, font=ui_font(9, chosen))
            for fmt, b in self.date_buttons.items():
                chosen = fmt == texts.date_format()
                b._bg = c.select if chosen else c.well
                b.configure(bg=b._bg, font=ui_font(9, chosen))
            prefs = self.app.prefs
            for buttons, now in ((self.snap_buttons, prefs.snap_gap), (self.cursor_buttons, prefs.cursor_color),
                                 (self.bin_buttons, prefs.bin_days), (self.auto_buttons, prefs.auto_layout),
                                 (self.min_buttons, prefs.minimize_style)):
                for value, b in buttons.items():
                    chosen = value == now
                    b._bg = c.select if chosen else c.well
                    b.configure(bg=b._bg, font=ui_font(9, chosen))
            self._sync_rows()
        finally:
            self._syncing = False

    def _draw_swatch(self, cv, color, selected):
        c = Colors.of(cv, color, solid=True)        # the swatch is the color itself, never its pale page
        cv.delete("all")
        size = int(cv.cget("width"))
        cv.create_rectangle(0, 0, size - 1, size - 1, fill=color,
                            outline=c.fg if selected else c.border, width=2 if selected else 1)
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
            lbl.configure(bg=c.bg, fg=c.muted)
        for line in self.lines:
            line.configure(bg=c.line)
        for row, name, value, dot, chevron in self.list_rows.values():
            for w in (row, name, value, chevron, dot):
                if w is not None:
                    w.configure(bg=c.bg)
            name.configure(fg=c.fg)
            value.configure(fg=c.muted)
            paint_glyph(self.app, chevron, GLYPH["unfold"], c.muted, box=SECTION_ICON_BOX)
        for b in self.flat:
            b.recolor(c)
        for basic, custom in self.palettes.values():
            for cv in [cv for cv, _ in basic] + custom:
                cv.configure(bg=c.bg)
        for _warn, words, *_rest in self.warnings.values():
            words.configure(bg=c.bg, fg=c.muted)
        self.alpha_unit.configure(bg=c.bg, fg=c.muted)
        self.snap_unit.configure(bg=c.bg, fg=c.muted)
        self.alpha.recolor(c)
        for box in (self.alpha_box, self.size_box, self.pin_box):
            box.recolor(c)
        self.font_picker.recolor(c)
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
                             font=(UI_FONT, 8), anchor="w")
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
        meta = readable(self.frame, c.muted, c.bar, MARK_CONTRAST)     # on the strip, as in the list
        top = tk.Frame(card, bg=c.bar)
        top.pack(fill="x")
        left = tk.Label(top, text=self.time_left(note), bg=c.bar, fg=c.fg, font=(UI_FONT, 8))
        left.pack(side="left", padx=(px(8), 0), pady=px(3))
        self.notices[note.id] = left
        tk.Label(top, text=_span_label(note), bg=c.bar, fg=meta,
                 font=(UI_FONT, 8)).pack(side="right", padx=(0, px(8)))
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
        self.info.configure(bg=c.bg, fg=c.muted)
        _danger_icon(self.empty_btn, c)
        self.area.recolor(c.bg)


def _danger_icon(button, c):
    """An icon button for deleting: drawn in the red of the colors ``c``."""
    button.recolor(c)
    button._fg = button.ink_color = c.danger
    button._draw()


# every name (underscored ones too) goes on to the next part: see app.py
__all__ = [_n for _n in list(globals()) if not _n.startswith("__")]
