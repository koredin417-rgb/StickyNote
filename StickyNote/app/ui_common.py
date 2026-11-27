"""Shared pieces of the Sticky Note UI: constants, colors, animation, icons, small widgets, menus."""
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

import anim
import holidays
import texts
import perf
import winapi
from geom import CAL, PILE_RESET, PILE_STEP, TILE_SHRINK_STEP    # noqa: F401  (shared with the Tk-free modules)
from geom import overlap as _overlap, pad_box as _pad_box, shown_h as _shown_h, touching as _touching  # noqa: F401
from icon import draw_icon
from store import (BIN_DAY_CHOICES, CURSOR_COLORS, CUSTOM_COLORS, EMPTY_TITLE, INLINE, LIST_SORTS, MARK_KINDS,
                   PIN_LIMIT_MAX, SNAP_GAPS, STYLES, TIDY_ORDERS, Note, NoteStore, Pad, Prefs)
from texts import tr
_APP_PART = True                # marks the modules that make up the UI (set_shared)


APP_NAME = "Sticky Note"
FONT_DIR = Path(__file__).resolve().parent / "fonts"      # Pretendard, the default memo font

GLYPH = {
    "add": "", "note": "", "list": "", "calendar": "",
    "style": "", "pin": "", "pinned": "", "gear": "",
    "minimize": "", "close": "", "check": "", "back": "",
    "search": "", "prev": "", "next": "",
}
GLYPH["trash"] = ""                 # Delete (bin)
GLYPH.update(bold="\ue8dd", italic="\ue8db", underline="\ue8dc", strike="\uede0",
             bullets="\ue8fd", todo="\ue73a", picture="\ueb9f")       # the format bar under the memo
GLYPH.update(undo="\ue72c", remove="\ue711", more="\ue712")     # more: the rail's \u22ef
GLYPH.update(lock="\ue72e", unlock="\ue785", expand="\ue740", shrink="\ue73f")    # calendar header
GLYPH.update(fold="\ue70d", unfold="\ue76c", sort="\ue8cb")     # list part heads: open / folded, sort switch
# menus, the bin, the undo bar, empty pages (icons in place of words; the words stay in tooltips)
GLYPH.update(undo_action="\ue7a7", restore="\ue777", open_window="\ue8a7", unpin="\ue77a", tidy="\uf0e2",
             one_day="\ue8bf", info="\ue946", link="\ue71b", cut="\ue8c6", fit="\ue9a6", paste="\ue77f",
             empty_note="\ue70b", fold_up="\ue70e", fold_down="\ue70d")
     # on a to-do line under the mouse (undo: drawn mirrored)
ICON_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
ICON_FONT_FILES = {"Segoe Fluent Icons": "SegoeIcons.ttf", "Segoe MDL2 Assets": "segmdl2.ttf"}
ICON_BOX = 14                    # every bar icon is drawn this big (px at 100 %), centred in its button
SMALL_ICON_BOX = 12              # icons inside the list
SECTION_ICON_BOX = 9             # ▾ / ▸ and the sort icon beside the list's small part heads (8 pt text)
BIN_ICON_BOX = 18                # the bin's icon under the memo list (px at 100 %)
OPTICAL_SCALE = {GLYPH["minimize"]: 0.8, GLYPH["close"]: 0.8}   # they fill the box corners: draw smaller
UI_FONT = texts.UI_FONTS[texts.DEFAULT]    # changes with the language (Korean: Malgun Gothic)
UI_BOLD = texts.UI_BOLD_FONTS[texts.DEFAULT]     # bold UI text: (UI_BOLD, size, "bold")

PALETTE = (
    ("Yellow", "#FFF4A3"), ("Orange", "#FFE0B8"), ("Pink", "#FFD6E7"),
    ("Purple", "#E3D7FF"), ("Blue", "#CFE6FF"), ("Green", "#CDEFC4"),
    ("Mint", "#C9F0E8"), ("White", "#FFFFFF"), ("Gray", "#E6E6E8"),
    ("Charcoal", "#2E2E2E"),
)

MIN_W, MIN_H = 260, 170
SAVE_DELAY_MS = 400
SAVE_SOON_MS = 1000              # save_soon: once the motion an action started is over, at most this late
SIGNAL_POLL_MS = 10_000          # the signal files (an older launcher or installer): the port is the way now
DAY_CHECK_MS = 30_000            # (unused: the day is checked at midnight and on WM_TIMECHANGE / resume)
DOUBLE_CLICK_MS = 260
BIN_DAYS = 7                     # memos stay in the bin this long, then are deleted for good (Settings)
UNDO_MS = 8000                   # how long the "Moved to the bin · Undo" bar stays
CONFIRM_MS = 3000                # "click again to delete" waits this long for the second click
NOTICE_MS = 3500                 # a short notice in the bottom bar
PREVIEW_DELAY_MS = 250           # resting on a memo card this long shows the whole memo
PREVIEW_HIDE_MS = 300            # after leaving the card (time to move onto the preview)
TEXT_MIN_LINES = 3               # on a small image memo the picture shrinks so the text keeps this many lines
SNAP_REACH = 24                  # a dragged note snaps when an edge comes this close (px at 100 %)
SNAP_HOLD = 36                   # ... and stays snapped until the pointer goes this far from there
SNAP_TAU_S = 0.028               # ... a snap eases in (and out) on this lag: 90 % in 65 ms, no overshoot (B8)
THROW_WINDOW_S, THROW_MIN_S = 0.08, 0.03   # a drop's speed: the pointer's last 80 ms (none under 30 ms)
SNAP_ALIGN_PULL = 0.25           # touching a note on one side, its edges line up from this far (share of the size)
NEW_SNAP_PULL = 0.30             # a new note goes into the slot it lands this near to (share of its size)
PICTURE_CACHE = 96               # shrunk pictures kept for the list, thumbnails and preview
CLOSE_ALL_S = 2.0                # notes closed this shortly before the last one count as "close all"
IMAGE_PATTERNS = "*.png *.jpg *.jpeg *.gif *.bmp *.webp"
BULLET = "• "                     # a bulleted line starts with this
TODO, DONE = "\u2610 ", "\u2611 "  # a to-do line starts with an empty box, a done one with a ticked box
LINE_MARKS = (BULLET, TODO, DONE)   # all two characters long
BOX_FONT = "Segoe UI Symbol"        # draws the boxes the same in any memo font
FINISH_TYPING_TAG = "FinishTyping"  # bind tag: a click in a text field first finishes a Korean syllable
FORMAT_BUTTON_W = 30            # format bar buttons (px at 100 %)
DATE_ROW_H = 36                  # a note's date row along its top, its edge included: the folded strip
RAIL_W = 38                      # the rail down a note's left side, with its controls
RAIL_BUTTON = (30, 26)           # ... its buttons (w, h)
RAIL_PAD = 6                     # ... the room above its first button and under its ⋯
RAIL_GAP = 9                     # ... between its nav and format buttons (a short line in the middle)
DATE_NUM_PX = 22                 # the date row: today's day, bold (px, not pt) ...
DATE_SMALL_PX = 13               # ... the month and weekday beside it, a folded memo's text, a page's name
CAL_NUM_PX = 28                  # the calendar's head: the month's number, bold (px) ...
CAL_YEAR_PX = 13                 # ... and the year beside it, on its baseline (like the note's date row)
GLIDE_MS = anim.LONG             # a note sliding back onto the screen / detaching
FRAME_MS = 15                    # one step of a slide
FLASH_MS = 400                   # a new or reopened note's top bar fades from the theme color this long
NEW_SLIDE_MS = anim.LONG         # a new note slides out from behind the note it was made from
GROUP_RING = (6, 9, 2)           # the line around notes moving together: gap, corner radius, width (px at 100 %)
# short animations (ms): windows fade or slide; Tk cannot fade the widgets inside a window
TIP_FADE_MS = anim.FAST          # a tooltip fades in
PEEK_OFFSET = (12, 18)           # a day's memo preview: down-right of the pointer (px at 100 %)
PEEK_DROP = 10                   # ... it drops this far into place when the day changes
PEEK_DROP_MS = anim.BASE 
ROLL_MS = anim.BASE              # folding: the note rolls up to its top bar
MINIMIZE_MS = 280                # minimize: it rolls up, and (overlapping) its bar slides down and fades (B5)
SCREEN_POLL_MS = 15_000          # the monitors are read this often anyway (a change is an event: "screens")
SCREEN_SETTLE_POLL_MS = 300      # ... and this often while a change settles
SCREEN_SETTLE_MS = 600           # ... and a change is taken in once it has stayed this long
SCREEN_SETTLE_MAX_MS = 3000      # ... or, if it keeps changing (a taskbar settling), after this long anyway
MULTI_MIN_MS = 60                # minimize messages this close together are Win+M: no animation
MENU_FADE_MS = anim.FAST         # a menu fades in (and drops MENU_DROP px into place), and fades out in exit_ms of it
MENU_DROP = 6                    # ... px at 100 %
OPEN_FADE_MS = 160               # a new or reopened note fades in (and blinks)
CLOSE_FADE_MS = anim.FAST        # a closed note fades out (ease-in: it lets go, then goes)
CAL_SHOW_MS = anim.BASE          # the calendar slides out from its note and fades in (and back)
CAL_SLIDE = 8                    # ... this far (px at 100 %)
HOVER_FADE_MS = anim.FAST        # the calendar turns solid under the mouse
CAL_HOVER_IN_MS, CAL_HOVER_OUT_MS = anim.FAST, anim.BASE   # a day under the mouse fades in, the one left out ...
CAL_HOVER_STEPS = 5              # ... through this many colours (a fixed ramp: no new picture per frame)
MONTH_SLIDE_MS = anim.LONG       # paging months: the shown one slides out as the next slides in
VIEW_DIP_MS = anim.FAST          # big <-> mini by the user's click: the calendar dips out this fast, then fades back
DELETE_FLY_MS = anim.LONG        # a deleted memo's picture flies into the bin icon
TOAST_RISE_MS = anim.BASE        # the Undo / notice bar rises into place ...
TOAST_RISE = 10                  # ... from this far below (px at 100 %)
HINT_DROP_MS = anim.BASE         # the first-start tips drop into place ...
HINT_DROP = 8                    # ... from this far above (px at 100 %)
PICTURE_FADE_MS = anim.BASE      # the next picture (tab) fades over the last one
CHIP_SETTLE_MS = anim.FAST       # a dropped memo title slides into its new day
DONE_FADE_MS = anim.BASE         # a ticked to-do shows dark, then fades to its done color
BIG_CELL = (100, 84)             # a day in the big month view (px at 100 %), until resized
BIG_CELL_MIN, BIG_CELL_MAX = (64, 52), BIG_CELL     # never bigger than its default size (grip, docked or not)
BIG_CELL_FILL = (220, 180)       # the stretch rule's "big could fill the note" test only (keeps its old hysteresis)
SMALL_CELL = (32, 30)            # a day in the small month view (px at 100 %)
SMALL_CELL_MIN, SMALL_CELL_MAX = SMALL_CELL, SMALL_CELL     # the mini is locked at this size: bigger is the big view
PERIOD_BAND_H = 15               # a period memo's band in the big view (px at 100 %): 8 pt text
MEMO_CHIP_H = 18                 # a memo title in the big view (px at 100 %): 9 pt text
CAL_MIN_ALPHA = 0.92             # the calendar is never more see-through than this: what is behind stays out of its text
TOP_BUTTON_H = 28                # icon buttons in the top bar
assert PILE_STEP == DATE_ROW_H       # a folded note's height; geom keeps the 100 % value (it cannot import this module)
TIDY_SIZES = {"small": (260, 200), "medium": (320, 280), "large": (400, 360)}   # "Tidy up" (px at 100 %)
CASCADE_STEP = 28                # "Tidy up" on a full screen: the next layer starts this far in


