"""Saving: asked for, written when something changed, everything at exit and at Windows shutdown. (Part of App: see app.py.)"""
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


class PersistMixin:
    # ---- saving -----------------------------------------------------------------------
    def request_save(self):
        if self.closed:
            return
        self._dirty = True
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(SAVE_DELAY_MS, self._autosave)

    def save_soon(self):
        """Save once the motion an action just started is over (B4: no fsync in its first frames):
        when the frame clock goes still, at most SAVE_SOON_MS from now. Quitting saves anyway."""
        if self.closed:
            return
        self._dirty = True
        if getattr(self, "_soon_armed", False):
            return
        self._soon_armed = True
        self.clock.quiet(self._save_soon_due)
        self._soon_job = self.root.after(SAVE_SOON_MS, self._save_soon_due)

    def _save_soon_due(self):
        if not getattr(self, "_soon_armed", False):
            return                                  # (the other of its two triggers came first)
        self._soon_armed = False
        job, self._soon_job = getattr(self, "_soon_job", None), None
        if job is not None:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        if not self.closed:
            self.save_now()

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
                if w.view == "list" and w.win.winfo_exists():   # an open list too (the user: it still said
                    w.list_view.refresh(keep_view=True)         # "no memos yet" while one was being written)

    @perf.timed("save")
    def save_now(self, force: bool = False):
        """Write the notes, the windows and the settings. Nothing to do (no attribute set since
        the last save, no save asked for, no typing waiting to be read): it returns at once.
        ``force``: everything is read and compared anyway (at exit: a list changed in place)."""
        shape = (frozenset(self.notes), frozenset(self.windows), len(self._keep_pads))   # (a memo deleted:
        if (not force and not getattr(self, "_dirty", True) and _store.edits == getattr(self, "_saved_edits", -1)
                and shape == getattr(self, "_saved_shape", None)             # no attribute set, the dict changed)
                and not any("sync" in nw._jobs for nw in self.windows.values())):
            if self._save_job is not None:
                self.root.after_cancel(self._save_job)
                self._save_job = None
            return
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
            self._dirty, self._saved_edits, self._saved_shape = False, _store.edits, shape
        except OSError as exc:              # (still dirty: the next save tries again)
            self._log(f"save failed: {exc!r}")
            self._save_result(False)
        else:
            self._save_result(True)

    def _save_result(self, ok: bool) -> None:
        """Saving fails SAVE_FAILS_NOTICE times in a row: every note says so, with Open folder,
        until a save works (Q8; it used to go only to error.log)."""
        for w in list(self.windows.values()):       # phase 10 K: the saved dot (red while it fails)
            try:
                w.saved(ok)
            except tk.TclError:
                pass
        fails = 0 if ok else getattr(self, "_save_fails", 0) + 1
        self._save_fails = fails
        shown = getattr(self, "_save_notice", False)
        if ok != shown or (not ok and fails < SAVE_FAILS_NOTICE):
            return                          # (failing again: the notice is up, or comes back, as it is)
        self._save_notice = not ok
        for w in list(self.windows.values()):
            try:
                if not ok:
                    w.show_sticky(tr("save_failed"), self.open_folder, GLYPH["folder"], tr("open_folder"))
                elif getattr(w, "_sticky", False):
                    w.hide_undo()
            except tk.TclError:             # (a window going away)
                pass

    def tip_once(self, key) -> bool:
        """True the first time ever for the tip ``key`` (store.TIPS), which is then saved as shown."""
        if key in self.prefs.tips_seen:
            return False
        self.prefs.tips_seen = self.prefs.tips_seen + [key]
        self.request_save()
        return True

    def open_folder(self) -> None:
        """The memos' folder in Explorer."""
        try:
            os.startfile(str(self.store.folder))
        except OSError as exc:
            self._log(f"open folder failed: {exc!r}")

    def _ending_session(self) -> None:
        try:
            self.save_now(force=True)
        except Exception:
            self._report_error(*sys.exc_info())
