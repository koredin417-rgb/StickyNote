"""Where a docked calendar sits next to its note, how many cells fit, and when a stretched
mini calendar switches to the big view. Pure maths: no Tk, every size a plain int in pixels."""
from __future__ import annotations

import math

from geom import Box, center, fits_one, is_free

SIDES = ("right", "left", "below", "above")
STRETCH_UP = 1.75       # a mini stretched past this ratio (6-week month) becomes the big view
STRETCH_DOWN = 1.5      # a big view squeezed below this ratio goes back to mini


def spot_box(note: Box, side: str, w: int, h: int, gap: int) -> Box:
    """The calendar's box on ``side`` of the note. Right/left are top-aligned with the note,
    below/above left-aligned; above keeps its bottom edge at note.y0 - gap, so it grows upward."""
    if side == "right":
        x, y = note[2] + gap, note[1]
    elif side == "left":
        x, y = note[0] - gap - w, note[1]
    elif side == "below":
        x, y = note[0], note[3] + gap
    elif side == "above":
        x, y = note[0], note[1] - gap - h
    else:
        raise ValueError(side)
    return x, y, x + w, y + h


def side_order(note: Box, cal_center, sizes: dict[str, tuple[int, int]], gap: int) -> list[str]:
    """Sides nearest to ``cal_center`` first (by distance to each side's box centre). Ties go to
    the smaller up/down move, then right before left (S3), then SIDES order. With no centre,
    the SIDES order."""
    if cal_center is None:
        return list(SIDES)

    def key(s):
        cx, cy = center(spot_box(note, s, sizes[s][0], sizes[s][1], gap))
        dx, dy = cx - cal_center[0], cy - cal_center[1]
        return (dx * dx + dy * dy, abs(dy), SIDES.index(s))
    return sorted(SIDES, key=key)


def choose_side(note: Box, cal_center, sizes, areas, obstacles, gap) -> tuple[str | None, bool]:
    """Three outcomes:
    - ``(side, True)``: the nearest side that is on screen and clear.
    - ``(side, False)``: no side is clear, so make room (P1) on the nearest side that fits on a screen.
    - ``(None, False)``: no side fits on any screen, so the calendar undocks (G7).

    ``obstacles`` is used exactly as given. When an already-open calendar is re-docked, its own
    current box must not count as an obstacle: leaving it out is the caller's job."""
    order = side_order(note, cal_center, sizes, gap)
    for s in order:
        if is_free(spot_box(note, s, sizes[s][0], sizes[s][1], gap), areas, obstacles, gap):
            return s, True
    for s in order:
        if fits_one(spot_box(note, s, sizes[s][0], sizes[s][1], gap), areas):
            return s, False
    return None, False


def match_size(side: str, note_w: int, note_h: int, least_w: int, least_h: int):
    """The calendar's size along the shared edge, matching the note but never below the
    calendar's least size (so the note itself never grows). The other dimension is None (free)."""
    if side in ("right", "left"):
        return None, max(note_h, least_h)
    return max(note_w, least_w), None


def fit_cells(fit_w: float, fit_h: float, chrome_w: float, chrome_h: float, rows: int = 6):
    """``(cell_w, cell_h, ratio)`` for a 7 x ``rows`` grid in the space left after the chrome.
    The ratio (longer cell side over the shorter) is taken before any clamping."""
    cw = (fit_w - chrome_w) / 7
    ch = (fit_h - chrome_h) / rows
    lo, hi = min(cw, ch), max(cw, ch)
    return cw, ch, (hi / lo if lo > 0 else float("inf"))


def cap_ratio(cell_w, cell_h, free: str, limit: float = STRETCH_UP) -> tuple[int, int]:
    """The fixed dimension is rounded down (so it never exceeds the matched size); the free
    dimension ("w" or "h") is rounded up and grown just enough that the ratio is at most ``limit``.
    If the free side is already the long one it is only grown (never shrunk), so the ratio
    may stay above ``limit``."""
    if free == "w":
        h = math.floor(cell_h)
        return max(math.ceil(cell_w), math.ceil(h / limit - 1e-9)), h
    if free == "h":
        w = math.floor(cell_w)
        return w, max(math.ceil(cell_h), math.ceil(w / limit - 1e-9))
    raise ValueError(free)


def rule_view(ratio: float, view: str, big_fits: bool, big_can_fill: bool) -> str:
    if ratio > STRETCH_UP and big_fits:
        return "big"
    if view == "big" and (ratio < STRETCH_DOWN or not big_can_fill):
        return "mini"
    return view


def stretch_view(ratio, view, auto_big, hold, big_fits, big_can_fill) -> tuple[str, bool, str | None]:
    """``(view, auto_big, hold)``. A hold keeps its view until the rule agrees with it, then clears."""
    if hold is not None:
        if rule_view(ratio, hold, big_fits, big_can_fill) != hold:
            return hold, False, hold
    result = rule_view(ratio, view, big_fits, big_can_fill)
    return result, (result == "big" and (view != "big" or auto_big)), None


def peek_spot(pointer, w: int, h: int, area: Box, offset) -> tuple[int, int]:
    """Top-left of a ``w`` x ``h`` preview shown beside the pointer: at pointer + offset, flipped
    to the left of the pointer when it would pass the area's right edge and above it when it
    would pass the bottom, then kept inside ``area`` (the top-left wins when it is too small)."""
    px, py = pointer
    ox, oy = offset
    x, y = px + ox, py + oy
    if x + w > area[2]:
        x = px - ox - w
    if y + h > area[3]:
        y = py - oy - h
    return max(area[0], min(x, area[2] - w)), max(area[1], min(y, area[3] - h))
