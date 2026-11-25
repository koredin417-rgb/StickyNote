"""Screen geometry with no Tk in it: plain int pixels, boxes as (x0, y0, x1, y1)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Screen:
    """One monitor: its whole box and its work area (without the taskbar), both (x0, y0, x1, y1)."""
    monitor: tuple[int, int, int, int]
    work: tuple[int, int, int, int]


Box = tuple[int, int, int, int]

CAL = "cal"                     # the calendar's id in shape lists and the links graph
PILE_RESET = 8                  # a pile restarts after this many notes
TILE_SHRINK_STEP = 0.05
PILE_STEP = 36                  # = DATE_ROW_H, a folded note's height at 100 % scale (ui_common asserts it)


def shown_h(p) -> int:
    """How tall the note is on screen: its top bar only while folded up."""
    return getattr(p, "shown_height", None) or p.height if p.collapsed else p.height


def pad_box(p) -> Box:
    """The note's box. While it slides (glide_to) this is where it is going, so every placing
    decision (free places, detaching, which notes touch) sees the layout it will end in."""
    x, y = getattr(p, "target", None) or (p.x, p.y)
    return x, y, x + p.width, y + shown_h(p)


def overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def touching(a, b, reach, slack) -> bool:
    """Boxes (x0, y0, x1, y1) side by side or stacked, at most ``reach`` px apart (or
    overlapping by up to ``slack``), and sharing some of the edge between them."""
    rows = min(a[3], b[3]) - max(a[1], b[1]) > 0
    cols = min(a[2], b[2]) - max(a[0], b[0]) > 0
    beside = rows and (-slack <= b[0] - a[2] <= reach or -slack <= a[0] - b[2] <= reach)
    stacked = cols and (-slack <= b[1] - a[3] <= reach or -slack <= a[1] - b[3] <= reach)
    return beside or stacked


def union(boxes) -> Box:
    boxes = list(boxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def shift(box, dx, dy) -> Box:
    return box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy


def center(box) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def inflate(box, d) -> Box:
    return box[0] - d, box[1] - d, box[2] + d, box[3] + d


def usable(screens, gap) -> list[Box]:
    """Each work area inset by ``gap`` on every side, except a side lying on another screen's
    work-area edge (with an overlapping span): there the monitors meet, so no gap."""
    out = []
    for i, s in enumerate(screens):
        l, t, r, b = s.work
        ins = [gap, gap, gap, gap]
        for j, o in enumerate(screens):
            if j == i:
                continue
            ol, ot, orr, ob = o.work
            rows = min(b, ob) - max(t, ot) > 0
            cols = min(r, orr) - max(l, ol) > 0
            if rows and orr == l: ins[0] = 0
            if rows and ol == r: ins[2] = 0
            if cols and ob == t: ins[1] = 0
            if cols and ot == b: ins[3] = 0
        out.append((l + ins[0], t + ins[1], r - ins[2], b - ins[3]))
    return out


def fits_one(box, areas) -> bool:
    """The whole box lies inside a single usable area (not straddling two)."""
    return any(a[0] <= box[0] and a[1] <= box[1] and box[2] <= a[2] and box[3] <= a[3] for a in areas)


def screen_of(box, screens) -> int:
    """The screen containing the box's centre; otherwise the one it overlaps most; otherwise the nearest."""
    cx, cy = center(box)
    for i, s in enumerate(screens):
        m = s.monitor
        if m[0] <= cx < m[2] and m[1] <= cy < m[3]:
            return i
    best, best_area = -1, 0
    for i, s in enumerate(screens):
        m = s.monitor
        area = max(0, min(box[2], m[2]) - max(box[0], m[0])) * max(0, min(box[3], m[3]) - max(box[1], m[1]))
        if area > best_area:
            best, best_area = i, area
    if best >= 0:
        return best

    def dist(m):
        dx = max(m[0] - box[2], box[0] - m[2], 0)
        dy = max(m[1] - box[3], box[1] - m[3], 0)
        return dx * dx + dy * dy
    return min(range(len(screens)), key=lambda i: dist(screens[i].monitor))


def is_free(box, areas, obstacles, gap) -> bool:
    return fits_one(box, areas) and not any(overlap(inflate(box, gap), o) for o in obstacles)


def setup_key(screens) -> str:
    """The monitor setup as a string that doesn't depend on the order the screens are listed in."""
    return ";".join(sorted(",".join(str(v) for v in s.monitor) for s in screens))


def rescale(box, old, new, screens) -> Box:
    """Scale the box's position and size about the top-left of the monitor it is on."""
    ox, oy = screens[screen_of(box, screens)].monitor[:2]
    k = new / old
    x0, y0 = ox + (box[0] - ox) * k, oy + (box[1] - oy) * k
    w, h = (box[2] - box[0]) * k, (box[3] - box[1]) * k
    return round(x0), round(y0), round(x0 + w), round(y0 + h)
