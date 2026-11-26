"""The monitors: the setup now, the note places kept per setup, and a change of monitors taken in once it settles. (Part of App: see app.py.)"""
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


class ScreensMixin:
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
        """The pad's current (top-level) copy as its copy for setup ``key`` (the 8 setups seen last
        are kept: _keep_recent)."""
        if pad.x is None or pad.y is None:
            return
        _keep_recent(pad.setups, key, {"x": pad.x, "y": pad.y, "w": pad.width, "h": pad.height,
                                       "links": list(pad.links), "stacked": bool(pad.stacked)})
        _keep_recent(pad.calendar_setups, key, {"pos": list(pad.calendar_pos) if pad.calendar_pos else None})

    def _remember_setup(self, key: str) -> None:
        _keep_recent(self.prefs.setup_scales, key, self.scale)
        self.prefs.last_setup = key

    def _stamp_setups(self) -> None:
        """Every save: the current copy goes into setups[key] and calendar_setups[key], with the scale
        it was made at (N5)."""
        key = self.setup_key
        for pad in self._every_pad():
            self._stamp(pad, key)
        self._remember_setup(key)

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
            if date.today() != self._today:         # (a sleep that sent no resume message)
                self._check_day()
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

    # ---- auto layout: the notes tiled on a grid (L1-L5) ---------------------------------------
    def area_keys(self) -> list[str]:
        """One key per screen, in screens() order: the setup's key and the screen's monitor box."""
        screens = self.screens()
        setup = geom.setup_key(screens)
        return [f"{setup}|{','.join(str(v) for v in s.monitor)}" for s in screens]

    def _screen_index(self, box) -> int:
        return geom.screen_of(box, self.screens())
