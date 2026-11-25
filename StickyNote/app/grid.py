"""The auto layout grid (L1) and the calendar's block in it (L2). Pure maths: no Tk, every size a
plain int in pixels, boxes as (x0, y0, x1, y1).

The grid: tiles all one size, filled column by column, top down, from a home (the first tile's
top-left corner) toward a growth side ("right" or "left"). The docked calendar takes a block of
whole tiles beside its note; the undocked one snaps to the nearest block on the grid's lines.
When the grid runs out of room it slides back, then up, then all tiles shrink together, and what
still doesn't fit forms the overflow pile (P5)."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from calgeom import STRETCH_UP
from space import pile_corner, pile_spots, slide_in
from geom import PILE_STEP, TILE_SHRINK_STEP, Box, inflate, overlap

SIDES = ("right", "left")
VIEWS = ("mini", "big")


@dataclass(frozen=True)
class CalBlock:
    """The calendar on the grid's screen.

    - ``owner``: the tile it is docked to; None = undocked, and then ``near`` is its current box.
    - ``least_mini``, ``least_big``: each view's least size.
    - ``ratio_of(w, h)``: the mini's day-cell ratio (long side over short) in a w x h block.
    - ``hold``: a manual view ("mini" or "big", C2), which wins over the rule.
    - ``block``: a grip size saved in tiles, (cols, rows) (R31). At each tile size it is cut to
      what fits the area (a docked block leaves a column for its note), but never below the
      view's least size."""
    owner: str | None
    least_mini: tuple[int, int]
    least_big: tuple[int, int]
    ratio_of: Callable[[int, int], float]
    hold: str | None
    near: Box | None
    block: tuple[int, int] | None


@dataclass(frozen=True)
class GridInput:
    """One screen's tiles. ``order`` is the tile order (unique ids); ``folded`` maps a folded
    tile to its shown (top bar) height; ``base`` is the unshrunk tile size; ``home``/``side`` the
    saved grid home and growth side (None: the default start / the side with more room); ``area``
    the usable area (already inset by the gap); ``obstacles`` the boxes tiles flow around (free
    notes; not the undocked calendar, which is ``cal``); ``rows`` the column height kept from the
    last re-flow, set while the grid is dragged so it keeps its shape (L1). Kept rows and the home
    hold only while everything fits without shrinking; a grid that must shrink goes to the corner
    of its side ("it goes to a corner only when room runs out")."""
    order: list[str]
    folded: dict[str, int]
    base: tuple[int, int]
    home: tuple[int, int] | None
    side: str | None
    area: Box
    gap: int
    min_size: tuple[int, int]
    obstacles: list[Box]
    cal: CalBlock | None
    corner_step: int = PILE_STEP
    rows: int | None = None


@dataclass
class GridPlan:
    """``spots`` holds every tile, in order: the grid's tiles and the overflow pile's. ``pile``
    lists the piled ids in order. They are the order's last tiles, except that a docked calendar's
    note keeps its tile, so tiles before it can be piled. ``space.pile_spots`` places them, and no
    grid tile is under the pile's footprint. ``block`` is the calendar's box (None without one);
    ``view`` its view, which is the hold or "mini" whenever there is no block. ``home`` and
    ``side`` are where the grid ended up, ``rows`` its column height (tiles).

    ``block_failed``: the calendar belongs on this grid (docked to one of its tiles, or undocked
    with a ``near`` box) but even at the smallest tile size its block can't be placed. Either it
    has no room beside its note (or the note is piled), or it can't fit inside the area, or the
    overflow pile would come within the gap of it or its note. The tiles are then planned exactly
    as if there were no calendar, and ``block`` is None. A docked calendar is undocked by the
    caller (as G7 does when no side fits). False when there is no calendar here to place."""
    spots: dict[str, Box]
    tile: tuple[int, int]
    block: Box | None
    view: str
    home: tuple[int, int]
    side: str
    pile: list[str]
    full: bool
    rows: int
    block_failed: bool = False


