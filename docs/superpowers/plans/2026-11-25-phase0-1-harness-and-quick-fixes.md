# Phase 0–1: Perf Harness, Spikes and Quick Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure today's app (frame timing, handler cost, memory, handles) and answer the three platform questions the redesign depends on. Then ship the Phase 1 fixes, which change nothing the user can see: closed notes are freed, wasted work is removed, and glide frames are paced.

**Architecture:**
- A debug-only `perf.py` records frame timestamps, handler spans and process memory/handles when `STICKY_PERF=1`.
- A baseline script drives the app on a throwaway folder and writes the numbers to JSON.
- Three spike scripts test DWM corners/shadow, `DeferWindowPos` and DWM frame timing on real Tk windows.
- Phase 1 is a set of small, independent fixes in existing modules, each pinned by a `unittest` test that runs a real `App` on a temp folder with fake screens.

**Tech Stack:** Python 3.15 (bundled `StickyNote/runtime`), Tkinter, Pillow 12.3, ctypes/Win32, stdlib `unittest`.

**Spec:** `docs/2026-11-25-redesign-design.md` (Phases 0 and 1 in §7; spikes in §8). The diagnosis is in `docs/2026-11-25-performance-redesign-report.md`.

## Global Constraints

- **Runtime:** use only the bundled runtime and its stdlib, plus Pillow. Add no third-party packages (no pytest). Run everything with `.\StickyNote\runtime\python.exe`.
- **Module path:** the runtime's `python315._pth` already puts `..\app` on `sys.path`. Import app modules by bare name (`import winapi`, `from app import App`).
- **Data safety:** never touch `%APPDATA%\StickyNote`. Tests and scripts use `tempfile.TemporaryDirectory()` or a scratch folder.
- **Phase 1 changes no visible behaviour.** The anti-goals in spec §2 apply. Every layout rule (S1/S4, C1/C2, L2-L5, M2, N2, N5, P1-P6) gives the same results.
- **Text:** all user-visible text stays as it is in both languages (`texts.py` is not edited in this plan).
- **Working directory** for every command is the project root `C:\Users\KMH\Desktop\projects\StickyNote`.
- **Tests:** `.\StickyNote\runtime\python.exe -m unittest discover -s tests -v`. Tests open real Tk windows on the desktop; that is expected.

## Review Focus

1. **Closing the last note still saves and quits** after the release-on-close changes. Pinned in Task 7 (`test_last_window_close_quits_and_saves`).
2. **Switching language** rebuilds every window, and the old windows must be freed without breaking the new ones. Pinned in Task 7 (`test_set_language_frees_old_windows`).
3. **A title typed and then the note closed straight away** keeps the title, even with the new debounce. Pinned in Task 11 (`test_header_typed_then_closed_is_saved`).
4. **Win+M (several minimizes at once)** is still processed after the drain early-out: every note minimizes, without animation. Pinned in Task 10 (`test_multi_minimize_still_handled`).
5. **Snapshotting a window that isn't shown** (withdrawn or minimized) returns `None` and leaks no GDI handles. Pinned in Task 9 (`test_snapshot_withdrawn_returns_none_without_leak`).

---

## File Structure

| Path | Responsibility |
|---|---|
| `.gitignore` (new) | Keep the runtime, caches, scratch data and brainstorm files out of git |
| `tests/_support.py` (new) | `make_app`, `pump`, `close_app`: a real `App` on a temp folder with one fake screen |
| `tests/test_*.py` (new) | One file per task |
| `StickyNote/app/perf.py` (new) | Debug-only measurements: frame intervals, spans, memory/handles, live-window tracking |
| `StickyNote/app/winapi.py` | Add `process_memory()` and `gui_handles()`; fix `snapshot()` |
| `tools/baseline.py` (new) | Scenario driver that writes `docs/perf/<label>.json` |
| `tools/spikes/s1_dwm_corners.py`, `s2_defer_window_pos.py`, `s3_frame_timing.py` (new) | Platform questions S1–S3 |
| `docs/perf/` (new) | Baseline and Phase 1 result JSON plus spike screenshots |
| `StickyNote/app/ui_note.py` | Release on close, header debounce, preedit font cache, folded-title fit |
| `StickyNote/app/ui_views.py` | `ListView.release()` |
| `StickyNote/app/ui_picture.py` | `ImageViewer.release()` |
| `StickyNote/app/ui_calendar.py` | Drop the unused `marked_days()` call in `draw()` |
| `StickyNote/app/ui_common.py` | `fit_text()` helper; perf hook in `animate()` |
| `StickyNote/app/app.py` | Drain early-out, `gc.freeze()` after start, `last_note` cleared on close |
| `StickyNote/app/motion.py` | Hold the fine timer and pace frames on a grid |

---

## Phase 0

### Task 1: Git repository and test scaffolding

**Files:**
- Create: `.gitignore`, `tests/_support.py`, `tests/test_smoke.py`

