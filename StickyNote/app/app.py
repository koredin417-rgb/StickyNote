"""Sticky Note: minimal sticky notes for Windows, built on tkinter.

Each sticky-note window ("pad") shows one memo at a time and can switch, inside
the same window, between three pages:

    home      the memo itself
    list      every memo as a card (search, filter by calendar day)
    settings  color, transparency, font, memo date, delete

A thin grab strip runs along the top of every page: drag it (or the date) to
move the note.

Top bar on the home page:
    +  new memo   [note+]  new window   list   calendar   — today's date —
    style   pin   gear   minimize   close
Sub pages show  <- back  instead, which returns to the memo.
Under the memo, a format bar as in Windows Sticky Notes: bold, italic, underline,
strikethrough, bullets, picture.
The calendar opens as a small month view docked beside the note; Korean public
holidays are red, and clicking one tells what it is.
Image-style memos hold any number of pictures; the mouse wheel zooms the one shown.
The bin icon moves a memo to the bin (with an Undo bar); the bin keeps it for
BIN_DAYS days. Right-click menus are drawn in the memo's own colors.
"""
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

import calgeom
import calgeom
import geom
import grid
import holidays
import space
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
def _placed(cal) -> bool:
    """The calendar takes up space: it has been placed (target_box) and is not closing."""
    return getattr(cal, "target_box", None) is not None and not getattr(cal, "_closing", False)


def _side_of(note: Box, cal: Box) -> str:
    """Which side of the note's box the docked calendar's box is on: by their facing edges,
    else (overlapping, kept on a crowded screen) by their centres."""
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


QUIT_SIGNAL = "quit.signal"             # the installer asks a running app to close (saved)

