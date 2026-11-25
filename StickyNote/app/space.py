"""Where things can go: the shapes that take up space (S1), the nearest free spot (S2, S3),
shrink-to-fit and the overflow pile (P5), sliding back inside a screen (M3) and the new-note
column (N2). Pure maths: no Tk, every size a plain int in pixels, boxes ``(x0, y0, x1, y1)``.
``areas`` are the usable work areas (``geom.usable``), one per screen."""
from __future__ import annotations

from dataclasses import dataclass

from geom import PILE_RESET, TILE_SHRINK_STEP, Box, center, inflate, is_free, overlap, union

__all__ = ["Shape", "nearest_free", "shrink_to_fit", "pile_corner", "pile_spots", "pile_start",
           "column_spot", "slide_in", "split_pair"]


# ---------------------------------------------------------------------------------------------
# Shapes

@dataclass(frozen=True)
class Shape:
    """One thing in the space list.

    ``kind``: ``"note"``; ``"cal"`` (the undocked calendar, id ``geom.CAL``); ``"pair"`` (a note
    and its docked calendar: ``box`` is their union, ``parts == (note_box, cal_box)``, ``side`` is
    where the calendar sits); or ``"held"`` (the room a minimized note and its calendar keep, C4:
    a fixed obstacle nothing moves or lands on). ``least`` is the smallest box it may be squeezed
    or shrunk to; for a pair that is the union at the smallest note size."""
    id: str
    box: Box
    kind: str = "note"
    stacked: bool = False
    parts: tuple[Box, ...] = ()
    side: str | None = None
    least: tuple[int, int] | None = None
    cal_least: tuple[int, int] | None = None


# ---------------------------------------------------------------------------------------------
# Which area a box is on

def _holding(box, areas) -> int | None:
    """The area holding the box's centre, or None."""
    cx, cy = center(box)
    for i, a in enumerate(areas):
        if a[0] <= cx < a[2] and a[1] <= cy < a[3]:
            return i
    return None


def _area_of(box, areas) -> int:
    """The area holding the box's centre; otherwise the one it overlaps most; otherwise the nearest."""
    i = _holding(box, areas)
    if i is not None:
        return i

    def shared(a):
        return max(0, min(box[2], a[2]) - max(box[0], a[0])) * max(0, min(box[3], a[3]) - max(box[1], a[1]))
    best = max(range(len(areas)), key=lambda j: shared(areas[j]))
    if shared(areas[best]) > 0:
        return best

    def dist(a):
        dx = max(a[0] - box[2], box[0] - a[2], 0)
        dy = max(a[1] - box[3], box[1] - a[3], 0)
        return dx * dx + dy * dy
    return min(range(len(areas)), key=lambda j: dist(areas[j]))


# ---------------------------------------------------------------------------------------------
# Free spots (S2, S3) and shrink-to-fit (P5 step 1)

def _axis_values(want, lo, hi, size, starts, ends, gap) -> set[int]:
    """Where a ``size``-long box may start along one axis of an area ``[lo, hi)``: where it wants
    to be, flush with either edge, and a gap past or before each obstacle; clipped into the area."""
    last = hi - size
    vals = {want, lo, last}
    vals.update(e + gap for e in ends)
    vals.update(s - gap - size for s in starts)
    return {min(max(v, lo), last) for v in vals}


def nearest_free(w, h, origin, areas, obstacles, gap, home=None) -> Box | None:
    """The free ``w`` x ``h`` spot (S2) whose top-left is nearest ``origin`` (S3): on ``areas[home]``
    first, then by the length of the move, then the smaller up/down move, then right before left
    (then down before up). None: no free spot on any area."""
    ox, oy = origin
    obstacles = list(obstacles)
    starts_x, ends_x = [o[0] for o in obstacles], [o[2] for o in obstacles]
    starts_y, ends_y = [o[1] for o in obstacles], [o[3] for o in obstacles]
    ranked = []
    for i, a in enumerate(areas):
        if a[2] - a[0] < w or a[3] - a[1] < h:
            continue
        away = home is not None and i != home
        xs = _axis_values(ox, a[0], a[2], w, starts_x, ends_x, gap)
        ys = _axis_values(oy, a[1], a[3], h, starts_y, ends_y, gap)
        for x in xs:
            for y in ys:
                dx, dy = x - ox, y - oy
                ranked.append(((away, dx * dx + dy * dy, abs(dy), dx < 0, dy < 0, i), x, y))
    ranked.sort()
    for _key, x, y in ranked:
        box = (x, y, x + w, y + h)
        if is_free(box, areas, obstacles, gap):
            return box
    return None


def shrink_to_fit(w, h, min_w, min_h, origin, areas, obstacles, gap, home=None) -> Box | None:
    """The nearest free spot for the box scaled down in ``TILE_SHRINK_STEP`` steps from full size,
    each side never below its minimum (and never above its own size). None: not even at the
    minimum size."""
    obstacles = list(obstacles)
    floor = (min(min_w, w), min(min_h, h))
    tried = None
    for k in range(round(1 / TILE_SHRINK_STEP) + 1):
        s = 1 - k * TILE_SHRINK_STEP
        size = (max(floor[0], round(w * s)), max(floor[1], round(h * s)))
        if size != tried:
            tried = size
            hit = nearest_free(size[0], size[1], origin, areas, obstacles, gap, home)
            if hit is not None:
                return hit
        if size == floor:
            break
    return None


# ---------------------------------------------------------------------------------------------
# The overflow pile (P5 step 2)

CORNERS = ("br", "bl", "tr", "tl")      # also the tie order: bottom-right is the default


def _corner_point(box, corner) -> tuple[int, int]:
    """The box's point at ``corner``: its top-left for "tl", bottom-right for "br" and so on."""
    return (box[2] if corner[1] == "r" else box[0]), (box[3] if corner[0] == "b" else box[1])


def pile_corner(area, cal_box) -> str:
    """The corner of ``area`` farthest from the calendar's centre; "br" with no calendar."""
    if cal_box is None:
        return "br"
    cx, cy = center(cal_box)

    def far(c):
        x, y = _corner_point(area, c)
        return (x - cx) ** 2 + (y - cy) ** 2
    return max(CORNERS, key=far)


_MAX_CYCLES = 64        # a bound on the cycles one restart may use (each is >= (reset-1)*step wide)


