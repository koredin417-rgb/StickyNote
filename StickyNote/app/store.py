"""Data model and on-disk storage (one JSON file + an images folder).

* ``Note`` – one memo: its text/image, its look (color, font) and the day it
  belongs to on the calendar (``date``, YYYY-MM-DD).
* ``Pad`` – one sticky-note window on screen: where it is, how big, pinned,
  transparency, and which memo it is showing right now.
* ``Prefs`` – app-wide choices to remember, such as the last note layout.

Unknown keys are ignored and missing keys get defaults, so files from older
or newer versions still load. A value of the wrong kind (a damaged or hand-edited
file) resets only its own field, never the file; a notes.json that can't be read at
all is copied to notes.unreadable-<time>.json before a save replaces it. Version-1 files (notes carried their own window
position) are migrated on load, and a memo's old single ``image`` becomes its
``images`` list.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

import texts
from calgeom import SIDES as CALENDAR_SIDES

STYLES = ("plain", "header", "image")
MARK_KINDS = ("b", "i", "u", "s")   # text formats: bold, italic, underline, strikethrough
FILE_VERSION = 3
IMAGE_MAX = 1600                    # longest side of stored images, px
TITLE_MAX = 40
EMPTY_TITLE = "(empty)"
PREVIEW_MAX = 60
CASCADE = 30                        # offset of a new window from the one it came from
PIN_LIMIT_MAX = 10                  # memos pinned to the top of the list, at most
CUSTOM_COLORS = 4                   # personal colors next to the palette in Settings
SOLID_COLORS = 32                   # strong colors kept solid (Settings) remembered at most, the latest
DEFAULT_FONT = "Pretendard"         # bundled in fonts\ (SIL Open Font License), loaded by the app itself
NOTE_COLOR = "#FFF4A3"              # a memo's color until one is chosen
FONT_SIZE = 11                      # a memo's text size until one is chosen
FONT_SIZE_MAX = 1000                # a saved text size past this (or under 1) is junk
PAD_SIZE = 320                      # a window's width and height until it is resized
SNAP_GAPS = (0, 4, 8, 12, 16)       # gap (px) left between notes that snap together; None = no snapping
INLINE = "\ufffc"                   # stands for a picture inside a tab's text (see Note.inline)
LIST_SORTS = ("date", "added")      # list order: by the memo's day (newest first) / by when it was made
TIDY_ORDERS = ("place", "date", "pinned")   # where they are now / memo date (newest first) / always-on-top first
LIST_SECTIONS = ("pinned", "others")    # the list's two parts, each can be folded shut
CURSOR_COLORS = ("opposite", "text")    # text cursor: the main theme's opposite color / the text color
BIN_DAY_CHOICES = (1, 7, 30)        # how long the bin keeps memos (Settings)
BACKUPS_KEPT = 7                    # daily copies of notes.json in backups\ (one per day, newest kept)
UNREADABLE_TRIES = 100              # names tried for the copy of a notes.json that can't be read
CALENDAR_HOLDS = ("mini", "big")    # the calendar's manual-view hold (C2); None = no hold
GRID_SIDES = ("left", "right")      # the side an auto layout grid grows to (L1)
PX_MAX = 100_000                    # a saved spot or size (px) past this is junk
ORDER_MAX = 1_000_000               # ... a tile order past this (either way)
TILE_BLOCK_MAX = 100                # ... a calendar block (columns or rows of tiles) past this
SCALE_MIN, SCALE_MAX = 0.5, 10.0    # a setup copy's display scale outside this is junk
_HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _known(cls, data: dict) -> dict:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in names}


# ---- cleaners: every saved field goes through one in __post_init__. Each takes anything and
# never raises; a value of the wrong shape comes back as None (or empty), so only that field
# (or entry) is reset and the rest of the note, window or settings load as they are.
# Limits:
# * spots (x, y) within ±PX_MAX (100 000) px; sizes 1..PX_MAX px
# * the tile order within ±ORDER_MAX (1 000 000); a calendar tile block 1..TILE_BLOCK_MAX (100)
#   columns and rows; a setup's display scale SCALE_MIN..SCALE_MAX (0.5..10)
# * new flags are strict booleans: only true is true ("yes", 1 are junk)
# * a per-setup entry (``Pad.setups``) without a good x, y, w and h is dropped as a whole
# Older fields keep the rules they had for good values (clamped transparency, bool() flags,
# ints from digits); only what used to raise or slip through as junk is new.
def _to_int(value) -> int | None:
    """``value`` as an int (``int()`` of a number or of digits), else None: bools, NaN,
    infinity, words, lists ..."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _int(value, lo: int = -PX_MAX, hi: int = PX_MAX) -> int | None:
    """``value`` as an int in lo..hi, else None."""
    number = _to_int(value)
    return number if number is not None and lo <= number <= hi else None


