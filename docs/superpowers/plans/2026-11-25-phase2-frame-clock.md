# Phase 2: Frame Clock — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every animation in the app runs on one clock, paced to the display. Starting something new on a property that is already moving continues from where it is, and windows that move together move in the same frame.

**Architecture:**
- A new `anim.py` holds one `FrameClock` per app. It has:
  - frame requests;
  - progress animations: a drop-in replacement for today's `animate()`;
  - value tweens: one owner per (owner, channel), which retarget with velocity;
  - a per-frame window-move batch (`DeferWindowPos`);
  - an idle hook.
- `ui_common.animate`/`fade` become thin wrappers onto the clock, so every call site moves at once.
- `Motion` drops its own loop and drives its glides as clock tweens.
- The properties where reversing matters (window alpha, window position, month paging, settings page) become retargeting tweens.
- The fold/minimize roll (`"roll"`, `SetWindowRgn`) stays a progress animation on the clock in this phase. Its `clip` channel with reversal arrives with the C fold strip (spec Phases 3–4).
- Durations collapse onto three tokens, and a new Animations setting (Full / Reduced / Off) follows Windows' own animation setting by default.

**Tech Stack:** Python 3.15 (bundled `StickyNote/runtime`), Tkinter, ctypes/Win32 (`dwmapi`, `user32`), stdlib `unittest`.

**Spec:** `docs/2026-11-25-redesign-design.md` (§5.1 engine, §5.1.6 tokens, §5.1.7 motion setting, §7 Phase 2, §8 S2/S3 results). Phase 0–1 plan and results: `docs/superpowers/plans/2026-11-25-phase0-1-harness-and-quick-fixes.md`, spec sections "Baseline" and "Phase 1 results".

## Global Constraints