class _Pile:
    """One pile's layout (``pile_spots`` has the rules): which cycles each restart uses, where each
    cycle starts, and where pile index ``i`` sits. ``hint`` is the ``(w, h)`` assumed where no
    member says (a cycle's width, the footprint's height)."""

    def __init__(self, area, corner, step, reset, avoid, hint):
        if corner not in CORNERS:
            raise ValueError(corner)
        self.area, self.step, self.reset = tuple(area), step, reset
        self.avoid = [tuple(a) for a in avoid]
        self.right, self.bottom = corner[1] == "r", corner[0] == "b"
        self.half = max(1, step // 2)
        self.hint = hint
        self.offs = {0: 0}              # cycle -> how far in from the corner's side it starts
        self.wide = {}                  # cycle -> its widest member
        self.tall = hint[1]             # the tallest member (or the hint)
        self.used0, self.full0 = [], False     # restart 0's cycles, decided one at a time, in order
        self.per = {}                   # restart (>= 1) -> how many cycles it uses
        self.moves = {}                 # (w, h, r, c) -> the shared slide of that cycle at that size

    def inward(self, box) -> int:
        return self.area[2] - box[2] if self.right else box[0] - self.area[0]

    def anchor_y(self, box) -> int:
        return box[3] if self.bottom else box[1]

    def offset(self, c) -> int:
        if c not in self.offs:
            self.offs[c] = (self.offset(c - 1) + (self.reset - 1) * self.step
                            + self.wide.get(c - 1, self.hint[0]))
        return self.offs[c]

    def raw(self, w, h, r, c, k) -> Box:
        a0, a1, a2, a3 = self.area
        inward = self.offset(c) + k * self.step + r * self.half
        away = (r % 2) * self.half
        px = a2 - inward if self.right else a0 + inward
        py = a3 - (self.reset - 1) * self.step + k * self.step - away if self.bottom else a1 + k * self.step + away
        x0, y0 = (px - w if self.right else px), (py - h if self.bottom else py)
        return x0, y0, x0 + w, y0 + h

    def spot(self, w, h, r, c, k) -> Box:
        key = (w, h, r, c)
        if key not in self.moves:
            cycle = union(self.raw(w, h, r, c, j) for j in range(self.reset))
            self.moves[key] = slide_in(cycle, [self.area], 0)
        dx, dy = self.moves[key]
        x0, y0, x1, y1 = self.raw(w, h, r, c, k)
        return x0 + dx, y0 + dy, x1 + dx, y1 + dy

    def usable(self, r, c) -> bool:
        """Cycle ``c``'s whole footprint in restart ``r`` is inside the area and clear of ``avoid``."""
        a0, a1, a2, a3 = self.area
        lo = self.offset(c) + r * self.half
        hi = lo + (self.reset - 1) * self.step + max(self.wide.get(c, 0), self.hint[0])
        x0, x1 = (a2 - hi, a2 - lo) if self.right else (a0 + lo, a0 + hi)
        away, span = (r % 2) * self.half, (self.reset - 1) * self.step + self.tall
        y0, y1 = (a3 - away - span, a3 - away) if self.bottom else (a1 + away, a1 + away + span)
        foot = (x0, y0, x1, y1)
        return a0 <= x0 and a1 <= y0 and x1 <= a2 and y1 <= a3 and not any(overlap(foot, o) for o in self.avoid)

    def has0(self, c) -> bool:
        """Restart 0 uses cycle ``c``: cycles are taken in order while they fit (cycle 0 always)."""
        while len(self.used0) <= c and not self.full0:
            n = len(self.used0)
            if n == 0 or (n < _MAX_CYCLES and self.usable(0, n)):
                self.used0.append(n)
            else:
                self.full0 = True
        return c < len(self.used0)

    def cycles_in(self, r) -> int:
        if r == 0:
            self.has0(_MAX_CYCLES)
            return len(self.used0)
        if r not in self.per:
            n = 1
            while n < self.cycles_in(0) and self.usable(r, n):
                n += 1
            self.per[r] = n
        return self.per[r]

    def locate(self, i) -> tuple[int, int, int]:
        """``(restart, cycle, spot)`` of pile index ``i``."""
        r = 0
        while True:
            if r == 0:
                if self.has0(i // self.reset):
                    return 0, i // self.reset, i % self.reset
                i -= len(self.used0) * self.reset
            else:
                n = self.cycles_in(r)
                if i < n * self.reset:
                    return r, i // self.reset, i % self.reset
                i -= n * self.reset
            r += 1

    def index(self, r, c, k) -> int:
        return (sum(self.cycles_in(q) for q in range(r)) + c) * self.reset + k

    def add(self, c, w, h):
        self.wide[c] = max(self.wide.get(c, 0), w)
        self.tall = max(self.tall, h)

    def read(self, boxes) -> list[tuple[int, int, int, Box]]:
        """``(restart, cycle, spot, box)`` for each box that sits exactly on one of the pile's spots
        at its own size; nothing else is a member. Cycle 0 starts at the corner. A later cycle's
        offset is read from its members' own positions (``inward - k * step``, with ``k`` and the
        restart's parity from the box's y): the smallest one at least a footprint past the cycle
        before it, so it doesn't depend on a width that was dragged out."""
        boxes = [tuple(b) for b in boxes]
        restarts = len(boxes) // self.reset + 2
        found, pending = [], []
        for b in boxes:
            w, h = b[2] - b[0], b[3] - b[1]
            hit = next(((r, k) for r in range(restarts) for k in range(self.reset)
                        if self.spot(w, h, r, 0, k) == b), None)
            if hit is not None:
                found.append((hit[0], 0, hit[1], b))
                self.add(0, w, h)
                continue
            ay, q = self.anchor_y(b), self.inward(b)
            cands = [(q - k * self.step, rp, k) for rp in (0, 1) for k in range(self.reset)
                     if self.anchor_y(self.spot(w, h, rp, 0, k)) == ay]
            if cands:
                pending.append((b, cands))
        c = 1
        while pending and c < _MAX_CYCLES:
            least = self.offs[c - 1] + (self.reset - 1) * self.step + self.wide.get(c - 1, 0)
            starts = [q - rp * self.half for _b, cs in pending for q, rp, _k in cs if q - rp * self.half >= least]
            if not starts:
                break
            self.offs[c] = min(starts)
            rest = []
            for b, cs in pending:
                w, h = b[2] - b[0], b[3] - b[1]
                hit = None
                for q, rp, k in cs:
                    d = q - self.offs[c]
                    if (d >= 0 and d % self.half == 0 and d // self.half < restarts
                            and self.spot(w, h, d // self.half, c, k) == b):
                        hit = (d // self.half, c, k, b)
                        break
                if hit is None:
                    rest.append((b, cs))
                else:
                    found.append(hit)
                    self.add(c, w, h)
            pending = rest
            c += 1
        return found


def pile_spots(sizes, area, corner, step, reset=PILE_RESET, start=0, *, before=(), avoid=()) -> list[Box]:
    """One box per size, at the pile's spots ``start``, ``start + 1``, ...

    The pile is made of cycles of ``reset`` spots:
    - **In a cycle,** spot 0 is in the corner (raised by ``(reset - 1) * step`` for a bottom corner,
      so the last spot ends on the edge) and each next spot is ``step`` lower and ``step`` nearer
      the middle, so every top bar shows.
    - **The next cycle** starts one footprint further in from the corner's side, right beside it:
      ``offset(c + 1) = offset(c) + (reset - 1) * step + W(c)``, ``W(c)`` being cycle ``c``'s widest
      member (572 px for 320-wide notes at step 36, reset 8), so no later cycle covers an earlier
      top bar. Where a cycle has members its offset is read from their positions, so a widest member
      dragged out doesn't move it. Members not in this call come from ``before`` (the boxes on the
      pile, as given to ``pile_start``); only boxes exactly on a spot count (``pile_start``).
    - **A cycle is used** only while its whole footprint (``(reset - 1) * step`` plus the widest and
      the tallest size, on each axis) stays inside the area and overlaps none of ``avoid`` (callers
      pass the calendar's box). Cycle 0 is always used.
    - **When the next cycle would break that, the pile is full:** it starts over at cycle 0, restart
      ``r = 1, 2, ...``, every spot shifted ``r * step // 2`` inward, and ``step // 2`` away from the
      corner's edge on odd restarts, with the cycles that still fit shifted that way. This is the
      only overlap the pile makes: every note stays partly in sight and none lands exactly on
      another. (Shifting ``r * step // 2`` away on every restart would put restart 2 of a
      top-corner pile exactly on restart 0, one spot along.)
    - **Spot k of every size** in a cycle shares the same point at ``corner``, unless its cycle
      slides: a cycle too big for the area (only cycle 0, at a size it can't hold) slides in as one,
      with one shared ``(dx, dy)`` per size (``slide_in``'s rule: it lines up with the area's start,
      its top for the height), so its last spots can hang past the far edge with their top bars on
      screen; callers trim those members to fit."""
    sizes = [tuple(s) for s in sizes]
    if corner not in CORNERS:
        raise ValueError(corner)
    if not sizes:
        return []
    pile = _Pile(area, corner, step, reset, avoid, (max(w for w, _ in sizes), max(h for _, h in sizes)))
    pile.read(before)
    out = []
    for n, (w, h) in enumerate(sizes):
        r, c, k = pile.locate(start + n)
        out.append(pile.spot(w, h, r, c, k))
        pile.add(c, w, h)
    return out


def pile_start(stacked, size, area, corner, step, reset=PILE_RESET, *, avoid=()) -> int:
    """The ``start`` for a new member of ``size``, given the boxes of the stacked shapes in ``area``.

    A member is a box whose corner point sits exactly on a pile spot's, at its own size and for
    that index, the way ``pile_spots`` makes them; Tidy layers and other stacked boxes that only
    overlap the pile's corner are not members. ``size`` is the size assumed where no member says,
    as ``pile_spots([size], ...)`` assumes, and ``avoid`` is the same as for ``pile_spots``: pass
    the same ``stacked`` there as ``before`` so the new member lands where this reading counts.
    Returns ``max(members, 1 + highest index)``, so a note dragged out of the middle doesn't make
    the next one land on the top member; 0 with no members."""
    pile = _Pile(area, corner, step, reset, avoid, tuple(size))
    found = pile.read(stacked)
    if not found:
        return 0
    return max(len(found), 1 + max(pile.index(r, c, k) for r, c, k, _b in found))


# ---------------------------------------------------------------------------------------------
# Screen edges (M3)

def slide_in(box, areas, home=None) -> tuple[int, int]:
    """The ``(dx, dy)`` that puts ``box`` inside ``areas[home]`` (default: the area holding its
    centre, else the one it overlaps most, else the nearest), moving it as little as possible.
    Along an axis where it is longer than the area it lines up with the area's start."""
    if not areas:
        return 0, 0
    a = areas[_area_of(box, areas) if home is None else home]

    def axis(b0, b1, a0, a1):
        if b1 - b0 > a1 - a0 or b0 < a0:
            return a0 - b0
        if b1 > a1:
            return a1 - b1
        return 0
    return axis(box[0], box[2], a[0], a[2]), axis(box[1], box[3], a[1], a[3])


# ---------------------------------------------------------------------------------------------
# Note + docked calendar

SHARED_AXIS = {"right": 0, "left": 0, "below": 1, "above": 1}     # 0: side by side in x, 1: in y


def split_pair(shape, box, gap) -> tuple[Box, Box]:
    """``(note, cal)`` for a pair's new union ``box``, axis by axis:
    - same extent: both parts shift;
    - the shared axis changed: the calendar keeps its size and side, the note takes the rest
      minus ``gap``;
    - the other axis changed: the note takes the new extent and the calendar matches it (C1),
      never below ``cal_least`` (#20A), lined up with the note's start as it docks."""
    side = shape.side
    if side not in SHARED_AXIS or len(shape.parts) != 2:
        raise ValueError(side)
    note, cal = list(shape.parts[0]), list(shape.parts[1])
    old = shape.box
    least = shape.cal_least or (0, 0)
    far = side in ("right", "below")            # the calendar is at the far end of the shared axis
    for ax in (0, 1):
        lo, hi = ax, ax + 2
        if box[hi] - box[lo] == old[hi] - old[lo]:
            d = box[lo] - old[lo]
            note[lo] += d; note[hi] += d; cal[lo] += d; cal[hi] += d
        elif ax == SHARED_AXIS[side]:
            size = cal[hi] - cal[lo]
            if far:
                cal[lo], cal[hi] = box[hi] - size, box[hi]
                note[lo], note[hi] = box[lo], box[hi] - size - gap
            else:
                cal[lo], cal[hi] = box[lo], box[lo] + size
                note[lo], note[hi] = box[lo] + size + gap, box[hi]
        else:
            size = max(least[ax], box[hi] - box[lo])
            note[lo], note[hi] = box[lo], box[hi]
            cal[lo], cal[hi] = box[lo], box[lo] + size
    return tuple(note), tuple(cal)


# ---------------------------------------------------------------------------------------------
# New notes (N2)

def column_spot(parent_box, size, areas, obstacles, gap) -> Box | None:
    """Where a new ``size`` note made from the note at ``parent_box`` goes, on the parent's area:
    just under the parent; else down the columns to its right, then to its left (then flush with
    either edge), from the top of the parent's column; else those columns from the area's top.
    Clear of every obstacle by ``gap``. None: no room."""
    if not areas:
        return None
    w, h = size
    obstacles = list(obstacles)
    i = _holding(parent_box, areas)
    left, top, right, bottom = areas[0 if i is None else i]
    sx, sy = parent_box[0], parent_box[1]

    def first_free(x, y):
        if x < left or x + w > right:
            return None
        y = max(y, top)
        while y + h <= bottom:
            hit = [o for o in obstacles if overlap(inflate((x, y, x + w, y + h), gap), o)]
            if not hit:
                return y
            y = max(o[3] for o in hit) + gap
        return None

    step = w + gap
    xs = [sx + k * step for k in range(1, 40) if sx + k * step + w <= right]
    xs += [sx - k * step for k in range(1, 40) if sx - k * step >= left]
    for x in (left, right - w):                 # the area's edges too
        if x not in xs and x != sx:
            xs.append(x)
    column_top = min([o[1] for o in obstacles if o[0] < sx + w and sx < o[2]] + [sy])
    tries = [(sx, parent_box[3] + gap)] + [(x, column_top) for x in xs] + [(x, top) for x in [sx] + xs]
    for x, y0 in tries:
        y = first_free(x, y0)
        if y is not None:
            return x, y, x + w, y + h
    return None


# ---------------------------------------------------------------------------------------------
# Making room: growth pushes, the edge and relocations (P1, P2, P3); giving room back (P4).
# This section was added after the ones above; the extra names it needs are imported here.

from dataclasses import field                                   # noqa: E402

from geom import CAL, PILE_STEP, fits_one, union                # noqa: E402

__all__ += ["Plan", "plan_growth", "plan_close_up", "plan_give_back"]

GROW_SLACK = 2          # "in line" starts this many px back from the grower's old edge
_DIRS = ("right", "left", "down", "up")
_AXIS = {"right": 0, "left": 0, "down": 1, "up": 1}


@dataclass
class Plan:
    """What one growth, close-up or give-back does.

    ``boxes``: the final box of every id it moves or resizes, growers included. ``allowed``: in
    drag mode, every grower's box as far as it may grow (clamped at the edge); empty in app mode.
    ``relocated``: ids that left their place for a free spot, a shrunk spot or the pile;
    ``piled`` is the part of them that went to the pile. ``shrunk``: ids (growers excluded) the
    edge squeeze, shrink-to-fit or the pile made smaller. The plan sets no flags: the caller
    marks ``piled`` ids stacked and gives ``shrunk`` ids their own size (P5, P6)."""
    boxes: dict[str, Box] = field(default_factory=dict)
    allowed: dict[str, Box] = field(default_factory=dict)
    piled: list[str] = field(default_factory=list)
    relocated: list[str] = field(default_factory=list)
    shrunk: list[str] = field(default_factory=list)


def _turn(d, b) -> Box:
    """``b`` seen with direction ``d`` turned to "right": the push runs toward +x, so [0] is the
    near edge, [2] the far edge and [1]..[3] the rows. ``_unturn`` maps it back."""
    if d == "right":
        return b[0], b[1], b[2], b[3]
    if d == "left":
        return -b[2], b[1], -b[0], b[3]
    if d == "down":
        return b[1], b[0], b[3], b[2]
    return -b[3], b[0], -b[1], b[2]


def _unturn(d, t) -> Box:
    if d == "up":
        return t[1], -t[2], t[3], -t[0]
    return _turn(d, t)                          # the other three undo themselves


def _rows(a, b) -> bool:
    """Two turned boxes share some rows."""
    return a[1] < b[3] and b[1] < a[3]


def _area_index(box, areas) -> int | None:
    return _area_of(box, areas) if areas else None


def _chain(s, why) -> list:
    """The lane that put ``s`` where it is, farthest first: ``s`` and every shape whose width set
    its place. A rigid group mate passes its shift on, but its own width doesn't count."""
    lane, seen, cur = [s], {s}, s
    while True:
        r = why.get(cur)
        if r is None or r[0] == "seed" or r[1] in seen:
            return lane
        seen.add(r[1])
        if r[0] == "push":
            lane.append(r[1])
        cur = r[1]


def _spread(total, lane, caps) -> dict:
    """``total`` px taken evenly from the lane's shapes, none past its cap (water-filling);
    the px that don't divide evenly come off the farthest first."""
    cut = dict.fromkeys(lane, 0)
    left = total
    while left > 0:
        open_ = [m for m in lane if cut[m] < caps[m]]
        if not open_:
            break
        each = left // len(open_)
        if each == 0:
            for m in open_[:left]:
                cut[m] += 1
            break
        for m in open_:
            c = min(each, caps[m] - cut[m])
            cut[m] += c
            left -= c
    return cut


def _cut(sd, cut) -> None:
    """Take ``cut`` px off a drag seed's growth (P2). A box whose near edge moved forward too (a row
    mate that grows and shifts, P3) first moves back as a whole, no further than its old near edge;
    the rest comes off its far edge, never below its old far edge (nor, for a box that shifted,
    narrower than its floor, or its own old size when that is smaller: so it can always get back
    to its old box, and a cut always changes something until it has)."""
    if cut <= 0:
        return
    back = min(cut, max(0, sd["near"] - sd["near_old"]))
    sd["near"] -= back
    sd["new"] -= back
    lower = sd["old"]
    if sd["asked"] > sd["near_old"]:
        lower = min(sd["new"], max(lower, sd["near"] + min(sd["floor"], sd["old"] - sd["near_old"])))
    sd["new"] = max(sd["new"] - (cut - back), lower)


def _push(d, grows, movable, areas, held, rigid, gap, mode, least, slack):
    """One direction of P1 and P2.

    ``grows``: ``(id, old, new, in_line, floor)`` per grower (real boxes; ``in_line`` is False for
    a grower with no old shape, which pushes nothing; ``floor`` its smallest size, for the drag
    cut). ``movable``: the shapes that may be pushed. ``held``: boxes a lane stops at, like the
    area's edge. ``rigid``: id -> its linked group when the group moves as one, else None.
    Returns ``(moved, dropped, reach)``: ``moved[id] = (box, shift)``; the ids the app squeeze
    dropped from their lane, farthest first; and ``reach[id] = (near, far)``, each growing
    grower's edges in turned coordinates (``near`` None unless the drag cut moved it back)."""
    tareas = [_turn(d, a) for a in areas]
    theld = [(_turn(d, h), _area_index(h, areas)) for h in held]

    def far_cap(t, area):
        """How far a turned box's far edge may go: its area's edge, or a gap before held room
        ahead of it in its rows."""
        cap = tareas[area][2] if area is not None else float("inf")
        for th, ha in theld:
            if ha == area and _rows(th, t) and th[0] >= t[2] - slack:
                cap = min(cap, th[0] - gap)
        return cap

    seeds = []
    for gid, old, new, in_line, floor in grows:
        to, tn = _turn(d, old), _turn(d, new)
        if tn[2] <= to[2]:
            continue
        seeds.append({"id": gid, "rows": to, "old": to[2], "new": tn[2], "near_old": to[0], "near": tn[0],
                      "asked": tn[0], "floor": floor[_AXIS[d]], "in_line": in_line,
                      "cap": far_cap(to, _area_index(old, areas))})
    if mode == "drag":                          # a grower or shifted mate past the edge: the whole
        over = max([sd["new"] - sd["cap"] for sd in seeds] + [0])   # lane is cut by it together
        for sd in seeds:
            _cut(sd, over)

    def reach():
        return {sd["id"]: (None if sd["near"] == sd["asked"] else sd["near"], sd["new"]) for sd in seeds}

    if not movable or not any(sd["in_line"] and sd["new"] > sd["old"] for sd in seeds):
        return {}, [], reach()

    ax = _AXIS[d]
    items = {}                                  # id -> (turned box, area, far cap, floor)
    for s in movable:
        t = _turn(d, s.box)
        area = _area_index(s.box, areas)
        items[s.id] = (t, area, far_cap(t, area), min(t[2] - t[0], (s.least or least)[ax]))
    order = sorted(items, key=lambda i: (items[i][0][0], items[i][0][1], i))

    def relations(live):
        """Who can push whom: a seed or a shape pushes the shapes in its rows past its old far
        edge (minus the slack); rigid group mates never push each other. A push may reach across
        a monitor line (the gap holds there too, S2), but each shape stops at its own area's edge."""
        seeds_of, pushers_of = {}, {}
        for s in live:
            t = items[s][0]
            seeds_of[s] = [sd for sd in seeds if sd["in_line"] and _rows(sd["rows"], t)
                           and t[0] >= sd["old"] - slack]
            pushers_of[s] = [p for p in live if p != s and _rows(items[p][0], t)
                             and t[0] >= items[p][0][2] - slack
                             and (rigid.get(s) is None or rigid.get(s) != rigid.get(p))]
        groups, seen = [], set()
        for s in live:
            g = rigid.get(s)
            if g is not None and g not in seen:
                seen.add(g)
                members = [i for i in live if i in g]
                if len(members) > 1:
                    groups.append(members)
        return seeds_of, pushers_of, groups

    def sweep(live, width, seeds_of, pushers_of, groups):
        """Every shift, to a fixpoint: ``max(0, pusher's far edge + gap - near edge)`` over the
        seeds and the shapes that moved; a rigid group takes its largest shift."""
        shift, why = dict.fromkeys(live, 0), dict.fromkeys(live)
        for _ in range(len(live) + 2):          # bounded: tight touches inside a ring could creep
            changed = False
            for s in live:
                x0 = items[s][0][0]
                best, reason = shift[s], why[s]
                for sd in seeds_of[s]:
                    if sd["new"] > sd["old"] and sd["new"] + gap - x0 > best:
                        best, reason = sd["new"] + gap - x0, ("seed", sd["id"])
                for p in pushers_of[s]:
                    if shift[p] > 0:
                        need = items[p][0][0] + shift[p] + width[p] + gap - x0
                        if need > best:
                            best, reason = need, ("push", p)
                if best > shift[s]:
                    shift[s], why[s], changed = best, reason, True
            for members in groups:
                top = max(members, key=lambda i: shift[i])
                for i in members:
                    if shift[i] < shift[top]:
                        shift[i], why[i], changed = shift[top], ("group", top), True
            if not changed:
                break
        return shift, why

    full = {i: items[i][0][2] - items[i][0][0] for i in items}
    width = dict(full)
    live, dropped = list(order), []
    rel = relations(live)
    for _ in range(4 * len(order) + 8):
        shift, why = sweep(live, width, *rel)
        over = []
        for s in live:
            if shift[s] > 0:
                far = items[s][0][0] + shift[s] + width[s]
                if far > items[s][2]:
                    over.append((far - items[s][2], far, s))
        if not over:
            break
        if mode == "drag":                      # P2: the growth you drag stops at the edge
            cut = max(o[0] for o in over)
            active = [sd for sd in seeds if sd["new"] > sd["old"]]
            was = [(sd["near"], sd["new"]) for sd in active]
            for sd in active:
                _cut(sd, cut)
            if [(sd["near"], sd["new"]) for sd in active] == was:
                break                           # nothing left to give (no active seed, or none moved)
            continue
        o, _far, s = max(over)                  # P2: the growth the app does narrows the lane
        lane = _chain(s, why)
        caps = {m: max(0, width[m] - items[m][3]) for m in lane}
        if sum(caps.values()) < o:              # below the floor: the farthest one leaves the lane
            live.remove(s)
            dropped.append(s)
            width[s] = full[s]
            rel = relations(live)
            continue
        for m, c in _spread(o, lane, caps).items():
            width[m] -= c
    shift, why = sweep(live, width, *rel)

    moved = {}
    for s in live:
        if shift[s] > 0:
            t = items[s][0]
            moved[s] = (_unturn(d, (t[0] + shift[s], t[1], t[0] + shift[s] + width[s], t[3])), shift[s])
    return moved, dropped, reach()


def _stack_of(i, by_id, stacked) -> list:
    """The stacked shapes overlapping ``i``'s, transitively, in shapes order."""
    got, todo = {i}, [i]
    while todo:
        b = by_id[todo.pop()].box
        for j in stacked:
            if j not in got and overlap(by_id[j].box, b):
                got.add(j)
                todo.append(j)
    return [j for j in stacked if j in got]


def _pile_spot(size, floor, area, corner, step, members, avoid) -> Box:
    """Where a ``size`` shape joins the pile in ``area``'s ``corner``, after the ``members``
    already there (also handed to ``pile_spots`` as ``before``, so a later cycle clears the
    widest member of the ones before it), keeping off ``avoid`` (the calendar; the same for
    ``pile_start`` and ``pile_spots``, so they agree on the cycles). ``pile_spots`` has already
    slid the spot's cycle in; only what still hangs past the area is trimmed off, from the far
    side, so the top-left (and the top bar) stays where the pile put it, never below ``floor``;
    failing that it slides in."""
    start = pile_start(members, size, area, corner, step, avoid=avoid)
    spot = pile_spots([size], area, corner, step, start=start, before=members, avoid=avoid)[0]
    if not fits_one(spot, [area]):
        x0, y0 = max(spot[0], area[0]), max(spot[1], area[1])
        w = max(floor[0], min(spot[2], area[2]) - x0)
        h = max(floor[1], min(spot[3], area[3]) - y0)
        spot = x0, y0, x0 + w, y0 + h
        if not fits_one(spot, [area]):
            dx, dy = slide_in(spot, [area])
            spot = spot[0] + dx, spot[1] + dy, spot[2] + dx, spot[3] + dy
    return spot


def _smaller(a, b) -> bool:
    return a[2] - a[0] < b[2] - b[0] or a[3] - a[1] < b[3] - b[1]


def _cover(a, b, slack) -> int:
    """How much of ``b`` lies under ``a``: their shared area, or 0 when the overlap is no deeper
    than the touch ``slack`` on either axis (links let touching shapes overlap that much)."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > slack and h > slack else 0


def _newly(nb, ob, fb, fo, gap, slack) -> bool:
    """A shape at ``nb`` (``ob`` before) now has trouble with a box at ``fb`` (``fo`` before; None:
    it is new): it lies under it more than it did, or it is closer than the gap where it wasn't.
    Crowding that was already there is left alone; cover that grows never is."""
    if fo is None:
        return overlap(inflate(fb, gap), nb)
    return _cover(fb, nb, slack) > _cover(fo, ob, slack) or (
        overlap(inflate(fb, gap), nb) and not overlap(inflate(fo, gap), ob))


def plan_growth(changes, shapes, links, areas, gap, *, mode, min_w, min_h, pile_corner_="br",
                step=PILE_STEP, slack=GROW_SLACK) -> Plan:
    """Make room for ``changes`` (id -> new box), in S4's order: pushes, then the edge, then
    relocations (P1, P2, P3). Callers pass ``step = px(PILE_STEP)`` and ``slack = px(2)``.

    - **Pushes:** for each grower and each growing edge, the shapes in line (in its old rows for
      sideways growth, its old columns for vertical; past its old edge minus ``slack``) are
      pushed, and every pushed shape pushes the shapes in its own rows or columns in turn. A
      linked group takes its largest shift, except a group holding a grower (R19). Shifts from
      several growers merge by the largest. A push may cross a monitor line, but no pushed shape
      passes its own area's edge; one that lands on a grower or held room relocates instead.
    - **The edge,** ``mode="drag"``: the growth stops where the last pushed shape meets the area's
      edge (or held room); a grower that also shifted (P3) moves back first, no further than its
      old spot; ``allowed`` has every grower's box. ``mode="app"``: each lane narrows
      evenly to end exactly at the edge, never below ``shape.least or (min_w, min_h)``; when that
      isn't enough its farthest shapes leave it and relocate.
    - **Relocations:** shapes a final box now covers more than its old box did, or crowds closer
      than the gap where it didn't, go to the nearest free spot, else shrink to fit, else the
      pile in ``pile_corner_``, kept on screen.
      A stacked shape is never pushed: its whole stack relocates as one. Held shapes never move.
    - A grower missing from ``shapes`` (the undocked calendar opening) grows from a zero-size box
      at its new top-left: nothing is in line with it, so whatever it crowds relocates.
    Pure: the inputs are not changed."""
    if mode not in ("app", "drag"):
        raise ValueError(mode)
    shapes, areas = list(shapes), list(areas)
    by_id = {s.id: s for s in shapes}
    old, missing = {}, set()
    for g, new in changes.items():
        if g not in by_id:
            missing.add(g)
        s = by_id.get(g) or Shape(g, (new[0], new[1], new[0], new[1]), kind="cal" if g == CAL else "note")
        old[g] = s.box

    grower_groups = set()
    if links is not None:
        for g in changes:
            grower_groups |= links.group(g)
    held = [s.box for s in shapes if s.kind == "held" and s.id not in changes]
    movable = [s for s in shapes if s.id not in changes and not s.stacked and s.kind != "held"]
    movable_ids = {s.id for s in movable}
    rigid = {}
    for s in movable:
        g = frozenset() if links is None or s.id in grower_groups else frozenset(links.group(s.id) & movable_ids)
        rigid[s.id] = g if len(g) > 1 else None

    least = (min_w, min_h)
    grows = [(g, old[g], tuple(changes[g]), g not in missing, (by_id[g].least if g in by_id else None) or least)
             for g in changes]
    moved, dropped, reach = {}, [], {}
    for d in _DIRS:
        live = [s for s in movable if s.id not in dropped]
        moved[d], dr, reach[d] = _push(d, grows, live, areas, held, rigid, gap, mode, least, slack)
        dropped += dr

    plan = Plan()
    final = {s.id: s.box for s in shapes}
    for g in changes:
        box = tuple(changes[g])
        if mode == "drag":
            for d in _DIRS:
                if g in reach[d]:
                    near, far = reach[d][g]
                    t = list(_turn(d, box))
                    t[2] = far
                    if near is not None:            # moved back as a whole (only one way per axis)
                        t[0] = near
                    box = _unturn(d, t)
            plan.allowed[g] = box
        final[g] = box

    pushed = {}
    for s in movable:
        if s.id in dropped:
            continue
        box, hit = list(s.box), False
        for pair in (("right", "left"), ("down", "up")):
            got = [moved[d][s.id] for d in pair if s.id in moved[d]]
            if got:
                b = max(got, key=lambda m: m[1])[0]     # the larger shift; right or down on a tie
                ax = _AXIS[pair[0]]
                box[ax], box[ax + 2], hit = b[ax], b[ax + 2], True
        if hit:
            pushed[s.id] = tuple(box)

    # A pushed shape that lands on a grower's final box, held room or another pushed shape (a push
    # from each side, or pushes along both axes) relocates instead of staying there.
    fixed = [(final[g], None if g in missing else old[g]) for g in changes] + [(h, h) for h in held]
    kept = {}
    for i, nb in pushed.items():
        ob = by_id[i].box
        if any(_newly(nb, ob, fb, fo, gap, slack) for fb, fo in fixed) or any(
                _newly(nb, ob, kb, by_id[k].box, gap, slack) for k, kb in kept.items()):
            dropped.append(i)
        else:
            kept[i] = nb
    pushed = kept
    final.update(pushed)

    # Covered more, or newly crowded closer than the gap, by a box this plan made (see _newly). A
    # stacked grower's own stack mates stay: overlaps inside a stack are allowed (P5, T1).
    stacked = [s.id for s in shapes if s.stacked and s.kind != "held" and s.id not in changes]
    mates = {g: set(_stack_of(g, by_id, stacked)) for g in changes if g in by_id and by_id[g].stacked}
    before = {g: None if g in missing else old[g] for g in changes}
    before.update({i: by_id[i].box for i in pushed})
    movers = list(changes) + list(pushed)
    out = []
    for s in shapes:
        if s.id in changes or s.id in pushed or s.kind == "held":
            continue
        if s.id in dropped or any(_newly(s.box, s.box, final[m], before[m], gap, slack)
                                  for m in movers if s.id not in mates.get(m, ())):
            out.append(s.id)

    def calendar():
        """The calendar's final box(es), for the pile to keep off: the undocked one, or a pair's part."""
        out = [final[CAL]] if CAL in final else []
        for s in shapes:
            if s.kind == "pair" and len(s.parts) == 2:
                out.append(s.parts[1] if final[s.id] == s.box else split_pair(s, final[s.id], gap)[1])
        return out

    units, pending = [], set()
    for i in out:
        if i not in pending:
            unit = _stack_of(i, by_id, stacked) if by_id[i].stacked else [i]
            pending.update(unit)
            units.append(unit)
    for unit in units:
        if not areas:
            break
        obstacles = [b for j, b in final.items() if j not in pending]
        if len(unit) > 1:                       # a stack moves as one shape, or joins the pile
            u = union(by_id[j].box for j in unit)
            spot = nearest_free(u[2] - u[0], u[3] - u[1], (u[0], u[1]), areas, obstacles, gap, _area_of(u, areas))
            if spot is not None:
                dx, dy = spot[0] - u[0], spot[1] - u[1]
                for j in unit:
                    b = by_id[j].box
                    final[j] = b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy
                    plan.relocated.append(j)
                pending.difference_update(unit)
                continue
        for j in unit:
            s = by_id[j]
            b = s.box
            w, h = b[2] - b[0], b[3] - b[1]
            home = _area_of(b, areas)
            fw, fh = s.least or least
            spot = None
            if len(unit) == 1:
                spot = nearest_free(w, h, (b[0], b[1]), areas, obstacles, gap, home)
                if spot is None:
                    spot = shrink_to_fit(w, h, fw, fh, (b[0], b[1]), areas, obstacles, gap, home)
            if spot is None:
                ids = [k for k in stacked if k not in pending] + [k for k in plan.piled if k not in stacked]
                members = [final[k] for k in ids if _area_of(final[k], areas) == home]
                spot = _pile_spot((w, h), (min(fw, w), min(fh, h)), areas[home], pile_corner_, step, members,
                                  calendar())
                plan.piled.append(j)
            final[j] = spot
            plan.relocated.append(j)
            pending.discard(j)

    done = set(plan.relocated) | set(pushed)
    for s in shapes:
        if s.id in changes or s.id in done:
            plan.boxes[s.id] = final[s.id]
    for g in changes:
        plan.boxes.setdefault(g, final[g])
    plan.shrunk = [s.id for s in shapes if s.id in done and _smaller(final[s.id], s.box)]
    return plan


def plan_close_up(changes, shapes, links, gap, *, areas=None, slack=GROW_SLACK) -> Plan:
    """P4, a note or the calendar shrinking or folding (``changes``: id -> its smaller box): the
    shapes linked to it (its group) that are in line past a shrinking edge (minus ``slack``) shift
    back by the shrink amount, keeping their offsets. Nothing else moves, and none is pulled
    closer than the gap to a shape that stays (or that moves back less). With ``areas`` (callers
    pass ``usable()``), no pull takes a shape past its own area's edge, so nothing ends straddling
    two screens (S2). Stacked and held shapes never move. Callers pass ``slack = px(2)``."""
    shapes = list(shapes)
    areas = list(areas) if areas else None
    by_id = {s.id: s for s in shapes}
    best = {}                                   # (id, axis) -> (box, pull): the larger pull wins
    for d in _DIRS:
        ax = _AXIS[d]
        for g, new in changes.items():
            if g not in by_id:
                continue
            to = _turn(d, by_id[g].box)
            amount = to[2] - _turn(d, new)[2]
            if amount <= 0:
                continue
            group = links.group(g) if links is not None else {g}
            movers = [s for s in shapes if s.id in group and s.id not in changes and not s.stacked
                      and s.kind != "held" and _rows(_turn(d, s.box), to)
                      and _turn(d, s.box)[0] >= to[2] - slack]
            movers.sort(key=lambda s: (_turn(d, s.box)[0], _turn(d, s.box)[1], s.id))
            done = {}
            for s in movers:
                t = _turn(d, s.box)
                pull = amount
                if areas:                       # never back past its own area's edge
                    pull = min(pull, t[0] - _turn(d, areas[_area_of(s.box, areas)])[0])
                for o in shapes:                # what lies behind it in its rows (with the gap)
                    if o.id == s.id:
                        continue
                    ot = _turn(d, o.box)
                    if ot[2] > t[0] + slack or not (ot[1] < t[3] + gap and t[1] < ot[3] + gap):
                        continue
                    back = ot[2] - _turn(d, changes[o.id])[2] if o.id in changes else done.get(o.id, 0)
                    pull = min(pull, back + max(0, t[0] - ot[2] - gap))
                if pull > 0:
                    done[s.id] = pull
                    if pull > best.get((s.id, ax), (None, 0))[1]:
                        best[(s.id, ax)] = (_unturn(d, (t[0] - pull, t[1], t[2] - pull, t[3])), pull)
    plan = Plan()
    for g, new in changes.items():
        plan.boxes[g] = tuple(new)
    for s in shapes:
        box = list(s.box)
        for ax in (0, 1):
            if (s.id, ax) in best:
                b = best[(s.id, ax)][0]
                box[ax], box[ax + 2] = b[ax], b[ax + 2]
        if tuple(box) != s.box:
            plan.boxes[s.id] = tuple(box)
    return plan


def _apart(a, b) -> int:
    """The squared distance between two boxes (0 when they touch or overlap)."""
    dx = max(0, b[0] - a[2], a[0] - b[2])
    dy = max(0, b[1] - a[3], a[1] - b[3])
    return dx * dx + dy * dy


def _slide(unit, pos, marks, obstacles, areas, gap) -> bool:
    """Move the unit's boxes in ``pos`` toward their own boxes, one axis at a time (the longer way
    first), never past any member's own box nor through an obstacle in its path, as far as they
    end free: the farthest free stop, where that stop isn't the whole way (for example where the
    whole way would straddle two screens). True if they moved."""
    cur, own = union(pos[i] for i in unit), union(marks[i] for i in unit)
    moved = False
    for ax in sorted((0, 1), key=lambda a: -abs(own[a] - cur[a])):
        cur = union(pos[i] for i in unit)
        sign = (own[ax] > cur[ax]) - (own[ax] < cur[ax])
        if not sign:
            continue
        travel = min(abs(marks[i][ax] - pos[i][ax]) if (marks[i][ax] - pos[i][ax]) * sign > 0 else 0
                     for i in unit)
        p = 1 - ax
        for i in unit:
            b = pos[i]
            for o in obstacles:
                if not (o[p] < b[p + 2] + gap and b[p] < o[p + 2] + gap):
                    continue
                if sign < 0 and o[ax + 2] <= b[ax]:
                    travel = min(travel, max(0, b[ax] - o[ax + 2] - gap))
                elif sign > 0 and o[ax] >= b[ax + 2]:
                    travel = min(travel, max(0, o[ax] - b[ax + 2] - gap))
        if travel <= 0:
            continue
        # Being free only changes where a box edge meets an area's edge or an obstacle's edge plus
        # the gap, so the farthest free stop is ``travel`` or one of those.
        stops = {travel}
        for i in unit:
            b = pos[i]
            edges = [a[ax] - b[ax] for a in areas] + [a[ax + 2] - b[ax + 2] for a in areas]
            edges += [o[ax] - gap - b[ax + 2] for o in obstacles] + [o[ax + 2] + gap - b[ax] for o in obstacles]
            stops.update(v * sign for v in edges if 0 < v * sign < travel)
        for t in sorted(stops, reverse=True):
            dx, dy = (sign * t, 0) if ax == 0 else (0, sign * t)
            new = {i: (pos[i][0] + dx, pos[i][1] + dy, pos[i][2] + dx, pos[i][3] + dy) for i in unit}
            if all(is_free(new[i], areas, obstacles, gap) for i in unit):
                pos.update(new)
                moved = True
                break
    return moved


def plan_give_back(marks, shapes, links, areas, gap, toward) -> Plan:
    """P4, the calendar closing or shrinking. ``marks``: id -> its own box (from before the
    calendar first moved it). ``toward``: the calendar's new box, or its last box if it closed.

    Each marked id goes back to its own box when that is free against the unmarked shapes and the
    other marked ones (where they end up); a linked group of marked ids goes back together or not
    at all. The rest close up, nearest ``toward`` first: each moves from where it is toward its
    own box, along the axis it was pushed on, as far as it stays free and never past its own box,
    so a pushed block closes up to the calendar's new edge plus the gap. Held shapes stay."""
    shapes, areas = list(shapes), list(areas)
    pos = {s.id: s.box for s in shapes}
    marked = [s.id for s in shapes if s.id in marks and s.kind != "held"]
    units, seen = [], set()
    for i in marked:
        if i not in seen:
            group = links.group(i) if links is not None else {i}
            unit = [j for j in marked if j in group]
            seen.update(unit)
            units.append(unit)
    home = set()

    def others(unit):
        return [b for j, b in pos.items() if j not in unit]

    for _ in range(len(units) + 2):
        changed, grew = False, True
        while grew:                             # 1. own boxes, where free
            grew = False
            for k, unit in enumerate(units):
                if k not in home and all(is_free(tuple(marks[i]), areas, others(unit), gap) for i in unit):
                    for i in unit:
                        pos[i] = tuple(marks[i])
                    home.add(k)
                    grew = changed = True
        rest = sorted((k for k in range(len(units)) if k not in home),
                      key=lambda k: (_apart(union(pos[i] for i in units[k]), toward) if toward else 0, k))
        for k in rest:                          # 2. the rest close up, nearest the calendar first
            if _slide(units[k], pos, marks, others(units[k]), areas, gap):
                changed = True
        if not changed:
            break

    plan = Plan()
    for s in shapes:
        if s.id in marks and pos[s.id] != s.box:
            plan.boxes[s.id] = pos[s.id]
    return plan
