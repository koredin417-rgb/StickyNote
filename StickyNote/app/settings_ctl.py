"""The settings: each one set, saved and shown on every note. (Part of App: see app.py.)"""
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


class SettingsMixin:
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

    def font_families(self):
        if self._families is None:
            self._families = sorted({f for f in tkfont.families(self.root) if not f.startswith("@")},
                                    key=str.casefold)
        return self._families

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

    def set_note_size(self, nw: NoteWindow):
        """Menu "Use this size for new notes" (again: back to "like the note it came from")."""
        size = [nw.pad.width, nw.pad.height]
        self.prefs.note_size = None if self.prefs.note_size == size else size
        nw.show_notice(tr("default_size_set" if self.prefs.note_size else "default_size_off"))
        self.request_save()

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

    def set_date_format(self, fmt):
        """How dates look in the top bar and on the memo cards, in every note."""
        self.prefs.date_format = texts.set_date_format(fmt)
        for w in self.windows.values():
            w.update_date()
            if w.view == "settings":
                w.settings_view.sync()
        self.refresh_lists()
        self.request_save()