- **Runtime:** bundled runtime only; no new packages. `unittest.mock` can't be imported (no `asyncio`), so use `tests/_support.py` `patched`/`Spy`.
- **Commands** run from `C:\Users\KMH\Desktop\projects\StickyNote`. Tests: `.\StickyNote\runtime\python.exe -m unittest discover -s tests -v`.
- **Branch:** `phase2`, created from `phase0-1` (pull request #1 is still open).
- **Layout rules** (S1/S4, C1/C2, L2-L5, M2, N2, N5, P1-P6) give the same results. Only timing and smoothness change, apart from the duration changes listed in Task 8 and the new setting in Task 10.
- **Tokens** (spec §5.1.6):
  - `FAST = 120`, `BASE = 180`, `LONG = 240` ms, all ease-out cubic;
  - `exit` = round(⅔ × the entering token) = 80 / 120 ms, ease-in quad. The spec's "0.67×" rounds 180 to 121, but its table says 120, so ⅔ is used.
- **Retarget** starts from the current value and the current velocity, with the start slope capped at 1.5× the curve's normal start slope (spec §5.1.2).
- **Pacing** (spec §5.1.1):
  - Aim at the first vblank at least 4 ms away, minus 2 ms. The vblank comes from `DwmGetCompositionTimingInfo`.
  - Fallback: a 16.67 ms grid from the first frame.
  - High refresh: on a display faster than 60 Hz, step every second vblank once the last 10 frames' work is above 50 % of the period.
  - Hold `timeBeginPeriod(1)` from the first active tick until 500 ms idle.
- **Garbage collection** (spec §5.1.5, as amended in Phase 1): none while the clock is active. Collect 1 s after it goes idle, and at most every 10 s while idle.
- **Animations setting** (spec §5.1.7):
  - `prefs.motion` is one of `"full" | "reduced" | "off"`, default `"full"`.
  - If Windows' "Show animations" (`SPI_GETCLIENTAREAANIMATION`) is off, the effective default is `"off"`.
  - A value the user chose in the app wins. Store `None` for "not chosen".
- **New text** in both languages:
  - `set_motion`: "애니메이션" / "Animations"
  - `motion_full`: "전체" / "Full"
  - `motion_reduced`: "줄이기" / "Reduced"
  - `motion_off`: "끄기" / "Off"
  - `help_motion`: "창이 움직이고 나타나는 효과예요. 줄이기는 움직임 대신 짧게 흐려지고, 끄기는 바로 바뀌어요" / "How windows move and appear. Reduced swaps movement for a short fade; Off changes things at once."

## Review Focus

1. **Clicking again while something moves** (months, settings page, opening or closing the calendar, a later plan for a gliding note) continues from where it is: no jump, no snap back. Pinned in Task 6 (`test_later_plan_retargets_without_jump`) and Task 7 (`test_fast_paging_never_jumps`, `test_settings_reverse_mid_slide`).
2. **A note closed while it glides or fades:** its tweens are dropped, no Tcl errors, and the pad keeps where it got. Pinned in Task 6 (`test_close_mid_glide_keeps_pad_and_stops`).
3. **Minimize, restore and Win+M** still end in the same state with the roll on the clock. Pinned in Task 5 (`test_minimize_restore_round_trip`).
4. **"Off" mode:** every action still finishes. `done` callbacks run, glides land, saves happen. Pinned in Task 10 (`test_off_mode_still_lands_and_saves`).
5. **Batch fallback:** with `BATCH_MOVES = False`, every move still lands. S2 couldn't test a second monitor, so this is the safety net. Pinned in Task 4 (`test_batch_off_uses_geometry`).

---

## File Structure

| Path | Responsibility |
|---|---|
| `StickyNote/app/anim.py` (new) | `FrameClock`, curves, tokens, retarget maths, window batch, idle hook, motion mode |
| `StickyNote/app/winapi.py` | `composition_timing()`, `defer_move()`, `client_animations_enabled()` |
| `StickyNote/app/ui_common.py` | `animate`/`fade`/`stop_animation`/`animating` become clock wrappers; `_keep_timer_fine` removed; duration constants on tokens |
| `StickyNote/app/motion.py` | Glides as clock tweens; `_tick`/`next_delay` removed |
| `StickyNote/app/ui_note.py` | Open/close fade as alpha tweens; fly-to-bin and bin bounce on the clock |
| `StickyNote/app/ui_calendar.py` | Show/hide as pos+alpha tweens; dip on alpha; month paging as a retargeting canvas tween |
| `StickyNote/app/ui_views.py` | Settings page slide as a retargeting place tween; Animations setting row |
| `StickyNote/app/app.py` | Creates the clock; drops `collect_garbage()` from the 30 ms drain; `set_motion()` |
| `StickyNote/app/store.py` | `Prefs.motion: str | None = None` |
| `StickyNote/app/texts.py` | The five new strings |
| `tests/test_anim_*.py`, `tests/test_motion_clock.py`, ... (new) | One file per task |

---

### Task 1: Win32 helpers for timing, batched moves and the Windows animation setting

**Files:**
- Modify: `StickyNote/app/winapi.py` (append)
- Test: `tests/test_winapi_phase2.py`

**Interfaces:**
- Produces:
  - `composition_timing() -> tuple[float, float] | None`: `(last_vblank, period)` in `time.perf_counter()` seconds, or None when DWM fails. Use the packed `DWM_TIMING_INFO` from `tools/spikes/s3_frame_timing.py` (moved here) and `QueryPerformanceFrequency`. `perf_counter` and QPC share an epoch (S3).
  - `defer_move(moves: list[tuple[int, int, int, int | None, int | None]]) -> bool`: each entry is `(hwnd, x, y, w, h)`; `w`/`h` None means `SWP_NOSIZE`. One `BeginDeferWindowPos`/`DeferWindowPos`/`EndDeferWindowPos` with `SWP_NOZORDER | SWP_NOACTIVATE`. Returns False if any call fails.
  - `client_animations_enabled() -> bool`: `SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION = 0x1042, 0, &BOOL, 0)`; True if the call fails.

- [ ] **Step 0: Create the branch.** Run `git switch -c phase2 phase0-1`.
- [ ] **Step 1: Write the failing tests:**

```python
class WinapiPhase2Test(unittest.TestCase):
    def test_composition_timing(self):
        t = winapi.composition_timing()
        self.assertIsNotNone(t)
        vblank, period = t
        self.assertTrue(0.004 < period < 0.05)                         # 20-250 Hz
        self.assertLess(abs(time.perf_counter() - vblank), 1.0)        # a recent vblank, same clock

    def test_defer_move_moves_both(self):
        root = tk.Tk(); a, b = tk.Toplevel(root), tk.Toplevel(root)
        for w in (a, b): w.overrideredirect(True); w.geometry("100x80+100+100")
        root.update()
        ok = winapi.defer_move([(winapi.hwnd_of(a), 300, 200, None, None),
                                (winapi.hwnd_of(b), 420, 200, 150, 90)])
        root.update()
        self.assertTrue(ok)
        self.assertEqual((a.winfo_rootx(), a.winfo_rooty()), (300, 200))
        self.assertEqual((b.winfo_rootx(), b.winfo_width(), b.winfo_height()), (420, 150, 90))
        root.destroy()

    def test_client_animations_flag_is_bool(self):
        self.assertIsInstance(winapi.client_animations_enabled(), bool)
```

- [ ] **Step 2: Run** `... -p test_winapi_phase2.py -v`. Expected: `AttributeError: module 'winapi' has no attribute 'composition_timing'`.
- [ ] **Step 3: Implement** the three functions. Declare the prototypes once at module level.
- [ ] **Step 4: Run** the full suite. Expected: `OK`.
- [ ] **Step 5: Commit.** `git add -A StickyNote/app tests; git commit -m "feat(winapi): DWM timing, batched window moves, Windows animation setting"`.

### Task 2: Curves, tokens and retarget maths (pure)

**Files:**
- Create: `StickyNote/app/anim.py` (first part: pure functions and constants only, no Tk)
- Test: `tests/test_anim_curves.py`

**Interfaces:**
- Produces, in `anim.py`:
  - `FAST, BASE, LONG = 120, 180, 240`.
  - `def exit_ms(ms: int) -> int: return round(ms * 2 / 3)`.
  - `ease_out(s) = 1 - (1 - s) ** 3`, `ease_in(s) = s * s`.
  - `hermite(v0: float, v1: float, m: float, s: float) -> float`, with start slope `m` in value per unit `s` and end slope 0:

```
h00 = 2s³ − 3s² + 1;  h10 = s³ − 2s² + s;  h01 = −2s³ + 3s²
value = h00·v0 + h10·m + h01·v1
```

  - `hermite_slope(v0, v1, m, s) -> float`: d value / d s, using `h00' = 6s² − 6s`, `h10' = 3s² − 4s + 1`, `h01' = −6s² + 6s`.
  - `start_slope(v0: float, v1: float, velocity: float, duration_s: float) -> float`:
    - `normal = 3 * (v1 - v0)` (the ease-out cubic's start slope; with it `hermite` equals ease-out cubic);
    - `m = velocity * duration_s`;
    - `cap = 1.5 * max(abs(normal), 1.0)`;
    - returns `normal` when `velocity == 0`, else `m` clamped to `[-cap, cap]`.

- [ ] **Step 1: Write the failing tests:**

```python
class CurvesTest(unittest.TestCase):
    def test_tokens(self):
        self.assertEqual((anim.FAST, anim.BASE, anim.LONG), (120, 180, 240))
        self.assertEqual((anim.exit_ms(120), anim.exit_ms(180)), (80, 120))
    def test_hermite_with_normal_slope_is_ease_out_cubic(self):
        for s in (0, .1, .25, .5, .8, 1):
            self.assertAlmostEqual(anim.hermite(10, 110, 300, s), 10 + 100 * anim.ease_out(s))
    def test_hermite_ends(self):
        self.assertEqual(anim.hermite(5, 9, 40, 0), 5); self.assertEqual(anim.hermite(5, 9, 40, 1), 9)
        self.assertAlmostEqual(anim.hermite_slope(5, 9, 40, 1), 0)
    def test_reversal_turns_smoothly(self):        # moving +200/s, told to go back to 0 from 100
        m = anim.start_slope(100, 0, velocity=200, duration_s=0.24)
        self.assertGreater(m, 0)                   # keeps going forward briefly
        vals = [anim.hermite(100, 0, m, i / 20) for i in range(21)]
        self.assertGreater(max(vals), 100)         # turns after a small overshoot
        self.assertEqual(vals[-1], 0)
    def test_slope_capped(self):
        self.assertEqual(anim.start_slope(0, 10, velocity=1e6, duration_s=0.24), 1.5 * 30)
    def test_zero_velocity_is_normal(self):
        self.assertEqual(anim.start_slope(0, 10, 0, 0.24), 30)
```

- [ ] **Step 2: Run** `... -p test_anim_curves.py -v`. Expected: `ModuleNotFoundError: No module named 'anim'`.
- [ ] **Step 3: Implement** the functions listed under Interfaces.
- [ ] **Step 4: Run** the full suite. Expected: `OK`.
- [ ] **Step 5: Commit.** `git commit -m "feat(anim): tokens, curves, retarget maths"` (add the new files).

### Task 3: FrameClock — ticks, pacing, progress animations, value tweens, idle hook

**Files:**
- Modify: `StickyNote/app/anim.py`
- Test: `tests/test_anim_clock.py`

**Interfaces:**
- Consumes: Task 1 `winapi.composition_timing`, `winapi.fine_timer`; Task 2 curves.
- Produces:
  - `next_deadline(now: float, vblank: float | None, period: float | None, every: int = 1) -> float`:
    - with DWM timing: the first `vblank + k·period·every` that is ≥ `now + 0.004`, minus 0.002;
    - else: `now` rounded up to the next 1/60 s step from the first frame. Handled by the clock: pass `vblank=t0, period=1/60`.
  - `class FrameClock(root: tk.Misc)`:
    - `request(fn: Callable[[], None]) -> None`: runs `fn` once at the next tick; requesting the same `fn` twice before a tick runs it once.
    - `animate(owner, key: str, ms: int, step: Callable[[float], None], done=None, ease=ease_out) -> None`: a progress animation. `step(ease(t))` runs each tick, and `done()` after `t` reaches 1. Starting the same (owner, key) again replaces it, without calling the old `done`. A `TclError` from `step` drops the animation silently, without `done` (today's behaviour).
    - `tween(owner, channel: str, to, ms: int, *, read, write, ease=ease_out, frm=None, done=None) -> None`: a value tween. `to` is a float or a tuple of floats. `read()` returns the current value; `write(value)` applies it.
      - If (owner, channel) is already tweening, it retargets: it starts from the tween's current value, and each component's start slope is `start_slope(cur, to, velocity, ms/1000)`, where velocity comes from `hermite_slope` / duration.
      - A fresh tween starts from `frm` if given, else from `read()`, with the normal slope.
      - When `ease` is not `ease_out` (an exit), it uses `v0 + (to − v0)·ease(s)` and does no retarget slope.
    - `stop(owner, key: str | None = None) -> None`: stops at the current value without calling `done`. `key=None` stops all of the owner's animations and tweens.
    - `active(owner, key: str) -> bool`.
    - `idle(fn) -> None`: run `fn` once the clock has been idle for ≥ 1.0 s.
    - `busy -> bool`.
    - `fine_timer_held -> bool` (property): True while the clock holds `timeBeginPeriod(1)`.
    - `drop_owner(owner)`: same as `stop(owner)`, for destroy hooks.
  - Module functions:
    - `install(root) -> FrameClock` (one per root; stored on the root);
    - `clock_of(widget) -> FrameClock` (via `widget._root()`).
- **Tick order** (spec §5.1.1):
  1. `now`;
  2. requests;
  3. progress animations and tweens;
  4. window batch flush (Task 4);
  5. `done` callbacks;
  6. schedule the next tick at `next_deadline`.
- **Pacing state:**
  - Read `composition_timing()` at most once per 500 ms; the result is cached.
  - `every` becomes 2 when `period < 0.0155` (faster than about 65 Hz) and the mean work of the last 10 ticks is above `0.5 * period`.
- **Fine timer:** `winapi.fine_timer(True)` on the first active tick, released 500 ms after going idle.
- **Garbage collection:**
  - While active, call `gc.disable()` (today's state: winapi already disables it) and skip any collection.
  - When idle: `idle(collect)` with `collect = winapi.collect_garbage`, re-armed so it runs at most every 10 s while idle.
- **At rest:** no `after` is pending when nothing is active, apart from the fine-timer release and idle jobs.

- [ ] **Step 1: Write the failing tests:**

```python
class DeadlineTest(unittest.TestCase):
    def test_vblank_target(self):
        # vblank at 1.000, period 13.9 ms; now 1.010 -> first vblank >= 1.014 is 1.0278 -> minus 2 ms
        self.assertAlmostEqual(anim.next_deadline(1.010, 1.000, 0.0139), 1.0258, places=4)
    def test_every_second_vblank(self):
        self.assertAlmostEqual(anim.next_deadline(1.010, 1.000, 0.0069, every=2), 1.0256, places=4)
    def test_grid_fallback(self):
        self.assertAlmostEqual(anim.next_deadline(0.020, 0.0, 1 / 60), 1 / 30 - 0.002, places=4)

class ClockTest(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.root.withdraw(); self.clock = anim.install(self.root)
    def tearDown(self):
        self.root.destroy()
    def run_for(self, s):
        end = time.perf_counter() + s
        while time.perf_counter() < end: self.root.update(); time.sleep(0.001)

    def test_animate_runs_to_done(self):
        ks, done = [], []
        self.clock.animate(self.root, "x", 120, ks.append, lambda: done.append(1))
        self.run_for(0.3)
        self.assertEqual(ks[-1], 1.0); self.assertEqual(done, [1])
        self.assertTrue(all(a <= b for a, b in zip(ks, ks[1:])))

    def test_same_key_replaces_without_old_done(self):
        done = []
        self.clock.animate(self.root, "x", 200, lambda k: None, lambda: done.append("old"))
        self.clock.animate(self.root, "x", 50, lambda k: None, lambda: done.append("new"))
        self.run_for(0.3)
        self.assertEqual(done, ["new"])

    def test_request_coalesces(self):
        n = []
        f = lambda: n.append(1)  # noqa: E731
        self.clock.request(f); self.clock.request(f)
        self.run_for(0.05)
        self.assertEqual(n, [1])

    def test_tween_retargets_from_current_value(self):
        box = {"v": 0.0}
        rd, wr = (lambda: box["v"]), (lambda v: box.__setitem__("v", v))
        self.clock.tween(self.root, "c", 100.0, 240, read=rd, write=wr)
        self.run_for(0.08)
        mid = box["v"]
        self.assertTrue(0 < mid < 100)
        seen = []
        self.clock.tween(self.root, "c", 0.0, 240, read=rd, write=lambda v: (seen.append(v), wr(v)))
        self.run_for(0.35)
        self.assertAlmostEqual(seen[0], mid, delta=15)      # continues from where it was, no snap
        self.assertEqual(box["v"], 0.0)

    def test_frames_on_display_period(self):
        t = []
        self.clock.animate(self.root, "p", 600, lambda k: t.append(time.perf_counter()))
        self.run_for(0.7)
        iv = sorted((b - a) * 1000 for a, b in zip(t, t[1:]))
        period = winapi.composition_timing()[1] * 1000
        self.assertLess(abs(iv[len(iv) // 2] - period), 2.0)

    def test_idle_runs_after_quiet(self):
        n = []
        self.clock.idle(lambda: n.append(1))
        self.run_for(0.5); self.assertEqual(n, [])
        self.run_for(0.8); self.assertEqual(n, [1])

    def test_nothing_scheduled_at_rest(self):
        self.clock.animate(self.root, "x", 50, lambda k: None)
        self.run_for(0.8)
        self.assertFalse(self.clock.busy)
```

- [ ] **Step 2: Run** `... -p test_anim_clock.py -v`. Expected: `AttributeError: module 'anim' has no attribute 'next_deadline'`.
- [ ] **Step 3: Implement** as specified. Progress animations and tweens share one table keyed `(id(owner), key)`; tweens use their channel name as the key.
- [ ] **Step 4: Run** the full suite. Expected: `OK`.
- [ ] **Step 5: Commit.** `git commit -am "feat(anim): FrameClock with display pacing, retargeting tweens, idle hook"` (add new files).

### Task 4: Window batch — `pos` and `size` channels

**Files:**
- Modify: `StickyNote/app/anim.py`
- Test: `tests/test_anim_batch.py`

**Interfaces:**
- Consumes: `winapi.defer_move`, `winapi.hwnd_of`.
- Produces:
  - `BATCH_MOVES = True` (module flag).
  - `FrameClock.move(win: tk.Toplevel, x: int, y: int, w: int | None = None, h: int | None = None) -> None`: queues a move for this frame; the last one per window wins. Outside a tick, the next tick flushes it, and requesting a tick is implied.
  - `FrameClock.glide(win, to: tuple[int, int, int, int], ms: int, *, frm=None, done=None, sized: bool = False, write_extra=None, ease=ease_out) -> None`: a tween on channel `"box"` whose `write` rounds the box and calls `move(...)` with the size only when `sized`. `write_extra(box)` runs after each write; callers use it for bookkeeping such as `cal._xy`.
  - `FrameClock.box_now(win) -> tuple[int, int, int, int] | None`: the box last written for `win`.
- **Flush:**
  - With `BATCH_MOVES`, call `winapi.defer_move` for all queued windows.
  - On False, or for a window whose `winfo_rootx/rooty` don't match after `update_idletasks()`, use `win.geometry(...)` for that window. Mark the window so it uses `geometry()` from then on, and log once with `print(..., file=sys.stderr)`.
  - Windows that no longer exist are skipped.

- [ ] **Step 1: Write the failing tests:**

```python
class BatchTest(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.root.withdraw(); self.clock = anim.install(self.root)
        self.a, self.b = tk.Toplevel(self.root), tk.Toplevel(self.root)
        for w in (self.a, self.b): w.overrideredirect(True); w.geometry("120x90+100+100")
        self.root.update()
    def tearDown(self):
        anim.BATCH_MOVES = True; self.root.destroy()
    def frame(self):
        for _ in range(5): self.root.update(); time.sleep(0.01)

    def test_moves_land_in_same_flush(self):
        self.clock.move(self.a, 300, 200); self.clock.move(self.b, 430, 200)
        self.frame()
        self.assertEqual((self.a.winfo_rootx(), self.b.winfo_rootx()), (300, 430))

    def test_glide_lands_and_reports_box(self):
        self.clock.glide(self.a, (500, 300, 620, 390), 120)
        for _ in range(40): self.frame()
        self.assertEqual((self.a.winfo_rootx(), self.a.winfo_rooty()), (500, 300))
        self.assertEqual(self.clock.box_now(self.a), (500, 300, 620, 390))

    def test_batch_off_uses_geometry(self):
        anim.BATCH_MOVES = False
        self.clock.move(self.a, 222, 111, 150, 100)
        self.frame()
        self.assertEqual((self.a.winfo_rootx(), self.a.winfo_rooty(), self.a.winfo_width()), (222, 111, 150))

    def test_destroyed_window_skipped(self):
        self.clock.move(self.b, 300, 300); self.b.destroy()
        self.frame()                                      # no TclError
```

- [ ] **Step 2: Run** `... -p test_anim_batch.py -v`. Expected: `AttributeError: 'FrameClock' object has no attribute 'move'`.
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4: Run** the full suite. Expected: `OK`.
- [ ] **Step 5: Commit.** `git commit -am "feat(anim): per-frame window batch and box glides"` (add new files).

### Task 5: `ui_common.animate`/`fade` become clock wrappers; the app installs the clock

**Files:**
- Modify: `StickyNote/app/ui_common.py:326-420` (`_keep_timer_fine`, `animate`, `stop_animation`, `animating`, `fade`), `StickyNote/app/app.py` (`App.__init__`: `self.clock = anim.install(self.root)` right after the root is made)
- Test: `tests/test_anim_wrappers.py`

**Interfaces:**
- Consumes: Task 3 `clock_of`, `FrameClock.animate/stop/active/tween`.
- Produces:
  - `animate(widget, key, ms, step, done=None, ease=_ease_out)` → `clock_of(widget).animate(widget, key, ms, step, done, ease)`.
  - `stop_animation(widget, key)` → `clock_of(widget).stop(widget, key)`.
  - `animating(widget, key)` → `clock_of(widget).active(widget, key)`.
  - `fade(win, key, start, end, ms, done=None)`:
    - becomes an `"alpha"` tween on `win`, with `read=lambda: _alpha(win)` and `write=lambda v: win.attributes("-alpha", v)`;
    - `frm=start` only when the window has no alpha tween running, so a running fade retargets from where it is;
    - the `key` argument is accepted and ignored, so every fade on a window shares the one alpha owner (spec §5.1.2).
  - `_keep_timer_fine` and `_fine_timer` are removed; the clock holds the timer. Update `tests/test_motion_pacing.py`: drop `test_glide_holds_fine_timer`, which Task 6 replaces.
  - `perf.frame(key, now)` moves from `animate` into the clock's tick (one call per active key per tick).
  - **Fallback:** if the widget's root has no clock (for example a bare `tk.Tk()` in a test), `clock_of` installs one.

- [ ] **Step 1: Write the failing tests:**

```python
class WrapperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1); pump(self.app, timeout=0.5)
        self.nw = next(iter(self.app.windows.values()))
    def tearDown(self):
        close_app(self.app); self.tmp.cleanup()

    def test_app_has_clock(self):
        self.assertIs(anim.clock_of(self.app.root), self.app.clock)

    def test_fades_share_one_alpha_owner(self):
        w = self.nw.win
        fade(w, "a", 1.0, 0.2, 240)
        pump(self.app, timeout=0.08)
        mid = _alpha(w)
        fade(w, "b", 0.2, 1.0, 240)                 # a different key: still the same owner
        pump(self.app, timeout=0.02)
        self.assertAlmostEqual(_alpha(w), mid, delta=0.15)   # no jump to 0.2
        pump(self.app, timeout=0.4)
        self.assertAlmostEqual(_alpha(w), 1.0, places=2)

    def test_minimize_restore_round_trip(self):
        self.app.prefs.minimize_style = "fold"            # (the default "bar" folds instead of minimizing)
        p = self.nw.pad; box = (p.x, p.y, p.width, p.height)
        self.nw.minimize(); pump(self.app, timeout=1.0)
        self.nw.restore(); pump(self.app, timeout=1.0)
        self.assertEqual((p.x, p.y, p.width, p.height), box)
        self.assertEqual(self.nw.win.state(), "normal")
        self.assertFalse(self.nw.rolling)

    def test_no_frame_loops_outside_anim(self):
        import pathlib, re
        app_dir = pathlib.Path(anim.__file__).parent
        for f in app_dir.glob("*.py"):
            if f.name == "anim.py": continue
            src = f.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\.after\(\s*FRAME_MS", src), f.name)
            self.assertNotIn("_keep_timer_fine", src, f.name)
```

- [ ] **Step 2: Run** `... -p test_anim_wrappers.py -v`. Expected: `AttributeError: 'App' object has no attribute 'clock'`; the frame-loop test fails on `ui_note.py` and `motion.py`.
- [ ] **Step 3: Implement** the wrappers and install the clock. `test_no_frame_loops_outside_anim` stays red until Tasks 6 and 7 move `motion.py` and the fly loop. Mark it `@unittest.expectedFailure` in this commit, and remove the marker in Task 7.
- [ ] **Step 4: Run** the full suite. Expected: `OK`, with 1 expected failure.
- [ ] **Step 5: Commit.** `git commit -am "refactor(anim): animate/fade run on the shared FrameClock"` (add new files).

### Task 6: Motion glides on the clock

**Files:**
- Modify: `StickyNote/app/motion.py` (`run`, `_begin`, `_show`, `_tick`, `_land`, `_land_all`, `_end`, `cancel`, `finish`, `busy`, `drives`; remove `next_delay`, `_clock0`, `_job`, `_tick`)
- Modify: `tests/test_motion_pacing.py` (remove `test_next_delay_on_grid`; `next_delay` is gone)
- Test: `tests/test_motion_clock.py`

**Interfaces:**
- Consumes: Task 4 `FrameClock.glide`, `box_now`, `stop`, `active`.
- Produces: the `Motion` public API is unchanged (`run`, `cancel`, `finish`, `busy`, `drives`, `loops`). Inside:
  - Each moving id is a `clock.glide(win, end, ms, frm=start, sized=item.sized, done=lambda: self._landed(pid), write_extra=...)` on that id's window: the note's `win`, or the calendar's `top`.
  - `write_extra` updates `item.now`. For CAL it also sets `cal._xy`.
  - `_Item` keeps `id`, `start`, `end`, `now`, `sized`, `pad`.
  - **A later plan for a gliding id** calls `glide` again, so the clock retargets: no `_Item` replacement jump, and `frm` is not passed.
  - A note whose window has gone is dropped through the destroy hook (`clock.drop_owner(win)` in `NoteWindow.destroy` and `CalendarPopup.destroy`) and landed at `item.now`.
  - `busy()` is True while any Motion item is unlanded.
  - `loops()` returns 1 while busy, else 0, kept for callers.
  - `_end()` runs once, when the last item lands, as today: `settle_links`, then `request_save`, then the plans' `done` callbacks in order.
  - The S1/S4 rules, docked-calendar follow, jump-instead-of-sweep and freezing are unchanged. Only stepping moves to the clock.

- [ ] **Step 1: Write the failing tests:**

```python
class MotionClockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1); pump(self.app, timeout=0.5)
        self.nw = next(iter(self.app.windows.values())); p = self.nw.pad
        self.x, self.y, self.w, self.h = p.x, p.y, p.width, p.height
    def tearDown(self):
        close_app(self.app); self.tmp.cleanup()
    def box(self, dx):
        return {self.nw.pad.id: (self.x + dx, self.y, self.x + dx + self.w, self.y + self.h)}

    def test_glide_lands_and_ends_once(self):
        ends = []
        self.app.motion.run(self.box(200), done=lambda: ends.append(1))
        self.assertTrue(self.app.motion.busy())
        pump(self.app, lambda: not self.app.motion.busy(), timeout=1)
        pump(self.app, timeout=0.1)
        self.assertEqual((self.nw.pad.x, ends), (self.x + 200, [1]))

    def test_later_plan_retargets_without_jump(self):
        xs = []
        self.app.motion.run(self.box(300))
        pump(self.app, timeout=0.08)
        self.app.motion.run(self.box(0))                  # turn back mid-glide
        end = time.perf_counter() + 0.5
        while time.perf_counter() < end:
            self.app.root.update(); xs.append(self.nw.win.winfo_rootx()); time.sleep(0.002)
        steps = [abs(b - a) for a, b in zip(xs, xs[1:])]
        self.assertLess(max(steps), 40)                   # no frame jumps more than 40 px
        self.assertEqual(self.nw.pad.x, self.x)

    def test_cancel_stops_where_it_is(self):
        self.app.motion.run(self.box(300)); pump(self.app, timeout=0.08)
        self.app.motion.cancel([self.nw.pad.id])
        x = self.nw.pad.x; pump(self.app, timeout=0.3)
        self.assertTrue(self.x < x < self.x + 300); self.assertEqual(self.nw.pad.x, x)

    def test_close_mid_glide_keeps_pad_and_stops(self):
        nw2 = self.app.new_window(from_window=self.nw); pump(self.app, timeout=0.6)
        p = nw2.pad; x0 = p.x
        self.app.motion.run({p.id: (p.x + 300, p.y, p.x + 300 + p.width, p.y + p.height)})
        pump(self.app, timeout=0.06)
        self.app.close_window(nw2)
        pump(self.app, lambda: not self.app.motion.busy(), timeout=1)
        self.assertFalse(self.app.motion.busy())
        self.assertTrue(x0 <= p.x <= x0 + 300)

    def test_glide_holds_fine_timer(self):
        self.app.motion.run(self.box(200)); pump(self.app, timeout=0.05)
        self.assertTrue(self.app.clock.fine_timer_held)
```

- [ ] **Step 2: Run** `... -p test_motion_clock.py -v`. Expected: `test_later_plan_retargets_without_jump` FAILs (the old `_Item` replacement jumps), and `test_glide_holds_fine_timer` FAILs (Motion's own loop doesn't run on the clock).
- [ ] **Step 3: Implement** as specified. Keep `_resize_calendar` and freeze/thaw calls exactly where `_begin`/`_land` call them today.
- [ ] **Step 4: Run** the full suite, including all Phase 1 tests. Expected: `OK` (1 expected failure from Task 5).
- [ ] **Step 5: Commit.** `git commit -am "refactor(motion): glides are FrameClock tweens; later plans retarget"` (add new files).

### Task 7: Retargeting channels for window fades, calendar slide, month paging and the settings page; fly-to-bin on the clock

**Files:**
- Modify: `StickyNote/app/ui_note.py:383` (open fade), `:1008` (close fade), `:743-790` (`_fly_to_bin`, `_bin_bounce`)
- Modify: `StickyNote/app/ui_calendar.py:279` (hover), `:285-300` (`_slide`), `:948-970` (dip), `:1121-1158` (`_page_to`)
- Modify: `StickyNote/app/ui_views.py:1029-1055` (`SettingsView.open/close`)
- Test: `tests/test_anim_channels.py`

**Interfaces:**
- Consumes: `FrameClock.tween`, `glide`, `animate`; the `fade` wrapper from Task 5.

| Site | Becomes |
|---|---|
| Note open fade (`:383`) | `fade(win, "fade", 0.0, pad.alpha, OPEN_FADE_MS)` |
| Note close fade (`:1008`) | An alpha tween to 0 with `ease=anim.ease_in`, `ms=CLOSE_FADE_MS`. Its calendar gets the same tween on its `top`. |
| Calendar `_slide` | `clock.glide(top, box, CAL_SHOW_MS)` plus `fade(top, …, target_alpha)` when opening. When closing: `glide(…, exit_ms(CAL_SHOW_MS), ease=anim.ease_in)` plus fade to 0. The slide offset uses the docking side's axis (left/right: x; above/below: y), from `self._spot`'s side. |
| Calendar dip | `fade` out (`VIEW_DIP_MS`), then switch, then `apply_alpha(animated=True)`. `apply_alpha` no longer needs a `"dip"` guard, because alpha has one owner. |
| Month paging | A `canvas:paging` tween: `read` returns the paging tag's current x offset; `write` calls `canvas.move("paging", dx_since_last, 0)`. A second click during paging draws the next month to the side and retargets the same tween to the new end offset. **No end-of-paging redraw:** at the end, `delete("outgoing")` and `dtag("paging")`. The `marked_days`/peek guards from spec §5.4.1 are Phase 5. |
| Settings page | A `place:settings` tween over `relx` of both pages (one value `u` in [0, 1]; list `relx = -SETTING_SLIDE_BACK·u`, detail `relx = 1 − u`). Close tweens `u` to 0 from where it is. |
| Fly to bin | `clock.animate(cv, "fly", DELETE_FLY_MS, step, done)`, replacing the `cv.after(FRAME_MS, frame)` loop. `_bin_bounce` becomes `clock.animate(icon, "bounce", FAST, step)` with a sine bump. |

- [ ] **Step 1: Write the failing tests:**

```python
class ChannelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1); pump(self.app, timeout=0.5)
        self.nw = next(iter(self.app.windows.values()))
    def tearDown(self):
        close_app(self.app); self.tmp.cleanup()

    def test_fast_paging_never_jumps(self):
        self.nw.toggle_calendar(); pump(self.app, timeout=0.5)
        cal = self.nw.calendar; xs = []
        def watch():
            ids = cal.grid.find_withtag("paging")
            if ids: xs.append(cal.grid.coords(ids[0])[0])
        cal.next_month(); pump(self.app, timeout=0.06)
        cal.next_month()                               # second click mid-slide
        end = time.perf_counter() + 0.6
        while time.perf_counter() < end:
            self.app.root.update(); watch(); time.sleep(0.003)
        steps = [abs(b - a) for a, b in zip(xs, xs[1:])]
        self.assertLess(max(steps or [0]), cal.grid.winfo_width() * 0.25)
        self.assertEqual(cal.grid.find_withtag("paging"), ())

    def test_settings_reverse_mid_slide(self):
        self.nw.toggle_settings(); pump(self.app, timeout=0.3)
        sv = self.nw.settings_view; key = next(iter(sv.list_rows))
        sv.open(key); pump(self.app, timeout=0.08)
        x_mid = float(sv.detail_area.canvas.place_info()["relx"])
        sv.close(); pump(self.app, timeout=0.02)
        x_now = float(sv.detail_area.canvas.place_info()["relx"])
        self.assertLess(abs(x_now - x_mid), 0.2)       # turned back from where it was, no snap to 0
        pump(self.app, timeout=0.4)
        self.assertEqual(sv.opened, None)

    def test_calendar_open_close_fast_ends_closed(self):
        self.nw.toggle_calendar(); pump(self.app, timeout=0.05)
        self.nw.toggle_calendar(); pump(self.app, timeout=0.5)
        self.assertIsNone(self.nw.calendar)
```

- [ ] **Step 2: Run** `... -p test_anim_channels.py -v`. Expected: `test_fast_paging_never_jumps` and `test_settings_reverse_mid_slide` FAIL. `test_calendar_open_close_fast_ends_closed` PASSes; it guards behaviour.
- [ ] **Step 3: Implement** as listed under Interfaces. Remove the `@unittest.expectedFailure` marker from Task 5's frame-loop test.
- [ ] **Step 4: Run** the full suite. Expected: `OK` with no expected failures.
- [ ] **Step 5: Commit.** `git commit -am "feat(anim): retargeting fades, calendar slide, month paging and settings page"` (add new files).

### Task 8: Motion tokens

**Files:**
- Modify: `StickyNote/app/ui_common.py:95-126` (constants), `ui_views.py` (`SETTING_SLIDE_MS`), `ui_note.py:37` (`STICKER_FADE_MS`), `ui_common.py` (`SCROLL_FADE_MS`), `ui_calendar.py:1158` (drop `ease=_ease_out_sine`); remove `_ease_out_sine` if it has no other users
- Test: `tests/test_tokens.py`

**Interfaces:**
- Produces: these values, imported from `anim` where noted (spec §5.1.6):

| Constant | New value |
|---|---|
| TIP_FADE_MS, MENU_FADE_MS, HOVER_FADE_MS, STICKER_FADE_MS, OPEN_FADE_MS, CHIP_SETTLE_MS, VIEW_DIP_MS | `FAST` (120) |
| CLOSE_FADE_MS | `exit_ms(FAST)` (80) |
| CAL_SHOW_MS, ROLL_MS, DOCK_SLIDE_MS, TOAST_RISE_MS, HINT_DROP_MS, PEEK_DROP_MS, PICTURE_FADE_MS, DONE_FADE_MS | `BASE` (180) |
| GLIDE_MS, NEW_SLIDE_MS, MONTH_SLIDE_MS, SETTING_SLIDE_MS, SCROLL_FADE_MS, DELETE_FLY_MS | `LONG` (240) |
| FLASH_MS | 400 |

  `FRAME_MS` stays, but only for `PEEK`/poll uses; no frame loop reads it after Task 7.

- [ ] **Step 1: Write the failing test:**

```python
class TokenTest(unittest.TestCase):
    def test_durations_on_tokens(self):
        import ui_common as u, ui_views as v, ui_note as n
        fast = ("TIP_FADE_MS", "MENU_FADE_MS", "HOVER_FADE_MS", "OPEN_FADE_MS", "CHIP_SETTLE_MS", "VIEW_DIP_MS")
        base = ("CAL_SHOW_MS", "ROLL_MS", "DOCK_SLIDE_MS", "TOAST_RISE_MS", "HINT_DROP_MS", "PEEK_DROP_MS",
                "PICTURE_FADE_MS", "DONE_FADE_MS")
        long_ = ("GLIDE_MS", "NEW_SLIDE_MS", "MONTH_SLIDE_MS", "SCROLL_FADE_MS", "DELETE_FLY_MS")
        self.assertEqual({getattr(u, k) for k in fast} | {n.STICKER_FADE_MS}, {120})
        self.assertEqual({getattr(u, k) for k in base}, {180})
        self.assertEqual({getattr(u, k) for k in long_} | {v.SETTING_SLIDE_MS}, {240})
        self.assertEqual((u.CLOSE_FADE_MS, u.FLASH_MS), (80, 400))
        self.assertFalse(hasattr(u, "_ease_out_sine"))
```

- [ ] **Step 2: Run** `... -p test_tokens.py -v`. Expected: FAIL (for example `{150, 100, 140, 90, 120} != {120}`).
- [ ] **Step 3: Implement.** Set the constants from `anim.FAST/BASE/LONG/exit_ms`.
- [ ] **Step 4: Run** the full suite. Expected: `OK`.
- [ ] **Step 5: Commit.** `git commit -am "feat(anim): three motion tokens replace sixteen durations"` (add new files).

### Task 9: Garbage collection moves to the clock's idle hook

**Files:**
- Modify: `StickyNote/app/app.py:2747-2786` (`_drain_syscommands`: remove `winapi.collect_garbage()`), `anim.py` (idle collection is already specified in Task 3; this task wires and proves it)
- Test: `tests/test_gc_idle.py`

**Interfaces:**
- Consumes: `FrameClock.idle`.
- Produces:
  - `_drain_syscommands` no longer collects.
  - `FrameClock` runs `winapi.collect_garbage()` 1 s after going idle, and at most every 10 s while idle.
  - It never collects in a tick.

- [ ] **Step 1: Write the failing tests:**

```python
class GcIdleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
    def tearDown(self):
        close_app(self.app); self.tmp.cleanup()

    def test_drain_does_not_collect(self):
        with patched(winapi, "collect_garbage", Spy()) as spy:
            self.app._drain_syscommands()
        self.assertEqual(spy.call_count, 0)

    def test_collects_when_idle_not_while_animating(self):
        with patched(winapi, "collect_garbage", Spy()) as spy:
            nw = next(iter(self.app.windows.values())); p = nw.pad
            self.app.motion.run({p.id: (p.x + 100, p.y, p.x + 100 + p.width, p.y + p.height)})
            pump(self.app, timeout=0.2)
            self.assertEqual(spy.call_count, 0)
            pump(self.app, timeout=1.5)
            self.assertGreaterEqual(spy.call_count, 1)
```

- [ ] **Step 2: Run** `... -p test_gc_idle.py -v`. Expected: `test_drain_does_not_collect` FAILs (count 1).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full suite. Expected: `OK`.
- [ ] **Step 5: Commit.** `git commit -am "perf: collect garbage only when the frame clock is idle"` (add new files).

### Task 10: Animations setting (Full / Reduced / Off)

**Files:**
- Modify: `StickyNote/app/store.py` (`Prefs.motion: str | None = None`, validated to `None | "full" | "reduced" | "off"` in the same place as `minimize_style`)
- Modify: `StickyNote/app/anim.py` (`FrameClock.mode: str`)
- Modify: `StickyNote/app/app.py` (`set_motion(mode: str | None)`; at start and in the existing 1 s screen poll (`_poll_screens`), since Phase 6 moves this to `WM_SETTINGCHANGE`: `clock.mode = prefs.motion or ("full" if winapi.client_animations_enabled() else "off")`)
- Modify: `StickyNote/app/motion.py` (reduced: cross-fade)
- Modify: `StickyNote/app/ui_views.py` (`SETTING_GROUPS`: add `"set_motion"` to `grp_place` after `"set_minimize"`; `SETTING_HELP["set_motion"] = "help_motion"`; a page with three `FlatButton`s like `set_minimize`; a value lambda `tr(f"motion_{mode}")`; `sync()` marks the chosen one)
- Modify: `StickyNote/app/texts.py` (the five strings in Global Constraints)
- Test: `tests/test_motion_setting.py`

**Interfaces:**
- Produces:
  - `FrameClock.mode` is `"full" | "reduced" | "off"`.
  - `"off"`: every `animate` and `tween` completes in its first tick. Steps run once with 1.0, then `done`.
  - `"reduced"`:
    - `tween`/`glide` on any channel except `"alpha"`, and `animate` calls with `ms > FAST`, complete in their first tick;
    - alpha tweens keep `FAST`;
    - `Motion.run` cross-fades each moving window: alpha to 0 over 60 ms, jump to the end box, alpha back to `pad.alpha` (or `cal._target_alpha()`) over 60 ms. Glide `done`/end steps run after the fade-in.
  - `App.set_motion(mode)`: stores it, recomputes `clock.mode`, calls `request_save()`, and syncs open Settings pages (the same loop as `set_minimize_style`).
  - The Settings value text shows the effective mode's name. Nothing is marked as chosen when `prefs.motion is None`.

- [ ] **Step 1: Write the failing tests:**

```python
class MotionSettingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1); pump(self.app, timeout=0.5)
        self.nw = next(iter(self.app.windows.values()))
    def tearDown(self):
        close_app(self.app); self.tmp.cleanup()
    def move(self, dx=200):
        p = self.nw.pad
        self.app.motion.run({p.id: (p.x + dx, p.y, p.x + dx + p.width, p.y + p.height)})

    def test_default_follows_windows(self):
        self.assertIsNone(self.app.prefs.motion)
        self.assertEqual(self.app.clock.mode, "full" if winapi.client_animations_enabled() else "off")

    def test_off_mode_still_lands_and_saves(self):
        self.app.set_motion("off"); x = self.nw.pad.x; ends = []
        p = self.nw.pad
        self.app.motion.run({p.id: (x + 150, p.y, x + 150 + p.width, p.y + p.height)}, done=lambda: ends.append(1))
        pump(self.app, timeout=0.1)
        self.assertEqual((self.nw.pad.x, ends), (x + 150, [1]))
        self.app.save_now()
        self.assertIn('"motion": "off"', (Path(self.tmp.name) / "notes.json").read_text(encoding="utf-8"))

    def test_reduced_crossfades_instead_of_gliding(self):
        self.app.set_motion("reduced"); x0 = self.nw.win.winfo_rootx(); xs = []
        self.move(300)
        end = time.perf_counter() + 0.4
        while time.perf_counter() < end:
            self.app.root.update(); xs.append(self.nw.win.winfo_rootx()); time.sleep(0.003)
        self.assertEqual(set(xs) - {x0, x0 + 300}, set())   # never in between
        self.assertEqual(self.nw.pad.x, x0 + 300)

    def test_settings_row_lists_three_modes(self):
        self.assertIn("set_motion", dict(ui_views.SETTING_GROUPS)["grp_place"])
        self.assertEqual(texts.tr("motion_reduced"), "줄이기" if texts.language() == "ko" else "Reduced")
```

- [ ] **Step 2: Run** `... -p test_motion_setting.py -v`. Expected: `AttributeError: 'App' object has no attribute 'set_motion'` (and similar).
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4: Run** the full suite. Expected: `OK`.
- [ ] **Step 5: Commit.** `git commit -am "feat: Animations setting (Full / Reduced / Off), following Windows by default"` (add new files).

### Task 11: Phase 2 measurement and check-off

**Files:**
- Create: `docs/perf/phase2.json` (generated)
- Modify: `docs/2026-11-25-redesign-design.md` (add a "Phase 2 results" section)

- [ ] **Step 1: Run** `$env:STICKY_PERF='1'; .\StickyNote\runtime\python.exe tools\baseline.py phase2`. Expected: it exits 0 with 8 summary lines. Frame keys now come from the clock; glides show up as `box`.
- [ ] **Step 2: Check the spec §7 done criterion.** In `tidy`, `group_drag` and `resize`, glide frame p95 is within ±2 ms of the display period, which is `winapi.composition_timing()[1]`: 13.9 ms on this machine. Write the period into the results.
- [ ] **Step 3: Check that the frame loops are gone.** `test_no_frame_loops_outside_anim` passes in the suite.
- [ ] **Step 4:** Add a "Phase 2 results" table to the spec (baseline / Phase 1 / Phase 2 per scenario), including fade/flash maximum frame gaps. Re-run `tools/spikes/s2_defer_window_pos.py` and record its verdict again.
- [ ] **Step 5: Run** the full suite. Expected: `OK`.
- [ ] **Step 6: Commit.** `git add docs; git commit -m "perf: phase 2 results"`.
