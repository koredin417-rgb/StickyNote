"""The notes and their windows: opened, closed, reopened, binned, pinned; which window shows which memo; the calendar's note. (Part of App: see app.py.)"""
from __future__ import annotations


import calendar as _calendar
import colorsys
import gc
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

import calgeom
import geom
import grid
import holidays
import space
import store as _store
import texts
import anim
import gc
import perf
import winapi
from geom import Box, Screen
from icon import draw_icon
from links import Links, links_from_touching
from motion import Motion, Outlines
from shots import ShotCache
from waker import Waker
from store import (BIN_DAY_CHOICES, CURSOR_COLORS, CUSTOM_COLORS, EMPTY_TITLE, INLINE, LIST_SORTS, MARK_KINDS,
                   PIN_LIMIT_MAX, SNAP_GAPS, SOLID_COLORS, STYLES, TIDY_ORDERS, Note, NoteStore, Pad, Prefs)
from texts import tr
from ui_note import *  # noqa: F401,F403  (all parts of the UI: ui_common … ui_note)


# --------------------------------------------------------------------------- app
from appbase import *  # noqa: F401,F403


class RegistryMixin:
    def window_for(self, note_id):
        return next((w for w in self.windows.values() if w.note.id == note_id), None)

    def _latest_unshown(self):
        free = [n for n in self.notes.values() if not n.deleted and self.window_for(n.id) is None]
        return max(free, key=lambda n: n.modified, default=None)

    def _place(self, pad: Pad):
        """Give a window a position if it has none: the free spot nearest the main screen's
        centre, else P5 (N2, find_spot). A saved spot is left to the start-up steps (return_note):
        only the minimum size is enforced here."""
        pad.width, pad.height = max(pad.width, self.px(MIN_W)), max(pad.height, self.px(MIN_H))
        if pad.x is None or pad.y is None:
            a = self.usable()[0]                    # the main screen (screens() lists it first)
            origin = ((a[0] + a[2] - pad.width) // 2, (a[1] + a[3] - _shown_h(pad)) // 2)
            self.take_spot(pad, *self.find_spot(pad.width, _shown_h(pad), origin, exclude=(pad.id,)))

    def _open(self, pad: Pad, note: Note, fade_in=False) -> NoteWindow:
        pad.note_id = note.id
        pad.transparency = self.prefs.transparency     # one transparency for every note
        self._place(pad)
        nw = self.windows[pad.id] = NoteWindow(self, pad, note, fade_in=fade_in)
        self.space_changed()                        # it takes up space now
        self.close_tips()
        return nw

    def close_tips(self):
        """The × says when closing a note closes the app: the last note (Q7)."""
        last = len(self.windows) <= 1
        for w in self.windows.values():
            b = getattr(w, "btn_close", None)
            if b is not None:
                b.tooltip.text = tr("tip_close_last" if last else "tip_close")

    # ---- memos -------------------------------------------------------------------------
    def add_note(self, note: Note) -> Note:
        self.notes[note.id] = note
        return note

    def blank_note(self, template: Note | None = None, date: str | None = None) -> Note:
        """A new empty memo in the layout chosen last, looking like ``template``."""
        style = self.prefs.last_style
        note = Note.like(template, date=date, style=style) if template else Note(style=style, date=date)
        note.color = self.prefs.default_color or note.color
        return self.add_note(note)

    def export_text(self, path, from_window: NoteWindow | None = None) -> int:
        """Every memo as plain text in one file."""
        self.save_now()
        try:
            n = self.store.export_text(list(self.notes.values()), path, picture_word=tr("export_picture"))
        except OSError as exc:
            self._log(f"export failed: {exc!r}")
            if from_window is not None:
                from_window.show_notice(tr("export_failed"))
            return 0
        if from_window is not None:
            from_window.show_notice(tr("export_done", n=n))
        return n

    def _remove_images(self, note: Note):
        for name in note.images + note.all_inline:
            self.store.remove_image(name)

    def discard_note(self, note: Note):
        """Forget a memo nobody is looking at (used for blank memos)."""
        if note.id in self.notes and self.window_for(note.id) is None:
            del self.notes[note.id]
            self._remove_images(note)

    def trash_note(self, note_id) -> bool:
        """Move a memo to the bin. A window showing it switches to another memo."""
        note = self.notes.get(note_id)
        if note is None or note.deleted:
            return False
        shown_in = self.window_for(note_id)
        if shown_in is not None:
            shown_in.sync_from_widgets()
        if note.is_empty:                           # nothing worth keeping in the bin
            return False
        note.deleted = datetime.now().isoformat(timespec="microseconds")
        note.pinned = None
        if shown_in is not None:
            shown_in._load_note(self._latest_unshown() or self.blank_note(note))
        self.refresh_lists()
        self.save_soon()                            # (after the card's flight to the bin)
        return True

    def trash_notes(self, ids) -> list[str]:
        """Move several memos to the bin at once (the list's select mode): the ids that went. One
        list refresh and one save for the lot; windows showing one switch to another memo."""
        gone, now = [], datetime.now().isoformat(timespec="microseconds")
        for note_id in ids:
            note = self.notes.get(note_id)
            if note is None or note.deleted:
                continue
            shown_in = self.window_for(note_id)
            if shown_in is not None:
                shown_in.sync_from_widgets()
            if note.is_empty:
                continue
            note.deleted, note.pinned = now, None
            gone.append(note_id)
            if shown_in is not None:
                shown_in._load_note(self._latest_unshown() or self.blank_note(note))
        if gone:
            self.refresh_lists()
            self.save_soon()
        return gone

    def restore_notes(self, ids):
        """Undo of trash_notes: every one back, one refresh."""
        back = False
        for note_id in ids:
            note = self.notes.get(note_id)
            if note is not None and note.deleted:
                note.deleted, back = None, True
        if back:
            self.refresh_lists()
            self.save_soon()

    def restore_note(self, note_id) -> Note | None:
        note = self.notes.get(note_id)
        if note is None or not note.deleted:
            return None
        note.deleted = None
        self.refresh_lists()
        self.save_soon()
        return note

    def delete_forever(self, note_id):
        note = self.notes.get(note_id)
        if note is None or not note.deleted:
            return
        del self.notes[note_id]
        self._remove_images(note)
        self.refresh_lists()
        self.request_save()                 # (only the notes dict changed: no attribute set)
        self.save_now()

    def empty_bin(self):
        for note in [n for n in self.notes.values() if n.deleted]:
            del self.notes[note.id]
            self._remove_images(note)
        self.refresh_lists()
        self.request_save()                 # (only the notes dict changed: no attribute set)
        self.save_now()

    def purge_bin(self) -> bool:
        """Delete for good what has been in the bin longer than BIN_DAYS. True if anything went."""
        limit = datetime.now() - timedelta(days=BIN_DAYS)
        gone = False
        for note in [n for n in self.notes.values() if n.deleted]:
            try:
                expired = datetime.fromisoformat(note.deleted) < limit
            except (TypeError, ValueError):
                expired = False
            if expired:
                del self.notes[note.id]
                self._remove_images(note)
                gone = True
        return gone

    # ---- windows ----------------------------------------------------------------------
    def new_window(self, from_window: NoteWindow | None = None, note: Note | None = None) -> NoteWindow:
        if note is None:
            note = self.blank_note(from_window.note if from_window else None)
        pad = Pad.like(from_window.pad, note.id) if from_window else Pad(note_id=note.id)
        if self.prefs.note_size:            # "Use this size for new notes"
            pad.width, pad.height = self.prefs.note_size
        tiling = self.prefs.auto_layout and from_window is not None
        if from_window is not None and not tiling:  # N2: under the note it came from, else the next column
            parent, size, gap = _pad_box(from_window.pad), (pad.width, pad.height), self._gap()
            own = self.area_of(parent)              # first: column_spot takes areas[0] when none holds the parent
            areas = [own] + [a for a in self.usable() if a != own]
            obstacles = [s.box for s in self.space()]
            spot = space.column_spot(parent, size, areas, obstacles, gap)
            if spot is not None and spot[0] == parent[0] and spot[1] > parent[3] + gap:
                # something sits right under the parent (its calendar): the next column, beside it
                block = (parent[0], parent[3], parent[0] + size[0], max(own[3], spot[3]))
                spot = space.column_spot(parent, size, areas, obstacles + [block], gap) or spot
            if spot is None:                        # no column has room: the nearest free spot, else P5
                self.take_spot(pad, *self.find_spot(*size, (parent[0], parent[3] + gap)))
            else:
                self.take_spot(pad, spot, "free")
            if not pad.stacked:                     # the magnet, stronger: into the slot it is near
                box = (pad.x, pad.y, pad.x + pad.width, pad.y + _shown_h(pad))
                sx, sy, sid = self.snap(box, set(), reach=max(self.px(SNAP_REACH),
                                                              round(min(size) * NEW_SNAP_PULL)))
                if sid is not None:
                    pad.x, pad.y = sx, sy
        elif tiling:                    # auto layout: it starts at its note, then takes its tile
            pad.x, pad.y = from_window.pad.x, from_window.pad.y + 1
            parent_pad = from_window.pad            # L4: a new note goes after its parent in the tile order
            if parent_pad.order is not None and not parent_pad.free:
                for w in self.windows.values():
                    if w.pad.order is not None and w.pad.order > parent_pad.order:
                        w.pad.order += 1
                pad.order = parent_pad.order + 1
        nw = self._open(pad, note, fade_in=True)
        nw.show()                       # on top: it keeps the pin (always on top) of the note it came from
        if from_window is not None and not tiling:      # M2: a new note is linked to every note it touches
            slack, reach = self._touch_reach()
            for s in self.space({pad.id}):
                if s.kind != "held" and any(geom.touching(q, _pad_box(pad), reach, slack) for q in (s.parts or (s.box,))):
                    self.link(s.id, pad.id)
        if tiling:
            self.arrange()
        elif from_window is not None and from_window.win.winfo_exists():
            # it slides out from behind the note it was made from to its place, then comes on top
            target, src = (pad.x, pad.y), (from_window.pad.x, from_window.pad.y)
            nw.win.lower(from_window.win)
            nw.glide_to(*target, ms=NEW_SLIDE_MS, start_at=src)
            nw.win.after(NEW_SLIDE_MS + 20, lambda: nw.win.winfo_exists() and nw.win.lift())
        nw.flash()                      # the top bar in the theme color, fading back
        self.save_soon()                # once it has come out (no fsync in its first frames)
        return nw

    def newest_id(self) -> str | None:
        """The pad id of the newest window."""
        return next(reversed(self.windows), None)

    def can_reopen(self) -> bool:
        return any(self._reopenable(p) for p in self._closed)

    def _reopenable(self, pad):
        note = self.notes.get(pad.note_id)
        return note is not None and not note.deleted and not note.is_empty and self.window_for(note.id) is None

    def reopen_closed(self, from_window: NoteWindow | None = None) -> NoteWindow | None:
        """Bring back the note closed last, where it was and as big as it was."""
        while self._closed:
            pad = self._closed.pop()
            if not self._reopenable(pad):
                continue
            self._keep_pads = [p for p in self._keep_pads if p is not pad]
            self._recently_closed = [(t, p) for t, p in self._recently_closed if p is not pad]
            nw = self._open(pad, self.notes[pad.note_id], fade_in=True)
            nw.show()
            self.return_note(nw, "reopen")
            nw.flash()
            self.save_soon()
            return nw
        if from_window is not None:
            from_window.show_notice(tr("nothing_closed"))
        return None

    def unpin_all(self):
        """Take "always on top" off every note."""
        for w in self.windows.values():
            if w.pad.pinned:
                w.pad.pinned = False
                w.apply_look()
        self.request_save()

    def move_note_date(self, note: Note, iso: str):
        """Put a memo on another day of the calendar (dragged in the big month view)."""
        if note.end_date:                   # a period moves as a whole
            shift = date.fromisoformat(iso) - date.fromisoformat(note.date)
            note.end_date = (date.fromisoformat(note.end_date) + shift).isoformat()
        note.date = iso
        self.request_save()
        self.refresh_lists()

    def open_in_new_window(self, note: Note, from_window: NoteWindow):
        other = self.window_for(note.id)
        if other is not None:
            other.show()
            other.show_home()
            return other
        return self.new_window(from_window, note=note)

    def calendar_elsewhere(self, nw):
        """The note (not ``nw``) whose calendar is open, or None."""
        return next((w for w in self.windows.values() if w is not nw and w.calendar is not None), None)

    def calendar_buttons(self):
        """Show the calendar icon only where it may open one (see NoteWindow.toggle_calendar)."""
        for w in self.windows.values():
            if getattr(w, "_built", False):
                w._arrange_chrome()

    def close_window(self, nw: NoteWindow):
        """Close a note window. Closing the last one quits; the windows closed just before it
        (within CLOSE_ALL_S, e.g. the taskbar's "Close all windows") come back at the next
        start, where they were, with the last one."""
        if "sync" in nw._jobs:                      # typed just before (the sync waits for a pause):
            nw.sync_from_widgets()                  # caught up first, so is_empty below is right
        now = time.monotonic()
        if len(self.windows) == 1:                  # last one: quit, remembering where it was
            if nw.note.is_empty:
                del self.notes[nw.note.id]
            self._keep_pads = [pad for t, pad in self._recently_closed
                               if now - t <= CLOSE_ALL_S and pad.note_id in self.notes
                               and not self.notes[pad.note_id].deleted and not self.notes[pad.note_id].is_empty]
            nw.fade_out(self.quit)
            return
        if not nw.note.is_empty:
            self._recently_closed.append((now, nw.pad))
            self._closed.append(nw.pad)             # for "Reopen closed note" (Ctrl+Shift+T)
            del self._closed[:-CLOSED_KEPT]
        del self.windows[nw.pad.id]
        self.close_tips()
        self.forget_links(nw.pad.id)                # (calendar_heir has used them: NoteWindow.close)
        self.space_changed()
        self.calendar_buttons()                   # its calendar goes with it: the others get the icon
        self.arrange_soon()                         # auto layout: the others close up
        if nw.note.is_empty:
            self.discard_note(nw.note)
        else:                                       # "Note closed [Reopen]" where the keyboard goes (Q7)
            shown = [w for w in self._shown_notes() if not w.pad.collapsed]    # (folded: no room for it)
            heir = self.last_note if self.last_note in shown else (shown[-1] if shown else None)
            if heir is not None:
                text = tr("once_close") if self.tip_once("close") else tr("toast_closed")
                heir.show_undo_action(text, lambda h=heir: self.reopen_closed(h), tip=tr("menu_reopen"))
        self.save_soon()                            # once it has faded out

        def gone():                                 # the keyboard to a note still shown first: Windows
            self.note_minimized(nw)                 # would hand it to the proxy (read as a taskbar click)
            nw.destroy()
            self._minimized_at = time.monotonic()
            self.clock.idle(gc.collect)             # (its widgets are a cycle: freed now the app is quiet)
        nw.fade_out(gone)                           # fades out, then goes

    def pin_note(self, note: Note) -> bool:
        """Pin a memo to the top of the list. False when Settings' limit is reached."""
        if note.pinned:
            return True
        pinned = [n.pinned for n in self.notes.values() if n.pinned and not n.deleted]
        if len(pinned) >= self.prefs.pin_limit:
            return False
        stamp = datetime.now().isoformat(timespec="microseconds")
        note.pinned = max(stamp, max(pinned, default="") + "0")     # always after the last one
        self.request_save()
        return True

    def unpin_note(self, note: Note):
        note.pinned = None
        self.request_save()

    def calendar_heir(self, nw):
        """The note that takes ``nw``'s docked calendar when ``nw`` closes or is minimized:
        the nearest other note of its link group touching the calendar. None: the calendar
        closes with it."""
        cal = nw.calendar
        if cal is None or not cal.top.winfo_ismapped():
            return None
        cb = cal.box()
        ids = (self.group_of(nw.pad.id) if cal.docked else self.group_of(CAL)) - {nw.pad.id, CAL}
        near = self.group_windows(nw.pad.id, ids)           # (linked: they need not touch the calendar)
        return min(near, key=lambda w: (space._apart(cb, _pad_box(w.pad)), abs(w.pad.y - cb[1])), default=None)

    def calendar(self):
        """The one open calendar (there is one at a time), or None."""
        return self._open_calendar()

    def _open_calendar(self):
        """The open calendar (one at a time), or None."""
        return next((w.calendar for w in self.windows.values() if w.calendar is not None), None)

    def picture(self, name, box):
        """Memo picture ``name`` shrunk into ``box``, shared by the list cards, the thumbnail
        strip and the preview, so a picture file is not decoded again each time. Whoever
        shows it keeps its own reference too (old ones drop out of this cache)."""
        key = (name, tuple(box))
        if key in self._pictures:
            self._pictures.move_to_end(key)
            return self._pictures[key]
        photo = _picture_photo(self, name, box, self.root)
        if photo is None:
            return None
        self._pictures[key] = photo
        self._picture_bytes = getattr(self, "_picture_bytes", 0) + photo.width() * photo.height() * 4
        while self._picture_bytes > PICTURE_BUDGET and len(self._pictures) > 1:     # by bytes, oldest first
            _old, gone = self._pictures.popitem(last=False)
            self._picture_bytes -= gone.width() * gone.height() * 4
        return photo

    def refresh_lists(self):
        for w in self.windows.values():
            if not w.win.winfo_exists():    # destroyed but still listed: see save_now
                continue
            w.update_period_band()
            if w.view == "list":
                w.list_view.refresh()
            elif w.view == "bin":
                w.bin_view.refresh()
            if w.calendar:
                w.calendar.draw()