def today_label(d: date, lang: str | None = None) -> str:
    """``d`` in the date format chosen in Settings."""
    return texts.day_label(d, lang=lang)


def set_shared(name, value):
    """A setting the code reads as a plain name (UI_FONT, BIN_DAYS) changed while running:
    every part of the UI (ui_common … app) holds its own copy of the name, so all get it."""
    for module in list(sys.modules.values()):
        if getattr(module, "_APP_PART", False):
            setattr(module, name, value)


def use_language(code: str) -> str:
    """Switch the words and the UI font. Windows made afterwards use them."""
    code = texts.set_language(code)
    set_shared("UI_FONT", texts.UI_FONTS[code])
    set_shared("UI_BOLD", texts.UI_BOLD_FONTS[code])
    return code


def ui_font(size, bold=False):
    """UI text at ``size``: plain (Pretendard Medium) or bold (Pretendard's own Bold face)."""
    return (UI_BOLD, size, "bold") if bold else (UI_FONT, size, "normal")


def memo_title(note: Note) -> str:
    return tr("untitled") if note.title == EMPTY_TITLE else note.title


def _date_label(iso: str) -> str:
    try:
        return today_label(date.fromisoformat(iso))
    except (TypeError, ValueError):
        return ""


# --------------------------------------------------------------------------- colors
def _rgb(widget, color):
    if isinstance(color, str) and len(color) == 7 and color[0] == "#":     # "#RRGGBB": no need to ask Tk
        try:
            return tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        except ValueError:
            pass
    return tuple(v / 65535 for v in widget.winfo_rgb(color))


def _mix(widget, a, b, t):
    ra, rb = _rgb(widget, a), _rgb(widget, b)
    return "#%02X%02X%02X" % tuple(round((x + (y - x) * t) * 255) for x, y in zip(ra, rb))