class App:
    def __init__(self, folder, root: tk.Tk | None = None, signal_file: Path | None = None,
                 screens: list[Screen] | None = None):
        # tests: these screens stand in for the real monitors (see screens()), from the start
        # what the imports made (modules, classes, constants) lives for good: the collector stops
        # walking it. Done before any window or memo exists: frozen objects are never freed,
        # and a window has to be freed when it closes (NoteWindow._release)
        gc.collect()
        gc.freeze()
        self._fake_screens = list(screens) if screens is not None else None
        self._screens = None                        # the real monitors, read once (screens())
        self.store = NoteStore(folder)
        self.root = root or tk.Tk()
        self.clock = anim.install(self.root)        # the one frame clock every animation runs on
        self.shots = ShotCache(self)                # stand-in pictures of the notes (rolls, covers, fly)
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.root.report_callback_exception = self._report_error
        self.scale = max(1.0, self.root.winfo_fpixels("1i") / 96)
        Tooltip.app = self
        self.ring = GroupRing(self)                 # the line around notes moving together
        self.moving = False                         # a note (group) is being dragged or resized
        self.ring_source = None                     # the note being dragged with its group (see GroupRing)
        self._calendar_shown = None                 # what the calendars showed at the last save
        winapi.load_private_fonts(FONT_DIR)         # before Tk lists the fonts
        families = set(tkfont.families(self.root))
        self._apply_ui_font(families)
        self.icon_font = next((f for f in ICON_FONTS if f in families), "Segoe UI Symbol")
        self.icons = IconPainter(self.root, self.icon_font)
        self._families = None
        # several sizes: Windows takes the nearest for the taskbar (big) and title bars (small)
        self._icons = [ImageTk.PhotoImage(draw_icon(n), master=self.root) for n in (256, 64, 48, 32, 16)]
        self._icon = self._icons[1]
        self.root.iconphoto(True, *self._icons)
        # A click anywhere first finishes a half-typed Korean syllable (see finish_typing).
        self.root.bind_all("<ButtonPress>", self.finish_typing, add="+")
        self.root.bind_class(FINISH_TYPING_TAG, "<ButtonPress>", self.finish_typing)

        self.notes: dict[str, Note] = {}
        self.windows: dict[str, NoteWindow] = {}
        self._space_epoch = 0                       # bumped at every change of what takes up space (space())
        self._space_cache = None                    # (epoch, shapes) of the last space() built
        self.held_room: dict[str, Box] = {}         # pad id -> room a minimized note keeps (C4), see space()
        self._held_cal: dict[str, Box] = {}         # pad id -> the calendar's last box, kept while it is minimized
        # (before the pads: a window's <Configure> asks motion while it is being built)
        self._undo: dict | None = None              # the one Undo on offer (S5): before, anchor id, action, job
        self._chain: dict | None = None             # the plans running now, as one action: first before, label, gen
        self._restoring = False                     # restore_layout is running (its own apply keeps the offer)
        self.motion = Motion(self)                  # every move the app makes by itself (S4): apply()
        self.links = Links()                        # the links between notes (M2), loaded from pad.links below
        self._grid_rows: dict[str, int] = {}        # area key -> the grid's rows at the last re-flow (runtime only)
        self._grid_last: dict = {}                  # area key -> (the last GridPlan, its tile ids in order)
        self._held: set = set()                     # link pairs on hold while auto layout is on (hold_links)
        self.screens_pending = False                # the monitors changed and are not taken in yet
        self._screen_job = None
        self._taken = None                          # (the monitors the app has taken in, their key)
        self._seen = None                           # (what the last poll read, when it first read it)
        self._syscommands: list = []                # what the taskbar asked the notes (hooks only append)
        # the event loop wakes on events, not polls: the hooks, a second launch and the installer ping
        port_file = Path(folder) / "wake.port"      # (each data folder its own: the preview's apart)
        self.waker = Waker(self.root, {"sys": self._drain_syscommands, "screens": self._screens_event,
                                       "day": self._day_event, "show": self._show_all,
                                       "quit": self.quit}, port_file)
        self.waker._connect()                       # (now: a hook's ping must never wait for a connection)
        self.wake_sys = lambda: self.waker.ping("sys")
        self._sys_job = self._thumb_job = None
        self._pictures: OrderedDict = OrderedDict()
        self._recently_closed: list = []        # (time, pad) of notes closed while others stay open
        self._keep_pads: list = []              # those to bring back at the next start
        self._closed: list = []                 # pads of notes closed this session, last one last
        self.prefs = Prefs()
        self.closed = False
        self._dead_logged: set[str] = set()     # destroyed windows save_now found still listed
        self._save_job = self._poll_job = self._day_job = None
        self.signal_file = signal_file
        self._today = date.today()

        data = self.store.load()
        self.prefs = data.prefs
        self.apply_motion()                         # Animations: the user's choice, else Windows' setting
        Colors.keep_solid(self.prefs.solid_colors)      # Settings: strong colors painted solid all the same
        self._load_setup(data.pads)                 # N5: the copies of this screen setup (before any window)
        set_shared("BIN_DAYS", self.prefs.bin_days)     # Settings: how long the bin keeps memos
        use_language(self.prefs.language)
        texts.set_date_format(self.prefs.date_format)
        self.last_note = None                       # the note that had the keyboard last (NoteWindow)
        self.proxy = self._make_taskbar_proxy()     # the app's one taskbar button (before any note shows)
        for note in data.notes:
            self.notes[note.id] = note
        if self.prefs.transparency is None:         # older files: each window had its own; keep the first's
            self.prefs.transparency = data.pads[0].transparency if data.pads else 0
        self.purge_bin()                            # memos in the bin longer than BIN_DAYS
        if self.prefs.default_color is None:        # not chosen yet: keep the look already in use
            kept = [n for n in self.notes.values() if not n.deleted and not n.is_empty]
            latest = max(kept, key=lambda n: n.modified, default=None)
            self.prefs.default_color = latest.color.upper() if latest else PALETTE[0][1]
        if self.prefs.theme_color is None:          # not chosen yet: the calendar keeps the look it had
            first = self.notes.get(data.pads[0].note_id) if data.pads else None
            self.prefs.theme_color = (first.color.upper() if first is not None and not first.deleted
                                      else self.prefs.default_color)
        for pad in data.pads:
            note = self.notes.get(pad.note_id)
            if note is not None and note.deleted:
                note = None
            if note is not None and self.window_for(note.id) is not None:
                continue                           # two windows on one memo: keep the first
            if note is None:                        # its memo is gone: show the latest one instead
                note = self._latest_unshown() or self.blank_note()
            self._open(pad, note)
        if not self.windows:
            note = self._latest_unshown() or self.blank_note()
            self._open(Pad(note_id=note.id), note)
        for note in [n for n in self.notes.values() if n.is_empty]:
            self.discard_note(note)                 # blank memos nobody is looking at
        self._load_links()
        if not self.prefs.links_migrated:
            self.migrate_links()
        if self.prefs.auto_layout:
            self.hold_links(True)
        self._start_up()                            # (every window is in self.windows now)
        self.save_now()
        self._screen_job = self.root.after(SCREEN_POLL_MS, self._poll_screens)    # (a safety net: "screens")
        if not self.prefs.hints_seen:               # once: the controls that are easy to miss
            first = next(iter(self.windows.values()))
            self.root.after(300, lambda: first.win.winfo_exists() and first.show_hints())

        self._day_job = None
        self._arm_day()
        self.arrange_soon()                         # auto layout: tiled from the start
        if signal_file is not None:
            self._clear_signal()
            self._poll_job = self.root.after(SIGNAL_POLL_MS, self._poll_signal)    # (older launchers' files)

    # ---- helpers ---------------------------------------------------------------------
    def _apply_ui_font(self, families):
        """Every UI text uses Pretendard (the memo font is the user's own choice); when it
        can't be loaded the old UI fonts stay."""
        try:
            if texts.UI_FONT_NAME not in families or texts.UI_BOLD_NAME not in families:
                texts.UI_FONTS.update(texts.FALLBACK_UI_FONTS)
                texts.UI_BOLD_FONTS.update(texts.FALLBACK_UI_FONTS)
                set_shared("UI_FONT", texts.UI_FONTS[texts.language()])
                set_shared("UI_BOLD", texts.UI_BOLD_FONTS[texts.language()])
                return
            for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont",
                         "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont"):
                font = tkfont.nametofont(name, root=self.root)
                font.configure(family=texts.UI_BOLD_NAME if font.actual("weight") == "bold" else texts.UI_FONT_NAME)
        except Exception:
            pass

    def finish_typing(self, _event=None):
        """Put the syllable the Korean IME is still putting together into the field
        being typed in, right where it was typed. Tk would drop it when a click moves
        the cursor, switches the page or opens another memo first."""
        try:
            widget = self.root.focus_get()
        except (KeyError, tk.TclError):
            return
        if not isinstance(widget, (tk.Text, tk.Entry)) or str(widget.cget("state")) == "disabled":
            return
        pending = winapi.take_composition(widget.winfo_toplevel().winfo_id())
        if pending:
            widget.insert("insert", pending)
        for w in self.windows.values():
            w.preedit.place_forget()

    def px(self, value):
        return int(round(value * self.scale))

    def screens(self) -> list[Screen]:
        """Every monitor and its work area, the primary one first: a test's fake screens when
        given, else Windows' monitors, read once and kept until check_screens clears them."""
        if self._fake_screens is not None:
            return list(self._fake_screens)
        if self._screens is None:
            found = winapi.monitors()
            if not found:                           # (not on Windows: the one screen Tk sees)
                sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
                found = [((0, 0, sw, sh), (0, 0, sw, sh))]
            self._screens = [Screen(monitor=m, work=w) for m, w in found]
        return list(self._screens)

    def font_families(self):
        if self._families is None:
            self._families = sorted({f for f in tkfont.families(self.root) if not f.startswith("@")},
                                    key=str.casefold)
        return self._families

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
        return nw

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

    def set_default_color(self, color):
        """Color for every new memo from now on (Settings → default color)."""
        self.prefs.default_color = color.upper()
        self.save_now()
        for w in self.windows.values():
            if w.view == "settings":
                w.settings_view.sync()

    def theme_colors(self) -> Colors:
        """Every shade of the main theme color (Settings): the calendars use it."""
        return Colors.of(self.root, self.prefs.theme_color or self.prefs.default_color or PALETTE[0][1])

    def cursor_color(self, bg) -> str:
        """The text cursor on ``bg``: the main theme color's opposite (see opposite_color),
        or the text color if chosen so in Settings."""
        if self.prefs.cursor_color == "text":
            return Colors.of(self.root, bg).fg
        return opposite_color(self.root, self.prefs.theme_color or PALETTE[0][1], bg)

    def set_cursor_mode(self, mode):
        self.prefs.cursor_color = mode if mode in CURSOR_COLORS else CURSOR_COLORS[0]
        self.request_save()
        for w in self.windows.values():
            w.apply_look()

    def apply_motion(self):
        """The clock's mode: the Animations setting, or when none was chosen, Windows' own
        "Show animations" (off there: off here)."""
        self.clock.mode = self.prefs.motion or ("full" if winapi.client_animations_enabled() else "off")

    def set_motion(self, mode):
        """Animations: "full", "reduced" or "off"; None goes back to following Windows."""
        self.prefs.motion = mode if mode in ("full", "reduced", "off") else None
        self.apply_motion()
        self.request_save()
        for w in self.windows.values():
            if w.view == "settings":
                w.settings_view.sync()

    def set_minimize_style(self, style):
        """Minimize folds the note away (back from the taskbar button) or leaves a sticker."""
        self.prefs.minimize_style = style if style in ("fold", "bar", "sticker") else "bar"
        self.request_save()
        for w in self.windows.values():
            if w.view == "settings":
                w.settings_view.sync()

    def set_bin_days(self, days):
        """How long the bin keeps memos (1, 7 or 30 days)."""
        self.prefs.bin_days = days if days in BIN_DAY_CHOICES else 7
        set_shared("BIN_DAYS", self.prefs.bin_days)
        for w in self.windows.values():
            w.list_view._bin_badge()                # its tooltip: the count and the new days
            if w._bin_view is not None:
                w._bin_view.info.configure(text=tr("bin_info", days=BIN_DAYS))
            if w.view == "settings":
                w.settings_view.sync()
        if self.purge_bin():
            self.save_now()
        self.refresh_lists()
        self.request_save()

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

    def set_theme_color(self, color):
        """Main theme color for every note: their calendars, and the text cursor."""
        self.prefs.theme_color = color.upper()
        self.request_save()
        for w in self.windows.values():
            w.apply_look()
            if w.view == "settings":
                w.settings_view.sync()

    def keep_solid_color(self, color, keep=True):
        """Settings: paint the strong ``color`` solid all the same (``keep``), or give it its pale
        page again (see Colors). Every note, calendar and list takes the new look."""
        color = color.upper()
        colors = [c for c in self.prefs.solid_colors if c != color] + ([color] if keep else [])
        self.prefs.solid_colors = colors[-SOLID_COLORS:]
        Colors.keep_solid(self.prefs.solid_colors)
        self.request_save()
        for w in self.windows.values():
            w.apply_look()
            if w.view == "settings":
                w.settings_view.sync()
        self.refresh_lists()

    def toggle_group_drag(self):
        self.prefs.group_drag = not self.prefs.group_drag
        self.request_save()

    def set_list_sort(self, sort):
        self.prefs.list_sort = sort if sort in LIST_SORTS else LIST_SORTS[0]
        self.request_save()
        self.refresh_lists()

    def set_list_oldest(self, oldest):
        self.prefs.list_oldest = bool(oldest)
        self.request_save()
        self.refresh_lists()

    def toggle_list_section(self, section):
        """Fold a part of the list shut, or open it again (every note's list)."""
        folded = self.prefs.list_collapsed
        if section in folded:
            folded.remove(section)
        else:
            folded.append(section)
        self.request_save()
        self.refresh_lists()

    def _sync_settings(self):
        for w in self.windows.values():
            if w.view == "settings":
                w.settings_view.sync()

    def add_custom_color(self, color) -> int | None:
        """One more personal color, after the others. None when all four are taken."""
        colors = self.prefs.custom_colors
        if len(colors) >= CUSTOM_COLORS:
            return None
        colors.append(color.upper())
        self.request_save()
        self._sync_settings()
        return len(colors) - 1

    def replace_custom_color(self, index, color):
        if 0 <= index < len(self.prefs.custom_colors):
            self.prefs.custom_colors[index] = color.upper()
            self.request_save()
            self._sync_settings()

    def remove_custom_color(self, index):
        if 0 <= index < len(self.prefs.custom_colors):
            del self.prefs.custom_colors[index]
            self.request_save()
            self._sync_settings()

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
        self.save_now()
        return True

    def restore_note(self, note_id) -> Note | None:
        note = self.notes.get(note_id)
        if note is None or not note.deleted:
            return None
        note.deleted = None
        self.refresh_lists()
        self.save_now()
        return note

    def delete_forever(self, note_id):
        note = self.notes.get(note_id)
        if note is None or not note.deleted:
            return
        del self.notes[note_id]
        self._remove_images(note)
        self.refresh_lists()
        self.save_now()

    def empty_bin(self):
        for note in [n for n in self.notes.values() if n.deleted]:
            del self.notes[note.id]
            self._remove_images(note)
        self.refresh_lists()
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
        self.save_now()
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
            self.save_now()
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

    def calendar(self):
        """The open calendar (one at a time), or None."""
        return next((w.calendar for w in self.windows.values() if w.calendar is not None), None)

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
        del self.windows[nw.pad.id]
        self.forget_links(nw.pad.id)                # (calendar_heir has used them: NoteWindow.close)
        self.space_changed()
        self.calendar_buttons()                   # its calendar goes with it: the others get the icon
        self.arrange_soon()                         # auto layout: the others close up
        if nw.note.is_empty:
            self.discard_note(nw.note)
        self.save_now()

        def gone():                                 # the keyboard to a note still shown first: Windows
            self.note_minimized(nw)                 # would hand it to the proxy (read as a taskbar click)
            nw.destroy()
            self._minimized_at = time.monotonic()
        nw.fade_out(gone)                           # fades out, then goes

    def set_language(self, code):
        """Switch every note to another language. Each window is rebuilt in place:
        same memo, position, page and calendar."""
        code = code if code in texts.CODES else texts.DEFAULT
        if code == self.prefs.language:
            return
        self.prefs.language = use_language(code)
        self.proxy.title(tr("app_title"))
        PopupMenu.close_current()
        reopen = []
        for pad_id, old in list(self.windows.items()):
            view, day = old.view, old.list_view.day
            old.sync_from_widgets()
            self._minimized_at = time.monotonic()   # (rebuilt windows: the proxy may get the keyboard)
            old.destroy()
            self.space_changed()
            nw = self.windows[pad_id] = NoteWindow(self, old.pad, old.note)     # (built without its calendar)
            self.space_changed()
            if old.pad.calendar:
                reopen.append(nw)
            if view == "list":
                nw.show_list(day=day)
            elif view == "settings":
                nw.show_settings()
            elif view == "bin":
                nw.show_bin()
        for nw in reopen:                           # its calendar again, in place: no push, no give-back
            nw.make_calendar("language")
        if self.prefs.auto_layout:                  # sets the calendar's grid_view again
            self.arrange()
        self.save_now()

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

    def set_pin_limit(self, limit):
        """At most ``limit`` pinned memos; the ones pinned last stay pinned."""
        self.prefs.pin_limit = max(0, min(PIN_LIMIT_MAX, int(limit)))
        pinned = sorted((n for n in self.notes.values() if n.pinned), key=lambda n: n.pinned, reverse=True)
        for note in pinned[self.prefs.pin_limit:]:
            note.pinned = None
        self.refresh_lists()
        self.request_save()

    def set_transparency(self, percent, source=None):
        """See-through percent (0..90) of every note window, its calendar and preview."""
        value = max(0, min(90, int(round(float(percent)))))
        self.prefs.transparency = value
        for w in self.windows.values():
            w.pad.transparency = value
            w._apply_alpha()
            if w is not source and w.view == "settings":    # the other notes' sliders follow
                w.settings_view.alpha.set(value)
                w.settings_view.alpha_box.set(value)
        self.request_save()

    def snap(self, shape_box: Box, exclude: set[str] = frozenset(), parts=None,
             reach: int | None = None) -> tuple[int, int, str | None]:
        """The magnet (M1) for a whole dragged shape (a note, a group, the calendar) at
        ``shape_box``, against space() less the ids in ``exclude`` (the dragged group): next to
        another shape's edge with the gap, and lined up with its edges, when within SNAP_REACH.
        It offers only spots where the whole shape is free (geom.is_free). Returns the snapped
        top-left and the id it snapped to (None: no snap, and the top-left as given). Snapping
        Off: never. ``parts``: the pieces of a group (its notes and calendars, together making
        ``shape_box``): each piece snaps and each must be free, so a group can close around
        another note in its empty corner (the corner is not the group's)."""
        x0, y0 = shape_box[0], shape_box[1]
        if self.prefs.snap_gap is None:
            return x0, y0, None
        gap = self._gap()
        reach = self.px(SNAP_REACH) if reach is None else reach
        pieces = [tuple(p) for p in parts] if parts else [tuple(shape_box)]
        shapes = self.space(exclude)
        obstacles = [b for s in shapes for b in (s.parts or (s.box,))]
        xs, ys = [], []                     # (distance, shift, id, beside): the offers on each axis

        def offer(out, value, now, sid, edge, limit=reach):
            if abs(value - now) <= limit:
                out.append((abs(value - now), value - now, sid, edge))

        def pull(size, near, shared):
            """Line-up reach: touching this shape on the other axis and sharing at least half of
            its own side with it, the edges line up from further (SNAP_ALIGN_PULL)."""
            return max(reach, round(size * SNAP_ALIGN_PULL)) if near and shared >= size / 2 else reach
        for s in shapes:
            if s.kind == "held":            # (room a minimized note keeps: in the way, not snapped to)
                continue
            for ox0, oy0, ox1, oy1 in (s.parts or (s.box,)):
                for px0, py0, px1, py1 in pieces:
                    w, h = px1 - px0, py1 - py0
                    if py0 < oy1 + reach and py1 > oy0 - reach:         # rows overlap: it can sit left / right
                        for v in (ox1 + gap, ox0 - w - gap):
                            offer(xs, v, px0, s.id, True)
                        side = abs(px0 - (ox1 + gap)) <= reach or abs(px1 + gap - ox0) <= reach
                        lim = pull(h, side, min(py1, oy1) - max(py0, oy0))
                        for v in (oy0, oy1 - h):                         # tops / bottoms line up
                            offer(ys, v, py0, s.id, False, lim)
                    if px0 < ox1 + reach and px1 > ox0 - reach:         # columns overlap: above / below
                        for v in (oy1 + gap, oy0 - h - gap):
                            offer(ys, v, py0, s.id, True)
                        side = abs(py0 - (oy1 + gap)) <= reach or abs(py1 + gap - oy0) <= reach
                        lim = pull(w, side, min(px1, ox1) - max(px0, ox0))
                        for v in (ox0, ox1 - w):                         # left / right edges line up
                            offer(xs, v, px0, s.id, False, lim)
        areas = self.usable()
        combos = [(cx, cy) for cx in [None] + sorted(xs) for cy in [None] + sorted(ys) if cx or cy]
        combos.sort(key=lambda c: (-sum(1 for o in c if o), sum(o[0] for o in c if o)))
        seen = set()
        for cx, cy in combos:
            dx, dy = (cx[1] if cx else 0), (cy[1] if cy else 0)
            if (dx, dy) in seen:
                continue
            seen.add((dx, dy))
            if all(geom.is_free((p[0] + dx, p[1] + dy, p[2] + dx, p[3] + dy), areas, obstacles, gap) for p in pieces):
                picks = sorted((o for o in (cx, cy) if o), key=lambda o: (not o[3], o[0]))
                return x0 + dx, y0 + dy, picks[0][2]
        return x0, y0, None

    def hold_snap(self, owner, raw, snapped, sid):
        """The magnet's grip: once snapped, a drag stays there while the pointer is within
        SNAP_HOLD of it (a small wobble of the hand does not pull it off), and lets go past
        that. ``raw``: where the pointer puts it; ``snapped``, ``sid``: App.snap's answer for
        now. The spot held is kept on ``owner`` (the note or calendar being dragged)."""
        reach = self.px(SNAP_HOLD)
        held = list(getattr(owner, "_snap_hold", None) or (None, None))    # per axis: (value, id) or None
        out = list(raw)
        for i in (0, 1):                    # each axis on its own: a snap on one does not undo the other's hold
            if sid is not None and snapped[i] != raw[i]:
                held[i] = (snapped[i], sid)             # snapped on this axis now
            elif held[i] is not None and abs(raw[i] - held[i][0]) > reach:
                held[i] = None                          # pulled past the hold: let go
            if held[i] is not None:
                out[i] = held[i][0]
            elif sid is not None:
                out[i] = snapped[i]
        owner._snap_hold = tuple(held) if any(held) else None
        hid = next((h[1] for h in held if h is not None), sid)
        return out[0], out[1], hid

    def link_drop(self, pids, sid) -> None:
        """A snapped drop (M2): each of ``pids`` (the dragged group) links to every shape it now
        touches, ``sid`` (the shape ``snap`` snapped to) among them. (Only ``sid`` was linked
        before: in a corner several shapes line it up at once, and the one ``snap`` named could
        be a note in the same row that does not touch it, so the drop sometimes linked nothing.)"""
        shapes = {s.id: s for s in self.space()}
        if shapes.get(sid) is None:
            return
        moved = set(pids)
        slack, reach = self._touch_reach()
        for pid in pids:
            s = shapes.get(pid)
            if s is None:
                continue
            for tid, t in shapes.items():
                if tid in moved or t.kind == "held":
                    continue
                if any(geom.touching(p, q, reach, slack) for p in (s.parts or (s.box,)) for q in (t.parts or (t.box,))):
                    self.link(pid, tid)

    # ---- links (M2) ----------------------------------------------------------------------------
    def group_of(self, pid) -> set[str]:
        """The link group ``pid`` is in (it includes ``pid``), whatever the drag switch says."""
        return self.links.group(pid)

    def drag_group(self, pid, alt: bool = False) -> set[str]:
        """What a drag or resize of ``pid`` moves (a fold uses group_of): just ``pid`` with Alt,
        with the "move snapped notes together" switch off, or as a tile in auto layout; else the
        link group (in auto layout without the tiles: they stay in their grid)."""
        if alt or not self.prefs.group_drag:
            return {pid}
        group = self.group_of(pid)
        if self.prefs.auto_layout:
            if self._is_tile(pid):
                return {pid}
            return {g for g in group if not self._is_tile(g)}
        return group

    def group_windows(self, pid, ids=None) -> list[NoteWindow]:
        """The shown notes of ``ids`` (default: the link group of ``pid``), in window order."""
        ids = self.group_of(pid) if ids is None else ids
        return [w for i, w in self.windows.items() if i in ids and not w._closing and w.win.state() == "normal"]

    def _is_tile(self, pid) -> bool:
        """A note auto layout arranges (not pulled out of the tiles)."""
        nw = self.windows.get(pid)
        return nw is not None and not nw.pad.free

    def _touch_reach(self):
        """(slack, reach): the touch test of M2, the same at every gap (snapping Off: 8)."""
        slack = self.px(2)
        return slack, self._gap() + slack

    def link(self, a, b) -> None:
        """Link two notes (or a note and the calendar). Nothing forms with snapping Off, or with
        a tile in auto layout."""
        if a == b or self.prefs.snap_gap is None or self.links.linked(a, b):
            return
        if self.prefs.auto_layout and (self._is_tile(a) or self._is_tile(b)):
            return
        self.links.add(a, b)
        self._mirror_links()
        self.request_save()

    def unlink(self, pid) -> None:
        """Break every link ``pid`` has in the current setup (Detach)."""
        self.links.drop(pid)
        self._mirror_links()
        self.request_save()

    def _mirror_links(self) -> None:
        """pad.links of every note: who it is linked to in the current setup (saved)."""
        for pid, nw in self.windows.items():
            nw.pad.links = sorted(self.links.neighbours(pid))

    def _load_links(self) -> None:
        known = set(self.windows) | {CAL}
        self.links = Links.from_lists({pid: nw.pad.links for pid, nw in self.windows.items()}, known)
        self._mirror_links()

    def settle_links(self) -> None:
        """The end of an action (Motion's end step): links that no longer touch break (M2), over
        the parts of space() and the minimized notes at their pad boxes. Links on hold (auto
        layout) stay."""
        if not self.links.pairs():
            return
        parts = {s.id: list(s.parts or (s.box,)) for s in self.space() if s.kind != "held"}
        for s in self.space():                      # (a minimized note's held room: its note and docked calendar)
            if s.kind == "held" and s.parts and s.id in self.windows:
                parts[s.id] = list(s.parts)
        for pid, nw in self.windows.items():        # (minimized notes: where they were left)
            if pid not in parts and not nw._closing:
                parts[pid] = [_pad_box(nw.pad)]
        held = [p for p in self._held if self.prefs.auto_layout and self.links.linked(*p)]
        for a, b in held:
            self.links.remove(a, b)
        slack, reach = self._touch_reach()
        try:
            gone = self.links.prune_apart(parts, reach, slack)
        finally:
            for a, b in held:
                self.links.add(a, b)
        if gone:
            self._mirror_links()
            self.request_save()

    def forget_links(self, pid) -> None:
        """A note closes (M2): its links go, in the current setup and in every other one."""
        self.links.drop(pid)
        self._held = {p for p in self._held if pid not in p}
        pads = [w.pad for w in self.windows.values()] + self._keep_pads + self._closed + \
               [p for _t, p in self._recently_closed]
        for pad in pads:
            mine = pad.id == pid
            pad.links = [] if mine else [i for i in pad.links if i != pid]
            for entry in pad.setups.values():
                entry["links"] = [] if mine else [i for i in entry.get("links", ()) if i != pid]
        self._mirror_links()
        self.request_save()

    def migrate_links(self) -> None:
        """Once, at the first start after the update: links from what touches now (as today's
        distance-based groups), tiles in auto layout left out (M2)."""
        slack, reach = self._touch_reach()
        parts = {}
        for s in self.space():
            if s.kind in ("note", "pair") and not (self.prefs.auto_layout and self._is_tile(s.id)):
                parts[s.id] = list(s.parts or (s.box,))
        for a, b in links_from_touching(parts, reach, slack).pairs():
            self.links.add(a, b)
        self.prefs.links_migrated = True
        self._mirror_links()
        self.request_save()

    def hold_links(self, on: bool) -> None:
        """Auto layout (L5): on, the links of tiles are put on hold (kept, not pruned); off, they
        come back where the notes still touch and break where not."""
        if on:
            self._held = {p for p in self.links.pairs() if self._is_tile(p[0]) or self._is_tile(p[1])}
        else:
            self._held = set()
            self.settle_links()

    def off_calendars(self, places: dict) -> dict:
        """Notes let go over a docked calendar (not their own): they go beside it, on its
        nearer outer side, as if snapped there; the calendar stays where it is. If neither
        side has room (the screen's edge, other notes) they stay where they were let go.
        ``places``: window -> (x, y) where the drag put it. Returns where they glide to."""
        boxes = {w: (x, y, x + w.pad.width, y + _shown_h(w.pad)) for w, (x, y) in places.items()}
        gap = self._gap()
        area = self.area_of(next(iter(boxes.values())))     # the screen it was let go on
        for owner in self.windows.values():
            cal = owner.calendar
            if owner in places or cal is None or not cal.docked or not cal.top.winfo_ismapped():
                continue
            cb = cal.box()
            if not any(_overlap(cb, b) for b in boxes.values()):
                continue
            gl, gr = min(b[0] for b in boxes.values()), max(b[2] for b in boxes.values())
            to_left, to_right = cb[0] - gap - gr, cb[2] + gap - gl
            order = (to_left, to_right) if (gl + gr) / 2 < (cb[0] + cb[2]) / 2 else (to_right, to_left)
            others = [_pad_box(o.pad) for o in self.windows.values()
                      if o not in places and o.win.state() == "normal"]
            others += [o.calendar.box() for o in self.windows.values() if o not in places and o is not owner
                       and o.calendar is not None and o.calendar.docked and o.calendar.top.winfo_ismapped()]
            for dx in order:
                moved = [(b[0] + dx, b[1], b[2] + dx, b[3]) for b in boxes.values()]
                if all(area[0] <= b[0] and b[2] <= area[2] for b in moved) and \
                        not any(_overlap(b, o) for b in moved for o in others):
                    targets = {w: (b[0] + dx, b[1]) for w, b in boxes.items()}
                    for w, xy in targets.items():
                        w.glide_to(*xy, start_at=places[w])
                    return targets
            return {}
        return {}

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

    def _gap(self):
        return self.px(self.prefs.snap_gap if self.prefs.snap_gap is not None else 8)

    def push_clear(self, ids):
        """A group just let go (``ids``: its notes): any other note it really overlaps (the
        notes, their docked calendar, a calendar that came along) slides out the shortest way,
        staying on its screen. A note only in the empty corner of the group stays."""
        if self.prefs.auto_layout or self.closed:
            return
        members = [self.windows[i] for i in ids if i in self.windows]
        members = [w for w in members if not w._closing and w.win.state() == "normal"]
        if not members:
            return
        blocks = [_pad_box(w.pad) for w in members]
        cal = self._open_calendar()
        if cal is not None and cal.target_box is not None and cal.top.winfo_ismapped() and (
                cal.nw in members or CAL in self.group_of(members[0].pad.id)):
            blocks.append(tuple(cal.target_box))
        gap, targets = self._gap(), {}
        for pid, o in self.windows.items():
            if pid in ids or o._closing or o.win.state() != "normal" or self.motion.drives(pid):
                continue
            b = _pad_box(o.pad)
            if not any(geom.overlap(b, geom.inflate(k, gap - 1)) for k in blocks):   # on it, or closer than the gap
                continue
            area = self.area_of(b)
            best = None
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                x0, y0 = b[0], b[1]
                w, h = b[2] - b[0], b[3] - b[1]
                for _ in range(8):              # past each block in the way, in this direction
                    hit = next((k for k in blocks + list(targets.values())
                                if geom.overlap((x0, y0, x0 + w, y0 + h), geom.inflate(k, gap - 1))), None)
                    if hit is None:
                        break
                    if dx > 0:
                        x0 = hit[2] + gap
                    elif dx < 0:
                        x0 = hit[0] - gap - w
                    elif dy > 0:
                        y0 = hit[3] + gap
                    else:
                        y0 = hit[1] - gap - h
                box = (x0, y0, x0 + w, y0 + h)
                inside = area[0] <= x0 and area[1] <= y0 and box[2] <= area[2] and box[3] <= area[3]
                clear = not any(geom.overlap(box, geom.inflate(k, gap - 1)) for k in blocks)
                cost = abs(x0 - b[0]) + abs(y0 - b[1])
                if inside and clear and (best is None or cost < best[0]):
                    best = (cost, box)
            if best is not None:
                targets[pid] = best[1]
        if targets:
            for pid in targets:
                self.windows[pid].user_moved(moved=True)
            self.motion.run(targets)

    # ---- what takes up space (S1), where things may be (S2) and the nearest free spot (S3) ----
    def usable(self) -> list[Box]:
        """Where things may be, one box per screen (in screens() order): its work area less
        the gap, except on a side where it meets another monitor (geom.usable)."""
        return geom.usable(self.screens(), self._gap())

    def area_of(self, box) -> Box:
        """The usable area of ``box``'s screen: the one holding its centre, else the one it
        overlaps most, else the nearest (geom.screen_of)."""
        screens = self.screens()
        return geom.usable(screens, self._gap())[geom.screen_of(box, screens)]

    def space_changed(self):
        """Something that takes up space came, went, moved, changed size or changed state:
        the next space() builds the list again (and the taskbar preview is looked at)."""
        self._space_epoch += 1
        thumb = getattr(self, "thumb_soon", None)
        if thumb is not None:
            thumb()

    def space(self, exclude=()) -> list[space.Shape]:
        """S1, every shape that takes up space, each where it is going (at its destination
        while it glides):
        - every shown note (not minimized, not closing): kind "note", its pad box;
        - a note with its docked calendar: one "pair" (see _shape);
        - the undocked calendar: CAL, kind "cal", at its target_box;
        - the room minimized notes keep (held_room): kind "held".
        A calendar is listed (in a pair or as CAL) only once it has a target_box, and not while
        it closes. ``exclude``: ids left out; leaving out CAL makes a pair its plain note.
        The list is built once per _space_epoch (space_changed) from the pads and the
        calendar's caches (target_box, least) alone: it never measures a window."""
        if self._space_cache is None or self._space_cache[0] != self._space_epoch:
            self._space_cache = (self._space_epoch, self._build_space())
        shapes = self._space_cache[1]
        exclude = set(exclude)
        if not exclude:
            return list(shapes)
        return [space.Shape(s.id, s.parts[0], stacked=s.stacked) if s.kind == "pair" and CAL in exclude else s
                for s in shapes if s.id not in exclude and s.id.removesuffix("/cal") not in exclude]

    def _build_space(self) -> list[space.Shape]:
        notes, cals = [], []
        for nw in self.windows.values():
            try:
                shown = not nw._closing and nw.win.state() == "normal"
            except tk.TclError:                     # (a window being rebuilt: set_language)
                shown = False
            if not shown:
                cal = nw.calendar               # a calendar left on its own (its note minimized)
                if nw.minimized and cal is not None and not cal.docked and _placed(cal):
                    cals.append(space.Shape(CAL, tuple(cal.target_box), kind="cal", least=cal.least))
                continue
            notes.append(self._shape(nw))
            cal = nw.calendar
            if cal is not None and not cal.docked and _placed(cal):
                cals.append(space.Shape(CAL, tuple(cal.target_box), kind="cal", least=cal.least))
        held = [space.Shape(pad_id, tuple(b), kind="held") for pad_id, b in self.held_room.items()]
        for pad_id, cb in ([] if self.prefs.auto_layout else list(self._held_cal.items())):
            nw = self.windows.get(pad_id)              # (C4: auto layout holds nothing: the tiles re-flow)
            if nw is None:
                continue
            note, cb = _pad_box(nw.pad), tuple(cb)
            if nw.pad.calendar_docked:
                held.append(space.Shape(pad_id, geom.union([note, cb]), kind="held", parts=(note, cb)))
            else:
                held += [space.Shape(pad_id, note, kind="held"), space.Shape(f"{pad_id}/cal", cb, kind="held")]
        return notes + cals + held

    def shape_of(self, nw) -> space.Shape:
        """``nw``'s shape as space() lists it: its pad box, or the pair with its docked calendar
        (whether or not it is shown)."""
        return self._shape(nw)

    def _shape(self, nw) -> space.Shape:
        """The note alone, or with its docked (and placed) calendar as a "pair": ``box`` their
        union, ``parts`` (note, calendar), ``side`` where the calendar is, ``cal_least`` the
        calendar's least size and ``least`` the pair's (R4: split_pair keeps the calendar's
        current size on the shared axis, so that is the calendar's size there, not its least)."""
        p = nw.pad
        note = _pad_box(p)
        cal = nw.calendar
        if cal is None or not cal.docked or not _placed(cal):
            return space.Shape(p.id, note, stacked=p.stacked)
        cb = tuple(cal.target_box)
        side = _side_of(note, cb)
        cal_least = tuple(cal.least) if cal.least else (cb[2] - cb[0], cb[3] - cb[1])
        gap, px = self._gap(), self.px
        if side in ("right", "left"):
            least = (px(MIN_W) + gap + cb[2] - cb[0], max(px(MIN_H), cal_least[1]))
        else:
            least = (max(px(MIN_W), cal_least[0]), px(MIN_H) + gap + cb[3] - cb[1])
        return space.Shape(p.id, geom.union([note, cb]), kind="pair", stacked=p.stacked, parts=(note, cb),
                           side=side, least=least, cal_least=cal_least)

    def find_spot(self, w, h, origin, exclude=(), avoid: tuple = ()) -> tuple[Box, str]:
        """Where a ``w`` x ``h`` box that wants its top-left at ``origin`` goes, clear of
        space(exclude), and how:
        - "free": the nearest free spot (S2, S3), on origin's screen first;
        - "shrunk": else the nearest one for it made smaller, down to MIN_W x MIN_H (P5 step 1);
        - "piled": else the overflow pile on origin's screen, in the corner farthest from the
          calendar and keeping its cycles off it (P5 step 2), past every member already on it
          (a stacked pair counts by its note's box). A spot hanging past the area (a cycle
          longer than it) is trimmed to it, but never below MIN_W x MIN_H (R3).
        It sets nothing on any pad: callers hand the result to take_spot."""
        shapes = self.space(exclude)
        avoid = tuple(tuple(b) for b in avoid)      # boxes planned in this action that space() doesn't show yet
        obstacles = [s.box for s in shapes] + list(avoid)
        screens, gap, px = self.screens(), self._gap(), self.px
        areas = geom.usable(screens, gap)
        x, y = origin
        home = geom.screen_of((x, y, x + w, y + h), screens)
        spot = space.nearest_free(w, h, origin, areas, obstacles, gap, home)
        if spot is not None:
            return spot, "free"
        spot = space.shrink_to_fit(w, h, px(MIN_W), px(MIN_H), origin, areas, obstacles, gap, home)
        if spot is not None:
            return spot, "shrunk"
        area, step = areas[home], px(PILE_STEP)
        cal = next((s.parts[1] if s.kind == "pair" else s.box      # (where it is, even if left out above)
                    for s in self.space() if s.kind in ("pair", "cal")), None)
        corner, keep_off = space.pile_corner(area, cal), (() if cal is None else (cal,)) + avoid     # (and keep off it)
        members = [s.parts[0] if s.kind == "pair" else s.box        # a pair's note is what sits on a spot
                   for s in shapes if s.stacked and geom.screen_of(s.box, screens) == home]
        loose = tuple(s.box for s in shapes if not s.stacked)       # the top bars of the notes off the pile stay clear
        for keep in (keep_off + loose, keep_off):                   # ... unless that would restart the pile over its members
            start = space.pile_start(members, (w, h), area, corner, step, avoid=keep)
            x0, y0, x1, y1 = space.pile_spots([(w, h)], area, corner, step, start=start, before=members,
                                              avoid=keep)[0]
            if not any(geom.overlap((x0, y0, x1, y1), m) for m in members):
                break
        if x1 > area[2] and area[2] - x0 >= min(px(MIN_W), w):     # (it never hangs before the start)
            x1 = area[2]
        if y1 > area[3] and area[3] - y0 >= min(px(MIN_H), h):
            y1 = area[3]
        return (x0, y0, x1, y1), "piled"

    def take_spot(self, pad: Pad, spot, how):
        """What every caller does with find_spot's result: the pad takes the spot's box (a
        folded note keeps its own height); it is stacked only when piled (P5); and when the
        spot is smaller than the note, the note keeps its own size from before, once (P6)."""
        x0, y0, x1, y1 = spot
        w, h = x1 - x0, (pad.height if pad.collapsed else y1 - y0)
        if (w < pad.width or h < pad.height) and pad.own_size is None:
            pad.own_size = [pad.width, pad.height]
        pad.x, pad.y, pad.width, pad.height = x0, y0, w, h
        pad.stacked = how == "piled"
        self.space_changed()

    def calendar(self):
        """The one open calendar (there is one at a time), or None."""
        return self._open_calendar()

    # ---- the way back (N1, N2): start, reopen, restore, screens ------------------------------------
    def _start_up(self) -> None:
        """Once every window exists: each link group that does not fit one usable area slides in as
        one (M3), then every note returns in file order (return_note: nothing else is pushed)."""
        self._slide_groups()
        for nw in list(self.windows.values()):
            self.return_note(nw, "start")

    def _slide_groups(self) -> None:
        """Each link group with a member off its screens slides in as one shape (space.slide_in of its
        union), in one glide. One that cannot fit as one shape is placed member by member (return_note)
        and the members that move lose their links."""
        areas, screens = self.usable(), self.screens()
        slides, seen = {}, set()
        for pid in list(self.windows):
            group = self.group_of(pid) & set(self.windows)
            if pid in seen or len(group) < 2:
                continue
            seen |= group
            boxes = {i: _pad_box(self.windows[i].pad) for i in group}
            if all(geom.fits_one(b, areas) for b in boxes.values()):
                continue
            union = geom.union(list(boxes.values()))
            home = geom.screen_of(union, screens)
            dx, dy = space.slide_in(union, areas, home)
            if geom.fits_one(geom.shift(union, dx, dy), [areas[home]]):
                slides.update({i: geom.shift(b, dx, dy) for i, b in boxes.items()})
            else:
                for i, b in boxes.items():
                    if not geom.fits_one(b, areas):
                        self.links.drop(i)
        self._mirror_links()
        if slides:
            self.apply(slides)

    def return_note(self, nw: NoteWindow, why: str) -> None:
        """The one way a note comes back (``why``: "start", "reopen", "restore" or "screens"), in
        one plan that never pushes anything (N1):
        1. onto a screen; 2. its spot if free, else the nearest free one (find_spot); a stacked
        note keeps its spot (its stack slides in as one when off the screen);
        3. its calendar: docked on its saved side if that is clear, else the pair comes back
        together wherever it fits (#22A); undocked: at its own spot, or beside the note."""
        pad, pid = nw.pad, nw.pad.id
        if self.prefs.auto_layout and self._is_tile(pid):       # the tiles are arranged
            if pad.calendar and nw.calendar is None:
                if self.calendar_elsewhere(nw) is not None:
                    pad.calendar = False
                else:
                    nw.make_calendar("start")
            self.arrange_soon()
            return
        areas, gap, screens = self.usable(), self._gap(), self.screens()
        cal = nw.calendar
        excl = {pid, CAL} if cal is not None else {pid}
        self.space_changed()
        snap = self.space(exclude=excl)
        note = _pad_box(pad)
        home = geom.screen_of(note, screens)
        boxes: dict[str, Box] = {}
        if pad.stacked:                             # keeps its spot; its stack moves in as one
            stack, grew = {pid: note}, True
            while grew:
                grew = False
                for s in snap:
                    sb = s.parts[0] if s.kind == "pair" else s.box
                    if s.stacked and s.id not in stack and s.kind in ("note", "pair") and any(
                            geom.overlap(sb, b) for b in stack.values()):
                        stack[s.id], grew = sb, True
            ub = geom.union(list(stack.values()))
            if not geom.fits_one(ub, areas):
                dx, dy = space.slide_in(ub, areas, home)
                note = geom.shift(note, dx, dy)
                for sid in stack:
                    if sid != pid:
                        boxes[sid] = geom.shift(next(s.box for s in snap if s.id == sid), dx, dy)
        else:
            if not geom.fits_one(note, areas):
                dx, dy = space.slide_in(note, areas, home)
                note = geom.shift(note, dx, dy)
            if not geom.is_free(note, areas, [s.box for s in snap if not s.stacked], gap):
                w0, h0 = note[2] - note[0], note[3] - note[1]
                under = excl | {s.id for s in snap if s.stacked}    # (a note may lie under a pile: P5)
                spot, how = self.find_spot(w0, h0, note[:2], exclude=under)
                if how == "piled":
                    spot, how = self.find_spot(w0, h0, note[:2], exclude=excl)
                self._flag_spot(pad, how, spot, (w0, h0))
                note = spot
        boxes[pid] = note
        parts = None
        want = pad.calendar or cal is not None
        if want and cal is None and self.calendar_elsewhere(nw) is not None:
            pad.calendar = want = False             # one calendar at a time
        fresh = False
        if want:
            fresh = cal is None
            if fresh:
                cal = nw.calendar = CalendarPopup(nw)
                pad.calendar = True
            if cal.docked:
                side, view, cb, clear = cal.plan_dock(side=pad.calendar_side, note_box=note)
                if side is None:                    # G7: undocked, at a free spot
                    cal.undock_to(cb)
                    self._space_epoch += 1
                    boxes[CAL] = cb
                else:
                    cal.take_plan(side, view)
                    pair = clear
                    if not clear:                   # #22A: the pair comes back together, wherever it fits
                        un = geom.union([note, cb])
                        spot, how = self.find_spot(un[2] - un[0], un[3] - un[1], un[:2], exclude=excl)
                        if how == "piled":          # P5: no room for the pair: the calendar closes (pad.calendar and its side stay)
                            nw.close_calendar(remember=True)
                            cal, want, fresh = None, False, False
                            spot, how = self.find_spot(note[2] - note[0], note[3] - note[1], note[:2], exclude=excl)
                            self._flag_spot(pad, how, spot, (note[2] - note[0], note[3] - note[1]))
                            note = boxes[pid] = spot
                        else:
                            pair = True
                            self._flag_spot(pad, how, spot, (un[2] - un[0], un[3] - un[1]))
                            cl = tuple(cal.least) if cal.least else (cb[2] - cb[0], cb[3] - cb[1])
                            shape = space.Shape(pid, un, kind="pair", parts=(note, cb), side=side, cal_least=cl)
                            note, cb = space.split_pair(shape, spot, gap)
                    if pair:
                        parts = {pid: (note, cb)}
                        boxes[pid] = geom.union([note, cb])
            else:
                boxes[CAL] = self._undocked_return(nw, cal, note, snap, excl)
        self.space_changed()
        self.apply_plan(boxes, parts=parts)
        if pad.stacked and not pad.pinned:
            nw.win.lift()
        if fresh:
            cal.reveal()
            self.space_changed()
            self.calendar_buttons()
        self.request_save()

    def _flag_spot(self, pad: Pad, how: str, spot: Box, asked: tuple) -> None:
        """What find_spot's result means for a pad: piled makes it stacked; a smaller box than
        asked keeps the own size from before (P6)."""
        pad.stacked = how == "piled"
        if (spot[2] - spot[0] < asked[0] or spot[3] - spot[1] < asked[1]) and pad.own_size is None:
            pad.own_size = [pad.width, pad.height]

    def _undocked_return(self, nw: NoteWindow, cal, note: Box, snap: list, excl) -> Box:
        """Where an undocked calendar comes back (N1): its saved spot, at its own size, when that
        is free and a gap from the note; else the nearest free spot."""
        pad, gap, areas = nw.pad, self._gap(), self.usable()
        if cal.target_box is not None:
            w, h = cal.target_box[2] - cal.target_box[0], cal.target_box[3] - cal.target_box[1]
        else:
            cal.fit_size = None
            cal.top.geometry("")
            w, h = cal._size()
        pos = pad.calendar_pos or pad.calendar_big_pos
        if pos is None:
            boxes = [calgeom.spot_box(note, s, w, h, gap) for s in calgeom.SIDES]
            fit = next((b for b in boxes if geom.fits_one(b, areas)), None)
            if fit is None:
                r, a = boxes[0], self.area_of(boxes[0])
                fit = (min(max(r[0], a[0]), max(a[0], a[2] - w)), min(max(r[1], a[1]), max(a[1], a[3] - h)))
            pos = list(fit[:2])
        pad.calendar_pos = [int(pos[0]), int(pos[1])]
        x, y = pad.calendar_pos
        cb = (x, y, x + w, y + h)
        obstacles = [s.box for s in snap]
        if not geom.is_free(cb, [self.area_of(cb)], obstacles + [note], gap):
            cb, _how = self.find_spot(w, h, (x, y), exclude=excl, avoid=(note,))
            pad.calendar_pos = list(cb[:2])
        return cb

    def detach(self, nw: NoteWindow):
        """Menu "Detach this note": it moves the shortest way to where it touches nothing (every
        other box a gap and 1 px away), as one glide with no Undo; only it moves, and its links go."""
        pid = nw.pad.id
        if len(self.group_of(pid)) < 2:
            return False
        slack, reach = self._touch_reach()
        shape = self.shape_of(nw)                   # (with its docked calendar: the pair moves as one)
        here = shape.box
        w, h = here[2] - here[0], here[3] - here[1]
        areas, screens = self.usable(), self.screens()
        obstacles = [s.box for s in self.space(exclude={pid, CAL} if shape.kind == "pair" else {pid})]
        home = geom.screen_of(here, screens)
        spot = space.nearest_free(w, h, here[:2], areas, obstacles, reach + 1, home)
        self.unlink(pid)                            # (M2: Detach breaks its links, wherever it ends up)
        if spot is None:                            # a crowded screen: the usual last resort
            spot, how = self.find_spot(w, h, here[:2], exclude={pid, CAL} if shape.kind == "pair" else {pid})
            self._flag_spot(nw.pad, how, spot, (w, h))
        self.apply_plan({pid: spot})
        return True

    def grow(self, changes: dict, mode: str, undo_label: str | None = None, *, by_calendar: bool = False,
             parts: dict | None = None, shapes: list | None = None, before: dict | None = None,
             offer: bool = False) -> dict:
        """Make room for ``changes`` (id -> new box) as one plan (space.plan_growth against
        space()) and apply it. ``parts``: an owner's exact new (note, calendar) boxes. Returns the
        boxes the growers may have (drag mode: clamped at the edge), {} in app mode. ``shapes``: the
        space list to plan against (a resize planned from the boxes at its start, a fold from before
        it); ``before``: the layout Undo goes back to (a live resize moved the pads already);
        ``offer``: the Undo is offered even when only the growers moved."""
        parts = parts or {}
        changes = {k: tuple(int(v) for v in b) for k, b in changes.items()}
        cal = self._open_calendar()
        shapes = list(shapes) if shapes is not None else self.space()
        if parts and CAL not in changes:            # docking: the undocked calendar becomes part of the owner's pair
            shapes = [s for s in shapes if s.id != CAL]
        if self.prefs.auto_layout:                  # the tiles decide (arrange): a calendar being opened gets its box
            if cal is not None and cal.target_box is None:
                box = next((p[1] for p in parts.values()), changes.get(CAL))
                if box is not None:
                    cal.move_to(box)
            self.arrange()
            return {}
        screens, gap, px = self.screens(), self._gap(), self.px
        areas = geom.usable(screens, gap)
        cal_box = next((p[1] for p in parts.values()), changes.get(CAL))
        if cal_box is None and cal is not None and _placed(cal):
            cal_box = tuple(cal.target_box)
        area = areas[geom.screen_of(geom.union(list(changes.values())), screens)]
        plan = space.plan_growth(changes, shapes, self.links, areas, gap, mode=mode, min_w=px(MIN_W), min_h=px(MIN_H),
                                 pile_corner_=space.pile_corner(area, cal_box), step=px(PILE_STEP), slack=px(2))
        boxes = dict(plan.boxes)
        for g, b in changes.items():
            boxes.setdefault(g, b)
        moved_parts = dict(parts)
        for g, (nb, cb) in parts.items():           # drag mode, clamped: only the part that grew is cut back
            fb, nw = boxes.get(g), self.windows.get(g)
            if fb is None or fb == changes[g] or nw is None:
                continue
            old_note = geom.pad_box(nw.pad)
            old_cal = tuple(cal.target_box) if cal is not None and cal.target_box is not None else None

            def clip(b, old):
                if old is not None and tuple(b) == tuple(old):
                    return b
                return max(b[0], fb[0]), max(b[1], fb[1]), min(b[2], fb[2]), min(b[3], fb[3])
            moved_parts[g] = (clip(nb, old_note), clip(cb, old_cal))
        for pid in plan.piled:
            if pid in self.windows:
                self.windows[pid].pad.stacked = True
        for pid in plan.shrunk:
            nw = self.windows.get(pid)
            if nw is not None and nw.pad.own_size is None:
                nw.pad.own_size = [nw.pad.width, nw.pad.height]
        others = [i for i in plan.boxes if i not in changes]
        if by_calendar:                             # P4: what the calendar moved goes home when it gives room back
            for pid in set(others) | set(plan.piled) | set(plan.shrunk):
                nw = self.windows.get(pid)
                if nw is not None and pid not in changes and nw.pad.cal_mark is None:
                    x0, y0, x1, y1 = geom.pad_box(nw.pad)
                    nw.pad.cal_mark = [x0, y0, x1 - x0, y1 - y0]
        self.apply_plan(boxes, parts=moved_parts, undo_label=undo_label if others or offer else None,
                        before=before)
        for pid in plan.piled:                      # a pile is drawn above what it lies over (every top bar shows)
            if pid in self.windows and not self.windows[pid].pad.pinned:
                self.windows[pid].win.lift()
        return dict(plan.allowed)

    def plan_resize(self, changes: dict, shapes: list):
        """The plan of a live resize (drag mode, against ``shapes``): nothing is applied."""
        screens, gap, px = self.screens(), self._gap(), self.px
        areas = geom.usable(screens, gap)
        cal = self._open_calendar()
        cal_box = tuple(cal.target_box) if cal is not None and _placed(cal) else None
        area = areas[geom.screen_of(geom.union(list(changes.values())), screens)]
        return space.plan_growth(changes, shapes, self.links, areas, gap, mode="drag", min_w=px(MIN_W),
                                 min_h=px(MIN_H), pile_corner_=space.pile_corner(area, cal_box),
                                 step=px(PILE_STEP), slack=px(2))

    def close_up(self, changes: dict, shapes: list | None = None) -> None:
        """P4: ``changes`` (id -> a smaller box: a fold) close up with whatever is linked in line.
        One plan against ``shapes`` (default space()), applied once; no Undo."""
        changes = {k: tuple(int(v) for v in b) for k, b in changes.items()}
        shapes = list(shapes) if shapes is not None else self.space()
        plan = space.plan_close_up(changes, shapes, self.links, self._gap(), areas=self.usable(), slack=self.px(2))
        self.apply_plan(plan.boxes)

    def outlines(self):
        """The one dashed-outline window of the live drags (made when first needed)."""
        if getattr(self, "_outlines", None) is None:
            self._outlines = Outlines(self)
        return self._outlines

    def give_back(self, toward: Box) -> None:
        """P4: the calendar closed or shrank (``toward``: its new box, or its last one when it
        closed): the notes it moved go back to their own boxes where free, else close up toward it.
        Every id moved is unstacked; those home lose their mark."""
        marks = {}
        for pid, nw in self.windows.items():
            m = nw.pad.cal_mark
            if m is not None and not nw._closing:
                marks[pid] = (m[0], m[1], m[0] + m[2], m[1] + m[3])
        if not marks or self.prefs.auto_layout:
            return
        self.space_changed()
        shapes = self.space()
        plan = space.plan_give_back(marks, shapes, self.links, self.usable(), self._gap(),
                                    tuple(toward) if toward is not None else None)
        now = {s.id: s.box for s in shapes}
        for pid in plan.boxes:
            nw = self.windows.get(pid)
            if nw is not None:
                nw.pad.stacked = False
        for pid, m in marks.items():
            if plan.boxes.get(pid, now.get(pid)) == m:
                self.windows[pid].pad.cal_mark = None
        if plan.boxes:
            self.apply_plan(dict(plan.boxes), undo_label=None)
        self.request_save()

    def bring_back(self, nw: NoteWindow, places: dict):
        """Kept for the callers that name the dragged window and where each member was put:
        settle_drop of those notes (``places``: window -> (x, y))."""
        return self.settle_drop({w.pad.id for w in places}, places=places, anchor=nw)

    def settle_drop(self, ids: set, places: dict | None = None, anchor=None) -> dict:
        """After a drag or a resize (M1, M3): the dropped ``ids`` (note ids, and CAL for the
        undocked calendar) end up on the screen and clear of everything else, in one plan.
        1. Only when a member (a note with its docked calendar, or the calendar) doesn't fit one
           usable area, the whole group slides back in as one (space.slide_in of the union).
        2. Still too close to something (or sitting on it): the group goes to the nearest free
           spot (M1), keeping its shape.
        3. Members that still don't fit (a group wider than the screen, a crowded screen) go one
           by one to find_spot (P5): shrunk, or on the overflow pile.
        Then everything glides there in one apply (a note already gliding goes on from where it
        is now: its pad is not written to). ``places``: window -> (x, y) where the drag put it
        (default: where the pads say); ``anchor``: the window whose screen counts."""
        areas, gap, screens = self.usable(), self._gap(), self.screens()
        cal = self._open_calendar()
        if places is None:
            places = {w: geom.pad_box(w.pad)[:2] for i, w in self.windows.items()
                      if i in ids and not w._closing and w.win.state() == "normal"}
        free_cal = cal is not None and CAL in ids and not cal.docked and cal.target_box is not None
        w_of = {w.pad.id: w for w in places}

        def box(w, xy):
            return xy[0], xy[1], xy[0] + w.pad.width, xy[1] + _shown_h(w.pad)

        def shape(w, xy):       # with its docked calendar where it will follow it (C1): one shape (S1, M3)
            b = box(w, xy)
            if cal is None or cal.nw is not w or not cal.docked or cal.target_box is None:
                return b
            return geom.union([b, Motion._follow(cal, _pad_box(w.pad), b)])
        own = {w.pad.id: box(w, xy) for w, xy in places.items()}        # what moves: the note, or CAL
        shapes_ = {w.pad.id: shape(w, xy) for w, xy in places.items()}  # what must fit: with its calendar
        if free_cal:
            own[CAL] = shapes_[CAL] = tuple(cal.target_box)
        if not own:
            return {}
        self.space_changed()
        others = self.space(set(own))
        obstacles = [b for s in others for b in (s.parts or (s.box,))]
        union = geom.union(list(shapes_.values()))
        here = box(anchor, places[anchor]) if anchor in places else union
        home = geom.screen_of(here, screens)
        dx = dy = 0
        slid = not all(geom.fits_one(b, areas) for b in shapes_.values())
        if slid:
            dx, dy = space.slide_in(union, areas, home)

        def moved(b, ox, oy):
            return b[0] + ox, b[1] + oy, b[2] + ox, b[3] + oy
        own = {k: moved(b, dx, dy) for k, b in own.items()}
        shapes_ = {k: moved(b, dx, dy) for k, b in shapes_.items()}
        fits = (lambda b: geom.fits_one(b, [areas[home]])) if slid else (lambda b: geom.fits_one(b, areas))
        outside = [k for k in own if k != CAL and not fits(own[k])]
        inside = [k for k in own if k not in outside]
        if inside:
            ub = geom.union([shapes_[k] for k in inside])
            parts = [shapes_[k] for k in inside]
            if len(parts) > 1:              # a group: each of its pieces counts, not the empty corners
                crowded = [b for b in parts if not geom.is_free(b, areas, obstacles, gap)]   # between them (E)
                # only shown notes in the way: they make room (push_clear), the group stays
                blocked = any(s.kind != "note" for b in crowded for s in others
                              for q in (s.parts or (s.box,)) if geom.overlap(b, geom.inflate(q, gap - 1)))
                blocked = blocked or any(not geom.fits_one(b, areas) for b in crowded)
            else:
                blocked = not geom.is_free(ub, areas, obstacles, gap)
            if blocked:                     # too close to (or on) something: M1
                spot = space.nearest_free(ub[2] - ub[0], ub[3] - ub[1], ub[:2], areas, obstacles, gap, home)
                if spot is not None:
                    ox, oy = spot[0] - ub[0], spot[1] - ub[1]
                    own.update({k: moved(own[k], ox, oy) for k in inside})
                    shapes_.update({k: moved(shapes_[k], ox, oy) for k in inside})
                else:
                    outside += [k for k in inside if k != CAL]
                    inside = [k for k in inside if k == CAL]
        if not outside and not slid and all(own[k] == (box(w_of[k], places[w_of[k]]) if k != CAL
                                                       else tuple(cal.target_box)) for k in own):
            return {}
        saved = {w: (w.pad.x, w.pad.y, w.pad.width, w.pad.height, getattr(w.pad, "target", None)) for w in places}
        sizes = {w: (w.pad.width, w.pad.height) for w in places}
        driven = {w for w in places if self.motion.drives(w.pad.id)}   # gliding: it goes on from where it is
        cal_was = tuple(cal.target_box) if free_cal else None
        for k in inside:                            # the ones inside first: space() sees them there
            if k == CAL:
                cal.target_box = own[CAL]
            else:
                w_of[k].pad.target = own[k][:2]
        self.space_changed()
        for i, k in enumerate(outside):             # each in turn, clear of those placed before it
            w = w_of[k]
            p, xy = w.pad, own[k][:2]
            left, top, right, bottom = areas[home]
            origin = (min(max(xy[0], left), right - p.width), min(max(xy[1], top), bottom - _shown_h(p)))
            spot, how = self.find_spot(p.width, _shown_h(p), origin, exclude=set(outside[i:]))
            self.take_spot(p, spot, how)            # (shrunk to fit: the spot's size; flags only matter here)
            p.target = spot[:2]
            own[k] = (spot[0], spot[1], spot[0] + p.width, spot[1] + _shown_h(p))
        goal = {k: b for k, b in own.items()}
        if free_cal:
            cal.target_box = cal_was
        for w, xy in places.items():                # the pads where the windows are: Motion goes from there
            p = w.pad
            if w in driven:                         # (a gliding pad holds its old spot: starts would jump it back)
                p.x, p.y, p.width, p.height, p.target = saved[w]
                continue
            p.x, p.y = xy
            p.width, p.height = sizes[w]
            p.target = None
        self.space_changed()
        self.apply(goal, starts={w.pad.id: xy for w, xy in places.items() if w not in driven})
        return goal

    # ---- screen setups (N5): a home per monitor setup, and what a change of screens does ------------
    @property
    def setup_key(self) -> str:
        """The monitor setup now (monitor rectangles only: a taskbar change stays in the same one)."""
        return geom.setup_key(self.screens())

    def _every_pad(self) -> list[Pad]:
        pads = [w.pad for w in self.windows.values()] + self._keep_pads + self._closed + \
               [p for _t, p in self._recently_closed]
        seen, out = set(), []
        for p in pads:
            if id(p) not in seen:
                seen.add(id(p))
                out.append(p)
        return out

    @staticmethod
    def _stamp(pad: Pad, key: str) -> None:
        """The pad's current (top-level) copy as its copy for setup ``key``."""
        if pad.x is None or pad.y is None:
            return
        pad.setups[key] = {"x": pad.x, "y": pad.y, "w": pad.width, "h": pad.height,
                           "links": list(pad.links), "stacked": bool(pad.stacked)}
        pad.calendar_setups[key] = {"pos": list(pad.calendar_pos) if pad.calendar_pos else None}

    def _stamp_setups(self) -> None:
        """Every save: the current copy goes into setups[key] and calendar_setups[key], with the scale
        it was made at (N5)."""
        key = self.setup_key
        for pad in self._every_pad():
            self._stamp(pad, key)
        self.prefs.setup_scales[key] = self.scale
        self.prefs.last_setup = key

    def _rescaled(self, box, old):
        """``box`` made at display scale ``old`` (None, or this scale: unchanged), at this one (N5)."""
        if not old or abs(old - self.scale) < 1e-9:
            return tuple(box)
        return geom.rescale(tuple(box), old, self.scale, self.screens())

    def _rescale_top(self, pad: Pad, old) -> None:
        """The pad's current copy (its box and calendar_pos) from scale ``old`` to this one."""
        if pad.x is None or not old or abs(old - self.scale) < 1e-9:
            return
        b = self._rescaled((pad.x, pad.y, pad.x + pad.width, pad.y + pad.height), old)
        pad.x, pad.y, pad.width, pad.height = b[0], b[1], b[2] - b[0], b[3] - b[1]
        if pad.calendar_pos:
            pad.calendar_pos = list(self._rescaled((*pad.calendar_pos, *pad.calendar_pos), old)[:2])

    def _load_setup(self, pads: list[Pad]) -> None:
        """Start-up (before any window): the copies of this setup, rescaled when saved at another
        scale. It only loads: return_note runs N1 once, and the first save writes the setups."""
        key, last, scales = self.setup_key, self.prefs.last_setup, self.prefs.setup_scales
        if last is not None and last != key:
            was = scales.get(last)
            self._switch_copies(pads, last, key, start=True)
        else:
            was = scales.get(key)
            for pad in pads:
                self._rescale_top(pad, was)
        if was and abs(was - self.scale) > 1e-9:    # own sizes are shared by every setup: scaled once, here
            for pad in pads:
                if pad.own_size:
                    pad.own_size = [round(v * self.scale / was) for v in pad.own_size]
        self._taken = (self._signature(self.screens()), key)

    def _switch_copies(self, pads: list[Pad], old: str, new: str, start: bool) -> bool:
        """The data half of switch_setup: stamp ``old``, then load ``new``'s copies into the pads
        (rescaled) when known. Returns whether ``new`` was known."""
        scales = self.prefs.setup_scales
        for pad in pads:
            self._stamp(pad, old)                   # (a file saved before this task has no setups[old])
        s_old = scales.get(old) if start else None
        if not any(new in p.setups for p in pads):  # unknown: a copy of old (its scale taken in at start)
            for pad in pads:
                self._rescale_top(pad, s_old)
            return False
        s_new = scales.get(new)
        for pad in pads:
            e, ce = pad.setups.get(new), pad.calendar_setups.get(new)
            if e is not None:
                b = self._rescaled((e["x"], e["y"], e["x"] + e["w"], e["y"] + e["h"]), s_new)
                pad.x, pad.y, pad.width, pad.height = b[0], b[1], b[2] - b[0], b[3] - b[1]
                pad.links, pad.stacked = list(e.get("links", ())), bool(e.get("stacked"))
            else:                                   # made in old since: its copy is at old's scale (start only)
                self._rescale_top(pad, s_old)
            if ce is not None:
                pos = ce.get("pos")
                pad.calendar_pos = list(self._rescaled((*pos, *pos), s_new)[:2]) if pos else None
        return True

    def switch_setup(self, old: str, new: str, *, start: bool = False) -> None:
        """N5: the monitors are another setup. A known ``new`` loads each note's and the calendar's
        copy; an unknown one copies ``old``, moving in what is off the screens (a group as one
        shape). Then every note returns (return_note "screens"). ``start``: only loads."""
        pads = self._every_pad()
        known = self._switch_copies(pads, old, new, start)
        if start:
            return
        self.motion.cancel(set(self.windows) | {CAL})
        for nw in self.windows.values():
            nw.pad.target = None
            if known and nw.win.state() == "normal":
                b = _pad_box(nw.pad)
                nw.win.geometry(f"{b[2] - b[0]}x{b[3] - b[1]}+{b[0]}+{b[1]}")
        self._load_links()
        self.space_changed()
        if not known:
            self._slide_groups()
        self._return_all()

    def _return_all(self) -> None:
        for nw in list(self.windows.values()):
            if nw.win.state() == "normal":
                self.return_note(nw, "screens")

    @staticmethod
    def _signature(screens) -> tuple:
        return tuple(sorted((tuple(s.monitor), tuple(s.work)) for s in screens))

    def set_fake_screens(self, screens: list[Screen]) -> None:
        """Tests: these screens stand in for the monitors, taken in at once (no debounce)."""
        self._fake_screens = list(screens)
        self.check_screens(immediate=True)

    def check_screens(self, *, immediate: bool = False) -> None:
        """Polled every SCREEN_POLL_MS: when the monitors differ from the ones taken in and stay so
        for SCREEN_SETTLE_MS, take them in (the same setup: every note returns; another: switch_setup)."""
        if self._fake_screens is not None:
            cur = list(self._fake_screens)
        else:
            found = winapi.monitors()
            cur = [Screen(monitor=m, work=w) for m, w in found] if found else self.screens()
        sig = self._signature(cur)
        if self._taken is None or sig == self._taken[0]:
            self.screens_pending, self._seen, self._pending_since = False, None, None
            return
        now = time.monotonic()
        if not immediate:
            if getattr(self, "_pending_since", None) is None:
                self._pending_since = now
            flapping = (now - self._pending_since) * 1000 >= SCREEN_SETTLE_MAX_MS     # (never settles: take it now)
            if not flapping and (self._seen is None or self._seen[0] != sig):
                self._seen, self.screens_pending = (sig, now), True
                return
            if not flapping and (now - self._seen[1]) * 1000 < SCREEN_SETTLE_MS:
                return
        old_key = self._taken[1]
        if self._fake_screens is None:
            self._screens = cur
        new_key = geom.setup_key(cur)
        self._taken = (sig, new_key)
        self.screens_pending, self._seen, self._pending_since = False, None, None
        self.space_changed()
        if new_key != old_key:
            self.switch_setup(old_key, new_key)
        else:
            self._return_all()
        self.save_now()

    def _poll_screens(self) -> None:
        self._screen_job = None
        if self.closed:
            return
        try:
            self.check_screens()
            self.apply_motion()                     # (Windows' animation setting may have changed)
        finally:
            if not self.closed:                     # (a change settling: looked at again soon)
                ms = SCREEN_SETTLE_POLL_MS if self.screens_pending else SCREEN_POLL_MS
                self._screen_job = self.root.after(ms, self._poll_screens)

    def _screens_event(self) -> None:
        """The monitors, the work area, the DPI or a setting changed (WM_DISPLAYCHANGE...): looked at now."""
        if self.closed:
            return
        if self._screen_job is not None:
            self.root.after_cancel(self._screen_job)
            self._screen_job = None
        self._poll_screens()

    def set_note_size(self, nw: NoteWindow):
        """Menu "Use this size for new notes" (again: back to "like the note it came from")."""
        size = [nw.pad.width, nw.pad.height]
        self.prefs.note_size = None if self.prefs.note_size == size else size
        nw.show_notice(tr("default_size_set" if self.prefs.note_size else "default_size_off"))
        self.request_save()

    # ---- applying a plan: every move goes through motion (S4) ---------------------------------
    def apply(self, targets: dict[str, Box], *, undo_label: str | None = None, ms: int = GLIDE_MS,
              done=None, anchor=None, starts: dict | None = None, before: dict | None = None) -> None:
        """Glide every window in ``targets`` to its box, once, on the one clock (Motion.run).
        Window level: a pad id means that note's own box, CAL the calendar's. ``undo_label``
        (a texts key): Undo is offered once the action ends (offer_undo), on ``anchor`` (a
        NoteWindow), else on the first pad id's note. Plans that supersede a running one are one
        action: the first plan's boxes stay as the ``before`` (ids only a later plan touches
        join with their own), and the one offer at the final end carries the last plan's label.
        Any apply ends the Undo on offer (but the restore's own). ``starts``: where windows start
        that are not where their pads say (Motion.run)."""
        targets = dict(targets)
        if not self._restoring:
            self._drop_undo()
        chain = self._chain if self.motion.busy() else None
        fresh = self.layout_of(list(targets))
        if chain is None:
            chain = self._chain = {"before": fresh, "gen": 0}
        else:
            for pid, b in fresh.items():        # (ids the chain already moves keep their first box)
                chain["before"].setdefault(pid, b)
        chain["gen"] += 1
        chain.update(label=undo_label, anchor=anchor, first=next(iter(targets), None))
        if before:                              # a live resize: the boxes from before it started
            chain["before"].update(before)
        gen = chain["gen"]

        def finished():
            if self._chain is chain and chain["gen"] == gen:    # the last plan's end only
                self._chain = None
                before, label = chain["before"], chain["label"]
                if label is not None and self.layout_of(list(before)) != before:
                    nw = chain["anchor"] or self.windows.get(chain["first"]) or next(
                        (self.windows[i] for i in before if i in self.windows), None)
                    self.offer_undo(before, label, nw)
            if done is not None:
                done()
        self.motion.run(targets, ms=ms, done=finished, starts=starts)

    def apply_plan(self, boxes: dict[str, Box], *, parts: dict | None = None, **kw) -> None:
        """apply() for a planner's output, keyed by shape id (space()). An id in ``parts`` is
        its (note, calendar) boxes as given, whatever its shape now (the calendar opening or
        docking makes a plain note a pair); any other pair is split by space.split_pair."""
        parts = parts or {}
        shapes = {s.id: s for s in self.space()}
        targets: dict[str, Box] = {}
        for sid, b in boxes.items():
            if sid in parts:
                targets[sid], targets[CAL] = parts[sid]
            elif sid in shapes and shapes[sid].kind == "pair":
                targets[sid], targets[CAL] = space.split_pair(shapes[sid], b, self._gap())
            else:
                targets[sid] = b
        self.apply(targets, **kw)

    def offer_undo(self, before, label, anchor_nw) -> None:
        """Offer one Undo for an action that moved things (S5): ``label`` (a texts key) on
        ``anchor_nw``'s toast with the Undo button, which puts ``before`` back (restore_layout).
        One at a time; it goes after UNDO_MS or with the next apply of any kind."""
        self._drop_undo()
        if anchor_nw is None or not anchor_nw.win.winfo_exists():
            anchor_nw = next((self.windows[i] for i in before if i in self.windows), None)
        if anchor_nw is None:
            return
        offer = self._undo = {"before": dict(before), "anchor": anchor_nw.pad.id, "action": self.undo_now}
        offer["job"] = self.root.after(UNDO_MS, lambda: self._undo is offer and self._drop_undo())
        anchor_nw.show_undo_action(tr(label), self.undo_now)

    def _drop_undo(self) -> None:
        """The Undo on offer ends: its toast goes (if still showing it) and it can't be run."""
        offer, self._undo = self._undo, None
        if offer is None:
            return
        self.root.after_cancel(offer["job"])
        nw = self.windows.get(offer["anchor"])
        if nw is not None and nw._undo_action == offer["action"] and nw.win.winfo_exists():
            nw.hide_undo()

    def undo_now(self) -> None:
        """Run the Undo on offer, if any (the toast's button): every window back where it was."""
        offer = self._undo
        if offer is None:
            return
        self._drop_undo()
        self.restore_layout(offer["before"])

    def _open_calendar(self):
        """The open calendar (one at a time), or None."""
        return next((w.calendar for w in self.windows.values() if w.calendar is not None), None)

    def layout_of(self, ids) -> dict[str, Box]:
        """Where each id's window is (going), for Undo: a note's box (its pad box), and CAL's
        target_box when CAL is asked for or is docked to one of these notes (it moves with them)."""
        ids, out = list(ids), {}
        for pid in ids:
            nw = self.windows.get(pid)
            if pid != CAL and nw is not None:
                out[pid] = _pad_box(nw.pad)
        cal = self._open_calendar()
        if cal is not None and _placed(cal) and (CAL in ids or (cal.docked and cal.nw.pad.id in out)):
            out[CAL] = tuple(cal.target_box)
        return out

    def restore_layout(self, layout: dict[str, Box]) -> None:
        """Undo a tidy or a group resize: every id back to its box, in one apply (one glide)."""
        targets = {}
        for pid, b in layout.items():
            if pid == CAL:
                cal = self._open_calendar()
                if cal is not None and not getattr(cal, "_closing", False):
                    targets[CAL] = b
            elif pid in self.windows and not self.windows[pid]._closing and self.windows[pid].win.winfo_exists():
                targets[pid] = b
        self._restoring = True
        try:
            self.apply(targets)
        finally:
            self._restoring = False

    def fold_all(self, on: bool):
        """Menu "Fold up all notes" / "Unfold all notes": every shown note changes in one plan
        (S4), so each note moves once. No Undo (restore_layout does not put back the fold)."""
        wins = [w for w in self.windows.values() if w.win.state() == "normal" and not w._closing
                and w.pad.collapsed != on]
        if self.prefs.auto_layout:
            for w in wins:
                w.pad.collapsed = on
                w._apply_collapsed(shoot=True)
            self.arrange()
        else:
            self.set_folded(wins, on)
        self.request_save()

    def set_folded(self, wins: list, on: bool) -> None:
        """Fold (``on``) or unfold ``wins`` as one plan: folding closes up with every link (P4:
        whatever is in line and linked, whatever Alt or the drag switch say), unfolding pushes
        like any growth in app mode (nothing is dragged: F36). Both plan against the space list
        from before, as the notes already show their new state. No Undo."""
        if not wins:
            return
        old = self.space()
        by_id = {s.id: s for s in old}
        for w in wins:
            w.pad.collapsed = on
            w._apply_collapsed(shoot=True)
        changes, parts = {}, {}
        for w in wins:
            note, s = _pad_box(w.pad), by_id.get(w.pad.id)
            if s is not None and s.kind == "pair":
                parts[w.pad.id] = (note, s.parts[1])
                note = geom.union([note, s.parts[1]])
            changes[w.pad.id] = note
        if on:
            self.close_up(changes, old)
        else:
            self.grow(changes, "app", shapes=old, parts=parts)

    def tidy(self, nw: NoteWindow, size="keep"):
        """Menu "Tidy up notes" (T1): the notes on nw's screen into columns from the screen's right
        edge, top to bottom, in about the order they are in now (the undocked calendar sorts like
        a note), all one size (TIDY_SIZES, "default" = the new-note size) or each its own
        ("keep"). A docked calendar keeps its room beside its note, on its left, as tall as the
        note (C1; never below its least height): the pair is one item. They glide there in one
        apply (grid.plan_tidy: every box is inside the screen); on a full screen the next layer
        starts a little further in, over the first, and those notes are marked stacked."""
        area = self.area_of(_pad_box(nw.pad))
        gap, px = self._gap(), self.px
        wins = [w for w in self.windows.values() if w.win.state() == "normal" and not w._closing
                and _overlap(_pad_box(w.pad), area)]
        col = px(80)                        # notes this close in x count as one column now
        cal = self._open_calendar()
        free_cal = cal is not None and not cal.docked and _placed(cal) and _overlap(tuple(cal.target_box), area)
        order = self.prefs.tidy_order

        def sort_key(box, pinned=False, date="", created=""):
            if order == "date":             # the memo's day, newest first
                return date, created
            place = (-(box[2] // col), box[1])
            return (not pinned, place) if order == "pinned" else place
        if size in TIDY_SIZES:
            fixed = tuple(px(v) for v in TIDY_SIZES[size])
        elif size == "default" and self.prefs.note_size:
            fixed = tuple(self.prefs.note_size)
        else:
            fixed = None
        items = []                          # (sort key, id, slot w, slot h, note (w, h), cal (w, h) | None, window)
        for w in wins:
            p = w.pad
            ww, hh = fixed or (p.own_size if size == "keep" and p.own_size else (p.width, p.height))   # (shrunk to fit: its own size back, P6)
            sh = _shown_h(p) if p.collapsed else hh
            pair, c = None, w.calendar
            if c is not None and c.docked and _placed(c):
                cb = c.target_box
                cal_h = cb[3] - cb[1]
                if not p.collapsed:
                    cal_h = max(sh, c.least[1] if c.least else cal_h)
                pair = (cb[2] - cb[0], cal_h)
            key = sort_key(_pad_box(p), p.pinned, w.note.date or "", w.note.created)
            items.append((key, p.id, ww + (pair[0] + gap if pair else 0), max(sh, pair[1] if pair else 0),
                          (ww, sh), pair, w))
        if free_cal:
            cb = tuple(cal.target_box)
            items.append((sort_key(cb), CAL, cb[2] - cb[0], cb[3] - cb[1], None, None, None))
        items.sort(key=lambda it: it[0], reverse=order == "date")
        boxes, layered = grid.plan_tidy([grid.TidyItem(it[1], it[2], it[3]) for it in items], area, gap,
                                        px(PILE_STEP))
        parts = {}
        for _key, pid, _sw, _sh, (nw_, nh_), pair, w in [it for it in items if it[4] is not None]:
            x0, y0, x1, _y1 = boxes[pid]
            note = (x1 - nw_, y0, x1, y0 + nh_)
            if pair is None:
                boxes[pid] = note
            else:
                parts[pid] = (note, (x0, y0, x0 + pair[0], y0 + pair[1]))
                boxes[pid] = geom.union(list(parts[pid]))
            w.pad.stacked = pid in layered
            if size == "keep" and w.pad.own_size and not w.pad.collapsed:
                w.pad.own_size = None
        self.apply_plan(boxes, parts=parts, undo_label="tidied", anchor=nw)

    def set_auto_layout(self, on):
        """Settings: auto layout. On: the notes are tiled at once and kept tiled (arrange), their
        links on hold. Off (L5): the tiles keep the size they have (each has its own size
        saved), the calendar settles back to its own size in one grow, and the links come back
        where the notes still touch."""
        on = bool(on)
        was = self.prefs.auto_layout
        self.prefs.auto_layout = on
        self.request_save()
        self._sync_settings()
        if on:
            for w in self.windows.values():
                w.pad.free = False
                if w.pad.own_size is None:
                    w.pad.own_size = [w.pad.width, w.pad.height]
            self.hold_links(True)
            self.arrange()
        elif was:
            self._settle_calendar_off()
            self.hold_links(False)

    def _settle_calendar_off(self):
        """L5: the calendar takes its own size again (prefs.auto_layout is already False, so grow
        plans and pushes as usual)."""
        cal = self._open_calendar()
        if cal is None or cal.target_box is None or getattr(cal, "_closing", False):
            return
        pad = cal.nw.pad
        if cal.docked:
            note = _pad_box(pad)
            side, view, cal_box, _clear = cal.plan_dock(side=pad.calendar_side, note_box=note)
            parts = {pad.id: (note, cal_box)}
            if side is None:                # G7: no side fits on any screen: it undocks in the same grow
                self.grow({pad.id: note, CAL: cal_box}, "app", by_calendar=True, parts=parts)
                cal.undock_to(cal_box)
            else:
                cal.take_plan(side, view)
                self.grow({pad.id: geom.union([note, cal_box])}, "app", by_calendar=True, parts=parts)
        else:
            pad.calendar_pos = list(cal.target_box[:2])
            self.grow({CAL: cal._undocked_box()}, "app", by_calendar=True)

    # ---- auto layout: the notes tiled on a grid (L1-L5) ---------------------------------------
    def area_keys(self) -> list[str]:
        """One key per screen, in screens() order: the setup's key and the screen's monitor box."""
        screens = self.screens()
        setup = geom.setup_key(screens)
        return [f"{setup}|{','.join(str(v) for v in s.monitor)}" for s in screens]

    def _screen_index(self, box) -> int:
        return geom.screen_of(box, self.screens())

    def _grid_windows(self, i: int, shown_only: bool = False) -> list:
        """The tile windows on screen ``i`` (not free, not closing), in saved order (no order: last)."""
        out = []
        for w in self.windows.values():
            if w._closing or w.pad.free or self._screen_index(_pad_box(w.pad)) != i:
                continue
            if shown_only and w.win.state() != "normal":
                continue
            out.append(w)
        out.sort(key=lambda w: (w.pad.order is None, w.pad.order or 0))     # (stable: window order breaks ties)
        return out

    def tiled(self, area):
        """The notes auto layout arranges on the screen whose work area is ``area``: shown, not
        closing, not pulled out of the tiles (``pad.free``)."""
        for i, s in enumerate(self.screens()):
            if tuple(s.work) == tuple(area):
                return self._grid_windows(i, shown_only=True)
        return []

    def tile_order(self, area_key: str) -> list[str]:
        """The ids of the non-free tiles on that screen, in their saved order."""
        keys = self.area_keys()
        if area_key not in keys:
            return []
        return [w.pad.id for w in self._grid_windows(keys.index(area_key))]

    def _set_order(self, ids) -> None:
        for n, pid in enumerate(ids):
            if pid in self.windows:
                self.windows[pid].pad.order = n
        self.request_save()

    def arrange_soon(self):
        """Tile again once the current change is done (several changes: once)."""
        if self.prefs.auto_layout and not self.closed and getattr(self, "_arrange_job", None) is None:
            self._arrange_job = self.root.after_idle(self.arrange)

    def arrange(self):
        """Auto layout: on each screen, the grid planner's tiles (grid.plan_grid) applied in one
        apply (see _arrange_screen)."""
        self._arrange_job = None
        if not self.prefs.auto_layout or not self.windows or self.closed:
            return
        for i in range(len(self.screens())):
            self._arrange_screen(i)

    def move_grid(self, area_key: str, home: tuple[int, int], before: dict | None = None) -> None:
        """The user dropped the grid with its first tile at ``home``: the grid keeps its shape
        (rows) while it fits, and the dropped home is what is saved (planning clamps it each time)."""
        keys = self.area_keys()
        if area_key not in keys:
            return
        self._arrange_screen(keys.index(area_key), home=(int(home[0]), int(home[1])), keep_rows=True,
                             undo_label="grid_moved", before=before)

    def drop_grid(self, area_key: str, point) -> None:
        """The grid of ``area_key`` was dropped with the pointer at ``point``: the screen under it
        gets the grid. On another screen that has tiles, they join its order after its last tile and
        its home stays; on one with no grid, ``point`` becomes its home."""
        keys = self.area_keys()
        if area_key not in keys:
            return
        i = keys.index(area_key)
        point = (int(point[0]), int(point[1]))
        j = self._screen_index((*point, *point))
        if j == i:
            self._arrange_screen(i, home=point, keep_rows=True, undo_label="grid_moved")
            return
        mine = self._grid_windows(i)
        if not mine:
            return
        screens = self.screens()
        dx = screens[j].monitor[0] - screens[i].monitor[0]
        dy = screens[j].monitor[1] - screens[i].monitor[1]
        theirs = self._grid_windows(j)
        for w in mine:                      # they are on the other screen now (the windows glide there)
            w.pad.x += dx
            w.pad.y += dy
        self.space_changed()
        self._set_order([w.pad.id for w in theirs] + [w.pad.id for w in mine])
        if not theirs:
            side = self.prefs.grid_homes.get(area_key, {}).get("side", "right")
            self.prefs.grid_homes[keys[j]] = {"x": point[0], "y": point[1], "side": side}
        self.arrange()

    def drop_tile(self, nw, point, mods: set) -> None:
        """A tile (or a free note) was let go with the pointer at ``point``: Alt pulls it out of
        the grid (free); a free note let go over a tile rejoins at that tile's place (#25A); Ctrl over
        a tile swaps the two places. Then everything is tiled again."""
        point = (int(point[0]), int(point[1]))
        pad = nw.pad
        j = self._screen_index((*point, *point))
        key = self.area_keys()[j]
        under, last = None, self._grid_last.get(key)
        if last is not None:
            idx = grid.slot_at(last[0], point)
            if idx is not None:
                under = last[1][idx]
        if "alt" in mods:
            pad.free = True
            pad.stacked = False
        elif under is not None and under != pad.id:
            old = [w.pad.id for w in self._grid_windows(j)]
            if pad.free or pad.id not in old:       # rejoins at that tile's place
                pad.free = False
                order = [p for p in old if p != pad.id]
                order.insert(order.index(under) if under in order else len(order), pad.id)
            elif "ctrl" in mods and under in old:   # the two change places
                a, b = old.index(pad.id), old.index(under)
                old[a], old[b] = old[b], old[a]
                order = old
            else:
                order = old
            self._set_order(order)
        self.space_changed()
        self.arrange()
        self.request_save()

    def _free_shapes(self, i) -> dict:
        """{id: Shape} of the shown free notes on screen ``i`` (space()'s shapes: a note with its
        docked calendar is one pair)."""
        out = {}
        for w in self.windows.values():
            if w._closing or not w.pad.free or w.win.state() != "normal":
                continue
            s = self._shape(w)
            if self._screen_index(s.box) == i:
                out[w.pad.id] = s
        return out

    def _arrange_screen(self, i: int, *, home=None, keep_rows=False, undo_label=None, before=None) -> None:
        """One screen's grid (L1, L2): plan_grid over its tiles (saved order, saved home), the
        calendar's block and the free notes as obstacles; the free notes the block covers are
        pushed aside and the grid planned again around them; everything applied at once."""
        areas, gap, px = self.usable(), self._gap(), self.px
        area, key = areas[i], self.area_keys()[i]
        wins = self._grid_windows(i, shown_only=True)
        if not wins:
            return
        prefs = self.prefs
        entry = prefs.grid_homes.get(key)
        seeded = None
        if entry is None and home is None:      # the first grid on this screen: today's rule seeds it
            mid = sum(w.pad.x + w.pad.width / 2 for w in wins) / len(wins)
            seeded = "left" if mid >= (area[0] + area[2]) / 2 else "right"     # (the growth side)
        side = seeded or (entry or {}).get("side")
        base = tuple(prefs.auto_cell or prefs.note_size or [px(v) for v in TIDY_SIZES["small"]])
        if seeded == "left":
            use_home = (area[2] - base[0], area[1])
        else:
            use_home = home if home is not None else ((entry["x"], entry["y"]) if entry else None)
        # the order: the saved one, then the pads with none by today's key (column by column from the edge)

        def key_of(w):
            edge = area[2] - (w.pad.x + w.pad.width) if side == "left" else w.pad.x - area[0]
            return round(edge / px(80)), w.pad.y
        every = self._grid_windows(i)
        full = [w for w in every if w.pad.order is not None] + sorted(
            [w for w in every if w.pad.order is None], key=key_of)
        if [w.pad.order for w in full] != list(range(len(full))):
            self._set_order([w.pad.id for w in full])
        order = [w.pad.id for w in full if w in wins]
        folded = {w.pad.id: _shown_h(w.pad) for w in wins if w.pad.collapsed}
        for w in wins:                          # a note first becomes a tile: it keeps its own size
            if w.pad.own_size is None:
                w.pad.own_size = [w.pad.width, w.pad.height]
        cal = self._open_calendar()
        tids = set(order)
        rows = self._grid_rows.get(key) if keep_rows else None

        def ratio_of(w, h):
            lw, lh = cal._least_for("mini")
            return calgeom.fit_cells(w, h, lw - 7 * px(SMALL_CELL_MIN[0]), lh - 6 * px(SMALL_CELL_MIN[1]), 6)[2]

        def block_for(owner):
            if cal is None or cal.target_box is None or getattr(cal, "_closing", False):
                return None
            pad = cal.nw.pad
            if owner is not None:
                if not cal.docked or pad.id not in tids:
                    return None
            elif cal.docked or self._screen_index(tuple(cal.target_box)) != i:
                return None
            return grid.CalBlock(
                owner=owner, least_mini=tuple(cal._least_for("mini")), least_big=tuple(cal._least_for("big")),
                ratio_of=ratio_of, hold=pad.calendar_hold, near=tuple(cal.target_box),
                block=tuple(pad.calendar_tile_block) if pad.calendar_tile_block else None)

        def plan_with(calblock, obstacles):
            return grid.plan_grid(grid.GridInput(
                order=order, folded=folded, base=base, home=use_home, side=side, area=area, gap=gap,
                min_size=(px(MIN_W), px(MIN_H)), obstacles=list(obstacles), cal=calblock,
                corner_step=px(PILE_STEP), rows=rows))
        owner = cal.nw.pad.id if cal is not None and cal.docked and cal.nw.pad.id in tids else None
        calblock = block_for(owner)
        free_shapes = self._free_shapes(i)
        plan = plan_with(calblock, [s.box for s in free_shapes.values()])
        if plan.block_failed and owner is not None:     # no room beside its note: undock, as G7 does
            cal.docked = cal.nw.pad.calendar_docked = False
            cal._show_state()
            cal.nw.pad.calendar_pos = list(cal.target_box[:2])
            cal._dock_offset = None
            self.space_changed()
            free_shapes = self._free_shapes(i)
            calblock = block_for(None)
            plan = plan_with(calblock, [s.box for s in free_shapes.values()])
        pushed, shrunk, piled = {}, set(), set()
        for _round in range(2):
            if plan.block is None or not free_shapes:
                break
            pushed, shrunk, piled = self._push_free(plan, free_shapes, area, i)
            now = [pushed.get(pid, s.box) for pid, s in free_shapes.items()]
            again = plan_with(calblock, now)
            if again.block is None or again.block == plan.block:
                plan = again if again.block is not None else plan
                break
            plan = again
        # ---- apply
        for w in wins:
            w.pad.stacked = w.pad.id in plan.pile
        for pid in piled:
            if pid in self.windows:
                self.windows[pid].pad.stacked = True
        for pid in shrunk:
            nw = self.windows.get(pid)
            if nw is not None and nw.pad.own_size is None:
                nw.pad.own_size = [nw.pad.width, nw.pad.height]
        targets, starts = dict(plan.spots), {}
        targets.update(pushed)
        if plan.block is not None and cal is not None:
            cal.grid_view = plan.view
            cal.settle_view()
            targets[CAL] = plan.block
            if not cal.docked:
                cal.nw.pad.calendar_pos = list(plan.block[:2])
        for pid in list(targets):
            w = self.windows.get(pid)
            if w is not None and not self.motion.drives(pid):
                try:
                    starts[pid] = (w.win.winfo_rootx(), w.win.winfo_rooty())
                except tk.TclError:
                    pass
        self._grid_rows[key] = plan.rows
        self._grid_last[key] = (plan, list(plan.spots))
        if home is not None:                    # the user's dropped home, not plan.home
            prefs.grid_homes[key] = {"x": int(home[0]), "y": int(home[1]), "side": plan.side}
            self.request_save()
        elif entry is None:
            prefs.grid_homes[key] = {"x": int(plan.home[0]), "y": int(plan.home[1]), "side": plan.side}
            self.request_save()
        self.space_changed()
        self.apply(targets, starts=starts, undo_label=undo_label, before=before)
        if plan.full and not getattr(self, "_arrange_full", False):
            wins[-1].show_notice(tr("auto_full"))
        self._arrange_full = plan.full

    def _push_free(self, plan, free_shapes, area, i):
        """L2: the block pushes the free notes aside. Returns ({id: box} of the free notes that
        moved, the ids shrunk to fit, the ids piled)."""
        gap, px = self._gap(), self.px
        cal = self._open_calendar()
        block = tuple(plan.block)
        if cal is not None and cal.target_box is not None and cal.top.state() != "withdrawn":
            old = tuple(cal.target_box)
        else:                               # opening: nothing is in line, the covered ones relocate
            old = (block[0], block[1], block[0], block[1])
        tile_shapes = [space.Shape(tid, spot, kind="held") for tid, spot in plan.spots.items()]
        shapes = list(free_shapes.values()) + tile_shapes + [space.Shape(CAL, old, kind="cal")]
        areas = self.usable()
        push = space.plan_growth({CAL: block}, shapes, Links(), areas, gap, mode="app", min_w=px(MIN_W),
                                 min_h=px(MIN_H), pile_corner_=space.pile_corner(area, block),
                                 step=px(PILE_STEP), slack=px(2))
        boxes = {pid: tuple(b) for pid, b in push.boxes.items() if pid in free_shapes}
        shrunk = {p for p in push.shrunk if p in free_shapes}
        piled = {p for p in push.piled if p in free_shapes}
        final = {pid: boxes.get(pid, s.box) for pid, s in free_shapes.items()}
        crowded = [pid for pid, b in final.items() if geom.overlap(geom.inflate(block, gap), b)]
        fixed = [tuple(b) for b in plan.spots.values()] + [block]
        members = [s.parts[0] if s.kind == "pair" else s.box for s in self.space()
                   if s.stacked and self._screen_index(s.box) == i] + [tuple(plan.spots[t]) for t in plan.pile]
        members += [final[p] for p in piled]
        for pid in crowded:
            b = final[pid]
            w, h = b[2] - b[0], b[3] - b[1]
            obstacles = fixed + [x for p, x in final.items() if p != pid]
            spot = space.nearest_free(w, h, b[:2], areas, obstacles, gap, i)
            if spot is None:
                spot = space.shrink_to_fit(w, h, px(MIN_W), px(MIN_H), b[:2], areas, obstacles, gap, i)
                if spot is not None:
                    shrunk.add(pid)
            if spot is None:
                corner, step = space.pile_corner(area, block), px(PILE_STEP)
                start = space.pile_start(members, (w, h), area, corner, step, avoid=(block,))
                x0, y0, x1, y1 = space.pile_spots([(w, h)], area, corner, step, start=start, before=members,
                                                   avoid=(block,))[0]
                if not geom.fits_one((x0, y0, x1, y1), [area]):
                    x1, y1 = max(min(x1, area[2]), x0 + min(px(MIN_W), w)), max(min(y1, area[3]), y0 + min(px(MIN_H), h))
                    if not geom.fits_one((x0, y0, x1, y1), [area]):
                        dx, dy = space.slide_in((x0, y0, x1, y1), [area], 0)
                        x0, y0, x1, y1 = x0 + dx, y0 + dy, x1 + dx, y1 + dy
                spot = (x0, y0, x1, y1)
                piled.add(pid)
                shrunk.add(pid)
                members.append(spot)
            final[pid] = boxes[pid] = tuple(spot)
        moved = {pid: b for pid, b in boxes.items() if b != free_shapes[pid].box}
        return moved, shrunk, piled

    def set_snap_gap(self, gap):
        """Settings: the gap. Each link group is spaced anew to it, keeping its shape (R23);
        a group that is now closer to a screen's edge than the gap slides in as one (M3)."""
        old = self._gap()
        self.prefs.snap_gap = gap if gap in SNAP_GAPS else None
        self.space_changed()                      # (a pair's least size has the gap in it)
        self.request_save()
        self._sync_settings()
        boxes = self._respace(self._gap() - old)
        if boxes:
            self.apply_plan(boxes)
        for w in self.windows.values():           # docked calendars sit this far from their note too
            cal = w.calendar
            if cal is not None and cal.docked:
                kind = (getattr(cal, "_spot", None) or ("",))[0]
                if w.pad.id in boxes and kind in ("right", "left"):     # (planned: Motion puts it there)
                    cal._spot = (kind, w.pad.width + self._gap() if kind == "right" else -self._gap(), 0)
                else:
                    cal._spot = None
                    if w.pad.id not in boxes:
                        cal.place()

    def _respace(self, d: int) -> dict[str, Box]:
        """The boxes (by shape id, for apply_plan) that space every link group to the new gap
        (``d`` more than before), around its top-left members: a shape that has another linked
        on its left (or above) sits the gap from it. A docked calendar's room grows by ``d`` on its
        side. A group with a member not inside one usable area slides in as one (M3)."""
        shapes = {s.id: s for s in self.space() if s.kind != "held"}
        gap, slack, areas = self._gap(), self.px(2), self.usable()
        boxes, seen = {}, set()
        for sid, s in shapes.items():
            if sid in seen:
                continue
            ids = [i for i in shapes if i in self.group_of(sid)]
            seen.update(ids)
            grow = {i: [0, 0] for i in ids}                         # a pair: more room on its calendar's side
            for i in ids:
                if shapes[i].kind == "pair" and d:
                    grow[i][space.SHARED_AXIS[shapes[i].side]] = d
            new = {}
            for ax in (0, 1):                                       # x, then y
                before = {i: [] for i in ids}                       # those just before it on this axis
                for a, b in sorted(self.links.pairs()):
                    if a not in before or b not in before:
                        continue
                    ba, bb = shapes[a].box, shapes[b].box
                    if min(ba[3 - ax], bb[3 - ax]) - max(ba[1 - ax], bb[1 - ax]) <= 0:
                        continue                                    # no shared edge along this axis
                    if bb[ax] >= ba[ax + 2] - slack:
                        before[b].append(a)
                    elif ba[ax] >= bb[ax + 2] - slack:
                        before[a].append(b)
                start = {}

                def lo(i, trail=()):
                    if i not in start:
                        start[i] = shapes[i].box[ax]
                        if before[i] and i not in trail:
                            start[i] = max(lo(j, trail + (i,)) + shapes[j].box[ax + 2] - shapes[j].box[ax]
                                           + grow[j][ax] + gap for j in before[i])
                    return start[i]
                for i in ids:
                    new.setdefault(i, [0, 0, 0, 0])
                    new[i][ax] = lo(i)
                    new[i][ax + 2] = start[i] + shapes[i].box[ax + 2] - shapes[i].box[ax] + grow[i][ax]
            moved = {i: tuple(b) for i, b in new.items()}
            if not all(geom.fits_one(b, areas) for b in moved.values()):    # one that doesn't fit: the group slides
                dx, dy = space.slide_in(geom.union(moved.values()), areas)
                moved = {i: geom.shift(b, dx, dy) for i, b in moved.items()}
            boxes.update({i: b for i, b in moved.items()
                          if b != shapes[i].box or (shapes[i].kind == "pair" and d)})
        return boxes

    def picture(self, name, box):
        """Memo picture ``name`` shrunk into ``box``, shared by the list cards, the thumbnail
        strip and the preview, so a picture file is not decoded again each time. Whoever
        shows it keeps its own reference too (old ones drop out of this cache)."""
        key = (name, tuple(box))
        if key in self._pictures:
            self._pictures.move_to_end(key)
            return self._pictures[key]
        photo = self._pictures[key] = _picture_photo(self, name, box, self.root)
        while len(self._pictures) > PICTURE_CACHE:
            self._pictures.popitem(last=False)
        return photo

    def set_date_format(self, fmt):
        """How dates look in the top bar and on the memo cards, in every note."""
        self.prefs.date_format = texts.set_date_format(fmt)
        for w in self.windows.values():
            w.update_date()
            if w.view == "settings":
                w.settings_view.sync()
        self.refresh_lists()
        self.request_save()

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

    # ---- saving -----------------------------------------------------------------------
    def request_save(self):
        if self.closed:
            return
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(SAVE_DELAY_MS, self._autosave)

    def _autosave(self):
        self._save_job = None
        self.save_now()
        # keep the calendars in step with edits, but only when what they show changed
        # (titles, days, colors): not at every pause in typing the rest of a memo
        shown = tuple((n.id, memo_title(n), n.date, n.end_date, n.color, bool(n.deleted), n.is_empty)
                      for n in self.notes.values())
        if shown != self._calendar_shown:
            self._calendar_shown = shown
            for w in self.windows.values():
                if w.calendar:
                    w.calendar.draw()

    @perf.timed("save")
    def save_now(self):
        for nw in self.windows.values():
            if not nw.win.winfo_exists():
                # destroyed but still listed (a bug elsewhere, as set_language's on 2026-11-21):
                # reading it would stop every save, so its memo and pad go as last read. Logged
                # once, not at every autosave.
                if str(nw.win) not in self._dead_logged:
                    self._dead_logged.add(str(nw.win))
                    self._log(f"save: window {nw.win} (pad {nw.pad.id}) is destroyed but still listed;"
                              " its memo is saved as last read")
                continue
            try:
                nw.sync_from_widgets()      # may schedule a save; cancelled just below
            except Exception:               # one bad window must not stop the save of the others
                self._log(f"save: window {nw.win} (pad {nw.pad.id}) could not be read; "
                          "saved as last read\n" + traceback.format_exc())
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
            self._save_job = None
        if not self.screens_pending:
            self._stamp_setups()
        try:
            self.store.save(list(self.notes.values()), [w.pad for w in self.windows.values()] + self._keep_pads,
                            self.prefs)
        except OSError as exc:
            self._log(f"save failed: {exc!r}")

    def quit(self):
        if self.closed:
            return
        PopupMenu.close_current()
        try:
            self.save_now()
        except Exception:                   # logged; a failed save must not keep the process alive
            self._report_error(*sys.exc_info())
        self.closed = True
        for job in (self._poll_job, self._day_job, getattr(self, "_sys_job", None), self._screen_job,
                    getattr(self, "_thumb_job", None)):
            if job is not None:
                self.root.after_cancel(job)
        self.waker.close()
        for nw in self.windows.values():
            nw.cancel_jobs()
            if nw.calendar and nw.calendar._click_job:
                nw.calendar.grid.after_cancel(nw.calendar._click_job)
        self.clock.close()
        self.root.destroy()

    # ---- clock, second launch, errors ---------------------------------------------------
    def _arm_day(self) -> None:
        """The date is looked at next at midnight (and when the clock changes or the computer wakes: "day")."""
        if self._day_job is not None:
            self.root.after_cancel(self._day_job)
        now = datetime.now()
        midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
        wait = (midnight - now).total_seconds() + 1
        self._day_due = time.monotonic() + wait
        self._day_job = self.root.after(max(1000, round(wait * 1000)), self._check_day)

    def _day_event(self) -> None:
        if not self.closed:
            self._check_day()

    def _show_all(self) -> None:
        """A second launch asks: every note comes forward."""
        for nw in self.windows.values():
            nw.show(focus=False)

    def thumb_soon(self) -> None:
        """Something the taskbar preview shows changed: checked once, half a second from now."""
        if self._thumb_job is None and not self.closed:
            try:
                self._thumb_job = self.root.after(500, self._thumb_due)
            except tk.TclError:
                pass

    def _thumb_due(self) -> None:
        self._thumb_job = None
        self._thumb_at = 0.0
        self._check_thumbnail()

    def _rearm_timers(self) -> None:
        """The repeating timers armed again (a test counts the wakeups of an idle app)."""
        for name, ms, fn in (("_screen_job", SCREEN_POLL_MS, self._poll_screens),
                             ("_poll_job", SIGNAL_POLL_MS, self._poll_signal)):
            job = getattr(self, name, None)
            if job is not None:
                self.root.after_cancel(job)
                setattr(self, name, self.root.after(ms, fn))
        self._arm_day()

    def _check_day(self):
        self._day_job = None
        try:
            if date.today() != self._today:
                self._today = date.today()
                for w in self.windows.values():
                    if w.win.winfo_exists():        # (a destroyed one still listed: see save_now)
                        w.update_date()
                if self.purge_bin():
                    self.refresh_lists()
                    self.save_now()
        except Exception:                   # logged; the next day must still be checked
            self._report_error(*sys.exc_info())
        if not self.closed:
            self._arm_day()

    def _clear_signal(self):
        try:
            self.signal_file.unlink()
        except OSError:
            pass

    def _make_taskbar_proxy(self):
        """An invisible window (off-screen, see-through) that carries the app's one taskbar
        button and Alt+Tab entry. Every note is owned by it (NoteWindow.show): the notes have no
        buttons of their own, however many there are, and come forward with it. What the
        button asks (minimize / restore) goes to taskbar_click; its activation to _bring_notes."""
        p = tk.Toplevel(self.root)
        p.withdraw()
        p.overrideredirect(True)
        p.title(tr("app_title"))
        p.geometry("1x1+-30000+-30000")
        p.attributes("-alpha", 0.0)
        p.deiconify()
        p.update_idletasks()
        if winapi.show_in_taskbar(p):
            p.withdraw()
            p.deiconify()
        winapi.disable_transitions(p)
        winapi.hook_syscommand(p, self._syscommands, self.wake_sys)
        winapi.use_iconic_thumbnail(p)              # its preview: the notes as they lie (_send_thumbnail)
        self._thumb_sig = None
        self._proxy_ready = False                   # (its own first showing is no click)
        self._minimized_at = 0.0                    # when a note last went away (note_minimized)
        p.bind("<FocusIn>", lambda e: e.widget is p and self._proxy_activated())
        self.root.after(800, lambda: setattr(self, "_proxy_ready", True))
        return p

    def _proxy_activated(self):
        """The taskbar button or Alt+Tab brought the app forward (the notes came along, being
        owned by the proxy): the keyboard goes on to a note. (Not when Windows only handed
        the focus on because the note that had it was just minimized.)"""
        if self._proxy_ready and not self.closed and time.monotonic() - self._minimized_at > 0.8:
            self.root.after_idle(self._bring_notes)

    def note_minimized(self, nw):
        """``nw`` just went away (NoteWindow.minimize): the keyboard goes to a note still shown,
        so Windows need not hand it to the proxy (which would read as a taskbar click)."""
        self._minimized_at = time.monotonic()
        shown = [w for w in self._shown_notes() if w is not nw]
        if shown:
            last = self.last_note if self.last_note in shown else shown[-1]
            try:
                last.body.focus_force()
            except tk.TclError:
                pass

    def _shown_notes(self):
        return [nw for nw in self.windows.values() if not nw._closing and nw.win.state() == "normal"]

    def _folded(self):
        """Notes folded away (minimized with no sticker): only the taskbar button brings them back."""
        return [nw for nw in self.windows.values() if nw.minimized and nw.sticker is None and not nw._closing]

    def _bring_notes(self):
        """Every shown note in front, the one used last focused; the folded-away notes come
        back. With nothing shown at all, the stickers come back too."""
        shown = self._shown_notes()
        back = self._folded()
        if not shown:
            back = [nw for nw in self.windows.values() if nw.minimized and not nw._closing]
        if back:
            for nw in back:
                nw.restore()
            self.root.after(ROLL_MS + DOCK_SLIDE_MS + 60, self._focus_notes)   # once they have unrolled
            return
        self._focus_notes()

    def _focus_notes(self):
        shown = self._shown_notes()
        if not shown:
            return
        last = self.last_note if self.last_note in shown else shown[-1]
        for nw in shown:
            if nw is not last:
                nw.win.lift()
        last.win.lift()
        last.body.focus_force()

    def taskbar_click(self, what):
        """The one taskbar button minimized ("min": a click while the app is in front, Win+M)
        or restored the app. Notes folded away come back first; else every shown note is
        minimized (folds or becomes a sticker); with none shown, they all come back. The proxy
        itself never minimizes (its owned notes would hide with it)."""
        shown = self._shown_notes()
        if what == "min" and shown and not self._folded():
            for nw in shown:
                nw.minimize(animate=len(shown) <= 6)
        else:
            self._bring_notes()

    def _thumb_windows(self):
        """The app's windows a preview shows, bottom to top: shown notes, their calendars, stickers."""
        mine = {}
        for nw in self.windows.values():
            if nw._closing:
                continue
            mine[str(nw.win)] = nw.win
            if nw.calendar is not None:
                mine[str(nw.calendar.top)] = nw.calendar.top
            if nw.sticker is not None:
                mine[str(nw.sticker.top)] = nw.sticker.top
        try:
            order = [str(o) for o in self.root.tk.splitlist(self.root.tk.call("wm", "stackorder", "."))]
        except tk.TclError:
            order = list(mine)
        return [mine[path] for path in order if path in mine and mine[path].state() == "normal"]

    def _check_thumbnail(self):
        """Every half second: the preview is redrawn when DWM next asks if what it shows changed."""
        now = time.monotonic()
        if now - getattr(self, "_thumb_at", 0.0) < 0.5:
            return
        self._thumb_at = now
        sig = tuple((nw.pad.x, nw.pad.y, nw.pad.width, nw.pad.height, nw.minimized, nw.view, nw.note.id,
                     nw.look_version, nw.calendar is not None, nw.pad.collapsed) for nw in self.windows.values())
        if sig != self._thumb_sig:
            self._thumb_sig = sig
            winapi.invalidate_iconic(self.proxy)

    def _send_thumbnail(self, size):
        """DWM asks for the taskbar preview, at most ``size`` (w, h): every shown note (its
        calendar, the stickers) where it lies on the screen, shrunk to fit, on nothing."""
        max_w, max_h = size
        if max_w <= 0 or max_h <= 0 or getattr(self, "_thumb_off", False):
            return
        parts = []
        for top in self._thumb_windows():
            shot = winapi.snapshot(top)
            if not shot:
                continue
            w, h, raw = shot
            im = Image.frombuffer("RGB", (w, h), raw, "raw", "BGRX", 0, 1)
            mask = Image.new("L", (w, h), round(255 * _alpha(top)))
            try:
                keyed = bool(str(top.attributes("-transparentcolor")))
            except tk.TclError:
                keyed = False
            if keyed:                       # see-through corners come back black: leave them out
                r = min(self.px(10), w // 2, h // 2)
                dark = im.convert("L").point(lambda v: 255 if v <= 6 else 0)
                for bx, by in ((0, 0), (w - r, 0), (0, h - r), (w - r, h - r)):
                    box = (bx, by, bx + r, by + r)
                    mask.paste(Image.composite(Image.new("L", (r, r), 0), mask.crop(box), dark.crop(box)), box)
            parts.append((top.winfo_rootx(), top.winfo_rooty(), im, mask))
        if parts:
            x0 = min(x for x, y, im, m in parts)
            y0 = min(y for x, y, im, m in parts)
            x1 = max(x + im.width for x, y, im, m in parts)
            y1 = max(y + im.height for x, y, im, m in parts)
            pic = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
            for x, y, im, m in parts:
                pic.paste(im.convert("RGBA"), (x - x0, y - y0), m)
        else:
            pic = draw_icon(64).convert("RGBA")
        k = min(max_w / pic.width, max_h / pic.height, 1.0)
        pic = pic.resize((max(1, round(pic.width * k)), max(1, round(pic.height * k))), Image.LANCZOS)
        hr = winapi.set_iconic_thumbnail(self.proxy, pic)
        if hr != 0:                         # DWM would not take it: the plain preview, not an empty one
            winapi.use_iconic_thumbnail(self.proxy, False)
            self._thumb_off = True
            self._log(f"taskbar preview refused (HRESULT {hr:#x}); plain preview from now on")

    def _drain_syscommands(self):
        """What the taskbar asked (winapi.hook_syscommand only appends): minimize and restore,
        animated. Two or more minimizes close together are Win+M: all at once, no animation.
        Garbage is collected by the frame clock while it is idle (anim.FrameClock._run_idle)."""
        self._sys_job = None
        if self.closed:
            return
        asked, self._syscommands[:] = list(self._syscommands), []
        words = {e[0] for e in asked}
        asked = [e for e in asked if e[0] in ("min", "restore", "thumb")]
        if "screens" in words:
            self._screens_event()
        if "day" in words:
            self._day_event()
        proxy = winapi.hwnd_of(self.proxy)
        if winapi.is_iconic(self.proxy):            # minimized without a WM_SYSCOMMAND (Win+M...): undo it
            winapi.restore(self.proxy, raw=True)
            asked.append(("min", proxy, 0.0))
        by_hwnd = ({winapi.hwnd_of(nw.win): nw for nw in self.windows.values() if nw.win.winfo_exists()}
                   if asked else {})                # (idle: no note looked up, 33 times a second)
        mins = [e for e in asked if e[0] == "min"]
        multi = len(mins) >= 2 and mins[-1][2] - mins[0][2] <= MULTI_MIN_MS / 1000
        try:
            for what, hwnd, _t in asked:
                if hwnd == proxy:
                    if what == "thumb":
                        self._send_thumbnail(_t)
                    else:
                        self.taskbar_click(what)
                    continue
                nw = by_hwnd.get(hwnd)
                if nw is None:
                    continue
                if what == "min":
                    nw.minimize(animate=not multi)
                else:
                    nw.restore()
        except Exception:
            self._report_error(*sys.exc_info())

    def _poll_signal(self):  # (show.signal: come forward; quit.signal: close)
        quit_file = self.signal_file.with_name(QUIT_SIGNAL)
        if quit_file.exists():                  # the installer asks it to close (saved first)
            try:
                quit_file.unlink()
            except OSError:
                pass
            self.quit()
            return
        if self.signal_file.exists():
            self._clear_signal()
            for nw in self.windows.values():
                nw.show(focus=False)
        self._poll_job = self.root.after(SIGNAL_POLL_MS, self._poll_signal)

    def _log(self, text):
        try:
            self.store.folder.mkdir(parents=True, exist_ok=True)
            with open(self.store.folder / "error.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {text}\n")
        except OSError:
            pass

    def _report_error(self, exc, value, tb):
        text = "".join(traceback.format_exception(exc, value, tb))
        self._log(text)
        if sys.stderr:
            sys.stderr.write(text)
