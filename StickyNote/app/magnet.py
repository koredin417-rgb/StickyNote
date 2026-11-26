"""The magnet and the links: where a dragged note snaps, which notes move together, and the links kept between notes that touch. (Part of App: see app.py.)"""
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


class MagnetMixin:
    def snap(self, shape_box: Box, exclude: set[str] = frozenset(), parts=None,
             reach: int | None = None) -> tuple[int, int, str | None]:
        """The magnet (M1) for a whole dragged shape (a note, a group, the calendar) at
        ``shape_box``, against space() less the ids in ``exclude`` (the dragged group): next to
        another shape's edge with the gap, and lined up with its edges, when within SNAP_REACH.
        It offers only spots where the whole shape is free (geom.is_free). Returns the snapped
        top-left and the id it snapped to (None: no snap, and the top-left as given). Snapping
        Off: never. ``parts``: the pieces of a group (its notes and calendars, together making
        ``shape_box``): each piece snaps and each must be free, so a group can close around
        another note in its empty corner (the corner is not the group's)."""
        x0, y0 = shape_box[0], shape_box[1]
        if self.prefs.snap_gap is None:
            return x0, y0, None
        gap = self._gap()
        reach = self.px(SNAP_REACH) if reach is None else reach
        pieces = [tuple(p) for p in parts] if parts else [tuple(shape_box)]
        shapes = self.space(exclude)
        obstacles = [b for s in shapes for b in (s.parts or (s.box,))]
        xs, ys = [], []                     # (distance, shift, id, beside): the offers on each axis

        def offer(out, value, now, sid, edge, limit=reach):
            if abs(value - now) <= limit:
                out.append((abs(value - now), value - now, sid, edge))

        def pull(size, near, shared):
            """Line-up reach: touching this shape on the other axis and sharing at least half of
            its own side with it, the edges line up from further (SNAP_ALIGN_PULL)."""
            return max(reach, round(size * SNAP_ALIGN_PULL)) if near and shared >= size / 2 else reach
        for s in shapes:
            if s.kind == "held":            # (room a minimized note keeps: in the way, not snapped to)
                continue
            for ox0, oy0, ox1, oy1 in (s.parts or (s.box,)):
                for px0, py0, px1, py1 in pieces:
                    w, h = px1 - px0, py1 - py0
                    if py0 < oy1 + reach and py1 > oy0 - reach:         # rows overlap: it can sit left / right
                        for v in (ox1 + gap, ox0 - w - gap):
                            offer(xs, v, px0, s.id, True)
                        side = abs(px0 - (ox1 + gap)) <= reach or abs(px1 + gap - ox0) <= reach
                        lim = pull(h, side, min(py1, oy1) - max(py0, oy0))
                        for v in (oy0, oy1 - h):                         # tops / bottoms line up
                            offer(ys, v, py0, s.id, False, lim)
                    if px0 < ox1 + reach and px1 > ox0 - reach:         # columns overlap: above / below
                        for v in (oy1 + gap, oy0 - h - gap):
                            offer(ys, v, py0, s.id, True)
                        side = abs(py0 - (oy1 + gap)) <= reach or abs(py1 + gap - oy0) <= reach
                        lim = pull(w, side, min(px1, ox1) - max(px0, ox0))
                        for v in (ox0, ox1 - w):                         # left / right edges line up
                            offer(xs, v, px0, s.id, False, lim)
        areas = self.usable()
        combos = [(cx, cy) for cx in [None] + sorted(xs) for cy in [None] + sorted(ys) if cx or cy]
        combos.sort(key=lambda c: (-sum(1 for o in c if o), sum(o[0] for o in c if o)))
        seen = set()
        for cx, cy in combos:
            dx, dy = (cx[1] if cx else 0), (cy[1] if cy else 0)
            if (dx, dy) in seen:
                continue
            seen.add((dx, dy))
            if all(geom.is_free((p[0] + dx, p[1] + dy, p[2] + dx, p[3] + dy), areas, obstacles, gap) for p in pieces):
                picks = sorted((o for o in (cx, cy) if o), key=lambda o: (not o[3], o[0]))
                return x0 + dx, y0 + dy, picks[0][2]
        return x0, y0, None

    def hold_snap(self, owner, raw, snapped, sid):
        """The magnet's grip: once snapped, a drag stays there while the pointer is within
        SNAP_HOLD of it (a small wobble of the hand does not pull it off), and lets go past
        that. ``raw``: where the pointer puts it; ``snapped``, ``sid``: App.snap's answer for
        now. The spot held is kept on ``owner`` (the note or calendar being dragged)."""
        reach = self.px(SNAP_HOLD)
        held = list(getattr(owner, "_snap_hold", None) or (None, None))    # per axis: (value, id) or None
        out = list(raw)
        for i in (0, 1):                    # each axis on its own: a snap on one does not undo the other's hold
            if sid is not None and snapped[i] != raw[i]:
                held[i] = (snapped[i], sid)             # snapped on this axis now
            elif held[i] is not None and abs(raw[i] - held[i][0]) > reach:
                held[i] = None                          # pulled past the hold: let go
            if held[i] is not None:
                out[i] = held[i][0]
            elif sid is not None:
                out[i] = snapped[i]
        owner._snap_hold = tuple(held) if any(held) else None
        hid = next((h[1] for h in held if h is not None), sid)
        return out[0], out[1], hid

    def link_drop(self, pids, sid) -> None:
        """A snapped drop (M2): each of ``pids`` (the dragged group) links to every shape it now
        touches, ``sid`` (the shape ``snap`` snapped to) among them. (Only ``sid`` was linked
        before: in a corner several shapes line it up at once, and the one ``snap`` named could
        be a note in the same row that does not touch it, so the drop sometimes linked nothing.)"""
        shapes = {s.id: s for s in self.space()}
        if shapes.get(sid) is None:
            return
        moved = set(pids)
        slack, reach = self._touch_reach()
        for pid in pids:
            s = shapes.get(pid)
            if s is None:
                continue
            for tid, t in shapes.items():
                if tid in moved or t.kind == "held":
                    continue
                if any(geom.touching(p, q, reach, slack) for p in (s.parts or (s.box,)) for q in (t.parts or (t.box,))):
                    self.link(pid, tid)

    # ---- links (M2) ----------------------------------------------------------------------------
    def group_of(self, pid) -> set[str]:
        """The link group ``pid`` is in (it includes ``pid``), whatever the drag switch says."""
        return self.links.group(pid)

    def drag_group(self, pid, alt: bool = False) -> set[str]:
        """What a drag or resize of ``pid`` moves (a fold uses group_of): just ``pid`` with Alt,
        with the "move snapped notes together" switch off, or as a tile in auto layout; else the
        link group (in auto layout without the tiles: they stay in their grid)."""
        if alt or not self.prefs.group_drag:
            return {pid}
        group = self.group_of(pid)
        if self.prefs.auto_layout:
            if self._is_tile(pid):
                return {pid}
            return {g for g in group if not self._is_tile(g)}
        return group

    def group_windows(self, pid, ids=None) -> list[NoteWindow]:
        """The shown notes of ``ids`` (default: the link group of ``pid``), in window order."""
        ids = self.group_of(pid) if ids is None else ids
        return [w for i, w in self.windows.items() if i in ids and not w._closing and w.win.state() == "normal"]

    def _is_tile(self, pid) -> bool:
        """A note auto layout arranges (not pulled out of the tiles)."""
        nw = self.windows.get(pid)
        return nw is not None and not nw.pad.free

    def _touch_reach(self):
        """(slack, reach): the touch test of M2, the same at every gap (snapping Off: 8)."""
        slack = self.px(2)
        return slack, self._gap() + slack

    def link(self, a, b) -> None:
        """Link two notes (or a note and the calendar). Nothing forms with snapping Off, or with
        a tile in auto layout."""
        if a == b or self.prefs.snap_gap is None or self.links.linked(a, b):
            return
        if self.prefs.auto_layout and (self._is_tile(a) or self._is_tile(b)):
            return
        self.links.add(a, b)
        self._mirror_links()
        self.request_save()

    def unlink(self, pid) -> None:
        """Break every link ``pid`` has in the current setup (Detach)."""
        self.links.drop(pid)
        self._mirror_links()
        self.request_save()

    def _mirror_links(self) -> None:
        """pad.links of every note: who it is linked to in the current setup (saved)."""
        for pid, nw in self.windows.items():
            nw.pad.links = sorted(self.links.neighbours(pid))

    def _load_links(self) -> None:
        known = set(self.windows) | {CAL}
        self.links = Links.from_lists({pid: nw.pad.links for pid, nw in self.windows.items()}, known)
        self._mirror_links()

    def settle_links(self) -> None:
        """The end of an action (Motion's end step): links that no longer touch break (M2), over
        the parts of space() and the minimized notes at their pad boxes. Links on hold (auto
        layout) stay."""
        if not self.links.pairs():
            return
        parts = {s.id: list(s.parts or (s.box,)) for s in self.space() if s.kind != "held"}
        for s in self.space():                      # (a minimized note's held room: its note and docked calendar)
            if s.kind == "held" and s.parts and s.id in self.windows:
                parts[s.id] = list(s.parts)
        for pid, nw in self.windows.items():        # (minimized notes: where they were left)
            if pid not in parts and not nw._closing:
                parts[pid] = [_pad_box(nw.pad)]
        held = [p for p in self._held if self.prefs.auto_layout and self.links.linked(*p)]
        for a, b in held:
            self.links.remove(a, b)
        slack, reach = self._touch_reach()
        try:
            gone = self.links.prune_apart(parts, reach, slack)
        finally:
            for a, b in held:
                self.links.add(a, b)
        if gone:
            self._mirror_links()
            self.request_save()

    def forget_links(self, pid) -> None:
        """A note closes (M2): its links go, in the current setup and in every other one."""
        self.links.drop(pid)
        self._held = {p for p in self._held if pid not in p}
        pads = [w.pad for w in self.windows.values()] + self._keep_pads + self._closed + \
               [p for _t, p in self._recently_closed]
        for pad in pads:
            mine = pad.id == pid
            pad.links = [] if mine else [i for i in pad.links if i != pid]
            for entry in pad.setups.values():
                entry["links"] = [] if mine else [i for i in entry.get("links", ()) if i != pid]
        self._mirror_links()
        self.request_save()

    def migrate_links(self) -> None:
        """Once, at the first start after the update: links from what touches now (as today's
        distance-based groups), tiles in auto layout left out (M2)."""
        slack, reach = self._touch_reach()
        parts = {}
        for s in self.space():
            if s.kind in ("note", "pair") and not (self.prefs.auto_layout and self._is_tile(s.id)):
                parts[s.id] = list(s.parts or (s.box,))
        for a, b in links_from_touching(parts, reach, slack).pairs():
            self.links.add(a, b)
        self.prefs.links_migrated = True
        self._mirror_links()
        self.request_save()

    def hold_links(self, on: bool) -> None:
        """Auto layout (L5): on, the links of tiles are put on hold (kept, not pruned); off, they
        come back where the notes still touch and break where not."""
        if on:
            self._held = {p for p in self.links.pairs() if self._is_tile(p[0]) or self._is_tile(p[1])}
        else:
            self._held = set()
            self.settle_links()

    def off_calendars(self, places: dict) -> dict:
        """Notes let go over a docked calendar (not their own): they go beside it, on its
        nearer outer side, as if snapped there; the calendar stays where it is. If neither
        side has room (the screen's edge, other notes) they stay where they were let go.
        ``places``: window -> (x, y) where the drag put it. Returns where they glide to."""
        boxes = {w: (x, y, x + w.pad.width, y + _shown_h(w.pad)) for w, (x, y) in places.items()}
        gap = self._gap()
        area = self.area_of(next(iter(boxes.values())))     # the screen it was let go on
        for owner in self.windows.values():
            cal = owner.calendar
            if owner in places or cal is None or not cal.docked or not cal.top.winfo_ismapped():
                continue
            cb = cal.box()
            if not any(_overlap(cb, b) for b in boxes.values()):
                continue
            gl, gr = min(b[0] for b in boxes.values()), max(b[2] for b in boxes.values())
            to_left, to_right = cb[0] - gap - gr, cb[2] + gap - gl
            order = (to_left, to_right) if (gl + gr) / 2 < (cb[0] + cb[2]) / 2 else (to_right, to_left)
            others = [_pad_box(o.pad) for o in self.windows.values()
                      if o not in places and o.win.state() == "normal"]
            others += [o.calendar.box() for o in self.windows.values() if o not in places and o is not owner
                       and o.calendar is not None and o.calendar.docked and o.calendar.top.winfo_ismapped()]
            for dx in order:
                moved = [(b[0] + dx, b[1], b[2] + dx, b[3]) for b in boxes.values()]
                if all(area[0] <= b[0] and b[2] <= area[2] for b in moved) and \
                        not any(_overlap(b, o) for b in moved for o in others):
                    targets = {w: (b[0] + dx, b[1]) for w, b in boxes.items()}
                    for w, xy in targets.items():
                        w.glide_to(*xy, start_at=places[w])
                    return targets
            return {}
        return {}

    def _gap(self):
        return self.px(self.prefs.snap_gap if self.prefs.snap_gap is not None else 8)

    def push_clear(self, ids):
        """A group just let go (``ids``: its notes): any other note it really overlaps (the
        notes, their docked calendar, a calendar that came along) slides out the shortest way,
        staying on its screen. A note only in the empty corner of the group stays."""
        if self.prefs.auto_layout or self.closed:
            return
        members = [self.windows[i] for i in ids if i in self.windows]
        members = [w for w in members if not w._closing and w.win.state() == "normal"]
        if not members:
            return
        blocks = [_pad_box(w.pad) for w in members]
        cal = self._open_calendar()
        if cal is not None and cal.target_box is not None and cal.top.winfo_ismapped() and (
                cal.nw in members or CAL in self.group_of(members[0].pad.id)):
            blocks.append(tuple(cal.target_box))
        gap, targets = self._gap(), {}
        for pid, o in self.windows.items():
            if pid in ids or o._closing or o.win.state() != "normal" or self.motion.drives(pid):
                continue
            b = _pad_box(o.pad)
            if not any(geom.overlap(b, geom.inflate(k, gap - 1)) for k in blocks):   # on it, or closer than the gap
                continue
            area = self.area_of(b)
            best = None
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                x0, y0 = b[0], b[1]
                w, h = b[2] - b[0], b[3] - b[1]
                for _ in range(8):              # past each block in the way, in this direction
                    hit = next((k for k in blocks + list(targets.values())
                                if geom.overlap((x0, y0, x0 + w, y0 + h), geom.inflate(k, gap - 1))), None)
                    if hit is None:
                        break
                    if dx > 0:
                        x0 = hit[2] + gap
                    elif dx < 0:
                        x0 = hit[0] - gap - w
                    elif dy > 0:
                        y0 = hit[3] + gap
                    else:
                        y0 = hit[1] - gap - h
                box = (x0, y0, x0 + w, y0 + h)
                inside = area[0] <= x0 and area[1] <= y0 and box[2] <= area[2] and box[3] <= area[3]
                clear = not any(geom.overlap(box, geom.inflate(k, gap - 1)) for k in blocks)
                cost = abs(x0 - b[0]) + abs(y0 - b[1])
                if inside and clear and (best is None or cost < best[0]):
                    best = (cost, box)
            if best is not None:
                targets[pid] = best[1]
        if targets:
            for pid in targets:
                self.windows[pid].user_moved(moved=True)
            self.motion.run(targets)
