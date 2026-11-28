"""The app's one taskbar button: the proxy window, what the taskbar asks the notes (minimize, restore, the preview), and the preview itself. (Part of App: see app.py.)"""
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


class TaskbarMixin:
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

    def _make_taskbar_proxy(self):
        """An invisible window (off-screen, see-through) that carries the app's one taskbar
        button and Alt+Tab entry. Every note is owned by it (NoteWindow.show): the notes have no
        buttons of their own, however many there are, and come forward with it. What the
        button asks (minimize / restore) goes to taskbar_click; its activation to _bring_notes."""
        p = tk.Toplevel(self.root)
        p.withdraw()
        p.overrideredirect(True)
        p.title(tr("app_title"))
        p.protocol("WM_SAVE_YOURSELF", self._ending_session)      # Windows shutting down / signing out
        # The button's "Close window" (and Alt+F4 while the proxy has the focus) sends WM_CLOSE.
        # Tk alone would destroy the proxy, and Windows the notes it owns with it: the app ran on
        # with nothing on screen, and every later start only asked it to show them. It quits
        # instead, every note kept for the next start.
        p.protocol("WM_DELETE_WINDOW", self.quit)
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
            self.root.after(MINIMIZE_MS + 60, self._focus_notes)   # once they have unrolled
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
        tops = self._thumb_windows()
        rects = []
        for top in tops:
            try:
                rects.append((top, top.winfo_rootx(), top.winfo_rooty(), top.winfo_width(), top.winfo_height()))
            except tk.TclError:
                pass
        if rects:                           # the scale first: no picture is ever bigger than the preview
            x0 = min(r[1] for r in rects)
            y0 = min(r[2] for r in rects)
            x1 = max(r[1] + r[3] for r in rects)
            y1 = max(r[2] + r[4] for r in rects)
            k = min(max_w / max(1, x1 - x0), max_h / max(1, y1 - y0), 1.0)
            pic = Image.new("RGBA", (max(1, round((x1 - x0) * k)), max(1, round((y1 - y0) * k))), (0, 0, 0, 0))
            for top, x, y, _w, _h in rects:
                shot = winapi.snapshot(top)
                if not shot:
                    continue
                w, h, raw = shot
                sw, sh = max(1, round(w * k)), max(1, round(h * k))
                im = Image.frombuffer("RGB", (w, h), raw, "raw", "BGRX", 0, 1).resize((sw, sh), Image.BOX)
                mask = Image.new("L", (sw, sh), round(255 * _alpha(top)))
                try:
                    keyed = bool(str(top.attributes("-transparentcolor")))
                except tk.TclError:
                    keyed = False
                if keyed:                   # see-through corners come back black: leave them out
                    r = max(1, min(round(self.px(10) * k), sw // 2, sh // 2))
                    dark = im.convert("L").point(lambda v: 255 if v <= 6 else 0)
                    for bx, by in ((0, 0), (sw - r, 0), (0, sh - r), (sw - r, sh - r)):
                        box = (bx, by, bx + r, by + r)
                        mask.paste(Image.composite(Image.new("L", (r, r), 0), mask.crop(box), dark.crop(box)), box)
                pic.paste(im.convert("RGBA"), (round((x - x0) * k), round((y - y0) * k)), mask)
        else:
            pic = draw_icon(64).convert("RGBA")
            kk = min(max_w / pic.width, max_h / pic.height, 1.0)
            pic = pic.resize((max(1, round(pic.width * kk)), max(1, round(pic.height * kk))), Image.LANCZOS)
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
        if (any(e[0] == "min" and e[2] for e in asked) and not self._burst_job
                and not getattr(self, "_burst_waited", False)):
            # a minimize: the others of a burst (Win+D) come within MULTI_MIN_MS: all taken together
            self._syscommands[:0] = asked
            self._burst_waited = True
            self._burst_job = self.root.after(MULTI_MIN_MS, self._burst_due)
            return
        self._burst_waited = False
        words = {e[0] for e in asked}
        asked = [e for e in asked if e[0] in ("min", "restore", "thumb")]
        try:
            if "screens" in words:
                self._screens_event()
            if "day" in words:
                self._day_event()
        except Exception:
            self._report_error(*sys.exc_info())
        proxy = winapi.hwnd_of(self.proxy)
        if winapi.is_iconic(self.proxy):            # minimized without a WM_SYSCOMMAND (Win+M...): undo it
            winapi.restore(self.proxy, raw=True)
            if not any(e[0] == "restore" and e[1] == proxy for e in asked):    # (a click to restore: that)
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

    def _burst_due(self) -> None:
        self._burst_job = None
        self._drain_syscommands()

    def _drain_poll(self) -> None:
        """No wake channel: the taskbar's requests are drained every 30 ms, as before Phase 6."""
        self._sys_job = None
        if self.closed:
            return
        self._drain_syscommands()
        if not self.closed:
            self._sys_job = self.root.after(30, self._drain_poll)
