# Phase 4: Input on the Frame Clock and Stand-in Pictures, Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dragging and resizing notes do one unit of work per display frame, and the frame is cheap enough that no frame takes over twice the display period with 20 notes. Folds, restores and the delete fly use cached stand-in pictures.

**Architecture:**
- Drag and resize handlers record only the latest pointer and ask the `FrameClock` for one apply per frame.
- The apply does today's computation, unchanged, for that pointer. Windows move and resize through the clock's per-frame `DeferWindowPos` batch.
- While a gesture runs, notes skip the bookkeeping their `<Configure>` handler does per window. They catch up at release.
- A `ShotCache` keyed by a per-note look version gives fold, restore, resize-cover and delete-fly their pictures. Restore and unfold always get one.

**Tech Stack:** Python 3.15, Tkinter, Pillow, ctypes (PrintWindow, DeferWindowPos). Tests use stdlib `unittest` with `tests/_support.py`.

**Spec:** `docs/2026-11-25-redesign-design.md` §5.2 (input), §5.3 (stand-in pictures), §7 (Phase 4 row).

## Global Constraints

- **Behaviour rules:**
  - The layout rules must give the same results: snapping, links, `plan_growth` in drag mode, group resize, settle/drop, Undo.
  - Live plans are computed from the boxes at the start of the gesture, exactly as today. Only the moment they run changes: once per frame, for the latest pointer.
- **Data:** never touch `%APPDATA%\StickyNote`. Tests and benches use temp folders.
- **Tests:** run with `.\StickyNote\runtime\python.exe -m unittest discover -s tests` from the project root. All 127 existing tests stay green.
- **Done criterion (§7):**
  - `tools/interact_bench.py` with 20 notes shows no frame whose work exceeds 2× the display period in group drag, group resize and single resize.
  - The live plan comparison shows no mismatch.

## Measured before (`docs/perf/phase4-before.json`, 13.9 ms period, 16-note group)

| Gesture | Work per frame p50 / p95 / max | Frames over 2× period |
|---|---|---|
| Group drag | 13.6 / 14.6 / 15.7 ms | 0 / 60 (21 over 1×) |
| Group resize | 38.2 / 43.6 / 145 ms | 60 / 60 |
| Single resize (Alt) | about 18 ms (separate run) | 0 |

Findings that shape the plan:
- `plan_resize` costs 0.4 ms and `snap` under 0.01 ms.
- Tk already merges queued motion events.
- The cost is in the windows:
  - resizing 16 frozen covers takes 41 ms with `geometry()` each, 31 ms batched, and about 25 ms batched without the app's per-window `<Configure>` work;
  - the first frame pays 16 PrintWindow snapshots (145 ms).

## Review Focus

1. **Release before the frame applies:** the drop must use the latest pointer, not one frame behind (flush on release).
2. **Docked calendars:** they must still follow their notes during a drag, because `<Configure>` places them.
3. **Fold, unfold, minimize and restore while a shot is stale** (text typed, colour changed, resized): the cover must never show an old look.
4. **The Alt / Ctrl / auto-layout tile variants of drag and resize:** they keep today's results.
5. **A window closed mid-gesture or mid-fly:** no TclError, no leaked shot.

---

### Task 1: Gestures apply once per frame through the window batch

**Files:**
- Modify: `StickyNote/app/ui_note.py` (`_drag_move`, `_resize_move`, `_drag_end`, the new `_apply_drag` and `_apply_resize`, `_set_geometry`, `_follow_live`)
- Test: `tests/test_interact.py`

**Interfaces:**
- Produces:
  - `NoteWindow._drag_move(event)` and `_resize_move(event)` store `self._pointer = (x_root, y_root, state)` and call `app.clock.request(self._apply_drag / _apply_resize)`.
  - `_apply_drag()` and `_apply_resize()` hold today's bodies and read `self._pointer`.
  - `_flush_gesture()` runs a pending apply at once. It is called first thing in `_drag_end`.
- Window moves:
  - `_apply_drag` moves the group with `clock.move(win, x, y)`.
  - `_set_geometry(nw, geometry)` becomes `_place(nw, x, y, w=None, h=None)` → `clock.move`, skipping unchanged boxes.
  - The dragged note's own move goes through the batch too.

- [ ] Test `test_one_apply_per_frame`: three `_drag_move` calls in a row (no event loop in between) make exactly one `app.snap` call at the next frame, and the note ends at the third pointer's (snapped) place.
- [ ] Test `test_group_moves_in_one_batch`: during a group drag of 3 linked notes, one frame calls `winapi.defer_move` once, with all 3 hwnds.
- [ ] Test `test_release_flushes_latest_pointer`: `_drag_move(p1)`, `_drag_move(p2)`, then `_drag_end` with no pump. The pad ends at p2's place.
- [ ] Test `test_resize_one_plan_per_frame`: a single-note resize (Alt) with three `_resize_move` calls makes one `app.plan_resize` call. The size follows the last pointer.
- [ ] Test `test_live_plan_matches_per_event`: for a scripted resize path, the final `plan.boxes` from the coalesced apply equal `app.plan_resize` on the full input for the same final pointer. Comparing against `_resize_shapes` is what debug mode logs.
- [ ] Run, watch them fail, then implement and run until they pass. Run the full suite.
- [ ] Commit: `perf(interact): drag and resize apply once per frame through the window batch`.

### Task 2: No per-window bookkeeping mid-gesture

**Files:**
- Modify: `ui_note.py` (`_on_configure`, `_sized`, `thaw`)
- Test: `tests/test_interact.py`