def shade(widget, color, steps=1):
    """``color`` ``steps`` steps darker (lighter on dark colors), keeping its hue."""
    r, g, b = _rgb(widget, color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    dark = 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.5
    l = min(1.0, l + 0.06 * steps) if dark else max(0.0, l - 0.07 * steps)
    return "#%02X%02X%02X" % tuple(round(v * 255) for v in colorsys.hls_to_rgb(h, l, s))


def opposite_color(widget, theme, bg):
    """The text cursor's color: the main theme color's opposite hue (보색), made dark on a
    light memo and light on a dark one so the thin cursor is easy to see. A theme with no
    hue (white, gray, black) gives a plain gray cursor."""
    r, g, b = _rgb(widget, theme)
    h, _l, s = colorsys.rgb_to_hls(r, g, b)
    br, bg_, bb = _rgb(widget, bg)
    dark_bg = 0.2126 * br + 0.7152 * bg_ + 0.0722 * bb < 0.5
    s = 0.0 if s < 0.08 or max(r, g, b) - min(r, g, b) < 0.04 else max(s, 0.7)
    l = 0.72 if dark_bg else 0.38
    return "#%02X%02X%02X" % tuple(round(v * 255) for v in colorsys.hls_to_rgb((h + 0.5) % 1.0, l, s))


# readable colors (WCAG 2 contrast): text and marks are worked out to reach a contrast with
# what they sit on, so any memo or theme color, a strong red too, stays readable
TEXT_CONTRAST = 4.5         # text: memo text, day numbers, weekday letters
MARK_CONTRAST = 3.0         # marks and icons: memo bars under a day, selection lines
TINT_BELOW = 7.0            # a color whose best text reads under this gets a pale page in its hue
TINT_LUMINANCE = 0.80       # ... this light (WCAG luminance); the color itself goes on the bar and frame
DARK_INK, LIGHT_INK = "#202020", "#F3F3F3"
_readable_made: dict = {}


def _hls(h, l, s):
    return "#%02X%02X%02X" % tuple(round(v * 255) for v in colorsys.hls_to_rgb(h, l, s))


def luminance(widget, color) -> float:
    """WCAG relative luminance: 0 black .. 1 white."""
    r, g, b = (v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in _rgb(widget, color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(widget, a, b) -> float:
    """WCAG contrast ratio of two colors: 1 .. 21."""
    la, lb = sorted((luminance(widget, a), luminance(widget, b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def ink_for(widget, bg) -> str:
    """Text on ``bg``: the near-black or near-white that reads better there (pure black or
    white when that one stays under TEXT_CONTRAST)."""
    dark = contrast(widget, "#000000", bg) >= contrast(widget, "#FFFFFF", bg)
    ink, plain = (DARK_INK, "#000000") if dark else (LIGHT_INK, "#FFFFFF")
    return ink if contrast(widget, ink, bg) >= TEXT_CONTRAST else plain


def text_contrast(widget, color) -> float:
    """How well text reads on ``color``: its ink's contrast."""
    return contrast(widget, ink_for(widget, color), color)


def needs_tint(widget, color) -> bool:
    """A color too strong for text: it gets a pale page unless kept solid (Settings)."""
    return text_contrast(widget, color) < TINT_BELOW


def readable(widget, color, bg, need) -> str:
    """``color``, lighter or darker (same hue and saturation) just enough to reach ``need``
    against ``bg``; unchanged when it does already. If no shade of it gets there, ``bg``'s ink."""
    key = (str(color).upper(), str(bg).upper(), need)
    if key not in _readable_made:
        found = color if contrast(widget, color, bg) >= need else None
        h, l0, s = colorsys.rgb_to_hls(*_rgb(widget, color))
        for step in range(1, 101) if found is None else ():
            for l in (l0 - step / 100, l0 + step / 100):
                if found is None and 0 <= l <= 1 and contrast(widget, _hls(h, l, s), bg) >= need:
                    found = _hls(h, l, s)
            if found is not None:
                break
        _readable_made[key] = found or ink_for(widget, bg)
    return _readable_made[key]


def pale(widget, color) -> str:
    """A pale page in ``color``'s hue, as light as TINT_LUMINANCE."""
    h, l, s = colorsys.rgb_to_hls(*_rgb(widget, color))
    s = min(s, 0.85)
    while l < 1 and luminance(widget, _hls(h, l, s)) < TINT_LUMINANCE:
        l = min(1.0, l + 0.005)
    return _hls(h, l, s)


def _at_least(widget, bg, toward, t, need):
    """``bg`` mixed ``t`` of the way to ``toward``, or further until it reaches ``need`` against ``bg``."""
    while t < 1 and contrast(widget, _mix(widget, bg, toward, t), bg) < need:
        t = min(1.0, t + 0.02)
    return _mix(widget, bg, toward, t)


def accent_color(widget, theme, bg):
    """A stronger shade of the main theme color for outlines ("here it is"): its hue, made
    vivid, dark enough on a light memo and light enough on a dark one. A theme with no hue
    gives gray."""
    r, g, b = _rgb(widget, theme)
    h, _l, s = colorsys.rgb_to_hls(r, g, b)
    br, bg_, bb = _rgb(widget, bg)
    dark_bg = 0.2126 * br + 0.7152 * bg_ + 0.0722 * bb < 0.5
    s = 0.0 if s < 0.08 or max(r, g, b) - min(r, g, b) < 0.04 else max(s, 0.7)
    l = 0.7 if dark_bg else 0.55
    return "#%02X%02X%02X" % tuple(round(v * 255) for v in colorsys.hls_to_rgb(h, l, s))


def _span_label(note) -> str:
    """The memo's day, or its period ("11/21 ~ 11/25")."""
    if note.end_date:
        return f"{_date_label(note.date)} ~ {_date_label(note.end_date)}"
    return _date_label(note.date)


def fit_text(text: str, room: int, measure, min_char: int, ellipsis: str = "…") -> str:
    """``text`` cut to fit ``room`` px with ``ellipsis`` after it, by binary search (a long memo
    took a measure per character). The same rule as before: the whole text only if text +
    ellipsis fits; else the longest prefix that fits with it, separators trimmed; else the
    ellipsis alone. ``min_char``: the narrowest glyph's width, to cut a long text short first."""
    if not text:
        return ""
    if measure(text + ellipsis) <= room:
        return text
    lo, hi = 0, min(len(text) - 1, room // max(1, min_char) + 2)
    while lo < hi:                          # the longest prefix with measure(prefix + ellipsis) <= room
        mid = (lo + hi + 1) // 2
        if measure(text[:mid] + ellipsis) <= room:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip(" ·") + ellipsis


def _ease_out(t):
    return 1 - (1 - t) ** 3


def animate(widget, key, ms, step, done=None, ease=_ease_out, kind="move"):
    """Call ``step(k)`` once a frame for ``ms`` milliseconds, k easing (``ease``, out by
    default) from 0 to 1, then ``done()``: on the app's one frame clock (anim.FrameClock),
    paced to the display. The same key on the same widget replaces the running one. Stops
    quietly when the widget is gone. ``kind``: "move" or "fade" (Animations: Reduced keeps fades)."""
    anim.clock_of(widget).animate(widget, key, ms, step, done, ease, kind)


def stop_animation(widget, key):
    try:
        anim.clock_of(widget).stop(widget, key)
    except tk.TclError:
        pass


def animating(widget, key) -> bool:
    try:
        return anim.clock_of(widget).active(widget, key)
    except tk.TclError:
        return False


def fade(win, key, start, end, ms, done=None, ease=anim.ease_out):
    """Fade a whole window's opacity (Tk can only fade windows, not the widgets in them). Every
    fade of a window is one "alpha" tween (``key`` is kept for the callers but not used): a fade
    started while another runs turns from where that one is, never jumping to ``start``. A
    fade-out that goes with a move away uses ``ease=anim.ease_in`` (B7)."""
    clock = anim.clock_of(win)
    clock.tween(win, "alpha", end, ms, read=lambda: _alpha(win),
                write=lambda v: win.attributes("-alpha", v),
                frm=None if clock.active(win, "alpha") else start, done=done, ease=ease)


def menu_in(win, x, y, w, h, drop) -> None:
    """A menu or drop-down list opens at (x, y), w x h: it drops ``drop`` px into place (negative:
    it rises, opening upward) while it fades in, over MENU_FADE_MS. Where the Animations setting
    cuts movement it is just there."""
    clock = anim.clock_of(win)
    moves = not clock._instant("move")
    y0 = y - drop if moves else y
    win.geometry(f"{w}x{h}+{x}+{y0}")
    win.attributes("-alpha", 0.0)
    win.deiconify()
    fade(win, "show", 0.0, 1.0, MENU_FADE_MS)
    if moves:
        clock.glide(win, (x, y, x + w, y + h), MENU_FADE_MS, frm=(x, y0, x + w, y0 + h))


def menu_out(win) -> None:
    """A menu closes: it takes no input from now, fades out (ease-in, exit_ms of MENU_FADE_MS), and
    goes."""
    def gone():
        try:
            win.destroy()
        except tk.TclError:
            pass
    try:
        win.attributes("-disabled", True)
    except tk.TclError:
        gone()
        return
    fade(win, "show", _alpha(win), 0.0, anim.exit_ms(MENU_FADE_MS), done=gone, ease=anim.ease_in)


def _alpha(win) -> float:
    try:
        return float(win.attributes("-alpha"))
    except (tk.TclError, ValueError):
        return 1.0


class Colors:
    """Every shade a note needs, derived from its one color. A color too strong for text
    (needs_tint) gets a pale page in its hue, and the color itself goes on the top bar, the
    frame and today's tile, unless Settings keeps it solid (``Colors.keep_solid``).
    ``Colors.of`` reuses the set made earlier for the same color."""

    _made: dict = {}
    solid: frozenset = frozenset()      # colors kept solid (Settings), upper case

    @classmethod
    def of(cls, widget, bg, solid=None):
        """``solid``: True for a surface that must stay this color (a top bar); None: as Settings says."""
        key = str(bg).upper()
        key = (key, key in cls.solid if solid is None else bool(solid))
        if key not in cls._made:
            cls._made[key] = cls(widget, bg, key[1])
        return cls._made[key]

    @classmethod
    def keep_solid(cls, colors):
        cls.solid = frozenset(str(c).upper() for c in colors)

    def __init__(self, widget, bg, solid=False):
        self.color = bg                                   # the color as chosen
        self.tinted = not solid and needs_tint(widget, bg)
        bg = self.bg = pale(widget, bg) if self.tinted else bg
        self.fg = ink_for(widget, bg)
        self.dark = luminance(widget, self.fg) > 0.5      # light text: a dark page
        text = TEXT_CONTRAST if contrast(widget, self.fg, bg) >= TINT_BELOW else MARK_CONTRAST
        self.muted = _at_least(widget, bg, self.fg, 0.55, MARK_CONTRAST)
        self.hover = _at_least(widget, bg, self.fg, 0.10, 1.15)
        self.border = _at_least(widget, bg, self.fg, 0.25, 1.4)
        self.select = _at_least(widget, bg, self.fg, 0.22, 1.5)
        self.well = _mix(widget, bg, self.fg, 0.06)
        self.active = _at_least(widget, bg, self.fg, 0.16, 1.3)    # a format button that is on
        self.line = _mix(widget, bg, self.fg, 0.12)       # thin separator lines
        self.bar = self.color if self.tinted else shade(widget, bg, 1)     # top bar, like Windows Sticky Notes
        self.frame = self.color if self.tinted else self.border          # the window's thin edge
        self.today = self.color if self.tinted else self.fg              # today's tile in the calendar ...
        self.today_fg = ink_for(widget, self.color) if self.tinted else bg     # ... and its number
        self.danger = readable(widget, "#FF8A80" if self.dark else "#B3261E", self.well, text)
        self.sunday = readable(widget, _mix(widget, "#E5484D", self.fg, 0.15), bg, text)
        self.saturday = readable(widget, _mix(widget, "#3E7BFA", self.fg, 0.15), bg, text)


# --------------------------------------------------------------------------- small widgets
TIP_KEY = "#010203"                 # a color no tooltip uses: see-through, for the rounded corners
TIP_DELAY_MS = 500
TIP_MAX_W = 340                     # px at 100 %: longer lines wrap


def _rounded_card(w, h, radius, fill, border):
    """A rounded card for a window whose TIP_KEY color is see-through. The edge pixels are
    either card or key (no blending with the key color, which would leave a dark rim)."""
    s = 4
    big = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=radius * s, fill=255)
    shape = big.resize((w, h), Image.LANCZOS).point(lambda v: 255 if v >= 128 else 0)
    inner = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(inner).rounded_rectangle((s, s, w * s - 1 - s, h * s - 1 - s), radius=(radius - 1) * s,
                                            fill=255)
    inner = inner.resize((w, h), Image.LANCZOS)
    card = Image.composite(Image.new("RGB", (w, h), ImageColor.getrgb(fill)),
                           Image.new("RGB", (w, h), ImageColor.getrgb(border)), inner)
    return Image.composite(card, Image.new("RGB", (w, h), ImageColor.getrgb(TIP_KEY)), shape)


def _round_rect(x0, y0, x1, y1, r):
    """Points of a rounded rectangle for Canvas.create_polygon(..., smooth=True)."""
    return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
            x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]


class GroupRing:
    """One rounded line in the main theme color around the notes (and docked calendars)
    moving or resizing together: they read as one piece. A see-through window over them."""

    RING_SLACK = 96                 # px at 100 %: room the window keeps around the line, so a resize
                                    # (the line grows a little every frame) does not resize the window

    def __init__(self, app):
        self.app, self.top, self._size, self._frame = app, None, None, None

    def show(self, boxes, near, alpha=1.0):
        """``alpha``: as see-through as the notes it goes around."""
        if self.top is None:
            t = self.top = tk.Toplevel(self.app.root)
            t.withdraw()
            t.overrideredirect(True)
            t.configure(bg=TIP_KEY)
            try:
                t.attributes("-transparentcolor", TIP_KEY)
            except tk.TclError:
                pass
            self.cv = tk.Canvas(t, bg=TIP_KEY, bd=0, highlightthickness=0)
            self.cv.pack(fill="both", expand=True)
        self.color = accent_color(near, self.app.theme_colors().bg, "#FFFFFF")
        self._size = self._frame = self._need = None
        self.move(boxes, now=True)          # (withdrawn: put there now, before it shows)
        self.top.attributes("-alpha", 0.0)
        self.top.deiconify()
        self.top.attributes("-topmost", True)
        fade(self.top, "show", 0.0, alpha, MENU_FADE_MS)

    def move(self, boxes, now=False):
        """Around ``boxes``: the window goes in the frame's one batch with the notes it goes around
        (B6: never a frame behind them); ``now``: at once."""
        if self.top is None or not boxes:
            return
        px = self.app.px
        gap, r, lw = (px(v) for v in GROUP_RING)
        need = (min(b[0] for b in boxes) - gap - lw, min(b[1] for b in boxes) - gap - lw,
                max(b[2] for b in boxes) + gap + lw, max(b[3] for b in boxes) + gap + lw)
        rel = tuple(sorted(tuple(int(v) for v in (b[0] - need[0], b[1] - need[1], b[2] - need[0], b[3] - need[1]))
                           for b in boxes))
        f, last = self._frame, getattr(self, "_need", None)
        if f is not None and last is not None and rel == self._rel and need != last:
            dx, dy = need[0] - last[0], need[1] - last[1]       # the same outline, moved (a drag): the
            f = self._frame = (f[0] + dx, f[1] + dy, f[2] + dx, f[3] + dy)     # window moves, no redraw
        self._need, self._rel = need, rel
        if f is None or need[0] < f[0] or need[1] < f[1] or need[2] > f[2] or need[3] > f[3]:
            if f is None:                   # (the window: the line's box with room to grow; a move
                pad_ = 0                    # shifts it whole, so only a first resize frame takes room)
            else:
                pad_ = px(self.RING_SLACK)
            f = self._frame = (need[0] - pad_, need[1] - pad_, need[2] + pad_, need[3] + pad_)
            self._size = None
        x0, y0 = f[0], f[1]
        w, h = f[2] - f[0], f[3] - f[1]
        shape = tuple(sorted(tuple(int(v) for v in (b[0] - x0, b[1] - y0, b[2] - x0, b[3] - y0)) for b in boxes))
        if shape != self._size:             # the line follows the outline of the boxes, not their bounding box:
            self._size = shape              # each box grown by the gap and the line, in the line's color,
            self.cv.delete("all")           # then each grown by the gap only, see-through
            for a0, b0, a1, b1 in shape:
                self.cv.create_polygon(_round_rect(a0 - gap - lw, b0 - gap - lw, a1 + gap + lw, b1 + gap + lw, r + lw),
                                       smooth=True, fill=self.color, outline="")
            for a0, b0, a1, b1 in shape:
                self.cv.create_polygon(_round_rect(a0 - gap, b0 - gap, a1 + gap, b1 + gap, r),
                                       smooth=True, fill=TIP_KEY, outline="")
        geo = f"{w}x{h}+{x0}+{y0}"
        if geo != getattr(self, "_geo", None):
            self._geo = geo
            if now:
                self.top.geometry(geo)
            else:
                anim.clock_of(self.top).move(self.top, x0, y0, w, h)

    def hide(self):
        if self.top is not None:
            stop_animation(self.top, "show")
            self.top.withdraw()


class Tooltip:
    """A rounded card under the widget (above it near the screen's bottom) after a short
    rest, in the main theme's colors. A tip with more than one line shows its first line
    as a bold title and the rest smaller and gray."""

    app = None                      # set by App: theme colors and screen scale

    def __init__(self, widget, text):
        self.widget, self.text, self.tip, self.job = widget, text, None, None
        self._photo = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    def _schedule(self, _event=None):
        self.hide()
        self.job = self.widget.after(TIP_DELAY_MS, self._show)

    def _show(self):
        self.job = None
        w = self.widget
        if not w.winfo_ismapped() or not self.text:
            return
        app = Tooltip.app
        c = app.theme_colors() if app is not None else Colors.of(w, "#F3F3F3")
        px = app.px if app is not None else (lambda v: v)
        tip = self.tip = tk.Toplevel(w)
        tip.withdraw()
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.configure(bg=TIP_KEY)
        try:
            tip.attributes("-transparentcolor", TIP_KEY)
        except tk.TclError:
            pass
        cv = tk.Canvas(tip, bg=TIP_KEY, bd=0, highlightthickness=0)
        cv.pack()
        lines = self.text.split("\n")
        padx, pady, wrap = px(12), px(8), px(TIP_MAX_W)
        y = pady
        title = cv.create_text(padx, y, anchor="nw", text=lines[0], fill=c.fg, width=wrap,
                               font=ui_font(10, len(lines) > 1))
        y = cv.bbox(title)[3] + px(3)
        if len(lines) > 1:
            cv.create_text(padx, y, anchor="nw", text="\n".join(lines[1:]), fill=c.muted, width=wrap,
                           font=(UI_FONT, 9))
        x0, y0, x1, y1 = cv.bbox("all")
        width, height = x1 + padx, y1 + pady
        self._photo = ImageTk.PhotoImage(_rounded_card(width, height, px(7), c.bg, c.border), master=tip)
        cv.configure(width=width, height=height)
        cv.tag_lower(cv.create_image(0, 0, anchor="nw", image=self._photo))
        x0, y0 = w.winfo_rootx(), w.winfo_rooty()
        # a pop-up takes no space but stays on its widget's screen (S1)
        area = app.area_of((x0, y0, x0 + w.winfo_width(), y0 + w.winfo_height())) if app is not None else None
        x = x0 + w.winfo_width() // 2 - width // 2
        y = y0 + w.winfo_height() + px(6)
        if area is not None:
            x = min(max(x, area[0] + 4), area[2] - width - 4)
            if y + height > area[3]:
                y = y0 - height - px(6)
        tip.geometry(f"+{x}+{y}")
        tip.attributes("-alpha", 0.0)
        tip.deiconify()
        fade(tip, "show", 0.0, 1.0, TIP_FADE_MS)

    def hide(self, _event=None):
        if self.job:
            try:
                self.widget.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None
        if self.tip is not None:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None


def _icon_font_file(family):
    name = ICON_FONT_FILES.get(family)
    if not name:
        return None
    for folder in (Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
                   Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"):
        if (folder / name).is_file():
            return folder / name
    return None


def _with_plus_badge(img):
    """Cut a round hole in the bottom-right corner of a glyph and put a + in it."""
    w, h = img.size
    canvas = Image.new("L", (int(w * 1.12), int(h * 1.12)), 0)
    canvas.paste(img, (0, 0))
    d = ImageDraw.Draw(canvas)
    cx, cy, r = w * 0.80, h * 0.80, w * 0.34
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=0)
    arm, half = w * 0.24, max(1.0, w * 0.045)
    d.rectangle((cx - arm, cy - half, cx + arm, cy + half), fill=255)
    d.rectangle((cx - half, cy - arm, cx + half, cy + arm), fill=255)
    return canvas.crop(canvas.getbbox())


class IconPainter:
    """Draws icon-font glyphs as images. Each glyph is cut to its ink and scaled into
    the same square, so every icon looks equally big and sits exactly in the middle,
    whatever room the font leaves around it. Without the font file, icons fall back
    to plain text."""

    RENDER = 256
    _masks: dict = {}               # (font, glyph, box, badge) -> L image, shared by all windows

    def __init__(self, root, family):
        self.root = root
        self.path = _icon_font_file(family)
        self._photos: dict = {}
        try:
            self._font = ImageFont.truetype(str(self.path), self.RENDER) if self.path else None
        except Exception:
            self._font = None
        self.available = self._font is not None

    def mask(self, glyph, box, badge=False, mirror=False):
        key = (str(self.path), glyph, box, badge, mirror)
        if key not in IconPainter._masks:
            s = self.RENDER
            if glyph == TODAY_GLYPH:                    # drawn, not a font character
                img = _today_mask(s + 32)
            else:
                img = Image.new("L", (s * 2, s * 2), 0)
                ImageDraw.Draw(img).text((s // 2, s // 2), glyph, font=self._font, fill=255)
            img = img.crop(img.getbbox() or (0, 0, 1, 1))
            if badge:
                img = _with_plus_badge(img)
            w, h = img.size
            scale = box * OPTICAL_SCALE.get(glyph, 1.0) / max(w, h)
            size = (max(1, round(w * scale)), max(1, round(h * scale)))
            img = img.resize(size, Image.LANCZOS)
            if mirror:
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            square = Image.new("L", (box, box), 0)
            square.paste(img, ((box - size[0]) // 2, (box - size[1]) // 2))
            IconPainter._masks[key] = square
        return IconPainter._masks[key]

    def photo(self, glyph, color, box, badge=False, mirror=False):
        key = (glyph, color, box, badge, mirror)
        if key not in self._photos:
            mask = self.mask(glyph, box, badge, mirror)
            rgba = Image.new("RGBA", mask.size, ImageColor.getrgb(color)[:3] + (0,))
            rgba.putalpha(mask)
            self._photos[key] = ImageTk.PhotoImage(rgba, master=self.root)
        return self._photos[key]


def bin_photo(app, color, dot=None, box=BIN_ICON_BOX):
    """The bin icon, ``box`` px big, in ``color``. With ``dot`` (a colour): a small dot on the icon's
    top-right corner, with a thin ring of the icon cut away around it so the dot reads on any page.
    Drawn smooth (coverage from 16 x 16 samples a pixel). None without the icon font."""
    if not app.icons.available:
        return None
    px = app.px
    b, pad = px(box), px(4)                 # room above and to the right for the dot's ring
    key = ("bin", color, dot, b)
    photo = app.icons._photos.get(key)
    if photo is None:
        mask = app.icons.mask(GLYPH["trash"], b)
        alpha = Image.new("L", (b + pad, b + pad), 0)
        alpha.paste(mask, (0, pad))
        img = Image.new("RGBA", alpha.size, ImageColor.getrgb(color)[:3] + (0,))
        if dot:
            s = 16
            ink = mask.getbbox() or (0, 0, b, b)
            cx, cy = (ink[2] - px(1)) * s, (pad + ink[1] + px(1)) * s     # on the lid's right end
            big = (alpha.width * s, alpha.height * s)

            def disc(r):
                layer = Image.new("L", big, 0)
                ImageDraw.Draw(layer).ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
                return layer.reduce(s)
            hole, spot = disc(4.3 * app.scale * s), disc(2.8 * app.scale * s)
            alpha = Image.composite(Image.new("L", alpha.size, 0), alpha, hole)   # the ring cut away
            img.putalpha(alpha)
            top = Image.new("RGBA", alpha.size, ImageColor.getrgb(dot)[:3] + (0,))
            top.putalpha(spot)
            img = Image.alpha_composite(img, top)
        else:
            img.putalpha(alpha)
        photo = ImageTk.PhotoImage(img, master=app.root)
        app.icons._photos[key] = photo
    return photo


def size_icon(app, which, color, box=SMALL_ICON_BOX):
    """A small / medium / large rounded box (the tidy sizes), drawn smooth."""
    box = app.px(box)
    key = ("size", which, color, box)
    photo = app.icons._photos.get(key)
    if photo is None:
        s = 4
        full = box * s
        k = {"small": 0.5, "medium": 0.72, "large": 0.96}[which]
        w, h = round(full * k), round(full * k * 0.82)
        x0, y0 = (full - w) // 2, (full - h) // 2
        img = Image.new("RGBA", (full, full), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle((x0, y0, x0 + w - 1, y0 + h - 1), radius=s * 2,
                                              outline=ImageColor.getrgb(color)[:3] + (255,), width=round(s * 1.3))
        photo = app.icons._photos[key] = ImageTk.PhotoImage(img.resize((box, box), Image.LANCZOS),
                                                            master=app.root)
    return photo


def blank_icon(app):
    """A see-through square: keeps an icon's place (a Label's width counts in pixels only with an image)."""
    photo = app.icons._photos.get("blank")
    if photo is None:
        box = app.px(SMALL_ICON_BOX)
        photo = app.icons._photos["blank"] = ImageTk.PhotoImage(Image.new("RGBA", (box, box), (0, 0, 0, 0)),
                                                                master=app.root)
    return photo


def menu_icon(app, label, icon, fg):
    if isinstance(icon, tuple) and icon[0] == "size":
        label.configure(image=size_icon(app, icon[1], fg), text="")
    else:
        paint_glyph(app, label, icon, fg)


def empty_page(app, parent, c, glyph, text):
    """An empty list or bin: a big faint icon over one line."""
    px = app.px
    box = tk.Frame(parent, bg=c.bg, bd=0)
    box.pack(pady=(px(18), px(6)))
    pic = tk.Label(box, bg=c.bg, bd=0)
    pic.pack()
    paint_glyph(app, pic, glyph, _mix(parent, c.muted, c.bg, 0.35), box=24)
    tk.Label(box, text=text, bg=c.bg, fg=c.muted, font=(UI_FONT, 9)).pack(pady=(px(6), 0))
    return box


def paint_glyph(app, label, glyph, fg, box=SMALL_ICON_BOX, mirror=False):
    """Show an icon on a plain Label (same drawing as the bar buttons)."""
    if app.icons.available:
        label.configure(image=app.icons.photo(glyph, fg, app.px(box), mirror=mirror), text="")
    else:
        label.configure(text=glyph, fg=fg, font=(app.icon_font, max(6, round(box * 0.7))))


class IconButton(tk.Canvas):
    """A flat icon button that darkens on hover. ``overlay`` adds a small + badge
    (the sticky-note-with-plus icon)."""

    def __init__(self, master, app, glyph, command, tip, overlay=None, box=ICON_BOX, width=24, height=30):
        super().__init__(master, width=app.px(width), height=app.px(height), bd=0, highlightthickness=0)
        self.app, self.glyph, self.overlay, self.box = app, glyph, overlay, box
        self._command = command
        self._bg = self._hover = self._on_bg = self._on_hover = "#FFFFFF"
        self._fg = self.ink_color = "#000000"
        self._x0 = self._y0 = 0
        self.photo = None
        self.active = False             # format buttons: shaded while their format is on
        self.tooltip = Tooltip(self, tip)
        self.bind("<Enter>", lambda e: self.configure(bg=self._on_hover if self.active else self._hover), add="+")
        self.bind("<Leave>", lambda e: self.configure(bg=self._rest()), add="+")
        self.bind("<ButtonRelease-1>", self._release)

    def _rest(self):
        return self._on_bg if self.active else self._bg

    def set_active(self, on):
        if bool(on) != self.active:
            self.active = bool(on)
            self.configure(bg=self._rest())

    def _release(self, event):
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self._command()

    def set_glyph(self, glyph):
        self.glyph = glyph
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = int(self.cget("width")), int(self.cget("height"))
        box = self.app.px(self.box)
        self._x0, self._y0 = (w - box) // 2, (h - box) // 2
        if self.app.icons.available:
            self.photo = self.app.icons.photo(self.glyph, self._fg, box, badge=self.overlay is not None)
            self.create_image(self._x0, self._y0, anchor="nw", image=self.photo)
            return
        size = max(6, round(self.box * 0.72))           # no icon font file: plain text glyphs
        self.create_text(w / 2, h / 2, text=self.glyph, font=(self.app.icon_font, size), fill=self._fg)
        if self.overlay:
            self.create_text(w / 2 - 1, h / 2 - 1, text=self.overlay,
                             font=(self.app.icon_font, max(5, size - 4), "bold"), fill=self._fg)

    def set_ink(self, color):
        """Draw the icon in ``color`` (a fade steps through colours: see CalendarPopup._draw_head)."""
        if color != self._fg:
            self._fg = self.ink_color = color
            self._draw()

    def ink_box(self):
        """Where the icon's ink is, in this button's pixels: (x0, y0, x1, y1)."""
        box = self.app.px(self.box)
        x0, y0, x1, y1 = self.app.icons.mask(self.glyph, box, self.overlay is not None).getbbox()
        return self._x0 + x0, self._y0 + y0, self._x0 + x1, self._y0 + y1

    def recolor(self, colors, strong=False):
        self._bg, self._hover = colors.bg, colors.hover
        self._on_bg, self._on_hover = colors.active, colors.select
        self._fg = self.ink_color = colors.fg if strong else colors.muted
        self.configure(bg=self._rest())
        self._draw()


TODAY_GLYPH = "\x00today"       # not a font character: IconPainter draws it with _today_mask


def _today_mask(size):
    """The "today" icon: a calendar page with two rings and a dot. Drawn like the font
    icons, 16-unit strokes on a 224-unit page, so IconPainter cuts and scales it exactly
    like the lock, expand and close icons next to it."""
    st = 16
    img = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(img)
    left, top = 16, 30
    right, bottom = left + 224, top + 224
    d.rounded_rectangle((left, top, right, bottom), radius=38, outline=255, width=st)
    band = top + 66                                          # the line under the page's head
    d.rectangle((left, band, right, band + st - 1), fill=255)
    for x in (left + 65, left + 159):                        # the two rings, round at both ends
        d.rectangle((x - st // 2, top - 13, x + st // 2 - 1, top + 40), fill=255)
        for y in (top - 13, top + 40):
            d.ellipse((x - st // 2, y - st // 2, x + st // 2 - 1, y + st // 2 - 1), fill=255)
    cx, cy, r = left + 112, top + 145, 29                    # the dot: today
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    return img


class FlatButton(tk.Label):
    """A text button that looks like part of the note."""

    def __init__(self, master, text, command, danger=False, **kw):
        k = max(1.0, master.winfo_fpixels("1i") / 96)      # (App.scale)
        super().__init__(master, text=text, cursor="hand2", bd=0, padx=round(9 * k), pady=round(4 * k),
                         font=(UI_FONT, 9), **kw)
        self._command, self.danger = command, danger
        self._bg = self._hover = "#FFFFFF"
        self.bind("<Enter>", lambda e: self.configure(bg=self._hover))
        self.bind("<Leave>", lambda e: self.configure(bg=self._bg))
        self.bind("<ButtonRelease-1>", self._release)

    def _release(self, event):
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self._command()

    def recolor(self, colors):
        self._bg, self._hover = colors.well, colors.hover
        self.configure(bg=colors.well, fg=colors.danger if self.danger else colors.fg)


class Slider(tk.Canvas):
    """A thin track with a round knob, drawn in the note's colors.
    Click anywhere on the track to jump there; drag to adjust."""

    def __init__(self, master, app, from_, to, command):
        super().__init__(master, height=app.px(20), bd=0, highlightthickness=0, cursor="hand2")
        self.app, self.lo, self.hi, self.command = app, from_, to, command
        self.value = from_
        self.colors = None
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._pointer)
        self.bind("<B1-Motion>", self._pointer)

    def _span(self):
        r = self.app.px(7)
        return r + 1, max(r + 2, self.winfo_width() - r - 1)

    def _pointer(self, event):
        x0, x1 = self._span()
        frac = min(1.0, max(0.0, (event.x - x0) / (x1 - x0)))
        self.set(round(self.lo + frac * (self.hi - self.lo)))
        self.command(self.value)

    def set(self, value):
        self.value = min(self.hi, max(self.lo, int(round(float(value)))))
        self._draw()

    def _draw(self):
        """Drawn 4x larger with Pillow and scaled down, so the knob and track are smooth."""
        c = self.colors
        if c is None:
            return
        w, h = max(8, self.winfo_width()), int(self.cget("height"))
        s = 4
        x0, x1 = self._span()
        y, r, t = h / 2, self.app.px(7), self.app.px(2)
        x = x0 + (self.value - self.lo) / (self.hi - self.lo) * (x1 - x0)
        img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((x0 * s, (y - t) * s, x1 * s, (y + t) * s), radius=t * s, fill=c.border)
        d.rounded_rectangle((x0 * s, (y - t) * s, max(x, x0 + 2 * t) * s, (y + t) * s), radius=t * s, fill=c.muted)
        d.ellipse(((x - r) * s, (y - r) * s, (x + r) * s, (y + r) * s), fill=c.fg, outline=c.bg, width=2 * s)
        photo = ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS), master=self)
        self.delete("all")                  # items first: Tk 9 dislikes images freed under them
        self.create_image(0, 0, anchor="nw", image=photo)
        self._photo = photo

    def recolor(self, colors):
        self.colors = colors
        self.configure(bg=colors.bg)
        self._draw()


def _triangle(color, size, up):
    """A smooth (anti-aliased) triangle pointing up or down, as a Pillow image."""
    s = 4
    w, h = size
    img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    top, bottom, left, right = h * s * 0.22, h * s * 0.78, w * s * 0.12, w * s * 0.88
    pts = ([(w * s / 2, top), (right, bottom), (left, bottom)] if up
           else [(left, top), (right, top), (w * s / 2, bottom)])
    ImageDraw.Draw(img).polygon(pts, fill=color)
    return img.resize((w, h), Image.LANCZOS)


class NumberBox(tk.Frame):
    """A whole-number field with small smooth up/down triangles, in the note's colors.
    Type a number (Enter or leaving the field applies it), click a triangle, use the
    mouse wheel or the Up/Down keys."""

    def __init__(self, master, app, from_, to, command, width=3):
        super().__init__(master, bd=0)
        self.app, self.lo, self.hi, self.command = app, from_, to, command
        self.var = tk.StringVar(master)
        self._last = from_
        self._photos = ()
        px = app.px
        self.entry = tk.Entry(self, textvariable=self.var, width=width, bd=0, relief="flat",
                              highlightthickness=0, font=(UI_FONT, 10), justify="center")
        self.entry.pack(side="left", ipady=px(3), padx=(px(4), 0))
        self.arrows = tk.Canvas(self, width=px(12), height=px(22), bd=0, highlightthickness=0, cursor="hand2")
        self.arrows.pack(side="left", padx=(px(1), px(3)))
        self.arrows.bind("<ButtonRelease-1>", lambda e: self.step(1 if e.y < self.arrows.winfo_height() / 2 else -1))
        for w in (self, self.entry, self.arrows):
            w.bind("<MouseWheel>", lambda e: (self.step(1 if e.delta > 0 else -1), "break")[1])
        self.entry.bind("<Return>", lambda e: self.apply())
        self.entry.bind("<FocusOut>", lambda e: self.apply())
        self.entry.bind("<Up>", lambda e: (self.step(1), "break")[1])
        self.entry.bind("<Down>", lambda e: (self.step(-1), "break")[1])

    def set(self, value):
        self._last = int(value)
        self.var.set(str(self._last))

    def _clamp(self, value):
        return max(self.lo, min(self.hi, int(value)))

    def apply(self):
        try:
            value = self._clamp(round(float(self.var.get().strip().rstrip("%"))))
        except ValueError:
            self.var.set(str(self._last))
            return
        self.var.set(str(value))
        if value != self._last:
            self._last = value
            self.command(value)

    def step(self, delta):
        try:
            current = int(float(self.var.get()))
        except ValueError:
            current = self._last
        self.var.set(str(self._clamp(current + delta)))
        self.apply()

    def recolor(self, c):
        px = self.app.px
        self.configure(bg=c.well)
        self.entry.configure(bg=c.well, fg=c.fg, insertbackground=self.app.cursor_color(c.well),
                             selectbackground=c.select, selectforeground=c.fg)
        self.arrows.configure(bg=c.well)
        size = (px(9), px(7))
        up = ImageTk.PhotoImage(_triangle(c.muted, size, True), master=self.arrows)
        down = ImageTk.PhotoImage(_triangle(c.muted, size, False), master=self.arrows)
        h = int(self.arrows.cget("height"))
        self.arrows.delete("all")
        self.arrows.create_image(px(6), h / 2 - px(1), anchor="s", image=up)
        self.arrows.create_image(px(6), h / 2 + px(1), anchor="n", image=down)
        self._photos = (up, down)


class FontPicker(tk.Frame):
    """The font name in a flat field with a smooth down-triangle; clicking opens a
    list of fonts in the note's own colors (type a letter to jump)."""

    def __init__(self, master, app, command):
        super().__init__(master, bd=0, cursor="hand2")
        self.app, self.command = app, command
        self.value = ""
        self.colors = None
        self.popup = None
        self._photo = None
        px = app.px
        self.label = tk.Label(self, anchor="w", font=(UI_FONT, 10), padx=px(6), pady=px(3), cursor="hand2")
        self.label.pack(side="left", fill="x", expand=True)
        self.arrow = tk.Label(self, bd=0, padx=px(6), cursor="hand2")
        self.arrow.pack(side="right")
        for w in (self, self.label, self.arrow):
            w.bind("<ButtonRelease-1>", lambda e: self.open())

    def set(self, family):
        self.value = family
        self.label.configure(text=family)

    def open(self):
        if self.popup is not None:
            self.close()
            return
        c, px = self.colors, self.app.px
        top = tk.Toplevel(self.winfo_toplevel())
        top.withdraw()
        top.overrideredirect(True)
        top.configure(bg=c.border)
        lb = tk.Listbox(top, bd=0, highlightthickness=0, activestyle="none", exportselection=False,
                        bg=c.bg, fg=c.fg, selectbackground=c.select, selectforeground=c.fg,
                        font=(UI_FONT, 10), height=12)
        lb.pack(fill="both", expand=True, padx=1, pady=1)
        families = self.app.font_families()
        for fam in families:
            lb.insert("end", fam)
        if self.value in families:
            i = families.index(self.value)
            lb.selection_set(i)
            lb.see(i)
        self.popup, self.listbox = top, lb
        lb.bind("<ButtonRelease-1>", lambda e: self._choose_index(lb.nearest(e.y)))
        lb.bind("<Return>", lambda e: self._choose_index(lb.index("active")))
        lb.bind("<Escape>", lambda e: self.close())
        lb.bind("<Key>", self._jump)
        lb.bind("<FocusOut>", lambda e: top.after(150, self._close_if_away))
        top.update_idletasks()
        w, h = max(self.winfo_width(), px(160)), top.winfo_reqheight()
        x, y = self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + px(2)
        area = self.app.area_of((x, self.winfo_rooty(), x + self.winfo_width(), y))     # (its own screen)
        up = y + h > area[3]
        if up:
            y = self.winfo_rooty() - h - px(2)
        menu_in(top, x, y, w, h, px(MENU_DROP) * (-1 if up else 1))
        top.attributes("-topmost", True)
        lb.focus_force()

    def _jump(self, event):
        ch = (event.char or "").casefold()
        if not ch.strip():
            return None
        names = self.listbox.get(0, "end")
        start = (self.listbox.curselection() or (-1,))[0] + 1
        for i in list(range(start, len(names))) + list(range(0, start)):
            if names[i].casefold().startswith(ch):
                self.listbox.selection_clear(0, "end")
                self.listbox.selection_set(i)
                self.listbox.activate(i)
                self.listbox.see(i)
                break
        return "break"

    def choose(self, family):
        self.set(family)
        self.close()
        self.command(family)

    def _choose_index(self, index):
        if self.popup is not None and 0 <= index < self.listbox.size():
            self.choose(self.listbox.get(index))

    def _close_if_away(self):
        if self.popup is None:
            return
        try:
            focus = self.popup.focus_get()
        except (KeyError, tk.TclError):
            focus = None
        if focus is None or focus.winfo_toplevel() is not self.popup:
            self.close()

    def close(self):
        if self.popup is not None:
            popup, self.popup = self.popup, None
            menu_out(popup)

    def recolor(self, c):
        self.colors = c
        self.configure(bg=c.well)
        self.label.configure(bg=c.well, fg=c.fg)
        self.arrow.configure(bg=c.well)
        self._photo = ImageTk.PhotoImage(_triangle(c.muted, (self.app.px(9), self.app.px(7)), False),
                                         master=self.arrow)
        self.arrow.configure(image=self._photo)


SCROLL_W = 5                     # the scroll thumb shown while scrolling (px at 100 %) ...
SCROLL_W_HOVER = 8               # ... under the mouse or dragged
SCROLL_MIN = 24                  # ... never shorter than this
SCROLL_HIDE_MS = 900             # it fades out this long after the view last moved ...
SCROLL_FADE_MS = anim.LONG       # ... taking this long


class OverlayScroll:
    """A thin rounded thumb in the main theme color over the right edge of ``target`` (a Text
    or a Canvas): it shows while the view moves (wheel, typing, a drag) and fades out after
    SCROLL_HIDE_MS. Dragging it scrolls; a click beside it jumps there. It takes ``target``'s
    yscrollcommand. Placed ``in_`` the target, so it hides with it."""

    def __init__(self, target, app, units=1):
        self.target, self.app, self.units = target, app, units
        px = app.px
        self.width = px(SCROLL_W_HOVER) + px(3)
        self.cv = tk.Canvas(target.master, width=self.width, bd=0, highlightthickness=0, cursor="arrow")
        self.bg, self.thumb = "#FFFFFF", "#888888"
        self._view = (0.0, 1.0)
        self._shown = self._hover = False
        self._k = 1.0                       # 1 = solid, 0 = faded into the page
        self._drag = None
        self._job = None
        target.configure(yscrollcommand=self._set)
        cv = self.cv
        cv.bind("<Configure>", lambda e: self._draw())
        cv.bind("<Enter>", lambda e: self._set_hover(True))
        cv.bind("<Leave>", lambda e: self._set_hover(False))
        cv.bind("<ButtonPress-1>", self._press)
        cv.bind("<B1-Motion>", self._motion)
        cv.bind("<ButtonRelease-1>", self._release)
        cv.bind("<MouseWheel>", self._wheel)

    def recolor(self, bg):
        self.bg = bg
        accent = accent_color(self.target, self.app.theme_colors().color, bg)
        self.thumb = readable(self.target, accent, bg, MARK_CONTRAST)    # seen on a page of its own hue too
        self.cv.configure(bg=bg)
        self._draw()

    def _overflows(self):
        return self._view[1] - self._view[0] < 0.999

    def _set(self, first, last):
        old, self._view = self._view, (float(first), float(last))
        if not self._overflows():
            self._hide(now=True)
            return
        if self._view[0] != old[0]:         # the view moved (not just more text laid out)
            self.flash()
        elif self._shown:
            self._draw()

    def flash(self):
        """Show the thumb (solid) and fade it out a moment after."""
        if not self._overflows():
            return
        stop_animation(self.cv, "fade")
        self._k = 1.0
        if not self._shown:
            self._shown = True
            self.cv.place(in_=self.target, relx=1.0, rely=0.0, relheight=1.0, anchor="ne", width=self.width)
            tk.Misc.tkraise(self.cv)
        self._draw()
        if self._job is not None:
            self.cv.after_cancel(self._job)
        self._job = self.cv.after(SCROLL_HIDE_MS, self._hide)

    def _hide(self, now=False):
        self._job = None
        if not self._shown:
            return
        if now:
            stop_animation(self.cv, "fade")
            self._shown = False
            self.cv.place_forget()
            return
        if self._hover or self._drag is not None:   # it stays while it is in use
            self._job = self.cv.after(SCROLL_HIDE_MS, self._hide)
            return

        def step(k):
            self._k = 1.0 - k
            self._draw()
        animate(self.cv, "fade", SCROLL_FADE_MS, step, lambda: self._hide(now=True), ease=anim.ease_in, kind="fade")

    def _geometry(self):
        """(x, y0, y1, w) of the thumb's line on the canvas."""
        px = self.app.px
        h = max(1, self.cv.winfo_height())
        pad = px(3)
        track = max(1, h - 2 * pad)
        first, last = self._view
        length = max(px(SCROLL_MIN), (last - first) * track)
        free = max(0.0, track - length)
        span = max(1e-6, 1.0 - (last - first))
        y0 = pad + free * min(1.0, first / span)
        w = px(SCROLL_W_HOVER if (self._hover or self._drag is not None) else SCROLL_W)
        x = self.width - px(2) - w / 2
        return x, y0 + w / 2, y0 + length - w / 2, w, track, length

    def _draw(self):
        cv = self.cv
        cv.delete("all")
        if not self._shown:
            return
        x, y0, y1, w, _track, _len = self._geometry()
        color = _mix(cv, self.bg, self.thumb, self._k)
        cv.create_line(x, y0, x, max(y0, y1), width=w, capstyle="round", fill=color)

    def _set_hover(self, on):
        self._hover = on
        if on:
            self.flash()
        else:
            self._draw()

    def _press(self, e):
        _x, y0, y1, w, track, length = self._geometry()
        if not (y0 - w / 2 <= e.y <= y1 + w / 2):   # beside the thumb: jump so it is centred there
            first = (e.y - self.app.px(3) - length / 2) / track
            self.target.yview_moveto(max(0.0, first))
        self._drag = (e.y, self._view[0], track)
        self.flash()

    def _motion(self, e):
        if self._drag is None:
            return
        y, first, track = self._drag
        _x, _y0, _y1, _w, _t, length = self._geometry()
        visible = self._view[1] - self._view[0]
        free = max(1.0, track - length)
        span = 1.0 - visible
        self.target.yview_moveto(max(0.0, first + (e.y - y) / free * span))

    def _release(self, _e):
        self._drag = None
        self.flash()

    def _wheel(self, e):
        steps = -1 if e.delta > 0 else 1
        self.target.yview_scroll(steps * self.units, "units")
        return "break"


class ScrollArea:
    """A vertically scrolling frame (mouse wheel; a thin theme-colored thumb while it moves)."""

    def __init__(self, master, app):
        self.canvas = tk.Canvas(master, bd=0, highlightthickness=0, yscrollincrement=app.px(24))
        self.inner = tk.Frame(self.canvas, bd=0)
        self._item = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._item, width=e.width))
        self.scroll = OverlayScroll(self.canvas, app)
        self._listeners: list = []
        self.step = 1                       # units a wheel notch scrolls (see fine_steps)

    def fine_steps(self, notch):
        """Scroll to the pixel (the view can be put anywhere), ``notch`` px a wheel notch."""
        self.canvas.configure(yscrollincrement=1)
        self.step = self.scroll.units = notch       # (the wheel over the thumb as over the list)

    def listen(self, fn):
        """``fn()`` after every change of the view (scrolled, resized, a new scroll room)."""
        if not self._listeners:
            self.canvas.configure(yscrollcommand=self._yscroll)
        self._listeners.append(fn)

    def _yscroll(self, first, last):
        self.scroll._set(first, last)
        for fn in self._listeners:
            fn()

    def wheel(self, event):
        if self.inner.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll((-1 if event.delta > 0 else 1) * self.step, "units")

    def to_top(self):
        self.canvas.yview_moveto(0)

    def show(self, widget):
        """Scroll just enough that ``widget`` (inside the area) is fully seen."""
        self.canvas.update_idletasks()
        total = max(1, self.inner.winfo_height())
        view = self.canvas.winfo_height()
        top = widget.winfo_y()
        bottom = top + widget.winfo_height()
        first = self.canvas.canvasy(0)
        if top < first:
            self.canvas.yview_moveto(top / total)
        elif bottom > first + view:
            self.canvas.yview_moveto(max(0, bottom - view) / total)

    def recolor(self, bg):
        self.canvas.configure(bg=bg)
        self.inner.configure(bg=bg)
        self.scroll.recolor(bg)


def _clipboard_image():
    """An image on the clipboard (copied picture or copied image file), else None."""
    try:
        data = ImageGrab.grabclipboard()
    except Exception:
        return None
    if isinstance(data, Image.Image):
        return data
    for path in data if isinstance(data, list) else ():
        try:
            return _open_image(path)
        except Exception:
            continue
    return None


def _open_image(path):
    with Image.open(path) as img:
        img.load()
        return img.copy()


# Every change to a Text widget goes through its Tcl command. Renaming that command
# and putting this proc in its place lets the app see each insert (typing, paste,
# IME, undo) and each cursor move, after Tk has done it. Errors pass through as is.
_TEXT_PROXY = r"""
namespace eval ::sticky {}
proc ::sticky::text_proxy {w callback args} {
    set orig "${w}__orig"
    switch -- [lindex $args 0] {
        insert {
            set at [$orig index [lindex $args 1]]
            if {[$orig compare $at == end]} {set at [$orig index end-1c]}
            set chars ""
            foreach {s t} [lrange $args 2 end] {append chars $s}
            set result [$orig {*}$args]
            $callback inserted $at [$orig index "$at + [string length $chars] chars"]
            return $result
        }
        delete {
            set at [$orig index [lindex $args 1]]
            set result [$orig {*}$args]
            $callback deleted $at
            return $result
        }
        mark {
            set result [$orig {*}$args]
            if {[lindex $args 1] eq "set" && [lindex $args 2] eq "insert"} {$callback moved}
            return $result
        }
        default {return [$orig {*}$args]}
    }
}
"""


def _picture_photo(app, name, box, master):
    """Memo picture ``name`` shrunk to fit ``box`` (width, height), as a PhotoImage;
    None if the file cannot be read."""
    try:
        img = _open_image(app.store.image_path(name))
        img.thumbnail(box)
        return ImageTk.PhotoImage(img, master=master)
    except Exception:
        return None


def _fill_rich_text(text: tk.Text, body, marks, inline, embed):
    """Add a stored text at the end of ``text``: each INLINE character becomes the next
    picture of ``inline`` (``embed(index, name)`` puts it there) and ``marks`` become tags.
    Positions count a picture as one, as the stored text does."""
    start = text.index("end-1c")
    text.insert("end", body)
    places = [i for i, ch in enumerate(body) if ch == INLINE]
    for pos, name in reversed(list(zip(places, inline))):     # from the end: earlier places stay put
        index = text.index(f"{start}+{pos} indices")
        text.delete(index)
        embed(index, name)
    for kind, s, e in marks:
        text.tag_add(kind, f"{start}+{s} indices", f"{start}+{e} indices")


def _watch_text(text: tk.Text, callback):
    """Call ``callback("inserted", start, end)`` after every insert, ``callback("deleted", at)``
    after every delete and ``callback("moved")`` after every cursor move in ``text``."""
    t = text.tk
    if not t.call("info", "commands", "::sticky::text_proxy"):
        t.eval(_TEXT_PROXY)
    name = text.register(callback)
    t.call("rename", text._w, text._w + "__orig")
    t.call("interp", "alias", "", text._w, "", "::sticky::text_proxy", text._w, name)
    t.call("bind", text._w, "<Destroy>", "+catch {rename %W {}}")


def _finish_typing_first(widget):
    """A click in this text field finishes a half-typed Korean syllable before the
    click moves the cursor (App.finish_typing), so the syllable stays where it was typed."""
    widget.bindtags((FINISH_TYPING_TAG,) + tuple(widget.bindtags()))


def _bind_tree(widget, sequence, handler):
    widget.bind(sequence, handler, add="+")
    for child in widget.winfo_children():
        _bind_tree(child, sequence, handler)


# --------------------------------------------------------------------------- menus
class PopupMenu:
    """A small menu drawn in the memo's own colors. (Tk's menus on Windows ignore
    colors and always look like system menus.) Closes on a choice, Esc, or a
    click anywhere else."""

    current: PopupMenu | None = None

    def __init__(self, app, owner, colors=None):
        # every menu is drawn in the main theme color (Settings), whichever memo it is for
        self.app, self.owner, self.colors = app, owner, app.theme_colors()
        self.items: list = []           # (label, command, checked, danger, icon, key) or None for a line
        self.rows: list = []            # (row frame, text label, item)
        self.top = self.body = None
        self._active = None
        self._had_focus = False

    def add(self, label, command, checked=False, danger=False, icon=None, key=None) -> PopupMenu:
        """``icon``: a GLYPH, or ("size", "small" | "medium" | "large"); ``key``: its shortcut,
        shown as a small chip on the right."""
        self.items.append((label, command, checked, danger, icon, key))
        return self

    def separator(self) -> PopupMenu:
        self.items.append(None)
        return self

    def labels(self):
        return [item[0] for item in self.items if item]

    def checked(self):
        return [item[0] for item in self.items if item and item[2]]

    @classmethod
    def close_current(cls):
        if cls.current is not None:
            cls.current.close()

    def popup(self, x, y):
        PopupMenu.close_current()
        c, px = self.colors, self.app.px
        top = self.top = tk.Toplevel(self.owner.winfo_toplevel())
        top.withdraw()
        top.overrideredirect(True)
        top.configure(bg=c.border)
        body = self.body = tk.Frame(top, bg=c.bg, bd=0)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Frame(body, bg=c.bg, height=px(4)).pack(fill="x")
        icons = any(item and item[4] for item in self.items)
        for item in self.items:
            if item is None:
                tk.Frame(body, bg=c.border, height=1).pack(fill="x", padx=px(8), pady=px(3))
                continue
            label, _command, checked, danger, icon, key = item
            row = tk.Frame(body, bg=c.bg, cursor="hand2")
            row.pack(fill="x")
            mark = tk.Label(row, text=GLYPH["check"] if checked else "", width=2, bg=c.bg, fg=c.fg,
                            font=(self.app.icon_font, 8))
            mark.pack(side="left", padx=(px(6), 0))
            parts = [row, mark]
            if icons:                       # one column of icons, blank where an item has none
                pic = tk.Label(row, bg=c.bg, bd=0, image=blank_icon(self.app), width=px(16))   # px: has an image
                pic.pack(side="left", padx=(0, px(6)))
                if icon:
                    menu_icon(self.app, pic, icon, c.danger if danger else c.muted)
                parts.append(pic)
            if key:
                chip = tk.Label(row, text=key, bg=c.bg, fg=c.muted, font=(UI_FONT, 7), padx=px(3), pady=0,
                                highlightthickness=1, highlightbackground=c.border, highlightcolor=c.border)
                chip.pack(side="right", padx=(px(6), px(10)))
                parts.append(chip)
            text = tk.Label(row, text=label, bg=c.bg, fg=c.danger if danger else c.fg, anchor="w",
                            font=(UI_FONT, 9), pady=px(4))
            text.pack(side="left", fill="x", expand=True, padx=(px(2), px(6) if key else px(16)))
            parts.append(text)
            self.rows.append((row, text, item))
            for w in parts:
                w.bind("<Enter>", lambda e, i=len(self.rows) - 1: self._hover(i))
                w.bind("<ButtonRelease-1>", lambda e, it=item: self._choose(it))
        tk.Frame(body, bg=c.bg, height=px(4)).pack(fill="x")

        top.update_idletasks()
        w, h = top.winfo_reqwidth(), top.winfo_reqheight()
        area = self.app.area_of((int(x), int(y), int(x), int(y)))      # the screen it opens on (S1)
        if x + w > area[2]:
            x = max(area[0], x - w)
        up = y + h > area[3]                # (no room under the pointer: it opens upward, rising)
        if up:
            y = max(area[1], y - h)
        menu_in(top, int(x), int(y), w, h, self.app.px(MENU_DROP) * (-1 if up else 1))
        top.attributes("-topmost", True)
        top.lift()
        top.bind("<ButtonPress>", self._press, add="+")
        top.bind("<Escape>", lambda e: self.close())
        top.bind("<Up>", lambda e: self._step(-1))
        top.bind("<Down>", lambda e: self._step(1))
        top.bind("<Return>", lambda e: self._active is not None and self._choose(self.rows[self._active][2]))
        top.bind("<FocusIn>", self._focus_in)
        top.bind("<FocusOut>", self._focus_out)
        PopupMenu.current = self
        top.focus_force()
        try:
            top.grab_set()              # clicks elsewhere in the app come here, and close the menu
        except tk.TclError:
            pass

    def invoke(self, label):
        self._choose(next(item for item in self.items if item and item[0] == label))

    def close(self):
        if PopupMenu.current is self:
            PopupMenu.current = None
        top, self.top = self.top, None
        if top is not None:
            try:
                top.grab_release()
            except tk.TclError:
                pass
            menu_out(top)                   # (it fades out; a new menu may open meanwhile)

    def _choose(self, item):
        self.close()
        item[1]()

    def _hover(self, index):
        self._active = index
        for i, (row, _text, _item) in enumerate(self.rows):
            bg = self.colors.hover if i == index else self.colors.bg
            for w in (row, *row.winfo_children()):
                w.configure(bg=bg)

    def _step(self, delta):
        if self.rows:
            self._hover(((self._active if self._active is not None else -delta) + delta) % len(self.rows))

    def _press(self, event):
        t = self.top
        inside = (t.winfo_rootx() <= event.x_root < t.winfo_rootx() + t.winfo_width()
                  and t.winfo_rooty() <= event.y_root < t.winfo_rooty() + t.winfo_height())
        if not inside:
            self.close()

    def _focus_in(self, _event):
        self._had_focus = True

    def _focus_out(self, _event):
        if self._had_focus and self.top is not None:   # e.g. a click in another program
            self.top.after(30, self._check_focus)

    def _check_focus(self):
        try:
            if self.top.winfo_exists() and self.top.focus_get() is None:
                self.close()
        except (tk.TclError, KeyError):
            self.close()


# every name (underscored ones too) goes on to the next part: see app.py
__all__ = [_n for _n in list(globals()) if not _n.startswith("__")]