**Interfaces:**
- Produces:
  - `make_app(folder: Path) -> App`: calls `winapi.set_dpi_aware()` once at import, then `App(folder, screens=[SCREEN])` with `SCREEN = Screen(monitor=(0, 0, 1920, 1080), work=(0, 0, 1920, 1040))`.
  - `pump(app: App, until: Callable[[], bool] = lambda: False, timeout: float = 2.0) -> bool`: runs `app.root.update()` every 10 ms until `until()` is true (returns True) or the timeout passes (returns False); stops early if the root is gone.
  - `close_app(app: App) -> None`: `app.quit()` if not `app.closed`, swallowing `tk.TclError`.

- [ ] **Step 1:** Run `git init`. Write `.gitignore` with:
  - `StickyNote/runtime/`
  - `__pycache__/`
  - `*.pyc`
  - `StickyNote/preview-data/`
  - `.superpowers/`
  - `docs/perf/*.png`
- [ ] **Step 2: Write the smoke test** `tests/test_smoke.py`:

```python
class SmokeTest(unittest.TestCase):
    def test_app_starts_with_one_window_and_quits(self):
        with tempfile.TemporaryDirectory() as d:
            app = make_app(Path(d))
            try:
                self.assertTrue(pump(app, lambda: len(app.windows) == 1))
                self.assertTrue((Path(d) / "notes.json").exists())
            finally:
                close_app(app)
            self.assertTrue(app.closed)
```

