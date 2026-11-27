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
import geom
import grid
import holidays
import space
import store as _store
import texts
import anim
import threading
import updater as _updater
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
from appbase import *  # noqa: F401,F403  (the constants and helpers the parts share)
from taskbar import TaskbarMixin
from persist import PersistMixin
from screens import ScreensMixin
from settings_ctl import SettingsMixin
from registry import RegistryMixin
from magnet import MagnetMixin
from layout import LayoutMixin
from tiles import TilesMixin


UPDATE_POLL_MS = 100            # the Update page reads the updater's news this often while it works
UPDATE_NOTICE_MS = 600          # "Updated to v..." shows this long after start-up
UPDATE_CLEAN_DELAY = 3.0        # seconds before the old downloads are deleted (see _after_update)


class App(TaskbarMixin, PersistMixin, ScreensMixin, SettingsMixin, RegistryMixin, MagnetMixin, LayoutMixin, TilesMixin):


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
        self._sys_job = self._thumb_job = self._burst_job = None
        try:
            self.waker = Waker(self.root, {"sys": self._drain_syscommands, "screens": self._screens_event,
                                           "day": self._day_event, "show": self._show_all,
                                           "quit": self.quit}, port_file)
            self.waker.connect()                    # (now: a hook's ping never waits for a connection)
        except (OSError, tk.TclError) as exc:       # no wake channel: the taskbar is polled, as before
            self.waker = None
            self._log(f"wake channel: {exc!r}; polling instead")
        self.wake_sys = (lambda: self.waker.ping("sys")) if self.waker is not None else (lambda: None)
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
        # Settings → Update: one for the app, so every note's Update page shows the same check
        self.updater = _updater.Updater(Path(_updater.__file__).resolve().parent, data_folder=Path(folder))
        self._update_job = None

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
        if self.waker is None:
            self._sys_job = self.root.after(30, self._drain_poll)
        self.arrange_soon()                         # auto layout: tiled from the start
        if signal_file is not None:
            self._clear_signal()
            self._poll_job = self.root.after(self._signal_ms(), self._poll_signal)    # (older launchers' files)
        self._after_update()

    # ---- self-update (updater.py) -----------------------------------------------------------
    def update_check(self) -> None:
        """The Update page's Check button."""
        self.updater.check()
        self._update_poll_soon()

    def update_install(self) -> None:
        """Its Update now: the installer it starts closes this app and opens the new version."""
        self.updater.start_install()
        self._update_poll_soon()

    def _update_poll_soon(self) -> None:
        if self._update_job is None:
            self._update_poll()

    def _update_poll(self) -> None:
        """While a check or download runs: its news shown every UPDATE_POLL_MS (then no more wakeups)."""
        self._update_job = None
        if not self.closed and self.updater.pump():
            self._update_job = self.root.after(UPDATE_POLL_MS, self._update_poll)

    def _after_update(self) -> None:
        """At start-up: what the last in-app update's installer wrote, shown once; the downloads
        of earlier updates go (a moment later, on a thread: the installer that just started this
        app may still be running from its folder)."""
        threading.Thread(target=lambda: (time.sleep(UPDATE_CLEAN_DELAY), _updater.clean_temp()),
                         daemon=True, name="update-clean").start()
        result = _updater.read_result(self.store.folder)
        if result is None:
            return
        if result["ok"]:
            text = tr("upd_done", v=result.get("version", ""))
        else:                                   # (the installer put the old version back)
            text = tr("upd_failed")
            u = self.updater
            u.state, u.error, u.error_detail = "error", "upd_err_install", str(result.get("error", ""))
        first = next(iter(self.windows.values()))
        self.root.after(UPDATE_NOTICE_MS, lambda: first.win.winfo_exists() and first.show_notice(text))

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

    # ---- the way back (N1, N2): start, reopen, restore, screens ------------------------------------
    def _start_up(self) -> None:
        """Once every window exists: each link group that does not fit one usable area slides in as
        one (M3), then every note returns in file order (return_note: nothing else is pushed)."""
        self._slide_groups()
        for nw in list(self.windows.values()):
            self.return_note(nw, "start")

    def quit(self):
        if self.closed:
            return
        PopupMenu.close_current()
        try:
            self.save_now(force=True)
        except Exception:                   # logged; a failed save must not keep the process alive
            self._report_error(*sys.exc_info())
        self.closed = True
        for job in (self._poll_job, self._day_job, getattr(self, "_sys_job", None), self._screen_job,
                    getattr(self, "_thumb_job", None), getattr(self, "_burst_job", None),
                    getattr(self, "_update_job", None)):
            if job is not None:
                self.root.after_cancel(job)
        if self.waker is not None:
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
                    self.request_save()     # (only the notes dict changed: no attribute set)
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
        self._poll_job = self.root.after(self._signal_ms(), self._poll_signal)

    def _signal_ms(self) -> int:
        """The signal files are the only way in without a wake channel: looked at often then."""
        return SIGNAL_POLL_MS if getattr(self, "waker", None) is not None else 800

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