def _ints(value, count: int, lo: int, hi: int) -> list[int] | None:
    """A list of exactly ``count`` ints in lo..hi, else None."""
    if not isinstance(value, (list, tuple)) or len(value) != count:
        return None
    out = [_int(v, lo, hi) for v in value]
    return None if None in out else out


def _spot(value) -> list[int] | None:
    """[x, y] (px; may be negative, on a monitor left of or above the main one)."""
    return _ints(value, 2, -PX_MAX, PX_MAX)


def _size(value) -> list[int] | None:
    """[width, height] (px, at least 1)."""
    return _ints(value, 2, 1, PX_MAX)


def _box(value) -> list[int] | None:
    """[x, y, width, height]."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    spot, size = _spot(value[:2]), _size(value[2:])
    return spot + size if spot is not None and size is not None else None


def _flag(value) -> bool:
    """Only True is True: "yes", 1 and the like are junk."""
    return value is True


def _bool(value, default: bool) -> bool:
    """True or False as given; anything else is ``default``."""
    return value if isinstance(value, bool) else default


def _text(value, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _id_or_new(value) -> str:
    return value if isinstance(value, str) and value else _new_id()


def _names(value) -> list[str]:
    """Picture file names: only the non-empty strings of a list. (Nothing is turned into a
    string: str() of a deeply nested list would raise.)"""
    return [n for n in value if isinstance(n, str) and n] if isinstance(value, (list, tuple)) else []


def _day(value) -> str | None:
    """A day as YYYY-MM-DD, else None."""
    try:
        return _date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        return None


def _bin_time(value) -> str | None:
    """When a memo went to the bin, as saved: an ISO time (no time zone) the bin can read and
    count days on from, else None."""
    try:
        when = datetime.fromisoformat(value)
        when + timedelta(days=max(BIN_DAY_CHOICES))
    except (TypeError, ValueError, OverflowError):
        return None
    return value if when.tzinfo is None else None


def _choice(value, choices: tuple) -> str | None:
    return value if isinstance(value, str) and value in choices else None


def _is_key(value) -> bool:
    """A setup key (or grid home key): a non-empty string."""
    return isinstance(value, str) and value != ""


def _links(value, own_id: str | None = None) -> list[str]:
    """Pad ids (or "cal") in order, each once; anything else, and the pad itself, is dropped."""
    out, seen = [], set()
    for item in value if isinstance(value, (list, tuple)) else ():
        if isinstance(item, str) and item and item != own_id and item not in seen:
            out.append(item)
            seen.add(item)
    return out


def _entries(value):
    """(key, entry) for each dict entry of ``value`` under a setup key; nothing for a non-dict."""
    for key, entry in value.items() if isinstance(value, dict) else ():
        if _is_key(key) and isinstance(entry, dict):
            yield key, entry


def _clean_setups(value, own_id: str | None) -> dict:
    """{setup_key: {"x", "y", "w", "h", "links", "stacked"}}. An entry without a good box is
    dropped (the app places the note by N1 there); bad links or stacked reset only themselves."""
    out = {}
    for key, entry in _entries(value):
        spot, size = _spot([entry.get("x"), entry.get("y")]), _size([entry.get("w"), entry.get("h")])
        if spot is not None and size is not None:
            out[key] = {"x": spot[0], "y": spot[1], "w": size[0], "h": size[1],
                        "links": _links(entry.get("links"), own_id), "stacked": _flag(entry.get("stacked"))}
    return out


def _clean_calendar_setups(value) -> dict:
    """{setup_key: {"pos": [x, y] | None}}; a bad pos becomes None."""
    return {key: {"pos": _spot(entry.get("pos"))} for key, entry in _entries(value)}


def _clean_grid_homes(value) -> dict:
    """{f"{setup_key}|{ml},{mt},{mr},{mb}": {"x", "y", "side"}}; a bad entry is dropped."""
    out = {}
    for key, home in _entries(value):
        spot, side = _spot([home.get("x"), home.get("y")]), _choice(home.get("side"), GRID_SIDES)
        if "|" in key and spot is not None and side is not None:
            out[key] = {"x": spot[0], "y": spot[1], "side": side}
    return out


def _scale(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if SCALE_MIN <= number <= SCALE_MAX else None    # (NaN fails both)


def _clean_scales(value) -> dict:
    """{setup_key: float}; a bad scale is dropped."""
    out = {}
    for key, scale in value.items() if isinstance(value, dict) else ():
        scale = _scale(scale)
        if _is_key(key) and scale is not None:
            out[key] = scale
    return out


edits = 0       # bumped by every attribute set on a Note, Pad or Prefs: a save with none since does nothing


class _Tracked:
    """Every attribute set counts as an edit (``edits``). (A list or dict changed in place is not
    counted: App.request_save marks those, and the save at exit always checks everything.)"""
    __slots__ = ()

    def __setattr__(self, name, value):
        global edits
        edits += 1
        object.__setattr__(self, name, value)


@dataclass
class Note(_Tracked):
    id: str = field(default_factory=_new_id)
    style: str = "plain"            # one of STYLES
    header: str = ""
    body: str = ""
    images: list[str] = field(default_factory=list)   # file names inside the images folder
    color: str = NOTE_COLOR         # #RRGGBB
    font_family: str = DEFAULT_FONT
    font_size: int = FONT_SIZE
    created: str = field(default_factory=_now)
    modified: str = field(default_factory=_now)
    date: str | None = None         # calendar day; defaults to the day it was created
    end_date: str | None = None     # a period memo's last day (after ``date``); None = just that day
    deleted: str | None = None      # when it was moved to the bin (ISO time); None = not in the bin
    marks: list[list] = field(default_factory=list)   # [kind, start, end] formatted body text, kind in MARK_KINDS
    pinned: str | None = None       # when it was pinned to the top of the list (ISO time); None = not pinned
    # Image + text memos: every picture is a tab with its own text. The first picture's text is
    # ``body``/``marks``/``inline``; the others' are here, in picture order:
    # {"body": str, "marks": [...], "inline": [...]}.
    extra_texts: list[dict] = field(default_factory=list)
    # pictures inside the text (added with "+ Add picture" under it): each INLINE character in
    # ``body`` is one of them, in this order
    inline: list[str] = field(default_factory=list)

    def __post_init__(self):
        # every field is cleaned (see the cleaners above): junk resets that field only
        self.id = _id_or_new(self.id)
        if self.style not in STYLES:
            self.style = "plain"
        self.header, self.body = _text(self.header), _text(self.body)
        if not (isinstance(self.color, str) and _HEX_COLOR.fullmatch(self.color)):
            self.color = NOTE_COLOR
        if not (isinstance(self.font_family, str) and self.font_family):
            self.font_family = DEFAULT_FONT
        size = _int(self.font_size, 1, FONT_SIZE_MAX)
        self.font_size = FONT_SIZE if size is None else size
        self.created = self.created if isinstance(self.created, str) else _now()
        self.modified = self.modified if isinstance(self.modified, str) else _now()
        # its day: a good one as given, else the day it was made (today if that is no day either)
        self.date = _day(self.date) or _day((self.created or _now())[:10]) or _date.today().isoformat()
        end = _day(self.end_date)
        self.end_date = end if end is not None and end > self.date else None
        if not self.deleted:                        # (None, "", false, 0, [] ...): not in the bin
            self.deleted = None
        elif _bin_time(self.deleted) is None:       # in the bin, but when is junk: a full bin period from now
            self.deleted = _now()
        if not isinstance(self.pinned, str):
            self.pinned = None
        self.images = _names(self.images)
        self.body, self.inline = self._clean_inline(self.body, self.inline)
        self.marks = self._clean_marks(self.marks, len(self.body))
        extra = []
        for item in self.extra_texts if isinstance(self.extra_texts, list) else []:
            item = item if isinstance(item, dict) else {}
            body, inline = self._clean_inline(_text(item.get("body")), item.get("inline", []))
            extra.append({"body": body, "marks": self._clean_marks(item.get("marks", []), len(body)),
                          "inline": inline})
        wanted = max(0, len(self.images) - 1)
        for left_over in extra[wanted:]:            # more texts than pictures: keep the words in the memo
            if left_over["body"].strip():
                sep = "\n\n" if self.body.strip() else ""
                self.body = self.body.rstrip("\n") + sep + left_over["body"] if sep else left_over["body"]
                self.inline = self.inline + left_over["inline"]
        self.extra_texts = extra[:wanted] + [{"body": "", "marks": [], "inline": []}
                                             for _ in range(wanted - len(extra))]

    @staticmethod
    def _clean_inline(body: str, names) -> tuple[str, list[str]]:
        """Exactly one picture name per INLINE character in ``body``."""
        names = _names(names)
        count = body.count(INLINE)
        if count < len(names):
            names = names[:count]
        elif count > len(names):                    # placeholders without a picture: drop them
            body = "".join(body.rsplit(INLINE, count - len(names)))
        return body, names

    @staticmethod
    def _clean_marks(marks, length) -> list[list]:
        clean = []
        for m in marks if isinstance(marks, list) else []:
            if not (isinstance(m, (list, tuple)) and len(m) == 3 and m[0] in MARK_KINDS):
                continue
            try:
                start, end = max(0, int(m[1])), min(length, int(m[2]))
            except (TypeError, ValueError, OverflowError):
                continue
            if start < end:
                clean.append([m[0], start, end])
        return clean

    def covers(self, iso: str) -> bool:
        """Whether the memo is on day ``iso`` (its day, or any day of its period)."""
        return self.date == iso or bool(self.end_date and self.date <= iso <= self.end_date)

    @property
    def date_span(self) -> str:
        """"2026-11-21" or "2026-11-21 ~ 2026-11-25"."""
        return f"{self.date} ~ {self.end_date}" if self.end_date else str(self.date)

    # ---- picture tabs ----------------------------------------------------
    def tabs(self) -> list[tuple]:
        """(picture name or None, text, marks, pictures in the text) for every tab; one tab
        without a picture when the memo has no pictures."""
        if not self.images:
            return [(None, self.body, self.marks, self.inline)]
        out = [(self.images[0], self.body, self.marks, self.inline)]
        out += [(name, t["body"], t["marks"], t["inline"]) for name, t in zip(self.images[1:], self.extra_texts)]
        return out

    def tab_text(self, index: int) -> tuple[str, list, list]:
        """(text, marks, pictures in the text) of tab ``index``."""
        if index <= 0 or index > len(self.extra_texts):
            return self.body, self.marks, self.inline
        t = self.extra_texts[index - 1]
        return t["body"], t["marks"], t["inline"]

    def set_tab_text(self, index: int, body: str, marks: list, inline: list | None = None) -> bool:
        """Store a tab's text. True if it changed."""
        inline = list(inline or [])
        if index <= 0 or index > len(self.extra_texts):
            changed = (body, marks, inline) != (self.body, self.marks, self.inline)
            self.body, self.marks, self.inline = body, marks, inline
            return changed
        t = self.extra_texts[index - 1]
        changed = (body, marks, inline) != (t["body"], t["marks"], t["inline"])
        t["body"], t["marks"], t["inline"] = body, marks, inline
        return changed

    def add_image(self, name: str) -> int:
        """One more picture, as a new tab with no text yet. Returns its index."""
        self.images.append(name)
        if len(self.images) > 1:
            self.extra_texts.append({"body": "", "marks": [], "inline": []})
        return len(self.images) - 1

    def remove_image(self, index: int) -> str:
        """Take a picture (tab) out and return its file name. Its text (and the pictures
        in it) is not lost: it is added to the tab before it (or after it, for the first tab)."""
        tabs = self.tabs()
        name, body, marks, inline = tabs.pop(index)
        if body.strip() and tabs:
            j = max(0, index - 1)
            n_img, n_body, n_marks, n_inline = tabs[j]
            sep = "\n\n" if n_body.strip() else ""
            if j < index:                   # goes after the previous tab's text
                shift = len(n_body) + len(sep)
                tabs[j] = (n_img, n_body + sep + body,
                           n_marks + [[k, a + shift, b + shift] for k, a, b in marks], n_inline + inline)
            else:                           # the first tab: goes before the next tab's text
                shift = len(body) + len(sep)
                tabs[j] = (n_img, body + sep + n_body,
                           marks + [[k, a + shift, b + shift] for k, a, b in n_marks], inline + n_inline)
        elif not tabs:                      # the last picture: its text stays as the memo's text
            tabs = [(None, body, marks, inline)]
        self.images = [img for img, _b, _m, _i in tabs if img]
        self.body, self.marks, self.inline = tabs[0][1], tabs[0][2], tabs[0][3]
        self.extra_texts = [{"body": b, "marks": m, "inline": i} for _img, b, m, i in tabs[1:]]
        return name

    @property
    def all_inline(self) -> list[str]:
        """Every picture inside the memo's texts."""
        return [name for tab in self.tabs() for name in tab[3]]

    @property
    def texts(self) -> list[str]:
        """The text of every tab, without the pictures in it."""
        return [t.replace(INLINE, "") for t in [self.body] + [t["body"] for t in self.extra_texts]]

    @property
    def search_text(self) -> str:
        return "\n".join([self.header, *self.texts])

    @property
    def title(self) -> str:
        if self.style == "header" and self.header.strip():
            return _shorten(self.header.strip(), TITLE_MAX)
        first = next((ln.strip() for text in self.texts for ln in text.splitlines() if ln.strip()), "")
        return _shorten(first, TITLE_MAX) if first else EMPTY_TITLE

    @property
    def is_empty(self) -> bool:
        """Nothing worth keeping. A period memo is kept even with no words: the period is the content."""
        return (not self.end_date and not any(t.strip() for t in self.texts) and not self.header.strip()
                and not self.images and not self.all_inline)

    def preview_lines(self, count: int) -> list[str]:
        lines = [ln.strip() for text in self.texts for ln in text.splitlines() if ln.strip()]
        return [_shorten(ln, PREVIEW_MAX) for ln in lines[:count]]

    @classmethod
    def like(cls, template: Note, date: str | None = None, style: str | None = None) -> Note:
        """A blank memo with the same look as ``template``, in ``style`` if given."""
        if style is None:
            style = template.style if template.style != "image" else "plain"
        return cls(color=template.color, font_family=template.font_family,
                   font_size=template.font_size, style=style,
                   date=date or _date.today().isoformat())

    @classmethod
    def from_dict(cls, data: dict) -> Note:
        data = dict(data)
        old_single = data.pop("image", None)      # files before version 3
        if isinstance(old_single, str) and old_single and not data.get("images"):
            data["images"] = [old_single]
        return cls(**_known(cls, data))