- [ ] **Step 3: Run it** (it fails: `_support` doesn't exist yet). Run: `.\StickyNote\runtime\python.exe -m unittest discover -s tests -p test_smoke.py -v`. Expected: `ModuleNotFoundError: No module named '_support'`.
- [ ] **Step 4: Implement `tests/_support.py`** with the three functions above.
- [ ] **Step 5: Run it again.** Expected: `OK`, 1 test.
- [ ] **Step 6: Commit.** `git add .gitignore tests StickyNote docs` then `git commit -m "chore: git repo, test scaffolding"`.

### Task 2: `perf.py`, the debug-only measurement module

**Files:**
- Create: `StickyNote/app/perf.py`, `tests/test_perf.py`
- Modify: `StickyNote/app/winapi.py` (append two functions), `StickyNote/app/ui_common.py:350-378` (`animate`), `StickyNote/app/motion.py:321` (`_tick`), `StickyNote/app/ui_note.py:132` (`NoteWindow.__init__`), `ui_note.py:1607` (`_on_body_modified`), `ui_note.py:2152` (`_drag_move`), `ui_note.py:2207` (`_resize_move`), `ui_calendar.py:1621` (`draw`), `ui_views.py:123` (`ListView.refresh`), `app.py:2514` (`save_now`)

**Interfaces:**
- Produces:
  - In `winapi.py`:
    - `process_memory() -> int`: private bytes, from `GetProcessMemoryInfo` with `PROCESS_MEMORY_COUNTERS_EX.PrivateUsage`.
    - `gui_handles() -> tuple[int, int]`: GDI and USER handle counts, from `GetGuiResources(GetCurrentProcess(), 0 / 1)`.
  - In `perf.py`:
    - `ENABLED: bool`, true when `os.environ.get("STICKY_PERF") == "1"`.
    - `perf = Perf()`.
    - `Perf.frame(key: str, t: float) -> None`.
    - `Perf.span(name: str)`: a context manager that records elapsed ms.
    - `Perf.track_window(obj) -> None`: keeps a `weakref`.
    - `Perf.live_windows() -> int`.
    - `Perf.sample() -> dict`, with keys `private_bytes`, `gdi`, `user`, `live_windows`.
    - `Perf.report() -> dict`:
      - `{"frames": {key: {"n", "p50", "p95", "max"}}, "spans": {name: {"n", "p50", "p95", "max"}}}`.
      - Frame stats are over *intervals* in ms between consecutive `frame()` calls with the same key.
      - A gap above 250 ms starts a new run and is not counted.
    - `Perf.reset() -> None`.
- Hook rule: each hook is `if perf.ENABLED: ...`, so the disabled cost is one attribute read.

| Hook | Records |
|---|---|
| `animate()` frame | `perf.frame(key, now)` |
| `Motion._tick` | `perf.frame("motion", now)` |
| `NoteWindow.__init__` | `perf.track_window(self)` |
| `_on_body_modified` | `with perf.span("body_modified")` |
| `_drag_move` | `with perf.span("drag_move")` |
| `_resize_move` | `with perf.span("resize_move")` |
| `CalendarPopup.draw` | `with perf.span("calendar_draw")` |
| `ListView.refresh` | `with perf.span("list_refresh")` |
| `App.save_now` | `with perf.span("save")` |

- [ ] **Step 1: Write the failing tests** `tests/test_perf.py`:

```python
class PerfTest(unittest.TestCase):
    def test_frame_intervals(self):
        p = perf.Perf()
        for t in (0.000, 0.016, 0.032, 0.063, 1.000, 1.016):   # 1.000 starts a new run (gap > 250 ms)
            p.frame("glide", t)
        f = p.report()["frames"]["glide"]
        self.assertEqual(f["n"], 4)
        self.assertAlmostEqual(f["max"], 31.0, places=3)
        self.assertAlmostEqual(f["p50"], 16.0, places=3)

    def test_span_records_ms(self):
        p = perf.Perf()
        with p.span("save"):
            time.sleep(0.02)
        s = p.report()["spans"]["save"]
        self.assertEqual(s["n"], 1)
        self.assertGreaterEqual(s["max"], 15.0)

    def test_sample_reads_process(self):
        s = perf.Perf().sample()
        self.assertGreater(s["private_bytes"], 1_000_000)
        self.assertGreaterEqual(s["gdi"], 0)
        self.assertGreaterEqual(s["user"], 0)

    def test_live_windows_drop_when_collected(self):
        class W: pass
        p, w = perf.Perf(), W()
        p.track_window(w)
        self.assertEqual(p.live_windows(), 1)
        del w; gc.collect()
        self.assertEqual(p.live_windows(), 0)
```

- [ ] **Step 2: Run** `.\StickyNote\runtime\python.exe -m unittest discover -s tests -p test_perf.py -v`. Expected: `ModuleNotFoundError: No module named 'perf'`.
- [ ] **Step 3:** Implement `winapi.process_memory`, `winapi.gui_handles` and `perf.py` as specified. Percentiles use nearest rank on the sorted list.
- [ ] **Step 4:** Add the hooks listed above.
- [ ] **Step 5: Run** `.\StickyNote\runtime\python.exe -m unittest discover -s tests -v`. Expected: `OK` (smoke + perf).
- [ ] **Step 6: Commit.** `git commit -am "feat(perf): debug-only frame/span/memory measurements"` (and `git add` the new files).

### Task 3: Baseline scenario driver and the recorded baseline

**Files:**
- Create: `tools/baseline.py`, `docs/perf/baseline.json` (generated)

**Interfaces:**
- Consumes: `perf.perf` (Task 2), `make_app`/`pump` style setup (re-implemented in the script; it must not import from `tests/`).
- Produces: `python tools/baseline.py <label>` writes `docs/perf/<label>.json`. The file has one entry per scenario: `{"perf": Perf.report(), "before": sample, "after": sample, "wall_ms": float}`.
- **Run with:** `$env:STICKY_PERF='1'; .\StickyNote\runtime\python.exe tools\baseline.py baseline`.
- **Setup:** real screens (no fake screens), a scratch folder under `%TEMP%`.
- **Fake events** are `types.SimpleNamespace(x_root=..., y_root=..., x=0, y=0)`, passed straight to the handlers.
- **Scenarios, in order** (wait for idle between them by pumping until `not app.motion.busy()` and 300 ms have passed):

| Scenario | What it does |
|---|---|
| `open_20` | `app.new_window(from_window=last)` 19 times |
| `tidy` | `app.tidy(first, "keep")` |
| `group_drag` | After `tidy`, call `_drag_start` on the first note's `date_label` with a fake event at its centre, 60 `_drag_move` events 5 px apart over 1 s (`root.after` 16 ms each), then `_drag_end`. Record `len(app.group_windows(first.pad.id))` in the JSON (the drag moves whatever group the note has after `tidy`). |
| `resize` | `_resize_start` on the first note's grip, 60 `_resize_move` events growing by 3 px each, then `_drag_end` |
| `calendar_paging` | `first.toggle_calendar()`, pump 500 ms, then `cal.next_month()` 6 times, 350 ms apart |
| `typing` | Insert 300 characters into `first.body`, one `insert` + `event_generate("<<Modified>>")` per character, every 16 ms |
| `list_500` | `app.add_note(Note(header=f"메모 {i}", body="본문 " * 30))` × 500, then `first.show_list()`, then call `first.list_view._build_more()` until it returns False |
| `open_close_50` | Sample memory. Then 50 times: `nw = app.new_window(from_window=first)`, pump 200 ms, `app.close_window(nw)`, pump until it's out of `app.windows` plus 300 ms. Then `gc.collect()` and sample again. Record `perf.live_windows()`. |

- [ ] **Step 1:** Write `tools/baseline.py` with the scenarios above. Call `perf.perf.reset()` at the start of each scenario. When done, write the JSON and print a one-line-per-scenario summary: frames p95/max per key, spans p95, Δprivate MB, live windows.
- [ ] **Step 2: Run it.** Expected: it exits 0, `docs/perf/baseline.json` exists, and the summary has 8 scenario lines.
- [ ] **Step 3:** Add a "Baseline (Phase 0)" section to the end of `docs/2026-11-25-redesign-design.md` with the printed summary table, as recorded.
- [ ] **Step 4: Commit.** `git add tools/baseline.py docs; git commit -m "perf: baseline driver and recorded baseline"`.

### Task 4: Spike S1, DWM corners and shadow on borderless layered windows

**Files:**
- Create: `tools/spikes/s1_dwm_corners.py`; screenshots under `docs/perf/s1-*.png`

**Interfaces:**
- Produces: a verdict line written into spec §8 row S1, from this matrix:

| Window | `-alpha` 1.0 | `-alpha` 0.92 |
|---|---|---|
| Plain `overrideredirect` | ? | ? |
| With `DwmExtendFrameIntoClientArea` 1 px margins | ? | ? |
| With the `CS_DROPSHADOW` class style | ? | ? |

  Each cell answers: rounded? shadow?
- **Method:**
  - One `Toplevel` per cell: `overrideredirect(True)`, 220×160, a yellow `#FFF4A3` fill, placed on a mid-grey `Toplevel` backdrop (`#5B6676`) that is 40 px larger.
  - Call `DwmSetWindowAttribute(hwnd, 33, byref(c_int(2)), 4)` (`DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND`) on the frame hwnd (`winapi.hwnd_of`).
  - After 500 ms, capture the backdrop region with `ImageGrab.grab(bbox)` (the script's own windows only).
  - **Rounded:** the pixel 1 px in from the corner equals the backdrop colour.
  - **Shadow:** the pixel 6 px outside the bottom edge is darker than the backdrop by more than 8 in luminance.

- [ ] **Step 1:** Write the script. It prints the matrix and saves one PNG per cell to `docs/perf/s1-<row>-<alpha>.png`.
- [ ] **Step 2: Run** `.\StickyNote\runtime\python.exe tools\spikes\s1_dwm_corners.py`. Expected: a 3×2 matrix of `rounded=…/shadow=…`, and 6 PNGs.
- [ ] **Step 3:** Write the verdict into spec §8 S1. Name the method that worked, or "fallback applies (policy in §8)".
- [ ] **Step 4: Commit.** `git add tools/spikes/s1_dwm_corners.py docs/2026-11-25-redesign-design.md; git commit -m "spike(S1): DWM corners/shadow on layered popups"`.

### Task 5: Spike S2, `DeferWindowPos` with Tk toplevels

**Files:**
- Create: `tools/spikes/s2_defer_window_pos.py`

**Interfaces:**
- Produces: a verdict in spec §8 S2. Either "batch OK" or "keep `geometry()`", with the reason.
- **Method:**
  1. Create 4 `overrideredirect` toplevels, each with a `<Configure>` counter.
  2. Move all 4 by (+37, +23) with one `BeginDeferWindowPos(4)` / `DeferWindowPos(…, SWP_NOZORDER|SWP_NOACTIVATE|SWP_NOSIZE)` / `EndDeferWindowPos` call on their frame hwnds.
  3. Run `update_idletasks()` and `update()`.
  4. Assert for each: `winfo_rootx/rooty` equals the new position, and its `<Configure>` fired at least once.
  5. Repeat 120 times at 16 ms (a 2 s glide) and check none drift.
  6. If there's more than one monitor, repeat with one window moved across the monitor boundary.

- [ ] **Step 1:** Write the script. It prints `PASS`/`FAIL` per check, and the max drift in px.
- [ ] **Step 2: Run** `.\StickyNote\runtime\python.exe tools\spikes\s2_defer_window_pos.py`. Expected: a PASS/FAIL line per check, and a final verdict line.
- [ ] **Step 3:** Write the verdict into spec §8 S2.
- [ ] **Step 4: Commit.** `git commit -m "spike(S2): DeferWindowPos with Tk"` (and `git add` the script).

### Task 6: Spike S3, DWM frame timing and `after()` accuracy

**Files:**
- Create: `tools/spikes/s3_frame_timing.py`

**Interfaces:**
- Produces: a verdict in spec §8 S3. Record:
  - whether `DwmGetCompositionTimingInfo(None, &DWM_TIMING_INFO)` succeeds (with `cbSize` set);
  - `qpcRefreshPeriod` in ms;
  - the p50/p95/max lateness in ms of 300 `after()` callbacks aimed at "next vblank − 2 ms", with `timeBeginPeriod(1)` held (`winapi.fine_timer(True)`).
- **The target time** for each callback comes from `qpcVBlank` plus a multiple of the period, converted from QPC to `perf_counter` time with `QueryPerformanceFrequency`.

- [ ] **Step 1:** Write the script. It prints the period, the success flag and the lateness stats. It also runs the same 300 callbacks on a plain 16.67 ms grid from `t0` for comparison.
- [ ] **Step 2: Run** `.\StickyNote\runtime\python.exe tools\spikes\s3_frame_timing.py`. Expected: both stat lines printed.
- [ ] **Step 3:** Write the verdict into spec §8 S3. The target is p95 lateness ≤ 2 ms; otherwise say "grid fallback".
- [ ] **Step 4: Commit.** `git commit -m "spike(S3): DWM timing and after() accuracy"` (and `git add` the script).

**Checkpoint:** stop after Task 6. Show the user the S1 screenshots and the three verdicts before Phase 1 continues (spec §8 policy).

---

## Phase 1

### Task 7: Free note windows when they close

**Files:**
- Modify: `StickyNote/app/ui_note.py:302` (header trace), `ui_note.py:1173-1183` (`NoteWindow.destroy`), `ui_note.py:1019` (`_roll_shot` stays for now, released in destroy)
- Modify: `StickyNote/app/ui_views.py:55` (search trace), new method `ListView.release()`
- Modify: `StickyNote/app/ui_picture.py`, new method `ImageViewer.release()`
- Modify: `StickyNote/app/app.py:624-660` (`close_window`, clear `last_note`)
- Test: `tests/test_release.py`

**Interfaces:**
- Produces:
  - `NoteWindow._trace_ids: list[tuple[tk.Variable, str]]`, filled by `trace_add` calls.
  - `ListView.release() -> None`: removes the search trace.
  - `ImageViewer.release() -> None`: sets `_source`, `_base`, `_shown` and `_photo` to None, and clears the thumbnail dict.
  - `NoteWindow.destroy()` additionally:
    - calls `trace_remove` for each `_trace_ids` entry;
    - calls `self.list_view.release()` and `self.viewer.release()`;
    - stops the "flash", "done_fade" and "rise" animations on the widgets that run them (the keys used at `ui_note.py:2591`, `:1800`, `:824`);
    - sets `self._roll_shot = None` and `self._inline = {}`;
    - if `self.app.last_note is self`, sets it to None.

- [ ] **Step 1: Write the failing tests** `tests/test_release.py`:

```python
class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
    def tearDown(self):
        close_app(self.app); self.tmp.cleanup()

    def _closed_ref(self):
        first = next(iter(self.app.windows.values()))
        nw = self.app.new_window(from_window=first)
        nw.header_var.set("x"); nw.show_list(); pump(self.app, timeout=0.3)
        ref = weakref.ref(nw)
        self.app.close_window(nw); del nw
        pump(self.app, lambda: len(self.app.windows) == 1, timeout=2)
        pump(self.app, timeout=0.3); gc.collect()
        return ref

    def test_closed_window_is_freed(self):
        self.assertIsNone(self._closed_ref()())

    def test_set_language_frees_old_windows(self):
        old = [weakref.ref(w) for w in self.app.windows.values()]
        self.app.set_language("en" if self.app.prefs.language == "ko" else "ko")
        pump(self.app, timeout=0.5); gc.collect()
        self.assertTrue(all(r() is None for r in old))
        self.assertEqual(len(self.app.windows), 1)

    def test_last_window_close_quits_and_saves(self):
        only = next(iter(self.app.windows.values()))
        only.body.insert("1.0", "keep me"); only.sync_from_widgets()
        self.app.close_window(only)
        pump(self.app, lambda: self.app.closed, timeout=2)
        self.assertTrue(self.app.closed)
        self.assertIn("keep me", (Path(self.tmp.name) / "notes.json").read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run** `.\StickyNote\runtime\python.exe -m unittest discover -s tests -p test_release.py -v`. Expected: `test_closed_window_is_freed` and `test_set_language_frees_old_windows` FAIL (the ref is still alive). `test_last_window_close_quits_and_saves` PASSes (it guards the quit path).
- [ ] **Step 3: Implement.**
  - Store the name each `trace_add` returns. For the header, store `(self.header_var, name)`. For the list, `ListView` keeps its own `(self.search, name)`.
  - Extend `NoteWindow.destroy()` and add the two `release()` methods as listed under Interfaces.
  - If a test still finds a referrer, find it with `gc.get_referrers` and release it in `destroy()` too. Record each extra referrer in the commit message.
- [ ] **Step 4: Run** `.\StickyNote\runtime\python.exe -m unittest discover -s tests -v`. Expected: all `OK`.
- [ ] **Step 5: Commit.** `git commit -am "fix: free note windows on close (traces, images, last_note)"`.

### Task 8: Drop the unused `marked_days()` call from calendar drawing

**Files:**
- Modify: `StickyNote/app/ui_calendar.py:1633`
- Test: `tests/test_calendar_draw.py`

**Interfaces:**
- Produces: `CalendarPopup.draw()` no longer calls `marked_days()`. `marked_days()` itself stays, for its other callers.

- [ ] **Step 1: Write the failing test:**

```python
class CalendarDrawTest(unittest.TestCase):
    def test_draw_does_not_compute_marked_days(self):
        with tempfile.TemporaryDirectory() as d:
            app = make_app(Path(d))
            try:
                pump(app, lambda: len(app.windows) == 1)
                nw = next(iter(app.windows.values())); nw.toggle_calendar()
                pump(app, lambda: nw.calendar is not None, timeout=1)
                with mock.patch.object(type(nw.calendar), "marked_days", side_effect=AssertionError("called")):
                    nw.calendar.draw()
            finally:
                close_app(app)
```

- [ ] **Step 2: Run** `... -p test_calendar_draw.py -v`. Expected: FAIL with `AssertionError: called`.
- [ ] **Step 3: Implement.** Change line 1633 to `today = date.today()`, and remove `marked` (it is unused).
- [ ] **Step 4: Run** the full suite. Expected: `OK`.
- [ ] **Step 5: Commit.** `git commit -am "perf(calendar): skip unused marked_days() in draw"`.

### Task 9: `snapshot()`, bitmap restore and a single copy

**Files:**
- Modify: `StickyNote/app/winapi.py:85-137`
- Test: `tests/test_snapshot.py`

**Interfaces:**
- Produces: `snapshot(win) -> tuple[int, int, ctypes.Array] | None`.
  - The third element is the ctypes buffer itself, not `buf.raw`. It supports the buffer protocol, so the existing `Image.frombuffer(..., data, ...)` callers (`ui_note.py:1018`, `:2427`, `app.py:2710`) keep working unchanged.
  - `old = SelectObject(mdc, bmp)`; in `finally`: `SelectObject(mdc, old)`, then `DeleteObject(bmp)`, `DeleteDC(mdc)`, `ReleaseDC`.
  - The gdi32/user32 prototypes are declared once at module level, not per call.

- [ ] **Step 1: Write the failing tests:**

```python
class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.top = tk.Toplevel(self.root); self.top.geometry("200x120+50+50")
        self.root.update()
    def tearDown(self):
        self.root.destroy()

    def test_snapshot_returns_buffer_of_right_size(self):
        w, h, data = winapi.snapshot(self.top)
        self.assertNotIsInstance(data, bytes)               # no extra copy
        self.assertEqual(len(memoryview(data).cast("B")), w * h * 4)

    def test_snapshot_does_not_leak_gdi(self):
        before = winapi.gui_handles()[0]
        for _ in range(50):
            winapi.snapshot(self.top)
        self.assertLessEqual(winapi.gui_handles()[0] - before, 2)

    def test_snapshot_withdrawn_returns_none_without_leak(self):
        self.top.withdraw(); self.root.update()
        before = winapi.gui_handles()[0]
        for _ in range(20):
            r = winapi.snapshot(self.top)
        self.assertLessEqual(winapi.gui_handles()[0] - before, 2)
        self.assertTrue(r is None or r[0] > 0)              # PrintWindow may still draw a withdrawn window
```

- [ ] **Step 2: Run** `... -p test_snapshot.py -v`. Expected: `test_snapshot_returns_buffer_of_right_size` FAILs (it returns `bytes`).
- [ ] **Step 3: Implement** as listed under Interfaces.
- [ ] **Step 4: Run** the full suite. Expected: `OK`.
- [ ] **Step 5: Commit.** `git commit -am "fix(winapi): snapshot restores the DC bitmap and returns the buffer without copying"`.

### Task 10: Skip the 30 ms drain's per-window work when nothing is queued

**Files:**
- Modify: `StickyNote/app/app.py:2741-2775` (`_drain_syscommands`)
- Test: `tests/test_drain.py`

**Interfaces:**
- Produces:
  - `_drain_syscommands` builds `by_hwnd` only when `asked` is non-empty.
  - The proxy iconic check stays.
  - `_check_thumbnail()` still runs every tick; it is internally throttled.
  - The tick interval (30 ms) and `collect_garbage()` stay. Phase 2 removes them (spec §5.1.5, §5.6).
  - The kept `hwnd → NoteWindow` dict from spec §5.6 is **not** built here. With the early-out, the map is built only when a command arrives, and the dict comes with the event-driven drain in Phase 6.

- [ ] **Step 1: Write the failing tests:**

```python
class DrainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        first = next(iter(self.app.windows.values()))
        for _ in range(4):
            self.app.new_window(from_window=first)
        pump(self.app, timeout=0.5)
    def tearDown(self):
        close_app(self.app); self.tmp.cleanup()

    def test_idle_drain_does_no_per_window_lookups(self):
        with mock.patch.object(self.app, "_check_thumbnail"), \
             mock.patch("app.winapi.hwnd_of", wraps=winapi.hwnd_of) as spy:
            self.app._drain_syscommands()
        self.assertLessEqual(spy.call_count, 1)             # the proxy only

    def test_multi_minimize_still_handled(self):
        wins = list(self.app.windows.values())[:2]
        t = time.perf_counter()
        self.app._syscommands += [("min", winapi.hwnd_of(w.win), t) for w in wins]
        with mock.patch.object(type(wins[0]), "minimize", autospec=True) as m:
            self.app._drain_syscommands()
        self.assertEqual(m.call_count, 2)
        self.assertTrue(all(c.kwargs.get("animate") is False for c in m.call_args_list))
```

- [ ] **Step 2: Run** `... -p test_drain.py -v`. Expected: `test_idle_drain_does_no_per_window_lookups` FAILs (call_count is 6). `test_multi_minimize_still_handled` PASSes.
- [ ] **Step 3: Implement** the early-out.
- [ ] **Step 4: Run** the full suite. Expected: `OK`.
- [ ] **Step 5: Commit.** `git commit -am "perf: idle syscommand drain skips per-window lookups"`.

### Task 11: The title field waits for a typing pause before syncing

**Files:**
- Modify: `StickyNote/app/ui_note.py:302`
- Test: `tests/test_header_sync.py`

**Interfaces:**
- Consumes: `NoteWindow._sync_soon()` (`ui_note.py:1614`) and `_trace_ids` (Task 7).
- Produces: the header trace calls `self._sync_soon()` instead of `self.sync_from_widgets()`.

- [ ] **Step 1: Write the failing tests:**

```python
class HeaderSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
    def tearDown(self):
        close_app(self.app); self.tmp.cleanup()

    def test_header_keystroke_does_not_sync_at_once(self):
        with mock.patch.object(type(self.nw), "sync_from_widgets", autospec=True) as m:
            self.nw.header_var.set("제목")
            self.assertEqual(m.call_count, 0)
            pump(self.app, timeout=0.4)                     # > TYPING_SYNC_MS (250)
            self.assertGreaterEqual(m.call_count, 1)        # (an autosave may sync too)

    def test_header_typed_then_closed_is_saved(self):
        first = self.nw
        nw = self.app.new_window(from_window=first); pump(self.app, timeout=0.3)
        nw.header_var.set("닫기 직전 제목")
        self.app.close_window(nw)
        pump(self.app, lambda: nw.pad.id not in self.app.windows, timeout=2)
        self.app.save_now()
        self.assertIn("닫기 직전 제목", (Path(self.tmp.name) / "notes.json").read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run** `... -p test_header_sync.py -v`. Expected: `test_header_keystroke_does_not_sync_at_once` FAILs (the count is 1 at once).
- [ ] **Step 3: Implement.** Change the trace callback. If the close-path test fails, the gap is `close_window` reading `note.is_empty` before the pending sync. Fix it by calling `nw.sync_from_widgets()` at the top of `App.close_window` when `"sync" in nw._jobs`.
- [ ] **Step 4: Run** the full suite. Expected: `OK`.
- [ ] **Step 5: Commit.** `git commit -am "perf(note): title field syncs after a typing pause"`.

### Task 12: Cache the Korean preedit font

**Files:**
- Modify: `StickyNote/app/ui_note.py:586-610`
- Test: `tests/test_preedit_font.py`

**Interfaces:**
- Produces:
  - `NoteWindow._preedit_font_for(bold: bool, italic: bool) -> tkfont.Font`: cached per (family, size, bold, italic) in `self._preedit_fonts: dict`.
  - The cache is cleared when the note's font family or size changes (`apply_look`).
  - `_show_preedit` uses it. It skips `configure`/`place` when (text, box, font) is unchanged from the last call (kept in `self._preedit_last`).

- [ ] **Step 1: Write the failing test:**

```python
class PreeditFontTest(unittest.TestCase):
    def test_same_style_reuses_font(self):
        with tempfile.TemporaryDirectory() as d:
            app = make_app(Path(d))
            try:
                pump(app, lambda: len(app.windows) == 1)
                nw = next(iter(app.windows.values()))
                a = nw._preedit_font_for(True, False)
                self.assertIs(a, nw._preedit_font_for(True, False))
                self.assertIsNot(a, nw._preedit_font_for(False, False))
                self.assertTrue(a.cget("underline"))
            finally:
                close_app(app)
```

- [ ] **Step 2: Run** `... -p test_preedit_font.py -v`. Expected: `AttributeError: ... '_preedit_font_for'`.
- [ ] **Step 3: Implement** as listed under Interfaces.
- [ ] **Step 4: Run** the full suite. Expected: `OK`.
- [ ] **Step 5: Commit.** `git commit -am "perf(note): cache the IME preedit font"`.

### Task 13: Fit the folded title with a binary search

**Files:**
- Modify: `StickyNote/app/ui_common.py` (new `fit_text`), `StickyNote/app/ui_note.py:1332-1337` (`_fit_date`, folded branch)
- Test: `tests/test_fit_text.py`

**Interfaces:**
- Produces: `fit_text(text: str, room: int, measure: Callable[[str], int], min_char: int, ellipsis: str = "…") -> str`. It returns:
  - `text` itself when `measure(text) <= room`;
  - else the longest prefix `p` with `measure(p + ellipsis) <= room`, returned as `p.rstrip(" ·") + ellipsis`. That is today's rule: test the raw prefix, strip the separators afterwards;
  - `ellipsis` alone when no prefix fits, as today's loop does;
  - `""` for empty `text`.
- Before searching, `text` is cut to `room // max(1, min_char) + 2` characters.
- `NoteWindow` caches the result in `self._fold_fit: tuple[key, str]`, keyed by `(full, room, str(self._date_font))`. `min_char = self._date_font.measure("i")`.
- The behaviour matches today's loop for every input (same output string).

- [ ] **Step 1: Write the failing tests:**

```python
def measure(s): return 7 * len(s)          # every character 7 px

class FitTextTest(unittest.TestCase):
    def test_fits_unchanged(self):
        self.assertEqual(fit_text("abc", 21, measure, 7), "abc")
    def test_cut_with_ellipsis(self):
        self.assertEqual(fit_text("abcdefgh", 35, measure, 7), "abcd…")
    def test_strips_separator_before_ellipsis(self):
        self.assertEqual(fit_text("ab · cdef", 35, measure, 7), "ab…")
    def test_no_room_gives_ellipsis_like_today(self):
        self.assertEqual(fit_text("abc", 3, measure, 7), "…")
    def test_empty(self):
        self.assertEqual(fit_text("", 50, measure, 7), "")
    def test_long_text_uses_few_measures(self):
        calls = []
        fit_text("가" * 20000, 700, lambda s: (calls.append(1), 7 * len(s))[1], 7)
        self.assertLess(len(calls), 20)
```

- [ ] **Step 2: Run** `... -p test_fit_text.py -v`. Expected: `ImportError: cannot import name 'fit_text'`.
- [ ] **Step 3: Implement** `fit_text`. Replace the `while` loop in `_fit_date`'s folded branch with the cached `fit_text` call.
- [ ] **Step 4: Run** the full suite. Expected: `OK`.
- [ ] **Step 5: Commit.** `git commit -am "perf(note): folded title fits by binary search, cached"`.

### Task 14: Freeze startup objects out of garbage collection

**Files:**
- Modify: `StickyNote/app/app.py:150-201` (end of `App.__init__`)
- Test: `tests/test_gc_freeze.py`

**Interfaces:**
- Produces: `App._freeze_startup_objects() -> None`, scheduled with `self.root.after_idle(...)` right after `self.save_now()` in `__init__`. It runs `gc.collect()` then `gc.freeze()`, once.

- [ ] **Step 1: Write the failing test:**

```python
class GcFreezeTest(unittest.TestCase):
    def test_startup_objects_frozen(self):
        gc.unfreeze()
        with tempfile.TemporaryDirectory() as d:
            app = make_app(Path(d))
            try:
                pump(app, timeout=0.5)
                self.assertGreater(gc.get_freeze_count(), 0)
            finally:
                close_app(app); gc.unfreeze()
```

- [ ] **Step 2: Run** `... -p test_gc_freeze.py -v`. Expected: FAIL (freeze count is 0).
- [ ] **Step 3: Implement** as listed under Interfaces.
- [ ] **Step 4: Run** the full suite. Expected: `OK`.
- [ ] **Step 5: Commit.** `git commit -am "perf: gc.freeze() the startup objects"`.

### Task 15: Glides hold the fine timer and step on a grid

**Files:**
- Modify: `StickyNote/app/motion.py:239-246` (`run`), `motion.py:321-340` (`_tick`)
- Test: `tests/test_motion_pacing.py`

**Interfaces:**
- Consumes: `ui_common._keep_timer_fine(widget)`, `FRAME_MS`.
- Produces:
  - Module function `next_delay(t0: float, now: float, frame_ms: int = FRAME_MS) -> int`. It returns the ms until the next grid line `t0 + k·frame_ms` after `now`, and never less than 1.
  - `Motion._clock0: float | None`: when the loop started, set when `_job` is first scheduled and cleared when the loop ends.
  - `run()` and `_tick()` call `_keep_timer_fine(self.app.root)` whenever a frame is scheduled.
  - `_tick` schedules `after(next_delay(self._clock0, perf_counter()), self._tick)`.

- [ ] **Step 1: Write the failing tests:**

```python
class MotionPacingTest(unittest.TestCase):
    def test_next_delay_on_grid(self):
        self.assertEqual(motion.next_delay(0.0, 0.020, 15), 10)
        self.assertEqual(motion.next_delay(0.0, 0.031, 15), 14)
        self.assertEqual(motion.next_delay(0.0, 0.0449, 15), 1)
        self.assertEqual(motion.next_delay(0.0, 0.045, 15), 15)

    def test_glide_holds_fine_timer(self):
        with tempfile.TemporaryDirectory() as d:
            app = make_app(Path(d))
            try:
                pump(app, lambda: len(app.windows) == 1)
                nw = next(iter(app.windows.values()))
                pump(app, timeout=1.0)                      # the opening fade (which holds the timer) is over
                ui_common._fine_timer["last"] = 0.0
                x, y = nw.pad.x, nw.pad.y
                app.motion.run({nw.pad.id: (x + 200, y, x + 200 + nw.pad.width, y + nw.pad.height)})
                pump(app, timeout=0.05)
                self.assertGreater(ui_common._fine_timer["last"], 0.0)
                pump(app, lambda: not app.motion.busy(), timeout=1)
                self.assertEqual(nw.pad.x, x + 200)
            finally:
                close_app(app)
```

- [ ] **Step 2: Run** `... -p test_motion_pacing.py -v`. Expected: `AttributeError: module 'motion' has no attribute 'next_delay'`.
- [ ] **Step 3: Implement** as listed under Interfaces.
- [ ] **Step 4: Run** the full suite. Expected: `OK`.
- [ ] **Step 5: Commit.** `git commit -am "perf(motion): hold the 1 ms timer and pace glides on the frame grid"`.

### Task 16: Phase 1 measurement and check-off

**Files:**
- Create: `docs/perf/phase1.json` (generated)
- Modify: `docs/2026-11-25-redesign-design.md` (add a "Phase 1 results" section)

- [ ] **Step 1: Run** `$env:STICKY_PERF='1'; .\StickyNote\runtime\python.exe tools\baseline.py phase1`. Expected: it exits 0 with 8 summary lines.
- [ ] **Step 2: Check the Phase 1 done criterion** (spec §7). In `open_close_50`:
  - `after.private_bytes − before.private_bytes ≤ 5 MB`;
  - `live_windows` equals the number of open windows.

  If it fails, go back to Task 7 with the `gc.get_referrers` output.
- [ ] **Step 3: Check that motion frames improved.** In `tidy`, `frames.motion.p95` should be lower than baseline, and `frames.motion.max` should be ≤ 20 ms.
- [ ] **Step 4:** Add a "Phase 1 results" table (baseline vs. Phase 1 per scenario) to the spec.
- [ ] **Step 5: Run** the full suite once more. Expected: `OK`.
- [ ] **Step 6: Commit.** `git add docs; git commit -m "perf: phase 1 results"`.
