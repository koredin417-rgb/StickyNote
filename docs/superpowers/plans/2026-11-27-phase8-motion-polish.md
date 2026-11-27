# Phase 8: Motion Polish, Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every animation shows its whole curve at the display's full rate. This covers the new-note fade, group resize, fold, minimize and drops, and it makes the Reduced and Off settings do what they say.

**Architecture:**
- **The frame clock (`anim.py`):**
  - Each animation's clock starts at its first frame.
  - The half-rate trigger is median-based, with hysteresis, and is cleared at idle.
  - It gets three new hooks: `quiet()`, `glide_ms()` and `velocity=`.
- **The call sites take the new rules and tokens.** Saves move behind the motion. Chained phases overlap.
- **Group resize:** a frozen note's window stops changing size every frame; a window region shows the size instead. The roll already does this.
- **Drag companions:** the group ring and docked calendars join the frame's one DeferWindowPos.

**Tech Stack:** Python 3.15 (bundled runtime), Tkinter, ctypes (user32/gdi32), Pillow. Tests use stdlib `unittest`.

**Spec:**
- `docs/2026-11-27-improvement-proposals.md` §3 B: B1, B2, B3, B4, B5, B6, B7, B8, B9, plus C4's close easing.
- The engine it changes: `docs/2026-11-25-redesign-design.md` §5.1.
- Results go in the redesign spec under "Phase 8 results".

## Global Constraints

- **Data:** never touch `%APPDATA%\StickyNote`. Benches and tests use temp folders.
- **Tests:** run with `.\StickyNote\runtime\python.exe -m unittest discover -s tests`. All 206 existing tests stay green; a test that pins an old value is updated in the same task, with a ledger line.
- **Tokens stay named in `ui_common.py`.** Durations come from `anim.FAST/BASE/LONG` or a new named constant, never a bare number at a call site.
- **Keep today's behaviour** everywhere this plan doesn't name a change: links, magnet, Undo offers, docked-calendar sides, taskbar minimize/restore (Win+M, Win+D).
- **No `cProfile`** (the runtime lacks it). Profile with perf spans or wrapper timers.
- **Commits:** on branch `phase8`, one or more per task, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No push without the user.

## Decisions (calls made for this plan)