@dataclass
class Pad(_Tracked):
    id: str = field(default_factory=_new_id)
    note_id: str | None = None
    x: int | None = None            # None = let the app choose
    y: int | None = None
    width: int = PAD_SIZE
    height: int = PAD_SIZE
    pinned: bool = False            # always on top
    transparency: int = 0           # percent, 0..90
    tab: int = 0                    # which picture (tab) of an image memo is shown
    calendar: bool = False          # its calendar is open
    calendar_docked: bool = True    # ... beside the note (the lock icon); else where it was put
    calendar_expanded: bool = False     # ... as the big month view
    calendar_pos: list | None = None    # [x, y] of the small calendar when not docked
    calendar_big_pos: list | None = None    # [x, y] of the big month view
    calendar_big_cell: list | None = None   # [width, height] of a day in the big month view (px at 100 %)
    calendar_small_cell: list | None = None     # ... in the small one
    collapsed: bool = False         # folded up to its top bar (width and height above are the full size)
    # ---- layout (the movement rules; ids like L3 and P4 are the spec's) ----
    free: bool = False              # pulled out of the auto layout grid with Alt (L3)
    order: int | None = None        # its place in the tile order (L4); None = not given one yet
    own_size: list | None = None    # [w, h]: its own size from before it was shrunk to fit (P6, L5)
    cal_mark: list | None = None    # [x, y, w, h]: its own box from before the calendar moved it (P4)
    stacked: bool = False           # in the overflow pile or a Tidy layer, an allowed overlap (P5)
    links: list = field(default_factory=list)      # pad ids (or "cal") linked to it in the current setup (M2)
    # per screen setup (N5): {setup_key: {"x", "y", "w", "h", "links": [...], "stacked": bool}}
    setups: dict = field(default_factory=dict)
    calendar_side: str | None = None    # which side of the note its calendar docks on: one of CALENDAR_SIDES
    calendar_auto_big: bool = False     # ... switched to the big view by the stretch rule ("auto-big", C2)
    calendar_hold: str | None = None    # ... your own mini/big click, held (C2): one of CALENDAR_HOLDS, None = none
    calendar_tile_block: list | None = None     # ... [cols, rows] of tiles it takes in auto layout (L2)
    # ... its undocked spot per screen setup, one for both views (C2): {setup_key: {"pos": [x, y] | None}}
    calendar_setups: dict = field(default_factory=dict)

    def __post_init__(self):
        # every field is cleaned (see the cleaners above): junk resets that field only
        self.id = _id_or_new(self.id)
        if not isinstance(self.note_id, str):
            self.note_id = None
        self.x, self.y = _int(self.x), _int(self.y)
        width, height = _int(self.width, 1, PX_MAX), _int(self.height, 1, PX_MAX)
        self.width = PAD_SIZE if width is None else width
        self.height = PAD_SIZE if height is None else height
        self.pinned = _bool(self.pinned, False)
        transparency = _to_int(self.transparency)
        self.transparency = 0 if transparency is None else max(0, min(90, transparency))
        tab = _to_int(self.tab)
        self.tab = 0 if tab is None else tab
        self.calendar = _bool(self.calendar, False)
        self.calendar_docked = _bool(self.calendar_docked, True)
        self.calendar_expanded = _bool(self.calendar_expanded, False)
        self.calendar_pos, self.calendar_big_pos = _spot(self.calendar_pos), _spot(self.calendar_big_pos)
        self.collapsed = bool(self.collapsed)
        for name in ("calendar_big_cell", "calendar_small_cell"):   # (clamped where they are used)
            setattr(self, name, _ints(getattr(self, name), 2, -PX_MAX, PX_MAX))
        # the layout fields
        self.free = _flag(self.free)
        self.order = _int(self.order, -ORDER_MAX, ORDER_MAX)
        self.own_size = _size(self.own_size)
        self.cal_mark = _box(self.cal_mark)
        self.stacked = _flag(self.stacked)
        self.links = _links(self.links, self.id)
        self.setups = _clean_setups(self.setups, self.id)
        self.calendar_side = _choice(self.calendar_side, CALENDAR_SIDES)
        self.calendar_auto_big = _flag(self.calendar_auto_big)
        self.calendar_hold = _choice(self.calendar_hold, CALENDAR_HOLDS)
        self.calendar_tile_block = _ints(self.calendar_tile_block, 2, 1, TILE_BLOCK_MAX)
        self.calendar_setups = _clean_calendar_setups(self.calendar_setups)

    @property
    def alpha(self) -> float:
        return round(1 - self.transparency / 100, 2)

    @classmethod
    def like(cls, template: Pad, note_id: str) -> Pad:
        """A window just below-right of ``template``, same size and transparency."""
        x = None if template.x is None else template.x + CASCADE
        y = None if template.y is None else template.y + CASCADE
        return cls(note_id=note_id, x=x, y=y, width=template.width, height=template.height,
                   pinned=template.pinned, transparency=template.transparency)

    @classmethod
    def from_dict(cls, data: dict) -> Pad:
        return cls(**_known(cls, data))


