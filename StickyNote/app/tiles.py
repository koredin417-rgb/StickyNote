"""Tidy up and auto layout: the notes in columns, the grid of tiles, its home and order, and respacing when the gap changes. (Part of App: see app.py.)"""
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


class TilesMixin:
    def tidy(self, nw: NoteWindow, size="keep"):
        """Menu "Tidy up notes" (T1): the notes on nw's screen into columns from the screen's right
        edge, top to bottom, in about the order they are in now (the undocked calendar sorts like
        a note), all one size (TIDY_SIZES, "default" = the new-note size) or each its own
        ("keep"). A docked calendar keeps its room beside its note, on its left, as tall as the
        note (C1; never below its least height): the pair is one item. They glide there in one
        apply (grid.plan_tidy: every box is inside the screen); on a full screen the next layer
        starts a little further in, over the first, and those notes are marked stacked."""
        area = self.area_of(_pad_box(nw.pad))
        gap, px = self._gap(), self.px
        wins = [w for w in self.windows.values() if w.win.state() == "normal" and not w._closing
                and _overlap(_pad_box(w.pad), area)]
        col = px(80)                        # notes this close in x count as one column now
        cal = self._open_calendar()
        free_cal = cal is not None and not cal.docked and _placed(cal) and _overlap(tuple(cal.target_box), area)
        order = self.prefs.tidy_order

        def sort_key(box, pinned=False, date="", created=""):
            if order == "date":             # the memo's day, newest first
                return date, created
            place = (-(box[2] // col), box[1])
            return (not pinned, place) if order == "pinned" else place
        if size in TIDY_SIZES:
            fixed = tuple(px(v) for v in TIDY_SIZES[size])
        elif size == "default" and self.prefs.note_size:
            fixed = tuple(self.prefs.note_size)
        else:
            fixed = None
        items = []                          # (sort key, id, slot w, slot h, note (w, h), cal (w, h) | None, window)
        for w in wins:
            p = w.pad
            ww, hh = fixed or (p.own_size if size == "keep" and p.own_size else (p.width, p.height))   # (shrunk to fit: its own size back, P6)
            sh = _shown_h(p) if p.collapsed else hh
            pair, c = None, w.calendar
            if c is not None and c.docked and _placed(c):
                cb = c.target_box
                cal_h = cb[3] - cb[1]
                if not p.collapsed:
                    cal_h = max(sh, c.least[1] if c.least else cal_h)
                pair = (cb[2] - cb[0], cal_h)
            key = sort_key(_pad_box(p), p.pinned, w.note.date or "", w.note.created)
            items.append((key, p.id, ww + (pair[0] + gap if pair else 0), max(sh, pair[1] if pair else 0),
                          (ww, sh), pair, w))
        if free_cal:
            cb = tuple(cal.target_box)
            items.append((sort_key(cb), CAL, cb[2] - cb[0], cb[3] - cb[1], None, None, None))
        items.sort(key=lambda it: it[0], reverse=order == "date")
        boxes, layered = grid.plan_tidy([grid.TidyItem(it[1], it[2], it[3]) for it in items], area, gap,
                                        px(PILE_STEP))
        parts = {}
        for _key, pid, _sw, _sh, (nw_, nh_), pair, w in [it for it in items if it[4] is not None]:
            x0, y0, x1, _y1 = boxes[pid]
            note = (x1 - nw_, y0, x1, y0 + nh_)
            if pair is None:
                boxes[pid] = note
            else:
                parts[pid] = (note, (x0, y0, x0 + pair[0], y0 + pair[1]))
                boxes[pid] = geom.union(list(parts[pid]))
            w.pad.stacked = pid in layered
            if size == "keep" and w.pad.own_size and not w.pad.collapsed:
                w.pad.own_size = None
        self.apply_plan(boxes, parts=parts, undo_label="tidied", anchor=nw)

    def _settle_calendar_off(self):
        """L5: the calendar takes its own size again (prefs.auto_layout is already False, so grow
        plans and pushes as usual)."""
        cal = self._open_calendar()
        if cal is None or cal.target_box is None or getattr(cal, "_closing", False):
            return
        pad = cal.nw.pad
        if cal.docked:
            note = _pad_box(pad)
            side, view, cal_box, _clear = cal.plan_dock(side=pad.calendar_side, note_box=note)
            parts = {pad.id: (note, cal_box)}
            if side is None:                # G7: no side fits on any screen: it undocks in the same grow
                self.grow({pad.id: note, CAL: cal_box}, "app", by_calendar=True, parts=parts)
                cal.undock_to(cal_box)
            else:
                cal.take_plan(side, view)
                self.grow({pad.id: geom.union([note, cal_box])}, "app", by_calendar=True, parts=parts)
        else:
            pad.calendar_pos = list(cal.target_box[:2])
            self.grow({CAL: cal._undocked_box()}, "app", by_calendar=True)

    def _grid_windows(self, i: int, shown_only: bool = False) -> list:
        """The tile windows on screen ``i`` (not free, not closing), in saved order (no order: last)."""
        out = []
        for w in self.windows.values():
            if w._closing or w.pad.free or self._screen_index(_pad_box(w.pad)) != i:
                continue
            if shown_only and w.win.state() != "normal":
                continue
            out.append(w)
        out.sort(key=lambda w: (w.pad.order is None, w.pad.order or 0))     # (stable: window order breaks ties)
        return out

    def tiled(self, area):
        """The notes auto layout arranges on the screen whose work area is ``area``: shown, not
        closing, not pulled out of the tiles (``pad.free``)."""
        for i, s in enumerate(self.screens()):
            if tuple(s.work) == tuple(area):
                return self._grid_windows(i, shown_only=True)
        return []

    def tile_order(self, area_key: str) -> list[str]:
        """The ids of the non-free tiles on that screen, in their saved order."""
        keys = self.area_keys()
        if area_key not in keys:
            return []
        return [w.pad.id for w in self._grid_windows(keys.index(area_key))]

    def _set_order(self, ids) -> None:
        for n, pid in enumerate(ids):
            if pid in self.windows:
                self.windows[pid].pad.order = n
        self.request_save()

    def arrange_soon(self):
        """Tile again once the current change is done (several changes: once)."""
        if self.prefs.auto_layout and not self.closed and getattr(self, "_arrange_job", None) is None:
            self._arrange_job = self.root.after_idle(self.arrange)

    def arrange(self):
        """Auto layout: on each screen, the grid planner's tiles (grid.plan_grid) applied in one
        apply (see _arrange_screen)."""
        self._arrange_job = None
        if not self.prefs.auto_layout or not self.windows or self.closed:
            return
        for i in range(len(self.screens())):
            self._arrange_screen(i)

    def move_grid(self, area_key: str, home: tuple[int, int], before: dict | None = None) -> None:
        """The user dropped the grid with its first tile at ``home``: the grid keeps its shape
        (rows) while it fits, and the dropped home is what is saved (planning clamps it each time)."""
        keys = self.area_keys()
        if area_key not in keys:
            return
        self._arrange_screen(keys.index(area_key), home=(int(home[0]), int(home[1])), keep_rows=True,
                             undo_label="grid_moved", before=before)

    def drop_grid(self, area_key: str, point) -> None:
        """The grid of ``area_key`` was dropped with the pointer at ``point``: the screen under it
        gets the grid. On another screen that has tiles, they join its order after its last tile and
        its home stays; on one with no grid, ``point`` becomes its home."""
        keys = self.area_keys()
        if area_key not in keys:
            return
        i = keys.index(area_key)
        point = (int(point[0]), int(point[1]))
        j = self._screen_index((*point, *point))
        if j == i:
            self._arrange_screen(i, home=point, keep_rows=True, undo_label="grid_moved")
            return
        mine = self._grid_windows(i)
        if not mine:
            return
        screens = self.screens()
        dx = screens[j].monitor[0] - screens[i].monitor[0]
        dy = screens[j].monitor[1] - screens[i].monitor[1]
        theirs = self._grid_windows(j)
        for w in mine:                      # they are on the other screen now (the windows glide there)
            w.pad.x += dx
            w.pad.y += dy
        self.space_changed()
        self._set_order([w.pad.id for w in theirs] + [w.pad.id for w in mine])
        if not theirs:
            side = self.prefs.grid_homes.get(area_key, {}).get("side", "right")
            _keep_recent(self.prefs.grid_homes, keys[j], {"x": point[0], "y": point[1], "side": side}, GRID_HOMES_KEPT)
        self.arrange()

    def drop_tile(self, nw, point, mods: set) -> None:
        """A tile (or a free note) was let go with the pointer at ``point``: Alt pulls it out of
        the grid (free); a free note let go over a tile rejoins at that tile's place (#25A); Ctrl over
        a tile swaps the two places. Then everything is tiled again."""
        point = (int(point[0]), int(point[1]))
        pad = nw.pad
        j = self._screen_index((*point, *point))
        key = self.area_keys()[j]
        under, last = None, self._grid_last.get(key)
        if last is not None:
            idx = grid.slot_at(last[0], point)
            if idx is not None:
                under = last[1][idx]
        if "alt" in mods:
            pad.free = True
            pad.stacked = False
        elif under is not None and under != pad.id:
            old = [w.pad.id for w in self._grid_windows(j)]
            if pad.free or pad.id not in old:       # rejoins at that tile's place
                pad.free = False
                order = [p for p in old if p != pad.id]
                order.insert(order.index(under) if under in order else len(order), pad.id)
            elif "ctrl" in mods and under in old:   # the two change places
                a, b = old.index(pad.id), old.index(under)
                old[a], old[b] = old[b], old[a]
                order = old
            else:
                order = old
            self._set_order(order)
        self.space_changed()
        self.arrange()
        self.request_save()

    def _free_shapes(self, i) -> dict:
        """{id: Shape} of the shown free notes on screen ``i`` (space()'s shapes: a note with its
        docked calendar is one pair)."""
        out = {}
        for w in self.windows.values():
            if w._closing or not w.pad.free or w.win.state() != "normal":
                continue
            s = self._shape(w)
            if self._screen_index(s.box) == i:
                out[w.pad.id] = s
        return out

    def _arrange_screen(self, i: int, *, home=None, keep_rows=False, undo_label=None, before=None) -> None:
        """One screen's grid (L1, L2): plan_grid over its tiles (saved order, saved home), the
        calendar's block and the free notes as obstacles; the free notes the block covers are
        pushed aside and the grid planned again around them; everything applied at once."""
        areas, gap, px = self.usable(), self._gap(), self.px
        area, key = areas[i], self.area_keys()[i]
        wins = self._grid_windows(i, shown_only=True)
        if not wins:
            return
        prefs = self.prefs
        entry = prefs.grid_homes.get(key)
        seeded = None
        if entry is None and home is None:      # the first grid on this screen: today's rule seeds it
            mid = sum(w.pad.x + w.pad.width / 2 for w in wins) / len(wins)
            seeded = "left" if mid >= (area[0] + area[2]) / 2 else "right"     # (the growth side)
        side = seeded or (entry or {}).get("side")
        base = tuple(prefs.auto_cell or prefs.note_size or [px(v) for v in TIDY_SIZES["small"]])
        if seeded == "left":
            use_home = (area[2] - base[0], area[1])
        else:
            use_home = home if home is not None else ((entry["x"], entry["y"]) if entry else None)
        # the order: the saved one, then the pads with none by today's key (column by column from the edge)

        def key_of(w):
            edge = area[2] - (w.pad.x + w.pad.width) if side == "left" else w.pad.x - area[0]
            return round(edge / px(80)), w.pad.y
        every = self._grid_windows(i)
        full = [w for w in every if w.pad.order is not None] + sorted(
            [w for w in every if w.pad.order is None], key=key_of)
        if [w.pad.order for w in full] != list(range(len(full))):
            self._set_order([w.pad.id for w in full])
        order = [w.pad.id for w in full if w in wins]
        folded = {w.pad.id: _shown_h(w.pad) for w in wins if w.pad.collapsed}
        for w in wins:                          # a note first becomes a tile: it keeps its own size
            if w.pad.own_size is None:
                w.pad.own_size = [w.pad.width, w.pad.height]
        cal = self._open_calendar()
        tids = set(order)
        rows = self._grid_rows.get(key) if keep_rows else None

        def ratio_of(w, h):
            lw, lh = cal._least_for("mini")
            return calgeom.fit_cells(w, h, lw - 7 * px(SMALL_CELL_MIN[0]), lh - 6 * px(SMALL_CELL_MIN[1]), 6)[2]

        def block_for(owner):
            if cal is None or cal.target_box is None or getattr(cal, "_closing", False):
                return None
            pad = cal.nw.pad
            if owner is not None:
                if not cal.docked or pad.id not in tids:
                    return None
            elif cal.docked or self._screen_index(tuple(cal.target_box)) != i:
                return None
            return grid.CalBlock(
                owner=owner, least_mini=tuple(cal._least_for("mini")), least_big=tuple(cal._least_for("big")),
                ratio_of=ratio_of, hold=pad.calendar_hold, near=tuple(cal.target_box),
                block=tuple(pad.calendar_tile_block) if pad.calendar_tile_block else None)

        def plan_with(calblock, obstacles):
            return grid.plan_grid(grid.GridInput(
                order=order, folded=folded, base=base, home=use_home, side=side, area=area, gap=gap,
                min_size=(px(MIN_W), px(MIN_H)), obstacles=list(obstacles), cal=calblock,
                corner_step=px(PILE_STEP), rows=rows))
        owner = cal.nw.pad.id if cal is not None and cal.docked and cal.nw.pad.id in tids else None
        calblock = block_for(owner)
        free_shapes = self._free_shapes(i)
        plan = plan_with(calblock, [s.box for s in free_shapes.values()])
        if plan.block_failed and owner is not None:     # no room beside its note: undock, as G7 does
            cal.docked = cal.nw.pad.calendar_docked = False
            cal._show_state()
            cal.nw.pad.calendar_pos = list(cal.target_box[:2])
            cal._dock_offset = None
            self.space_changed()
            free_shapes = self._free_shapes(i)
            calblock = block_for(None)
            plan = plan_with(calblock, [s.box for s in free_shapes.values()])
        pushed, shrunk, piled = {}, set(), set()
        for _round in range(2):
            if plan.block is None or not free_shapes:
                break
            pushed, shrunk, piled = self._push_free(plan, free_shapes, area, i)
            now = [pushed.get(pid, s.box) for pid, s in free_shapes.items()]
            again = plan_with(calblock, now)
            if again.block is None or again.block == plan.block:
                plan = again if again.block is not None else plan
                break
            plan = again
        # ---- apply
        for w in wins:
            w.pad.stacked = w.pad.id in plan.pile
        for pid in piled:
            if pid in self.windows:
                self.windows[pid].pad.stacked = True
        for pid in shrunk:
            nw = self.windows.get(pid)
            if nw is not None and nw.pad.own_size is None:
                nw.pad.own_size = [nw.pad.width, nw.pad.height]
        targets, starts = dict(plan.spots), {}
        targets.update(pushed)
        if plan.block is not None and cal is not None:
            cal.grid_view = plan.view
            cal.settle_view()
            targets[CAL] = plan.block
            if not cal.docked:
                cal.nw.pad.calendar_pos = list(plan.block[:2])
        for pid in list(targets):
            w = self.windows.get(pid)
            if w is not None and not self.motion.drives(pid):
                try:
                    starts[pid] = (w.win.winfo_rootx(), w.win.winfo_rooty())
                except tk.TclError:
                    pass
        self._grid_rows[key] = plan.rows
        self._grid_last[key] = (plan, list(plan.spots))
        if home is not None:                    # the user's dropped home, not plan.home
            _keep_recent(prefs.grid_homes, key, {"x": int(home[0]), "y": int(home[1]), "side": plan.side}, GRID_HOMES_KEPT)
            self.request_save()
        elif entry is None:
            _keep_recent(prefs.grid_homes, key, {"x": int(plan.home[0]), "y": int(plan.home[1]), "side": plan.side}, GRID_HOMES_KEPT)
            self.request_save()
        self.space_changed()
        self.apply(targets, starts=starts, undo_label=undo_label, before=before)
        if plan.full and not getattr(self, "_arrange_full", False):
            wins[-1].show_notice(tr("auto_full"))
        self._arrange_full = plan.full

    def _push_free(self, plan, free_shapes, area, i):
        """L2: the block pushes the free notes aside. Returns ({id: box} of the free notes that
        moved, the ids shrunk to fit, the ids piled)."""
        gap, px = self._gap(), self.px
        cal = self._open_calendar()
        block = tuple(plan.block)
        if cal is not None and cal.target_box is not None and cal.top.state() != "withdrawn":
            old = tuple(cal.target_box)
        else:                               # opening: nothing is in line, the covered ones relocate
            old = (block[0], block[1], block[0], block[1])
        tile_shapes = [space.Shape(tid, spot, kind="held") for tid, spot in plan.spots.items()]
        shapes = list(free_shapes.values()) + tile_shapes + [space.Shape(CAL, old, kind="cal")]
        areas = self.usable()
        push = space.plan_growth({CAL: block}, shapes, Links(), areas, gap, mode="app", min_w=px(MIN_W),
                                 min_h=px(MIN_H), pile_corner_=space.pile_corner(area, block),
                                 step=px(PILE_STEP), slack=px(2))
        boxes = {pid: tuple(b) for pid, b in push.boxes.items() if pid in free_shapes}
        shrunk = {p for p in push.shrunk if p in free_shapes}
        piled = {p for p in push.piled if p in free_shapes}
        final = {pid: boxes.get(pid, s.box) for pid, s in free_shapes.items()}
        crowded = [pid for pid, b in final.items() if geom.overlap(geom.inflate(block, gap), b)]
        fixed = [tuple(b) for b in plan.spots.values()] + [block]
        members = [s.parts[0] if s.kind == "pair" else s.box for s in self.space()
                   if s.stacked and self._screen_index(s.box) == i] + [tuple(plan.spots[t]) for t in plan.pile]
        members += [final[p] for p in piled]
        for pid in crowded:
            b = final[pid]
            w, h = b[2] - b[0], b[3] - b[1]
            obstacles = fixed + [x for p, x in final.items() if p != pid]
            spot = space.nearest_free(w, h, b[:2], areas, obstacles, gap, i)
            if spot is None:
                spot = space.shrink_to_fit(w, h, px(MIN_W), px(MIN_H), b[:2], areas, obstacles, gap, i)
                if spot is not None:
                    shrunk.add(pid)
            if spot is None:
                corner, step = space.pile_corner(area, block), px(PILE_STEP)
                start = space.pile_start(members, (w, h), area, corner, step, avoid=(block,))
                x0, y0, x1, y1 = space.pile_spots([(w, h)], area, corner, step, start=start, before=members,
                                                   avoid=(block,))[0]
                if not geom.fits_one((x0, y0, x1, y1), [area]):
                    x1, y1 = max(min(x1, area[2]), x0 + min(px(MIN_W), w)), max(min(y1, area[3]), y0 + min(px(MIN_H), h))
                    if not geom.fits_one((x0, y0, x1, y1), [area]):
                        dx, dy = space.slide_in((x0, y0, x1, y1), [area], 0)
                        x0, y0, x1, y1 = x0 + dx, y0 + dy, x1 + dx, y1 + dy
                spot = (x0, y0, x1, y1)
                piled.add(pid)
                shrunk.add(pid)
                members.append(spot)
            final[pid] = boxes[pid] = tuple(spot)
        moved = {pid: b for pid, b in boxes.items() if b != free_shapes[pid].box}
        return moved, shrunk, piled

    def _respace(self, d: int) -> dict[str, Box]:
        """The boxes (by shape id, for apply_plan) that space every link group to the new gap
        (``d`` more than before), around its top-left members: a shape that has another linked
        on its left (or above) sits the gap from it. A docked calendar's room grows by ``d`` on its
        side. A group with a member not inside one usable area slides in as one (M3)."""
        shapes = {s.id: s for s in self.space() if s.kind != "held"}
        gap, slack, areas = self._gap(), self.px(2), self.usable()
        boxes, seen = {}, set()
        for sid, s in shapes.items():
            if sid in seen:
                continue
            ids = [i for i in shapes if i in self.group_of(sid)]
            seen.update(ids)
            grow = {i: [0, 0] for i in ids}                         # a pair: more room on its calendar's side
            for i in ids:
                if shapes[i].kind == "pair" and d:
                    grow[i][space.SHARED_AXIS[shapes[i].side]] = d
            new = {}
            for ax in (0, 1):                                       # x, then y
                before = {i: [] for i in ids}                       # those just before it on this axis
                for a, b in sorted(self.links.pairs()):
                    if a not in before or b not in before:
                        continue
                    ba, bb = shapes[a].box, shapes[b].box
                    if min(ba[3 - ax], bb[3 - ax]) - max(ba[1 - ax], bb[1 - ax]) <= 0:
                        continue                                    # no shared edge along this axis
                    if bb[ax] >= ba[ax + 2] - slack:
                        before[b].append(a)
                    elif ba[ax] >= bb[ax + 2] - slack:
                        before[a].append(b)
                start = {}

                def lo(i, trail=()):
                    if i not in start:
                        start[i] = shapes[i].box[ax]
                        if before[i] and i not in trail:
                            start[i] = max(lo(j, trail + (i,)) + shapes[j].box[ax + 2] - shapes[j].box[ax]
                                           + grow[j][ax] + gap for j in before[i])
                    return start[i]
                for i in ids:
                    new.setdefault(i, [0, 0, 0, 0])
                    new[i][ax] = lo(i)
                    new[i][ax + 2] = start[i] + shapes[i].box[ax + 2] - shapes[i].box[ax] + grow[i][ax]
            moved = {i: tuple(b) for i, b in new.items()}
            if not all(geom.fits_one(b, areas) for b in moved.values()):    # one that doesn't fit: the group slides
                dx, dy = space.slide_in(geom.union(moved.values()), areas)
                moved = {i: geom.shift(b, dx, dy) for i, b in moved.items()}
            boxes.update({i: b for i, b in moved.items()
                          if b != shapes[i].box or (shapes[i].kind == "pair" and d)})
        return boxes