- **Numbering:** motion polish became Phase 8 because the user chose it first. The quick fixes (proposals' "Phase 8") become Phase 9. The proposals' §6 is updated in Task 10.
- **B7 "open with a 6 px rise": not done.** A new note already slides out from behind its parent, and a rise would fight that slide.
- **C4, closing the calendar:** opacity uses ease-in over the same 120 ms as the position. The proposals said linear over 80 ms, but that empties the window before it has moved a third of the way. B7's "ease-in for fade-outs" settles it.
- **B3, the approach (measured 2026-11-27, 16 linked notes):**
  - Today: p50 17.2 ms per frame, 46 of 60 frames over budget.
  - With the other notes' windows only moved, not resized: p50 6.4 ms, 0 over.
  - So a frozen note's window keeps its size and shows its current size through a window region. It grows in steps of `RING_SLACK` (96 px) when it needs more room.
  - The region has rounded corners (`CreateRoundRectRgn`, radius 8 px at 100 %), because DWM's own rounding switches off while a region is set.
- **B8:** the snap eases on a first-order lag: τ = 28 ms, 90 % in 65 ms, no overshoot. On release, whatever is left of the ease is applied at once, so the drop is exactly where the magnet said.
- **B9, the kinds:**
  - `animate()` defaults to `kind="move"`.
  - `tween()` reads its kind from the channel ("alpha" is a fade; everything else is a move).
  - The sites listed in Task 5 pass `kind="fade"`.

## Review Focus

- **Quitting right after an action whose save is now deferred** (new note, reopen, close, trash, then quit): nothing is lost. Pinned by Task 3, `test_quit_right_after_new_note_keeps_it`.
- **Animations Off or Reduced through each changed path** (minimize, restore, fold, unfold, close, group drop): each ends in its right state, with no window left at alpha 0, clipped or rolling. Pinned by Task 5, `test_off_and_reduced_end_states`.
- **Releasing a group resize:** every member's window is exactly its pad's box, no region is left behind, and a folded member keeps its folded height. Pinned by Task 6, `test_group_resize_release_exact` (with a folded member).
- **A glide grabbed before its first frame,** for example a new note grabbed as it appears: it stops where it is and never jumps to a later spot. Pinned by Task 1, `test_stop_before_first_frame_stays`.
- **The pointer held still during a snap ease:** the ease still finishes on its own frames, and the clock then goes idle. Pinned by Task 9, `test_snap_eases_with_still_pointer`.

---

### Task 1: B1, the clock starts at the first frame

**Files:**
- Modify: `StickyNote/app/anim.py`. The changes are in `_Anim.progress`, `FrameClock.animate`, `tween`, `_tick` and `_wake`, plus a new `_period()`.
- Test: `tests/test_anim_clock.py` (new class `FirstFrameTest`)

**Interfaces:**
- Produces:
  - `_Anim.t0: float | None`. It is None until the animation's first tick, and `progress()` returns 0.0 while it is None (`ms > 0`).
  - `FrameClock._period() -> float`: the DWM period, or `GRID`.
  - At the first tick, `t0 = now - self._period()`.
  - `_wake()` takes the 1 ms timer (`winapi.fine_timer(True)`) when it doesn't hold it.

- [ ] **Step 1: Write the failing tests** in `FirstFrameTest`. Use the `ClockTest` setUp, `run_for`, and the linear `ease=lambda t: t`. Let `P = clock._period()`.
  - `test_first_frame_starts_one_period_in`:
    - Call `animate(root, "x", 120, ks.append, ease=lin)`, then `time.sleep(0.06)` (work before the frame), then run for 0.3 s.
    - Assert `ks[0] == 0.0`, `0 < ks[1] <= 1.6 * P / 0.120` and `ks[-1] == 1.0`.
  - `test_tween_first_frame_one_period_in`: `tween(root, "c", 100.0, 120, frm=0.0, ease=lin, read=..., write=vals.append)`, sleep 0.06, run. Assert `vals[0] == 0.0` and `0 < vals[1] <= 100 * 1.6 * P / 0.120`.
  - `test_stop_before_first_frame_stays`: tween `frm=0.0` to 100, then at once `clock.stop(root, "c")`, then run 0.1 s. Assert `vals == [0.0]`.
  - `test_wake_takes_fine_timer`:
    - Let the clock go idle and call `clock._release_fine()`, so `fine_timer_held` is False.
    - Call `clock.request(lambda: None)`.
    - Assert `clock.fine_timer_held` is True before any `update()`.
- [ ] **Step 2: Run** `.\StickyNote\runtime\python.exe -m unittest tests.test_anim_clock -v`.
  Expected: the first two FAIL (ks[1] ≥ 0.5) and the wake test FAILS. The stop test may pass already.
- [ ] **Step 3: Implement** in `anim.py`:
  - `t0=None` at `_Anim` creation, in both `animate` and `tween`.
  - `progress()` handles None.
  - In `_tick`, set `a.t0 = now - self._period()` for each anim whose `t0` is None before computing `s`.
  - `_wake` takes the fine timer.
  - A retarget (`old.progress(now)` on an unticked old anim) starts from `old.v0`. That follows from `progress() == 0`.
- [ ] **Step 4: Run** the anim, motion and smoke tests: `... -m unittest tests.test_anim_clock tests.test_anim_channels tests.test_motion_clock tests.test_smoke -v`. Expected: PASS.
- [ ] **Step 5: Commit** `perf(anim): an animation's clock starts at its first frame`.

### Task 2: B2, a half-rate trigger that only reacts to real load

**Files:**
- Modify: `StickyNote/app/anim.py`. `HALF_RATE_WORK` is replaced by `HALF_RATE_ENTER = 0.8`, `HALF_RATE_LEAVE = 0.55` and `HALF_RATE_WINDOW = 6`. The other changes are a `_half` flag, `_every(period) -> int`, and edits to `_tick`, `_schedule` and `_went_idle`.
- Test: `tests/test_anim_clock.py` (new class `HalfRateTest`)

**Interfaces:**
- Consumes: Task 1's `t0 is None` as the "first tick" marker.
- Produces: `FrameClock._every(period: float) -> int`, which returns 1 or 2:
  - It returns 1 when `period >= HALF_RATE_BELOW` or fewer than `HALF_RATE_WINDOW` samples are kept.
  - Otherwise it works on the median `m` of the last 6:
    - enter half rate when `m > 0.8 * period`;
    - leave it when `m < 0.55 * period`;
    - else keep the current state.
- **What `_work` records:** the tick's time up to the end of `_flush`, so `done` callbacks are not counted. A tick in which any animation took its first step records nothing. `_went_idle` clears `_work` and sets `_half = False`.

- [ ] **Step 1: Write the failing tests:**
  - `test_hysteresis`, with `P = 0.0139`:
    - `_work = [0.012]*6` → `_every(P) == 2`;
    - then `[0.009]*6` → 2;
    - then `[0.007]*6` → 1.
    - `[0.012]*5` → 1, from rest.
    - `_every(0.0167)` with `[0.02]*6` → 1.
  - `test_one_heavy_tick_does_not_halve`: `_work = [0.002]*5 + [0.05]` → 1.
  - `test_idle_clears_work`:
    - Set `clock._work = [0.02]*6` and `clock._half = True`.
    - Animate 30 ms and run 0.3 s.
    - Assert `clock._work == []` and `clock._half is False`.
  - `test_done_not_counted`:
    - Start a light 300 ms animate.
    - Then start a 30 ms animate whose done does `time.sleep(0.025)`.
    - Run 0.15 s.
    - Assert `max(clock._work) < 0.010`.
  - `test_first_tick_not_counted`:
    - Start a light 300 ms animate and run 0.05 s.
    - Then start an animate whose step sleeps 25 ms on its second call only (its first tick).
    - Run 0.1 s.
    - Assert `max(clock._work) < 0.010`.
- [ ] **Step 2: Run** `... -m unittest tests.test_anim_clock -v`.
  Expected: the new tests FAIL (`_every` is missing, and work is counted).
- [ ] **Step 3: Implement as in the Interfaces.** `_schedule` uses `every = self._every(period)`.
- [ ] **Step 4: Run** `tests.test_anim_clock tests.test_motion_clock tests.test_anim_batch`. Expected: PASS.
- [ ] **Step 5: Commit** `perf(anim): half rate only under sustained load (median, hysteresis, cleared at idle)`.

### Task 3: B4, saves wait for the motion to end

**Files:**
- Modify:
  - `StickyNote/app/anim.py`: `FrameClock.quiet(fn)`.
  - `StickyNote/app/persist.py`: `save_soon()`, with `SAVE_SOON_MS = 1000` in `ui_common.py`.
  - `StickyNote/app/registry.py`: new note (line ~222), reopen (~248), close (~315), trash (~125) and restore (~134) call `save_soon()` instead of `save_now()`. In `close_window`, `nw.fade_out(gone)` starts before the bookkeeping.
- Test: `tests/test_saving.py` (new class `SaveSoonTest`)

**Interfaces:**
- Produces:
  - `FrameClock.quiet(fn) -> None`: runs `fn` once, the next time the clock goes idle (in `_went_idle`). If the clock isn't busy, it runs it at `after_idle`. Each fn runs at most once.
  - `PersistMixin.save_soon() -> None`:
    - It sets `_dirty`.
    - It arms one save at `clock.quiet` or after `SAVE_SOON_MS`, whichever comes first. The other trigger does nothing: a `_soon_armed` flag decides.
    - `save_now()` stays as it is. Quit already calls `save_now(force=True)`.
- `delete_forever`, `empty_bin`, export, settings and quit keep `save_now()`.

- [ ] **Step 1: Write the failing tests.** Count saves by wrapping `app.store.save` with `_support.patched`, recording `(time, app.clock.busy)`.
  - `test_new_note_saves_after_motion`:
    - Let `n0` be the save count.
    - Call `app.new_window(from_window=nw)`.
    - Assert the count is still `n0` right after the call.
    - Pump until a save (≤ 2 s). Assert it came, with `busy` False.
  - `test_save_soon_bounded_by_one_second`:
    - Keep the clock busy: `clock.animate(app.root, "hold", 3000, lambda k: None)`.
    - Call `app.request_save` (cancel its job), then `app.save_soon()`.
    - Assert one save lands between 0.9 and 1.6 s.
  - `test_quit_right_after_new_note_keeps_it`:
    - Create a new note, insert "keep me" into its body, and `sync_from_widgets()`.
    - Call `app.quit()` at once.
    - A fresh `NoteStore` on the folder holds a note with "keep me" and its pad.
- [ ] **Step 2: Run** `... -m unittest tests.test_saving -v`.
  Expected: the first two FAIL (a save inside the call, and `save_soon` missing). The third passes: it pins the behaviour so it stays.
- [ ] **Step 3: Implement as in the Interfaces.**
- [ ] **Step 4: Run** `tests.test_saving tests.test_smoke tests.test_phase6_review`. Expected: PASS.
- [ ] **Step 5: Commit** `perf(save): saves after new/reopen/close/trash wait for the motion (at most 1 s)`.

### Task 4: B7 and C4's close, durations and curves

**Files:**
- Modify:
  - `StickyNote/app/anim.py`: `smoothstep(s)`, and `glide_ms(d)` with `GLIDE_MIN, GLIDE_MAX = 180, 320`.
  - `StickyNote/app/ui_common.py`:
    - `OPEN_FADE_MS = 160` and `CLOSE_FADE_MS = anim.FAST`.
    - `fade(..., ease=anim.ease_out)`.
    - The scroll thumb's fade-out (line ~1229) uses `ease=anim.ease_in`.
  - `StickyNote/app/motion.py`: `run(targets, ms=None, ...)`, where None means a duration by distance, per item.
  - `StickyNote/app/layout.py`: `apply(..., ms=None)`.
  - `StickyNote/app/ui_note.py`:
    - `glide_to(..., ms=None)`.
    - `flash()`: linear t, colour by `smoothstep`, and a widget is configured only when its colour string changed.
  - `StickyNote/app/ui_calendar.py` (lines ~318-323): the close glide and fade both use `ease=anim.ease_in` over `anim.exit_ms(CAL_SHOW_MS)`.
- Test: `tests/test_anim_curves.py`, `tests/test_tokens.py` (update the `CLOSE_FADE_MS` pin to `(120, 400)` and move `OPEN_FADE_MS` out of the FAST tuple; ledger it), and `tests/test_motion_clock.py`.

**Interfaces:**
- Produces:
  - `anim.smoothstep(s: float) -> float` = `s*s*(3-2*s)`.
  - `anim.glide_ms(d: float) -> int` = `min(320, max(180, round(140 + 6 * sqrt(d))))`, where `d` is in px at 100 %.
  - `Motion.run(..., ms=None)`: each new `_Item` gets `glide_ms(d / scale)`. Here `d` is the largest corner travel, `max(hypot(Δx0, Δy0), hypot(Δx1, Δy1))`, and `scale = app.px(100) / 100`. An explicit `ms` applies to every item, as today.
  - `GLIDE_MS` stays as the name for a fixed glide.

- [ ] **Step 1: Write the failing tests:**
  - `test_glide_ms_by_distance`: `glide_ms(0) == 180`, `glide_ms(100) == 200`, `glide_ms(600) == 287` and `glide_ms(5000) == 320`.
  - `test_smoothstep`: values at 0, 0.25 (0.15625), 0.5 and 1.
  - `test_plan_ms_by_distance` (motion): note `nw` at x, then `app.apply({pid: box shifted 100 px right})`. Assert `app.motion._items[pid].ms == anim.glide_ms(100 / scale)`.
  - `test_explicit_ms_kept`: `nw.glide_to(x + 300, y, ms=NEW_SLIDE_MS)` gives item ms 240.
  - `test_calendar_close_eases_in`:
    - Open the calendar and let it settle, then `toggle_calendar()` to close it.
    - The running anims `clock._anims[(id(top), "alpha")]` and `(id(top), "box")` both have `.ease is anim.ease_in` and `.ms == 120`.
  - Tokens: `CLOSE_FADE_MS == 120` and `OPEN_FADE_MS == 160`.
- [ ] **Step 2: Run** `tests.test_anim_curves tests.test_tokens tests.test_motion_clock`. Expected: FAIL.
- [ ] **Step 3: Implement as in Files and Interfaces.**
- [ ] **Step 4: Run** `tests.test_anim_curves tests.test_tokens tests.test_motion_clock tests.test_anim_channels tests.test_interact tests.test_smoke`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(motion): glide time by distance; 160 ms open, 120 ms ease-in close; smoothstep flash`.

### Task 5: B9, Reduced and Off decided by kind

**Files:**
- Modify:
  - `StickyNote/app/anim.py`: `animate(..., kind="move")` and `tween(..., kind=None)`.
  - `StickyNote/app/ui_common.py`: `animate(..., kind="move")` passes it through.
  - These call sites pass `kind="fade"`:
    - `ui_calendar.py` dip (~998) and ink (~1196);
    - `ui_common.py` scroll fade (~1229);
    - `ui_note.py` done_fade (~1967) and flash (~2821);
    - `ui_picture.py` picture fade (~223);
    - `motion.py` crossfade (~292).
  - `ui_note.py`:
    - `minimize()` and `restore()`: in Off, take the `animate=False` path. In Reduced, fade (`CLOSE_FADE_MS` out, then `finish`; `OPEN_FADE_MS` in after `deiconify`), with no roll and no covers.
    - `toggle_collapse()`: anything but "full" takes the instant path.
- Test: `tests/test_motion_setting.py`

**Interfaces:**
- Produces: the mode rules in `FrameClock`:
  - "off": every animate and tween ends at once. `animate` calls `step(ease(1.0))` and `tween` writes `v1`, both inside the call; their `done` runs at the next frame (an `_Anim` with `ms=SKIP_MS`).
  - "reduced": `kind == "move"` behaves as "off"; `kind == "fade"` runs at its own ms, with no cap.
  - "full": as today.

- [ ] **Step 1: Write the failing tests** (set `app.apply_motion("reduced")` / `"off"` as the existing tests do):
  - `test_reduced_keeps_fades_cuts_moves`:
    - A `kind="fade"` animate of 120 ms is still `active` after 30 ms of pumping.
    - A 60 ms `kind="move"` animate (≤ FAST, which today's rule keeps) got `step(1.0)` inside the call. Its done is not called inside the call, and is called within 0.1 s.
  - `test_off_writes_end_at_once`: a tween `frm=0` to 100 reads 100 right after the call; its done is not called inside the call, and is called after pumping.
  - `test_off_and_reduced_end_states`: for each mode in ("off", "reduced"):
    - Minimize a note, pump, restore it, pump. It shows: `state() == "normal"`, alpha == `pad.alpha`, `nw.rolling` False, no `_rolling_cover`.
    - Fold it: `pad.collapsed` True at once and no `_rolling_cover`. Unfold it.
    - Close a second note: the window is destroyed within 0.5 s.
- [ ] **Step 2: Run** `tests.test_motion_setting`. Expected: FAIL.
- [ ] **Step 3: Implement as in Files and Interfaces.**
- [ ] **Step 4: Run** `tests.test_motion_setting tests.test_anim_clock tests.test_motion_clock tests.test_anim_channels tests.test_smoke`. Expected: PASS.
- [ ] **Step 5: Commit** `fix(motion): Reduced keeps fades and cuts moves; Off ends at once with no covers`.

### Task 6: B3, group resize without resizing windows each frame

**Files:**
- Modify:
  - `StickyNote/app/winapi.py`: `clip_box(win, w, h, radius) -> bool`, via `CreateRoundRectRgn(0, 0, w+1, h+1, 2r, 2r)` and `SetWindowRgn`. `clip_height(win)` with no size still clears the region.
  - `StickyNote/app/ui_note.py`:
    - `freeze()` keeps `lay` on the cover.
    - New `NoteWindow.clip_to(x, y, w, h)`.
    - `thaw()` ends the clip.
    - `_on_configure` returns early while `_clip` is set.
    - `_apply_resize` calls `o.clip_to(...)` for frozen group members instead of `self._place(o, x, y, ow, oh)`. The dragged note itself still uses `_place`.
- Test: `tests/test_interact.py` (new class `GroupResizeClipTest`)

**Interfaces:**
- Produces:
  - `NoteWindow._clip: tuple | None`: the (x, y, w, h) it shows while clipped.
  - `NoteWindow.clip_to(x, y, w, h) -> None` (frozen only; otherwise it falls back to `_place`):
    - When the window's real size holds (w, h), it queues `clock.move(win, x, y)`. Otherwise it first queues `clock.move(win, x, y, w + slack, h + slack)`, with `slack = px(GroupRing.RING_SLACK)`.
    - It sets the region with `clip_box(win, w, h, px(8))` and places the cover at `width=w-2e, height=h-2e`. It calls `cover.lay(...)` for the shown size.
    - It writes the pad (x, y, width, and height unless folded) and calls `space_changed()`. A docked calendar runs `place()`.
  - `thaw()` on a clipped note: `win.geometry(f"{w}x{h}+{x}+{y}")` from `_clip` first, then `clip_height(win)` (no region), then the cover goes as today.

- [ ] **Step 1: Write the failing tests.** Three linked notes in a row come from `new_window(from_window=...)` twice. Drive `_resize_start` / `_resize_move` / `_drag_end` on the first note's grip with synthetic events, pumping a frame each.
  - `test_group_resize_shrink_keeps_window_size`:
    - Shrink by 20 px in height over 5 frames.
    - The second note's `win.winfo_height()` is unchanged, while `nw2._clip[3] == h0 - 20`.
  - `test_group_resize_grow_steps_by_slack`: grow 150 px over 15 frames. Count `winfo_width()` changes of the second note: at most 2.
  - `test_group_resize_release_exact`, with the third note folded first:
    - After `_drag_end` and `update_idletasks()`, each member's `(winfo_rootx, winfo_rooty, winfo_width, winfo_height)` equals its pad box (folded: its shown height).
    - Each `_clip is None` and each `_cover is None`.
- [ ] **Step 2: Run** `tests.test_interact`. Expected: FAIL (`_clip` missing; the window resizes).
- [ ] **Step 3: Implement as in Files and Interfaces.**
- [ ] **Step 4: Run** `tests.test_interact tests.test_shots tests.test_corners tests.test_smoke`. Expected: PASS.
- [ ] **Step 5: Measure** `.\StickyNote\runtime\python.exe tools\interact_bench.py`.
  Expected: `group_resize` p50 < `period_ms`, `over_period` ≤ 6, `over_2x` 0. `group_drag` and `solo_resize` are no worse than today (p95 9.3 / 12.9 ms). Ledger the numbers.
- [ ] **Step 6: Look:** run a group resize by hand with `preview.py`, or capture three frames with `winapi.snapshot`. The corners are rounded during the gesture, with no flash at release. Ledger what was seen.
- [ ] **Step 7: Commit** `perf(resize): group resize shows sizes through a window region (72 fps)`.

### Task 7: B5, chained phases overlap

**Files:**
- Modify:
  - `StickyNote/app/layout.py`: `set_folded(wins, on, rolling=False)`.
  - `StickyNote/app/ui_note.py`:
    - `_apply_collapsed(shoot=False, geometry=True)`.
    - `_fold_rolling`: the plan runs at the roll's start.
    - `minimize` / `restore` each become one curve.
    - `_roll_geometry(h, dy)` uses the region path whenever a roll cover is up, `dy` included.
    - `_drag_end`'s push uses `motion.when_still`.
  - `StickyNote/app/ui_common.py`: `MINIMIZE_MS = 280`. `DOCK_SLIDE_MS` is removed.
  - `StickyNote/app/taskbar.py:125`: the focus timer becomes `MINIMIZE_MS + 60`.
  - `StickyNote/app/motion.py`: `when_still(fn)`.
- Test: `tests/test_interact.py` (new class `OverlapTest`); `tests/test_tokens.py` (the `DOCK_SLIDE_MS` entry goes; ledger it)

**Interfaces:**
- Produces:
  - `Motion.when_still(fn) -> None`: if a plan runs, `fn` joins `_dones` (run once at `_end`); else `clock.request(fn)`.
  - `set_folded(..., rolling=True)`: sets `pad.collapsed`, then plans and runs as today, but calls `w._apply_collapsed(shoot=True, geometry=False)` for those windows.
- **The fold:** after the roll, `_apply_collapsed(geometry=True)`. If `motion.drives(p.id)` right after the plan starts, the roll stops and the note just folds: drop the cover and `_apply_collapsed()`.
- **Minimize, one linear `animate` of `MINIMIZE_MS` with t in 0..1:**
  - height `shown + (bar - shown) * ease_out(min(1, t / 0.6))`;
  - slide and fade `u = ease_in(max(0, (t - 0.35) / 0.65))`;
  - `_roll_geometry(h, slide * u)`; alpha `alpha * (1 - u)`.
- **Restore is the mirror:**
  - slide and fade `u = ease_out(min(1, t / 0.65))`;
  - height `bar + (shown - bar) * ease_out(max(0, (t - 0.4) / 0.6))`.

- [ ] **Step 1: Write the failing tests:**
  - `test_fold_moves_neighbours_during_roll`:
    - Note B is linked under note A, which was made from A and placed below it. Fold A (`toggle_collapse()`).
    - Right after the call: `A.rolling` and `app.motion.drives(B.pad.id)`.
    - Pump until neither is busy, measuring elapsed: < 0.35 s.
    - B's top is A's folded bottom plus the gap.
  - `test_minimize_one_curve`:
    - Wrap `_roll_geometry` to record `(h, dy, alpha)` each call. Minimize.
    - Some record has `h > bar` and `alpha < pad.alpha`.
    - `nw.minimized` becomes True between 0.2 and 0.4 s.
  - `test_restore_one_curve`: the mirror. Some record has `h > bar` while `alpha < pad.alpha`. It ends at `alpha == pad.alpha` and full height.
  - `test_group_drop_pushes_without_timer`:
    - Wrap `app.push_clear` to record its time.
    - Drag a linked pair 40 px into free space and release.
    - `push_clear` runs within 0.06 s of the release (today ≥ 0.28 s).
- [ ] **Step 2: Run** `tests.test_interact tests.test_tokens`. Expected: FAIL.
- [ ] **Step 3: Implement as in Files and Interfaces.**
- [ ] **Step 4: Run** `tests.test_interact tests.test_tokens tests.test_motion_setting tests.test_smoke tests.test_corners`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(motion): fold, minimize and group drop run as one continuous motion`.

### Task 8: B6, the ring and docked calendars move in the note's batch

**Files:**
- Modify:
  - `StickyNote/app/ui_common.py`: `GroupRing.move(boxes, now=False)`. Window moves go through `clock.move`; `show()` passes `now=True`, a direct `geometry()` while the window is withdrawn.
  - `StickyNote/app/ui_calendar.py`: new `CalendarWindow.ride(x, y)`.
  - `StickyNote/app/ui_note.py`: `_apply_drag` rides each moved note's docked, mapped calendar.
- Test: `tests/test_interact.py` (new class `BatchTest`)

**Interfaces:**
- Produces: `CalendarWindow.ride(x: int, y: int) -> None`:
  - It queues `clock.move(self.top, x, y)` and sets `_xy` and `target_box` (same size) without `geometry()`.
  - A later `place()` from `<Configure>` then finds it in place and does nothing.
  - In `_apply_drag`: `ride(x + ox, y + oy)`, with `(ox, oy) = cal._xy - (w.pad.x, w.pad.y)` taken at drag start.

- [ ] **Step 1: Write the failing tests.** Wrap `winapi.defer_move` to record the set of hwnds per call.
  - `test_ring_moves_in_batch`: in a group drag of a linked pair, after the first two frames, every frame's batch holds the ring's hwnd with the notes' hwnds.
  - `test_docked_calendar_moves_in_batch`:
    - Open the calendar on a note (docked) and drag the note over 5 frames.
    - Each frame's batch holds both hwnds.
    - `CalendarWindow.move_to` is not called during the frames (wrap and count; 0).
- [ ] **Step 2: Run** `tests.test_interact`. Expected: FAIL.
- [ ] **Step 3: Implement as in Files and Interfaces.**
- [ ] **Step 4: Run** `tests.test_interact tests.test_calendar_draw tests.test_anim_batch tests.test_smoke`. Expected: PASS.
- [ ] **Step 5: Commit** `perf(drag): the group ring and a docked calendar move in the note's window batch`.

### Task 9: B8, snaps ease in and throws keep their speed

**Files:**
- Modify:
  - `StickyNote/app/ui_common.py`: `SNAP_TAU_S = 0.028`.
  - `StickyNote/app/ui_note.py`:
    - `_drag_move` keeps pointer samples.
    - `_apply_drag` eases the snap offset.
    - `_flush_gesture` / `_drag_end` finish the ease and pass the release velocity.
  - `StickyNote/app/anim.py`: `tween(..., velocity=None)` and `glide(..., velocity=None)`.
  - `StickyNote/app/motion.py`: `run(..., velocity=None)`.
  - `StickyNote/app/layout.py`: `apply(..., velocity=None)` and `settle_drop(..., velocity=None)`.
- Test: `tests/test_interact.py` (new class `SnapEaseTest`), `tests/test_anim_clock.py`

**Interfaces:**
- Produces:
  - `FrameClock.tween(..., velocity: tuple | None = None)`: when no tween of that channel runs, its `start_slope` uses `velocity[i]` (value per second).
  - `FrameClock.glide(..., velocity=(vx, vy))` passes `(vx, vy, vx, vy)`.
  - `Motion.run(..., velocity: dict | None = None)`: pid → (vx, vy), for items not already gliding.
  - `NoteWindow._release_velocity() -> tuple[float, float]`: from samples `(t, x_root, y_root)` of the last 80 ms. The displacement over the span is divided by the span; it is (0, 0) when the span is < 30 ms.
- **The ease in `_apply_drag`:**
  - `want = snapped - raw`;
  - `off = want + (off - want) * exp(-dt / SNAP_TAU_S)`;
  - shown = `raw + round(off)`.
  - While `abs(off - want) >= 0.5` on an axis, the frame asks for itself again (`clock.request(self._apply_drag)`).
- **At release:** `off = want` (the windows go to the snapped spot in the last batch) before `_dropped` is read.

- [ ] **Step 1: Write the failing tests:**
  - `test_tween_velocity_start_slope`: `tween(root, "c", 100.0, 200, frm=0.0, velocity=(1000.0,), ...)` gives `a.m[0] == anim.start_slope(0, 100, 1000, 0.2)`, which is 200. Without it: 300.
  - `test_release_velocity`:
    - Samples `[(0.00, 0, 0), (0.05, 50, 0)]` give `(1000.0, 0.0)`.
    - `[(0.00, 0, 0), (0.02, 20, 0)]` give `(0.0, 0.0)`.
  - `test_snap_eases_in`:
    - Notes A and B are unlinked, 200 px apart in a row.
    - Drag A toward B, 4 px a frame, until the snap engages. Record A's `winfo_rootx()` per frame.
    - At the engage frame, A moved less than the full snap shift.
    - Within 6 frames it sits at the snapped x.
  - `test_snap_eases_with_still_pointer`:
    - Engage a snap, then send no more motion.
    - A reaches the snapped x.
    - Then `app.clock.busy` goes False within 0.3 s.
  - `test_drop_lands_on_snap`: release on the engage frame. `A.pad.x` and the window x both equal the snapped x.
- [ ] **Step 2: Run** `tests.test_interact tests.test_anim_clock`. Expected: FAIL.
- [ ] **Step 3: Implement as in Files and Interfaces.**
- [ ] **Step 4: Run** `tests.test_interact tests.test_anim_clock tests.test_motion_clock tests.test_smoke`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(drag): the magnet eases in (28 ms); a thrown drop keeps its speed`.

### Task 10: Measure, record, full suite

**Files:**
- Modify:
  - `docs/2026-11-25-redesign-design.md`: append "## Phase 8 results (motion polish)".
  - `docs/2026-11-27-improvement-proposals.md`: §6 order (motion polish became Phase 8) and the B items marked done.
- Test: the whole suite.

- [ ] **Step 1: Run** the full suite: `.\StickyNote\runtime\python.exe -m unittest discover -s tests`. Expected: OK, 206 + the new tests.
- [ ] **Step 2: Measure** with these tools:
  - `tools\interact_bench.py`;
  - `tools\baseline.py`;
  - `tools\idle_bench.py`;
  - the scratch `first_frame.py`: the new note's fade first frame is ≤ 20 % of its time; fold, unfold and calendar open stay ≤ 5 %.
  - Expected: `idle_bench` stays at ≤ 2 wakeups in 10 s, and group_resize meets Task 6's line.
- [ ] **Step 3: Record** a results table in the spec, in the shape the Phase 7 results use: what, before, after, verdict. Update the proposals doc.
- [ ] **Step 4: Commit** `docs: phase 8 results (motion polish)`.