@dataclass
class _Fill:
    spots: dict[str, Box]
    block: Box | None
    cols: int           # columns used, the docked block's included
    ok: bool            # every tile got a slot


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class _Planner:
    def __init__(self, inp: GridInput):
        self.inp = inp
        self.order = list(dict.fromkeys(inp.order))
        self.area = inp.area
        self.gap = max(0, int(inp.gap))
        cal = inp.cal
        self.cal = cal
        self.owner = cal.owner if cal is not None and cal.owner in self.order else None
        self.rows = inp.rows if isinstance(inp.rows, int) and inp.rows >= 1 else None
        self.home = tuple(inp.home) if inp.home is not None else None
        bw = inp.base[0]
        if inp.side in SIDES:
            self.side = inp.side
        elif self.home is None:
            self.side = "right"
        else:                                   # the side with more room left over, ties go right
            room_right = self.area[2] - (self.home[0] + bw)
            room_left = self.home[0] - self.area[0]
            self.side = "left" if room_left > room_right else "right"

    # ---- sizes ------------------------------------------------------------------------------
    def sizes(self) -> list[tuple[int, int]]:
        """The base size, then smaller in TILE_SHRINK_STEP steps down to the least size (as today)."""
        (bw, bh), (mw, mh) = self.inp.base, self.inp.min_size
        out, step = [], 0
        while True:
            s = 1 - step * TILE_SHRINK_STEP
            size = (max(mw, round(bw * s)), max(mh, round(bh * s)))
            if not out or size != out[-1]:
                out.append(size)
            if (size[0] <= mw and size[1] <= mh) or s <= 0:
                return out
            step += 1

    def block_dims(self, view, w, h, room):
        """(cols, rows, width, height) of the calendar's block of whole tiles for ``view``: its
        least size in tiles, or the saved grip size cut to ``room`` (cols, rows: the room there is
        where the block goes), whichever is bigger."""
        gap, cal = self.gap, self.cal
        lw, lh = cal.least_big if view == "big" else cal.least_mini
        least = 2 if view == "big" else 1
        cols = max(least, _ceil_div(lw + gap, w + gap))
        rows = max(least, _ceil_div(lh + gap, h + gap))
        saved = cal.block
        if (isinstance(saved, (tuple, list)) and len(saved) == 2
                and all(isinstance(v, int) and v >= 1 for v in saved)):
            cols, rows = max(cols, min(saved[0], room[0])), max(rows, min(saved[1], room[1]))
        return cols, rows, cols * w + (cols - 1) * gap, rows * h + (rows - 1) * gap

    # ---- the view (L2, #4A, R30) ------------------------------------------------------------
    def view(self) -> str:
        cal = self.cal
        if cal is None:
            return "mini"
        if cal.hold in VIEWS:
            return cal.hold
        w, h = self.sizes()[0]
        rows = max(1, _ceil_div(cal.least_mini[1] + self.gap, h + self.gap))
        ratio = cal.ratio_of(w, rows * h + (rows - 1) * self.gap)    # the mini, one tile wide
        if ratio > STRETCH_UP and self.attempt(w, h, "big", shrunk=False) is not None:
            return "big"
        return "mini"

    def shown_view(self, view, block):
        """The view to report: with no block (no calendar here, no box, its note elsewhere, or no
        room beside it) the calendar's hold, else mini."""
        if block is not None:
            return view
        hold = self.cal.hold if self.cal is not None else None
        return hold if hold in VIEWS else "mini"

    # ---- placing ----------------------------------------------------------------------------
    def shown_h(self, tid, h):
        """A tile's height on screen: a folded one its top bar (never taller than a tile)."""
        th = self.inp.folded.get(tid)
        return h if not isinstance(th, int) else max(1, min(h, th))

    def inside(self, box):
        ax0, ay0, ax1, ay1 = self.area
        return ax0 <= box[0] and ay0 <= box[1] and box[2] <= ax1 and box[3] <= ay1

    def corner(self, w):
        ax0, ay0, ax1, _ = self.area
        return (ax0 if self.side == "right" else ax1 - w), ay0

    def span(self, n, w):
        """The range of home x that keeps ``n`` columns inside the area."""
        ax0, _, ax1, _ = self.area
        pitch = w + self.gap
        if self.side == "right":
            return ax0, ax1 - (n * pitch - self.gap)
        return ax0 + (n - 1) * pitch, ax1 - w

    def snap(self, v, origin, pitch, lo, hi, prefer_high):
        """The grid line ``origin + k*pitch`` nearest ``v`` with the block inside [lo, hi]
        (hi = the last start that fits). No line fits: ``v`` clamped (off the lines)."""
        if hi < lo:
            return lo
        kmin, kmax = -((origin - lo) // pitch), (hi - origin) // pitch
        if kmin > kmax:
            return _clamp(v, lo, hi)
        f = (v - origin) // pitch
        ks = [k for k in (f, f + 1) if kmin <= k <= kmax] or [kmin if f < kmin else kmax]
        k = min(ks, key=lambda k: (abs(origin + k * pitch - v), -k if prefer_high else k))
        return origin + k * pitch

    def fill(self, w, h, view, hx, hy, bottom, max_cols, reserved=(), pin=None) -> _Fill:
        """Tiles column by column from (hx, hy), each column down to ``bottom``, skipping any slot
        within the gap of an obstacle, a ``reserved`` box (the pile's footprint) or the calendar's
        block. The docked owner's block goes in the columns beside it, starting at its row (higher
        if it doesn't fit below), its saved grip size cut to the columns left beside it and to the
        area's height in rows (a block taller than the room below starts higher, L1).

        Without ``pin`` the fill stops (``ok`` False) at the first tile with no slot in
        ``max_cols`` columns, or at a docked owner with no room for its block beside it.
        ``pin`` = (owner box, block box) from an earlier fill: both stay put, the other tiles flow
        around them, and a tile with no slot left is skipped (it goes to the pile), as is every
        later one but the owner."""
        gap, side, inp, cal = self.gap, self.side, self.inp, self.cal
        ax0, ay0, ax1, ay1 = self.area
        px_, py_ = w + gap, h + gap
        fit_cols, fit_rows = (ax1 - ax0 + gap) // px_, (ay1 - ay0 + gap) // py_

        def colx(c):
            return hx + c * px_ if side == "right" else hx - c * px_

        def seek(c, y, th, boxes):
            """The first slot from (c, y) clear of ``boxes``: ``(c, y, box)``, or None."""
            while True:
                if c >= max_cols:
                    return None
                if y != hy and y + th > bottom:             # (an empty column takes even a too tall one)
                    c, y = c + 1, hy
                    continue
                x = colx(c)
                box = (x, y, x + w, y + th)
                if any(overlap(inflate(box, gap), o) for o in boxes):
                    y = hy + ((y - hy) // py_ + 1) * py_    # on to the next grid line
                    continue
                return c, y, box

        avoid = [tuple(o) for o in inp.obstacles] + [tuple(r) for r in reserved]
        block = None
        if cal is not None and cal.owner is None and cal.near is not None:
            _, _, bw_, bh_ = self.block_dims(view, w, h, (fit_cols, fit_rows))
            bx = self.snap(cal.near[0], hx, px_, ax0, ax1 - bw_, prefer_high=True)
            by = self.snap(cal.near[1], hy, py_, ay0, ay1 - bh_, prefer_high=False)
            block = (bx, by, bx + bw_, by + bh_)
            avoid.append(block)
        if pin is not None:
            block = pin[1]
            avoid.append(block)
        spots, cols, c, y = {}, 0, 0, hy
        for tid in self.order:
            th = self.shown_h(tid, h)
            if pin is not None and tid == self.owner:       # pinned: keeps its tile
                got = seek(c, y, th, avoid)
                if got is not None and got[2] == pin[0]:    # (the cursor is at it: step past it)
                    c, y = got[0], got[1] + th + gap
                spots[tid] = pin[0]
                continue
            got = seek(c, y, th, avoid + [pin[0]] if pin is not None else avoid)
            if got is None:
                if pin is None:
                    return _Fill(spots, block, cols, False)
                c = max_cols                                # no slot left: piled, as are the rest
                continue
            c, y, box = got
            if tid == self.owner and pin is None:           # its block: the next columns, at its row
                room = (fit_cols - c - 1, fit_rows)
                bcols, _, bw_, bh_ = self.block_dims(view, w, h, room)
                if c + bcols >= max_cols:
                    return _Fill(spots, block, cols, False)
                near_x = colx(c + 1)
                bx = near_x if side == "right" else near_x + w - bw_
                by = y if y + bh_ <= bottom else bottom - bh_    # doesn't fit below: starts higher
                by = max(ay0, min(by, ay1 - bh_))
                block = (bx, by, bx + bw_, by + bh_)
                avoid.append(block)
                cols = max(cols, c + 1 + bcols)
            spots[tid] = box
            cols = max(cols, c + 1)
            y += th + gap
        return _Fill(spots, block, cols, len(spots) == len(self.order))

    def column(self, h, hy, keep):
        """(hy, rows) for a grid whose home y is ``hy``: kept rows (``keep``) clamp the home so the
        shape fits (a kept height taller than the area, say after a work-area change, is cut to
        what fits); otherwise as many rows as fit below it."""
        _, ay0, _, ay1 = self.area
        py_ = h + self.gap
        if keep is not None:
            rows = max(1, min(keep, (ay1 - ay0 + self.gap) // py_))
            return _clamp(hy, ay0, max(ay0, ay1 - (rows * py_ - self.gap))), rows
        hy = _clamp(hy, ay0, max(ay0, ay1 - h))
        return hy, max(1, (ay1 - hy + self.gap) // py_)

    def slide(self, w, h, view, hx0, hy, rows):
        """The fill with the home slid sideways only as far as needed (from ``hx0``) to keep every
        column inside the area; None if no slide does, or if a tile or the calendar's block can't
        fit inside the area at this tile size (so the tiles shrink instead)."""
        ax0, ay0, ax1, ay1 = self.area
        if w > ax1 - ax0 or h > ay1 - ay0:
            return None
        bottom = hy + rows * (h + self.gap) - self.gap
        maxc = max(1, (ax1 - ax0 + self.gap) // (w + self.gap))
        need = 1
        lo, hi = self.span(need, w)
        hx = _clamp(hx0, lo, max(lo, hi))
        for _ in range(maxc + 2):
            f = self.fill(w, h, view, hx, hy, bottom, maxc + 1)
            if not f.ok:
                return None
            need = max(need, f.cols)
            lo, hi = self.span(need, w)
            if lo > hi:
                return None
            nhx = _clamp(hx0, lo, hi)
            if nhx == hx:
                if f.block is not None and not self.inside(f.block):
                    return None
                return f, (hx, hy), rows
            hx = nhx
        return None

    def attempt(self, w, h, view, shrunk):
        """Everything placed at tile size w x h without piling: ``(fill, home, rows)`` or None.
        Unshrunk, from the home (kept rows clamp it): slide sideways; past the full width (rows
        not kept) raise the home by the least amount that adds a row, until it fits or reaches
        the top. Shrunk tiles start from the corner of the grid's side with as many rows as fit:
        the home and kept rows count only while nothing has to shrink (L1)."""
        _, ay0, _, ay1 = self.area
        keep = None if shrunk else self.rows
        if self.home is None or shrunk:
            hx0, hy = self.corner(w)
        else:
            hx0, hy = self.home
        hy, rows = self.column(h, hy, keep)
        py_ = h + self.gap
        while True:
            got = self.slide(w, h, view, hx0, hy, rows)
            if got is not None or keep is not None or hy <= ay0:
                return got
            hy = max(ay0, ay1 + self.gap - (rows + 1) * py_)
            rows = max(1, (ay1 - hy + self.gap) // py_)

    # ---- the overflow pile (P5) -------------------------------------------------------------
    def frame(self, w, h):
        """The full grid at tile size w x h: ``(hx, hy, rows, bottom, max_cols)``, in the corner of
        its side with as many rows and columns as fit."""
        ax0, _, ax1, _ = self.area
        hx0, hy = self.corner(w)
        hy, rows = self.column(h, hy, None)
        maxc = max(1, (ax1 - ax0 + self.gap) // (w + self.gap))
        lo, hi = self.span(maxc, w)
        return _clamp(hx0, lo, max(lo, hi)), hy, rows, hy + rows * (h + self.gap) - self.gap, maxc

    def overflow(self, w, h, view):
        """At the least size: as many tiles as fit, the rest to the pile, which is
        ``(fill, pile ids, pile boxes, home, rows)``; None when the calendar's block fails (the
        caller then plans as if there were no calendar).

        The first fill has no pile reserved. A docked block placed there is settled: its note's
        tile and the block are pinned for the rest, so reserving the pile's room never loses a
        block that fit. The pile goes in the corner farthest from the calendar (P5,
        ``space.pile_corner``) and stops short of the calendar's box (``space.pile_spots``'s
        ``avoid``: the block, else the undocked calendar's ``near`` box). The block fails when:
        - it has no room beside its note at this size, or its note is piled;
        - it can't fit inside the area at this size (docked or undocked);
        - the settled pile still comes within the gap of its note (the note isn't avoided), or
          (a safety net: ``avoid`` keeps the pile off it) a piled box overlaps the block."""
        hx, hy, rows, bottom, maxc = self.frame(w, h)
        first = self.fill(w, h, view, hx, hy, bottom, maxc)
        if first.block is not None and not self.inside(first.block):
            return None
        pin = None
        if self.owner is not None:
            if first.block is None:                         # no room beside it, or it is piled
                return None
            pin = (first.spots[self.owner], first.block)
        near = self.cal.near if self.cal is not None and self.cal.owner is None else None
        cal_box = first.block if first.block is not None else near
        corner = pile_corner(self.area, cal_box)
        avoid = (tuple(cal_box),) if cal_box is not None else ()
        got = self.piled(w, h, view, (hx, hy, bottom, maxc), corner, pin, avoid)
        return None if got is None else (*got, (hx, hy), rows)

    def piled(self, w, h, view, frame, corner, pin, avoid):
        """The grid and its pile in ``corner``, kept off ``avoid`` (the calendar's box):
        ``(fill, pile ids, pile boxes)``. Each round that leaves a grid tile within the gap of a
        pile spot reserves the pile's footprint (its spots themselves, as they are and at full tile
        size, not their bounding box) and fills again. Reserving only adds obstacles, so the piled
        count never falls, and a pile reserves nothing unless it exists. A round that misses has a
        piled count not seen before (with an earlier count's footprint reserved, nothing can be
        near that pile), so ``len(order) + 1`` rounds always settle it. None when the pile comes
        within the gap of the pinned note, or onto an ``avoid`` box, neither of which can move."""
        hx, hy, bottom, maxc = frame
        step = self.inp.corner_step
        note = pin[0] if pin is not None else None
        reserved: list[Box] = []
        for _ in range(len(self.order) + 2):
            f = self.fill(w, h, view, hx, hy, bottom, maxc, reserved, pin)
            pile = [t for t in self.order if t not in f.spots]
            boxes = pile_spots([(w, self.shown_h(t, h)) for t in pile], self.area, corner, step, avoid=avoid)
            if note is not None and any(overlap(inflate(note, self.gap), s) for s in boxes):
                return None
            if any(overlap(a, s) for a in avoid for s in boxes):
                return None
            if not any(overlap(inflate(t, self.gap), s) for t in f.spots.values() for s in boxes):
                return f, pile, boxes
            full = pile_spots([(w, h)] * len(pile), self.area, corner, step, avoid=avoid)
            reserved = list(dict.fromkeys(reserved + boxes + full))
        if avoid:
            return None
        # (not reached, see above) every tile piled: no grid tile is under the pile
        return (_Fill({}, None, 0, False), list(self.order),
                pile_spots([(w, self.shown_h(t, h)) for t in self.order], self.area, corner, step))

    def plan(self) -> GridPlan:
        view = self.view()
        sizes = self.sizes()
        for n, (w, h) in enumerate(sizes):
            got = self.attempt(w, h, view, shrunk=n > 0)
            if got is not None:
                f, home, rows = got
                return GridPlan(dict(f.spots), (w, h), f.block, self.shown_view(view, f.block), home,
                                self.side, [], False, rows)
        w, h = sizes[-1]
        got = self.overflow(w, h, view)
        if got is None:                 # the calendar's block fails: as if there were no calendar
            plain = _Planner(replace(self.inp, cal=None)).plan()
            plain.view, plain.block_failed = self.shown_view(view, None), True
            return plain
        f, pile, boxes, home, rows = got
        piled = dict(zip(pile, boxes))
        spots = {t: f.spots[t] if t in f.spots else piled[t] for t in self.order}
        return GridPlan(spots, (w, h), f.block, self.shown_view(view, f.block), home, self.side,
                        pile, bool(pile), rows)


def plan_grid(inp: GridInput) -> GridPlan:
    """Plan the auto layout grid for one screen (L1, L2). Deterministic; see the module doc."""
    return _Planner(inp).plan()


def slot_at(plan_or_input, point) -> int | None:
    """The order index of the tile under ``point`` (the topmost one in the pile), or None over a
    gap, the calendar's block or nothing (Ctrl-swap and rejoin, L3)."""
    if isinstance(plan_or_input, GridPlan):
        plan, order = plan_or_input, list(plan_or_input.spots)
    else:
        plan, order = plan_grid(plan_or_input), list(plan_or_input.order)
    x, y = point
    for tid in reversed(list(plan.spots)):
        b = plan.spots[tid]
        if b[0] <= x < b[2] and b[1] <= y < b[3]:
            return order.index(tid)
    return None


# ---- Tidy (T1) ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TidyItem:
    """One note (or note + docked calendar pair) to tidy: its shown size, a pair's union."""
    id: str
    w: int
    h: int


def plan_tidy(items, area, gap, step) -> tuple[dict[str, Box], list[str]]:
    """Columns from the area's right edge, top down, in the given order, each slot right-aligned.
    A full screen starts another layer ``step`` further in (over the first), only once something
    is on the current layer. When the next layer's offset would start past the area, the layers
    start over from offset 0, so at that depth many layers overlap. Every box is then clamped into
    ``area`` per axis (``space.slide_in``: a box larger than the area lines up with its start);
    notes never shrink. Returns the boxes and every id whose final box overlaps another tidied one
    (to be marked stacked)."""
    left, top, right, bottom = area
    gap, step = max(0, int(gap)), max(0, int(step))
    x_right, y, col_w, layer, on_layer = right, top, 0, 0, 0
    boxes: dict[str, Box] = {}
    for it in items:
        base_y = top + layer * step
        if y > base_y and y + it.h > bottom:            # the column is full
            x_right -= col_w + gap
            y, col_w = base_y, 0
        if on_layer and x_right - it.w < left:          # the screen is full: another layer
            layer += 1
            if top + layer * step >= bottom or right - layer * step <= left:
                layer = 0                               # too deep to step further: start over
            x_right, y, col_w, on_layer = right - layer * step, top + layer * step, 0, 0
        box = (x_right - it.w, y, x_right, y + it.h)
        dx, dy = slide_in(box, [area], 0)
        boxes[it.id] = (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
        on_layer += 1
        y += it.h + gap
        col_w = max(col_w, it.w)
    ids = list(boxes)
    layered = [a for a in ids if any(b != a and overlap(boxes[a], boxes[b]) for b in ids)]
    return boxes, layered