@dataclass
class Prefs(_Tracked):
    last_style: str = "plain"       # layout for new memos: the one chosen last
    language: str = texts.DEFAULT   # "ko" or "en"
    default_color: str | None = None    # color of new memos (#RRGGBB); None = not chosen yet
    date_format: str = texts.DATE_FORMATS[0]    # how dates look (texts.DATE_FORMATS)
    pin_limit: int = 3              # how many memos may be pinned to the top of the list (0..PIN_LIMIT_MAX)
    custom_colors: list[str] = field(default_factory=list)   # personal colors (#RRGGBB), in the order added
    snap_gap: int | None = 8        # dragged notes snap to each other with this gap (SNAP_GAPS); None = off
    transparency: int | None = None     # percent 0..90, the same for every note; None = take the first window's
    theme_color: str | None = None  # main theme (#RRGGBB): the calendar's colors, the text cursor; None = not chosen yet
    list_sort: str = "date"         # the list's memos (not the pinned ones): one of LIST_SORTS
    list_collapsed: list[str] = field(default_factory=list)    # list sections folded shut: "pinned", "others"
    group_drag: bool = True         # dragging a note takes the notes snapped to it along
    auto_layout: bool = False       # the notes tiled from a screen edge, kept so (App.arrange)
    auto_cell: list | None = None   # [width, height] px of the tiles (a note resized while tiled); None = new-note size
    hints_seen: bool = False        # the short "hidden controls" hint was shown and closed
    list_oldest: bool = False       # the list's memos oldest first (else newest first)
    cursor_color: str = "opposite"  # text cursor: one of CURSOR_COLORS
    bin_days: int = 7               # memos stay in the bin this long (BIN_DAY_CHOICES)
    note_size: list | None = None   # [width, height] px of new notes ("use this size"); None = like their note
    tidy_order: str = "place"       # "Tidy up notes" order: one of TIDY_ORDERS
    resize_hint_seen: bool = False  # the "Alt: only this note" notice after a first group resize was shown
    # auto layout grid homes, per screen per setup (L1): {f"{setup_key}|{ml},{mt},{mr},{mb}":
    # {"x": int, "y": int, "side": "left" | "right"}}, keyed by the screen's monitor rectangle
    grid_homes: dict = field(default_factory=dict)
    setup_scales: dict = field(default_factory=dict)    # {setup_key: the display scale its copies were saved at} (N5)
    last_setup: str | None = None   # the screen setup key the app last saw
    links_migrated: bool = False    # the one-time move of older files' snapped notes to links (M2) is done
    # strong colors painted solid all the same ("Keep solid color" in Settings): no pale page for them
    solid_colors: list[str] = field(default_factory=list)
    motion: str | None = None       # animations: "full", "reduced", "off"; None = follow Windows (anim)
    minimize_style: str = "bar"     # minimize: "bar" (folds to its top bar; folded, goes away), "fold"
                                    # (rolls away, back from the taskbar) or "sticker"

    def __post_init__(self):
        self.grid_homes = _clean_grid_homes(self.grid_homes)
        self.setup_scales = _clean_scales(self.setup_scales)
        self.last_setup = self.last_setup if _is_key(self.last_setup) else None
        self.links_migrated = _flag(self.links_migrated)
        size = _ints(self.note_size, 2, -PX_MAX, PX_MAX)
        self.note_size = [max(100, size[0]), max(80, size[1])] if size else None
        for name in ("default_color", "theme_color"):
            value = getattr(self, name)
            if value is not None:
                ok = isinstance(value, str) and _HEX_COLOR.fullmatch(value)
                setattr(self, name, value.upper() if ok else None)
        if self.list_sort not in LIST_SORTS:
            self.list_sort = LIST_SORTS[0]
        if self.cursor_color not in CURSOR_COLORS:
            self.cursor_color = CURSOR_COLORS[0]
        if self.bin_days not in BIN_DAY_CHOICES:
            self.bin_days = 7
        self.list_oldest = bool(self.list_oldest)
        if self.minimize_style not in ("fold", "bar", "sticker"):
            self.minimize_style = "bar"
        if self.motion not in (None, "full", "reduced", "off"):
            self.motion = None
        if self.tidy_order not in TIDY_ORDERS:
            self.tidy_order = TIDY_ORDERS[0]
        self.resize_hint_seen = bool(self.resize_hint_seen)
        self.group_drag = bool(self.group_drag)
        self.auto_layout = bool(self.auto_layout)
        if not (isinstance(self.auto_cell, list) and len(self.auto_cell) == 2
                and all(isinstance(v, int) and 100 <= v <= 4000 for v in self.auto_cell)):
            self.auto_cell = None
        self.hints_seen = bool(self.hints_seen)
        sections = self.list_collapsed if isinstance(self.list_collapsed, list) else []
        self.list_collapsed = [s for s in LIST_SECTIONS if s in sections]
        if self.last_style not in STYLES:
            self.last_style = "plain"
        if self.language not in texts.CODES:
            self.language = texts.DEFAULT
        if self.date_format not in texts.DATE_FORMATS:
            self.date_format = texts.DATE_FORMATS[0]
        if self.transparency is not None:
            try:
                self.transparency = max(0, min(90, int(self.transparency)))
            except (TypeError, ValueError, OverflowError):
                self.transparency = None
        if self.snap_gap is not None and self.snap_gap not in SNAP_GAPS:
            self.snap_gap = 8
        colors = self.custom_colors if isinstance(self.custom_colors, list) else []
        self.custom_colors = [c.upper() for c in colors
                              if isinstance(c, str) and _HEX_COLOR.fullmatch(c)][:CUSTOM_COLORS]
        solid = self.solid_colors if isinstance(self.solid_colors, list) else []
        self.solid_colors = list(dict.fromkeys(c.upper() for c in solid
                                               if isinstance(c, str) and _HEX_COLOR.fullmatch(c)))[-SOLID_COLORS:]
        try:
            self.pin_limit = max(0, min(PIN_LIMIT_MAX, int(self.pin_limit)))
        except (TypeError, ValueError, OverflowError):
            self.pin_limit = 3

    @classmethod
    def from_dict(cls, data) -> Prefs:
        return cls(**_known(cls, data)) if isinstance(data, dict) else cls()