**Decision:**
- While `app.moving` is set, `_on_configure` still updates the pad and places a docked calendar (it follows its note), but does not call `request_save()`.
- A frozen note (`_cover` set) skips `_sized()`; `thaw()` runs it once for the final size.
- Release already saves (`_drag_end` → `request_save`).

- [ ] Test `test_frozen_note_lays_out_once`: during a group resize of 3 linked notes, frozen notes make no `_arrange_chrome` calls. After release, each makes one, and `rail_shown()` fits its new height.
- [ ] Test `test_docked_calendar_follows_drag`: a note with a docked calendar dragged through 5 frames has the calendar's `target_box` moved by the same delta after each frame.
- [ ] Test `test_no_save_mid_gesture`: a `request_save` Spy sees 0 calls during the motions and at least 1 after release.
- [ ] Run, watch them fail, then implement and run until they pass. Commit: `perf(interact): notes skip save and layout work while a gesture runs`.

### Task 3: ShotCache with look versions

**Files:**
- Create: `StickyNote/app/shots.py`
- Modify: `winapi.py` (`snapshot`: one copy, `frombuffer` from the ctypes buffer), `ui_note.py` (`look_version` bumps; `_shot`/`_kept_shot`/`_roll_shot` replaced; `freeze` uses the cache; `destroy` drops), `app.py` (`self.shots`)
- Test: `tests/test_shots.py`

**Interfaces:**
- `ShotCache.shot(nw) -> Image | None`: the cached image when `(nw.look_version, win size)` matches and the window is mapped; otherwise it captures (None when it can't).
- `ShotCache.peek(nw) -> Image | None`: the cached image only if still current, never capturing.
- `ShotCache.invalidate(nw)` and `drop(nw)`.
- `NoteWindow.look_version: int` and `bump_look()`, which are called on:
  - typing sync;
  - `apply_look` (colour, theme, font, pin, transparency);
  - tab, view or memo switch;
  - size change (`_sized`);
  - fold state.

- [ ] Test `test_shot_reused_until_changed`: two `shot(nw)` calls make one `winapi.snapshot` call. After `body.insert` plus `sync_from_widgets`, after `set_color`, and after a resize, a new call captures again.
- [ ] Test `test_shot_dropped_on_close`: after `close_window` and pump, the cache holds no entry for that pad.
- [ ] Test `test_freeze_uses_cache`: `shot(nw)`, then `freeze()`, makes no further `winapi.snapshot` call.
- [ ] Run, watch them fail, then implement and run until they pass. Commit: `perf(shots): one stand-in picture per note, kept while its look holds`.

### Task 4: Restore and unfold always have a cover

**Files:**
- Modify: `ui_note.py` (`_unfold_rolling`, `restore`, a new `_shot_unfolded()`)
- Test: `tests/test_shots.py`

**Decision:** with no current shot of the unfolded note, `_shot_unfolded()` runs these steps:
1. alpha 0;
2. `_roll_geometry(full height)` with the widgets laid out (`_apply_collapsed` state kept);
3. `update_idletasks()`;
4. take the shot;
5. clip back to the strip height;
6. set alpha back.

The roll then uses it.

- [ ] Test `test_unfold_without_kept_shot_is_covered`: fold instantly, change the memo text (stale shot), then `toggle_collapse()` animated. At the first pump step `_rolling_cover` is not None, and its picture height equals `pad.height`.
- [ ] Test `test_restore_without_kept_shot_is_covered`: the same for `minimize(animate=False)` then `restore()`.
- [ ] Run, watch them fail, then implement and run until they pass. Commit: `feat(shots): unfold and restore always roll with a current picture`.

### Task 5: The delete fly from the shot, one PhotoImage

**Files:**
- Modify: `ui_note.py` (`_page_picture`, `_fly_to_bin`)
- Test: `tests/test_shots.py`

**Decision:**
- `_page_picture` crops the home page's box out of `shots.shot(self)`; `ImageGrab` is no longer used.
- The fly keeps ½ and ¼ reductions and one `ImageTk.PhotoImage`. Each frame it resizes the right reduction and `paste`s it into that photo, after setting the Tk photo's width and height.

- [ ] Test `test_fly_reuses_one_photo`: during a fly, `cv._photo` is the same object at every frame, and `ImageGrab.grab` is never called (patched to raise).
- [ ] Run, watch it fail, then implement and run until it passes. Commit: `perf(shots): the delete fly pastes into one picture`.

### Task 6: Picture pan/zoom, calendar grip and range drag per frame

**Files:**
- Modify: `ui_picture.py` (pan and zoom handlers → `clock.request(render)`), `ui_calendar.py` (`_resize_move` → one redraw per frame; `_range_move` → the count card rebuilt only when the range changes)
- Test: `tests/test_interact.py`

- [ ] Test `test_picture_pan_renders_once_per_frame`: three pan motions in a row make one `render` at the next frame.
- [ ] Test `test_calendar_grip_draws_once_per_frame`: three grip motions make one `draw`.
- [ ] Test `test_range_card_only_on_change`: two range motions on the same day range build the count card once.
- [ ] Run, watch them fail, then implement and run until they pass. Commit: `perf(interact): picture pan, calendar grip and range drag once per frame`.

### Task 7: Measure and write results

**Files:**
- Modify: `tools/interact_bench.py` (each scenario on a fresh app), `docs/2026-11-25-redesign-design.md` (a "Phase 4 results" section)

- [ ] Run the bench and save `docs/perf/phase4.json`. Done when each gesture has 0 frames over 2× the period.
- [ ] If group resize misses, record the measured split (batch, Configure, repaint) and what's left for later in the results.
- [ ] Commit: `perf: phase 4 results`.