@dataclass
class Data:
    notes: list[Note]
    pads: list[Pad]
    prefs: Prefs = field(default_factory=Prefs)


def _objects(value) -> list[dict]:
    """The objects in a list from the file; anything else in it (or instead of it) is skipped."""
    return [d for d in value if isinstance(d, dict)] if isinstance(value, list) else []


def _parse(payload: dict) -> Data:
    raw_notes = _objects(payload.get("notes"))
    notes = [Note.from_dict(d) for d in raw_notes]
    if "pads" in payload:
        return Data(notes, [Pad.from_dict(d) for d in _objects(payload["pads"])],
                    Prefs.from_dict(payload.get("prefs")))
    # version 1: every visible note was its own window
    pads = [Pad(note_id=d.get("id"), x=d.get("x"), y=d.get("y"),
                width=d.get("width", PAD_SIZE), height=d.get("height", PAD_SIZE),
                pinned=bool(d.get("pinned", False)), transparency=d.get("transparency", 0))
            for d in raw_notes if d.get("visible", True)]
    return Data(notes, pads)


class NoteStore:
    def __init__(self, folder: Path | str):
        self.folder = Path(folder)
        self.path = self.folder / "notes.json"
        self.backup = self.folder / "notes.json.bak"
        self.images = self.folder / "images"
        self._written = None            # the last payload this app wrote (the file holds it, intact)

    # ---- notes and pads ------------------------------------------------
    def load(self) -> Data:
        for candidate in (self.path, self.backup):
            data = self._read(candidate)
            if data is not None:
                return data
        return Data([], [])

    @staticmethod
    def _read(path: Path) -> Data | None:
        try:
            payload = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError, RecursionError):   # missing, not text, not JSON, or nested past what json reads
            return None
        try:
            return _parse(payload)
        except (TypeError, ValueError, AttributeError):    # not a notes file (e.g. a list at the top)
            return None

    def save(self, notes: list[Note], pads: list[Pad], prefs: Prefs | None = None) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": FILE_VERSION,
                              "notes": [asdict(n) for n in notes],
                              "pads": [asdict(p) for p in pads],
                              "prefs": asdict(prefs or Prefs())},
                             ensure_ascii=False, separators=(",", ":"))      # (compact: loading takes both)
        if payload == self._written and self.path.exists():
            self._daily_backup(payload)         # nothing changed since the last save
            return
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:     # on the disk before it replaces the file
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        # the current file becomes the backup if it is good: known good when this app wrote it,
        # otherwise (the first save) read to check. One that can't be read is not replaced before
        # a copy of it is kept (if that fails, the OSError stops the save and the file stays).
        if self.path.exists():
            if self._written is not None or self._read(self.path) is not None:
                os.replace(self.path, self.backup)
            else:
                self._keep_unreadable()
        os.replace(tmp, self.path)
        self._written = payload
        self._daily_backup(payload)

    def _keep_unreadable(self, now: datetime | None = None) -> Path:
        """Copy notes.json, which can't be read, to notes.unreadable-YYYYmmdd-HHMMSS.json beside
        it (-2, -3 ... after the time if that name is taken: a copy is never overwritten)."""
        content = self.path.read_bytes()
        stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        for n in range(1, UNREADABLE_TRIES + 1):
            copy = self.folder / f"notes.unreadable-{stamp}{'' if n == 1 else f'-{n}'}.json"
            try:
                with open(copy, "xb") as out:       # (x: only a new file)
                    out.write(content)
                return copy
            except FileExistsError:
                continue
        raise FileExistsError(f"no free name for a copy of {self.path}")

    def _daily_backup(self, payload: str) -> None:
        """Once a day, a copy of the memos in backups\\ (notes-YYYY-MM-DD.json); only the
        newest BACKUPS_KEPT days are kept. Pictures are not copied."""
        folder = self.folder / "backups"
        today = folder / f"notes-{_date.today().isoformat()}.json"
        if today.exists():
            return
        try:
            folder.mkdir(parents=True, exist_ok=True)
            today.write_text(payload, "utf-8")
            for old in sorted(folder.glob("notes-*.json"), reverse=True)[BACKUPS_KEPT:]:
                old.unlink()
        except OSError:
            pass

    @staticmethod
    def export_text(notes: list[Note], path: Path | str, picture_word: str = "[picture]") -> int:
        """Every memo as plain text in one file (UTF-8), newest day first. Returns how many."""
        kept = sorted((n for n in notes if not n.deleted and not n.is_empty),
                      key=lambda n: (n.date or "", n.modified), reverse=True)
        parts = []
        for n in kept:
            lines = [f"=== {n.title if n.title != EMPTY_TITLE else ''} ===", n.date_span]
            if n.style == "header" and n.header.strip():
                lines.append(n.header.strip())
            for i, (image, body, _marks, _inline) in enumerate(n.tabs()):
                if image:
                    lines.append(picture_word)
                text = body.replace(INLINE, picture_word).strip()
                if text:
                    lines.append(text)
            parts.append("\n".join(lines))
        Path(path).write_text("\n\n".join(parts) + "\n", "utf-8")
        return len(kept)

    # ---- images ----------------------------------------------------------
    def image_path(self, name: str) -> Path:
        return self.images / Path(name).name

    def add_image(self, image) -> str:
        """Save a PIL image as PNG (shrunk to IMAGE_MAX) and return its file name."""
        self.images.mkdir(parents=True, exist_ok=True)
        name = f"{_new_id()}.png"
        img = image
        if img.mode not in ("RGB", "RGBA"):
            keeps_alpha = img.mode in ("P", "LA", "PA") or "A" in img.mode
            img = img.convert("RGBA" if keeps_alpha else "RGB")
        if max(img.size) > IMAGE_MAX:
            img = img.copy()
            img.thumbnail((IMAGE_MAX, IMAGE_MAX), Image.LANCZOS)
        img.save(self.image_path(name), "PNG")
        return name

    def remove_image(self, name: str) -> None:
        try:
            self.image_path(name).unlink()
        except FileNotFoundError:
            pass
