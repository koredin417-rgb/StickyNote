# Sticky Note: Performance, Animation and Memory Redesign Report

**Date:** 2026-11-25
**Scope:** `StickyNote/app/` (about 15,900 lines in 20 modules), Python 3.15, Tkinter and Pillow 12.3 (bundled runtime)
**Status:** analysis and proposed plan only. No project files have been changed.

**How this was checked.** Every module was read. The findings below were confirmed directly:

- the frame loop in `motion.py`;
- the 30 ms poll in `app.py`;
- the save path, timed with 1000 synthetic notes on the bundled runtime;
- the GDI handle behaviour of `winapi.snapshot`, tested on this Windows build;
- the closed-note memory leak, reproduced in a small script.

Everything else comes from reading the code, with line numbers given. Nothing was measured inside the running app.

---

## 1. Summary

The app is carefully built and its *behaviour* is well designed. Its layout rules, magnet and link model, calendar docking and fold/minimize are good, and they all stay. The problems sit in three layers underneath:

1. **Several clocks instead of one.** Window glides (`Motion`), fades and slides (`ui_common.animate`), the delete fly (its own `after` loop) and the new-note flash each run their own timer.
   - They step on a 15 ms grid, which a 60 Hz display shows as 16.7 ms frames.
   - `Motion` doesn't hold the 1 ms Windows timer, so its frames can land 16 or 31 ms apart.
   - Animations on the same window cut each other off instead of handing over smoothly.
2. **Work per input event instead of work per frame.**
   - Each mouse move during a drag rebuilds the space model and runs the magnet.
   - Each mouse move during a resize runs the whole growth planner.
   - Each keystroke re-tags the whole document.
   - Each picture pan or zoom resamples the full-resolution photo.
   - Each calendar or list refresh destroys and rebuilds everything.
3. **Memory held longer than needed.**
   - Every closed note window stays in memory for good, including its full-resolution picture (confirmed; see §3.4).
   - Several image caches are capped by count, or not capped at all.
   - The taskbar thumbnail is composited at full desktop resolution (up to about 66 MB on two 4K monitors).
   - Some per-monitor-setup data grows for good and is saved every time.

The recommended path is an **in-place restructuring on Tk** (Approach A in §4). It adds:

- one display-paced frame clock that owns every animated property;
- input coalesced to one unit of work per frame;
- incremental rendering for the calendar and the list;
- one byte-bounded image cache, with explicit release when a window closes;
- events in place of polling.

All features are kept. The UI changes are limited to motion and responsiveness (§6).

---

## 2. Current structure

| Module | Lines | Role today |
|---|---|---|
| `main.py` | 39 | Single-instance mutex, DPI awareness, starts `App` |
| `app.py` | 2804 | **God object.** About 140 methods and about 15 jobs: settings, window registry, magnet, links, calendar coordination, space model, return/detach, growth and drop planning, per-setup copies, screen polling, apply/undo, fold and tidy, auto-grid, gap respacing, picture cache, saving, taskbar proxy and thumbnail, syscommands, signal file |
| `motion.py` | 464 | `Motion`: one plan, one glide loop for notes and the calendar. Freezes notes whose size changes. `Outlines` overlay |
| `ui_common.py` | 1582 | Constants, colours, `animate`/`fade`, tooltips, icon painter, buttons, sliders, scroll overlay, popup menu, picture helpers |
| `ui_note.py` | 2654 | `NoteWindow`: one `Toplevel` per note, rich text, tabs, fold/minimize/roll, freeze cover, delete fly, toasts, drag and resize |
| `ui_picture.py` | 399 | Image memo viewer: pan, zoom, chevrons, tab fade |
| `ui_calendar.py` | 1943 | Docked or floating calendar, mini and big views, paging, chips, peeks |
| `ui_views.py` | 1447 | List, search, preview, settings, bin |
| `space.py` / `grid.py` / `geom.py` / `calgeom.py` / `links.py` | about 1950 | Pure layout maths: growth, slide-in, auto-grid, tidy, links |
| `store.py` | 794 | `notes.json` model and saving, image files |
| `winapi.py` | 653 | ctypes: layered windows, click-through, PrintWindow, fine timer, DWM thumbnails, window hooks, monitors |
| `texts.py`, `holidays.py`, `icon.py`, `shortcut.py`, `install.py` | about 1150 | Strings, Korean holidays, icon, .lnk, installer |

**Structural notes:**
- `app.py` and the UI modules reach into each other's private fields (`cal._dock_offset`, `w._closing`, `app._gap()`, `nw.calendar._click_job`).
- `from ui_note import *` imports the whole UI into `app.py`.
- The "sync every open Settings page" loop is copied about 8 times.
- Small leftovers: `calendar()` is defined twice (`app.py:610` and `:1196`), and `import calgeom` appears twice.

**Layering is already good in one place.** The planners (`space.py`, `grid.py`, `geom.py`, `calgeom.py`, `links.py`) are pure functions over boxes. The redesign builds on that.

---

## 3. Diagnosis

### 3.1 Animation and frame pacing

| # | Problem | Where | Effect on the user |
|---|---|---|---|
| A1 | **Two engines, many clocks.** `Motion._tick` schedules `after(FRAME_MS)` *after* its work, so it drifts. Each `animate()` call has its own timer. `_fly_to_bin` runs a third kind of loop. | `motion.py:321-340`, `ui_common.py:350-378`, `ui_note.py:726-763` | A glide, a fade and a flash running together update at different moments, so movement looks uneven. |
| A2 | **`Motion` never takes the 1 ms timer.** Only `animate()` calls `_keep_timer_fine`. | `motion.py` (no call), `ui_common.py:326` | A glide alone gets 15.6 ms timer steps: frames 16 or 31 ms apart, which looks like a stutter. |
| A3 | **15 ms grid against a 16.7 ms display.** | `ui_common.py:96` | About one doubled or missed frame every 9 frames, visible in the 260-280 ms slides. |
| A4 | **Animations fight over one property.** `move_to` stops "slide" and snaps alpha. `apply_alpha` guards against "slide" but not "dip". Settings open/close and month paging restart from their end points. | `ui_calendar.py:274, 474-476, 948-969, 1121-1157`, `ui_views.py:1010-1047` | Fades are cut short. Hovering during a view dip flickers. Reversing a settings slide or clicking quickly through months jumps. |
| A5 | **Restore and unfold often run without the picture cover.** `_kept_shot` matches only after an animated roll at the same size and colour in the same session. | `ui_note.py:1142, 2561` | After Win+M, a resize, a colour change or a fresh start, every roll frame re-lays out about 30 widgets and re-wraps the text: visible jank. |
| A6 | **The new-note flash repaints about 20 widgets per frame for 900 ms**, on its own timer. | `ui_note.py:2591-2608` | It adds load during the slide-out glide it overlaps. |
| A7 | **The delete fly makes a new PhotoImage and a BILINEAR resize per frame**, after a synchronous grab of the *whole virtual desktop*. | `ui_note.py:721-763` | A hitch before the fly starts (tens of MB, tens of ms). It also captures whatever is behind a translucent note. |
| A8 | **Synchronous captures at plan start.** `freeze()` calls `PrintWindow(PW_RENDERFULLCONTENT)` for each sized note, back to back. `Motion` resets its clock afterwards, which avoids a jump but delays the start. | `motion.py:244-246, 270`, `ui_note.py:2427` | Tidy or arrange with a dozen notes waits before moving. |
| A9 | **Window moves are not batched.** A group drag or a multi-note glide calls `geometry()` once per window. | `motion.py:313-315`, `ui_note.py:2160-2166` | Notes in a group drift apart by a frame while moving together. |
| A10 | **Mixed easing and durations.** Cubic out almost everywhere, sine for months. 16 different durations from 90 to 900 ms. | `ui_common.py:95-126` | Motion feels less like one system than it could. |

### 3.2 Work per input event

| # | Problem | Where |
|---|---|---|
| E1 | **Drag.** Each `<Configure>` calls `space_changed()` (cache cleared) and `request_save()` (timer cancelled and re-created). Then `App.snap` rebuilds `space()` and tries every x/y combination against every obstacle, on every mouse move. | `ui_note.py:2616-2636`, `app.py:724` |
| E2 | **Single-note resize.** `space.plan_growth` runs on every motion event. In the worst case it is O(n²) for each direction and sweep, plus `nearest_free` candidate searches. The note isn't frozen, so the real widgets re-lay out on every event. | `ui_note.py:2224, 2285`, `space.py:777` |
| E3 | **Typing.** Each key re-reads the whole text, removes four tags from the whole document and re-adds them line by line. There is also an O(B×I) bold-and-italic pass. The header field's trace skips the typing debounce and runs a full `sync_from_widgets` on every key. | `ui_note.py:302, 1607-1721` |
| E4 | **Korean IME.** `_show_preedit` runs twice per key and creates a new `tkfont.Font` each time, and re-polls every 120 ms while composing. | `ui_note.py:240, 602` |
| E5 | **Folded-note title.** It joins every line of every tab, then trims one character at a time with `font.measure`: O(n²) Tcl calls. It runs on resize and on `calendar_buttons()` for **every** window. | `ui_note.py:1330-1336` |
| E6 | **Picture pan and zoom.** Each event resamples from the full-resolution source and rebuilds the chevrons (4× mask, MaxFilter, GaussianBlur, two full-size `alpha_composite`s). | `ui_picture.py:182-316` |
| E7 | **Calendar.** `draw()` calls `marked_days()` and never uses the result: a full sort plus expanding every period memo by up to 800 days, on every draw. The by-day index is rebuilt twice per draw and again on every day hovered. `_fit` trims one character at a time. Fonts are created per draw. A grip resize redraws once per idle. | `ui_calendar.py:1633, 1645, 1701, 1772, 1822, 1893` |
| E8 | **Range-drag count card.** It rebuilds a 4×-supersampled PIL card and a PhotoImage on every motion event. | `ui_calendar.py:1226-1237` |
| E9 | **List.** `refresh()` destroys every card in *every* open note's list on any change (pin, width, search, 17 `refresh_lists` call sites). Cards are about 12-15 native widgets each and are only ever added: scrolling through 500 memos builds about 7,000 widgets. | `ui_views.py:123-198`, `app.py:2491` |
| E10 | **Calendar single click** waits `DOUBLE_CLICK_MS` (260 ms) before acting. | `ui_calendar.py:1406` |

### 3.3 Timers and polling (idle cost)

| Timer | Interval | Per tick |
|---|---|---|
| `_drain_syscommands` | **30 ms, forever** | `collect_garbage()`, then two Tcl calls per window to rebuild the hwnd map even when nothing is queued, then `IsIconic` and the thumbnail check. With 20 notes that is about 1,500 Tcl calls and 33 wakeups per second while idle. Confirmed at `app.py:2741-2775`. |
| `_poll_signal` | 800 ms | Two file `exists()` checks. A second launch is signalled by touching a file. |
| `_poll_screens` | 1000 ms | `EnumDisplayMonitors` plus `GetMonitorInfoW`, re-declaring ctypes types on each call. |
| `_check_day` | 30 s | `date.today()` |
| `request_save` | 400 ms debounce | Re-armed on every `<Configure>` during drags. |

### 3.4 Memory

| # | Problem | Evidence | Size |
|---|---|---|---|
| M1 | **Every closed note window is kept for good.** `header_var.trace_add("write", lambda: self.sync_from_widgets())` registers a Tcl command that holds `self`, and destroying the window does not remove variable traces. `ListView.search` has the same pattern. `set_language` rebuilds every window, so it keeps every old one. | `ui_note.py:302`, `ui_views.py:55`. **Reproduced:** a destroyed `Toplevel` with this trace stays alive after `gc.collect()`. | The full-resolution picture (36-48 MB for a 12 MP photo), the roll shot (1-2 MB), inline photos, thumbnails, the whole widget tree |
| M2 | The picture viewer always keeps the full-resolution source, plus three copies of the display image (`_base`, `_shown`, the Tk photo). | `ui_picture.py:139-264` | Tens of MB per image memo |
| M3 | Every note keeps `_roll_shot` for good. | `ui_note.py:1019` | About 1-2 MB per note on HiDPI |
| M4 | The taskbar thumbnail composites a full-resolution RGBA canvas over the bounding box of all windows, and then downsizes it. Typing while the preview is open re-captures every 0.5 s, because `note.modified` is part of the signature. | `app.py:2698-2739` | Up to about 66 MB peak (two 4K monitors). The process keeps that high-water mark. |
| M5 | The picture cache holds 96 entries capped by count, not bytes. Its key is the exact box size, so a resize churns it, and every miss decodes the full file on the UI thread (50-150 ms for a 12 MP JPEG). | `app.py:2458`, `ui_common.py:1373` | Unbounded in bytes |
| M6 | `IconPainter._photos`, the calendar `_tiles` and `_dots` have no bound and are never cleared on theme change. `_dots` gains one entry per day. | `ui_common.py:653`, `ui_calendar.py:175, 1788` | Small, but it grows all session |
| M7 | `pad.setups`, `calendar_setups`, `setup_scales` and `grid_homes` gain an entry for every monitor layout ever seen (Remote Desktop, VMs). All of it is saved every time. | `app.py`, `store.py` | Grows `notes.json` for good |
| M8 | GC is turned off for the ctypes window hooks, and a full gen-2 collection runs from the 30 ms poll. It can land in the middle of an animation frame. | `winapi.py:578, 618`, `app.py:2748` | Frame hitches |
| M9 | `snapshot` deletes the bitmap while it is still selected into the DC. **Tested: no handle leak on this Windows build** (`DeleteObject` returns 1). It is still worth restoring the old bitmap first, for correctness. | `winapi.py:126-135` | None today |

### 3.5 Saving

| What | Detail |
|---|---|
| What every save does | `sync_from_widgets` for **every** window, then `asdict`, then `json.dumps` with `indent=1`. It writes only if the text changed, but always pays for the serialisation. |
| Measured cost | 8.7 ms + 11.3 ms on the bundled runtime with 1000 notes (4.9 MB of JSON). It all runs on the UI thread. |
| When it runs | After every Motion action, even when nothing changed. |
| Crash safety | No `fsync` of the `.tmp` file, so a power cut can leave `notes.json` empty or truncated. Loading falls back to `.bak`. |
| Pictures | PNG encoding of pasted pictures also runs on the UI thread. |

---

## 4. Approaches considered

| | Approach | What it means | Trade-off |
|---|---|---|---|
| **A (recommended)** | **Restructure in place on Tk** | Keep one `Toplevel` per note and all behaviour. Add one frame clock, input coalescing, incremental rendering, a shared image cache and event-driven timers. Split `App` into focused modules. | Lowest risk. Every phase ships on its own and can be checked against today's behaviour. Limit: Tk can only fade whole windows, and each window move is still one Win32 call (batched with DeferWindowPos). |
| B | Port to Qt (PySide6) | Rewrite the UI layer and keep the planners. | GPU-backed widget animation and real per-widget opacity. But it adds 80-150 MB to the install, changes the Korean IME path, and means re-implementing about 9,000 lines of UI and every interaction rule. A rewrite, not an optimisation. |
| C | One composited overlay | A single click-through layered window draws every note as a bitmap (UpdateLayeredWindow), and a real Tk window appears only for the note being edited. | The smoothest possible glides. But it duplicates every note's rendering, makes text selection and IME across windows hard, and multiplies complexity. Worth revisiting only if A's limits turn out to matter. |

**Pick A.** It keeps your existing features and the behaviour rules you have already tuned. The problems found are about *how often* work is done and *who owns* each animation, not about Tk's ceiling. Approach C can later be applied to just the fold/minimize cover, if needed.

---

## 5. Target design (Approach A)

### 5.1 One frame clock: `anim.py` (new; replaces `ui_common.animate` and `Motion`'s own loop)

```
FrameClock (one per app)
 ├─ tick(): one root.after() chain, running only while something is active
 │    1. read the display period and next vblank (DwmGetCompositionTimingInfo); fall back to 16.67 ms
 │    2. run frame callbacks (coalesced input, see §5.2)
 │    3. step every Tween with the same `now`
 │    4. flush the window batch: one BeginDeferWindowPos ... EndDeferWindowPos for all moved windows
 │    5. schedule the next tick for about 2 ms before the next vblank
 ├─ holds timeBeginPeriod(1) only while active (moved out of ui_common)
 └─ suspends gc while active; gc.collect(1) once it has been idle for 1 s

Tween(target, prop, to, duration, curve, done)
 └─ one owner per (window, property): starting a new Tween on a busy property RETARGETS it
    from its current value (and current velocity, for position), never from its end point
```

- **Properties:** `pos` (x, y), `size`, `alpha`, `clip_h` (SetWindowRgn roll), and `canvas_offset` (paging, chips, settings slide via `place`).
- **`Motion` stays as the planner of glides.** It computes the boxes, freezes and lands exactly as today (S1/S4 rules unchanged), but it creates `pos`/`size` tweens on the clock instead of running its own loop.
- **The old API stays as a thin wrapper.** `animate()`/`fade()` remain as wrappers during migration, so call sites move one at a time.
- **Fixes A1-A4 and A9.** A1 to A3 by construction (one clock, paced to the display). A4 through the one-owner rule. A9 through the per-frame window batch.

### 5.2 Input coalescing

- **Handlers only record.** Drag, resize, picture pan and zoom, calendar grip and range-drag handlers just store the latest pointer and call `clock.request(callback)`. The work runs once per frame.
- **Drag/resize session object** (`interact.py`, new), created on button-down:
  - takes the obstacle list from `space()` once and keeps it for the gesture;
  - suppresses `space_changed()` and `request_save()` from `<Configure>` while `app.moving`;
  - runs the magnet against the frozen obstacles;
  - runs `plan_growth` at most once per frame, pre-filtered to shapes in the grower's rows and columns, and skipped when the edge reaches no neighbour;
  - commits once, on release (E1, E2).
- **Single-note resize** uses the same freeze cover as Motion's sized glides, so widgets re-lay out once, on release.

### 5.3 Snapshot service (`shots.py`, new)

- **One cached capture per note**, tagged with a "look version" that is bumped on text, colour, size, tab or theme change.
- **`freeze()`, the roll cover and the delete fly all read from it.** They capture only when the version is stale. A capture uses `PrintWindow` of that window (never `ImageGrab` of the desktop), with the old bitmap restored.
- **Restore and unfold always get a cover.** With no current shot, the note is mapped at full size with alpha 0, captured, then rolled (A5).
- **The delete fly** keeps pre-reduced levels (½, ¼) and paints into one reused PhotoImage with `paste()` (A7).
- **Memory.** Shots are dropped when a note is closed and are counted in the image budget (§5.5). That replaces `_roll_shot` being kept forever (M3).

### 5.4 Incremental rendering

**Calendar:**
- a `DayIndex` cached per store revision (built once, shared by draw, hover, peek and right-click);
- delete the unused `marked_days()` call;
- module-level `Font` objects;
- a memoized binary-search `_fit`;
- a grip redraw at most once per frame;
- paging ends with `delete("old")` and `dtag("paging")` instead of a full redraw;
- selection, hover and chip changes update only their own items;
- the count card is rebuilt only when the range changes.

**List** (E9):
- cards are kept by note id and updated in place;
- a pin moves one card, and a width change sets `wraplength`;
- a pool of card widgets covers the visible rows plus one screen (virtualized), so a 500-memo list holds about 30 cards, not 500;
- `refresh_lists(note_id)` touches only the lists that show that note.

**Note text** (E3-E5):
- re-tagging is limited to the lines an edit touched;
- the header uses the same debounce as the body;
- the IME preedit font is cached;
- the folded title is cut to the room's character budget, then binary-searched and cached.

**Picture viewer** (E6, M2):
- a working copy at most 2× the note size (`draft()` for JPEG, `reduce()` otherwise); full resolution only for zoom above 1:1;
- chevron sprites cached by (side, hover, colours, scale) and composited only into their own small box;
- one render per frame.

### 5.5 Memory

1. **Release on close** (M1). `NoteWindow.destroy()` and `ListView.destroy()`:
   - remove their variable traces (keep the name `trace_add` returns);
   - cancel all their animations and jobs;
   - drop `viewer._source`, shots, inline photos and thumbnails;
   - remove the window from `App.last_note`.

   A debug-only check confirms that a closed window is collected: a `weakref` to it is dead after the next idle `gc.collect`.
2. **One `ImageCache`** (`images.py`, new):
   - **Budget:** LRU capped by **bytes** (default 64 MB of decoded pixels).
   - **Contents:** pictures, inline photos, thumbnails, icon photos and calendar tiles.
   - **Keys:** box sizes rounded to 32 px buckets, so a resize doesn't churn it.
   - **Theme:** a theme or accent change drops that theme's icon and tile entries.
   - **Decoding:** picture decode and PNG encode run on a worker thread, with a placeholder tile until ready. Pillow releases the GIL while decoding, and Tk is touched only on the UI thread through `after`.
3. **Thumbnail** (M4):
   - work out the scale first, then shrink each capture with `reduce()`/BOX before pasting it into a thumbnail-sized canvas (peak under 2 MB);
   - leave `note.modified` out of the signature, so a new capture happens only when windows move, change size or change look.
4. **Per-setup data** (M7). Keep the 8 most recent monitor layouts.
5. **Garbage collection** (M8).
   - Call `gc.freeze()` after startup, so the permanent startup objects are never scanned.
   - Run collections only from the clock's idle hook (§5.1), never in the middle of an animation.
   - Hook only what each window needs: syscommands only on the proxy if possible, and the IME hook only on text windows.

### 5.6 Events instead of polls

| Today | Instead |
|---|---|
| 30 ms `_drain_syscommands` | The window hook queues the command and schedules **one** `after_idle(drain)` if none is pending. The hwnd map is kept up to date when windows open and close. The proxy's minimize is caught in its own hook (`WM_SIZE`/`SIZE_MINIMIZED`). |
| 800 ms `show.signal` file poll | The second launch finds the proxy window (`FindWindowW` on its class) and posts it a registered `WM_APP_SHOW` message. The file is kept only as a fallback, checked once at startup. |
| 1 s monitor poll | `WM_DISPLAYCHANGE`, `WM_SETTINGCHANGE` (SPI_SETWORKAREA) and `WM_DPICHANGED` on the proxy, with the existing 600 ms / 3 s settle logic kept. A 15 s safety poll remains. |
| 30 s day check | One timer to the next midnight, plus `WM_TIMECHANGE` and `WM_POWERBROADCAST` (resume). |

**Expected idle result:** about 33 wakeups per second down to well under 1.

### 5.7 Saving

- **Dirty generations.** A `dirty` counter means no serialisation at all when nothing changed. Motion's end step stops saving unconditionally.
- **Only edited text is read back.** `sync_from_widgets` runs only for windows with a pending edit.
- **Per-note cache.** Each note's dict is cached until that note changes.
- **Compact JSON.**
- **Background write with `fsync`.** The snapshot string is built on the UI thread and written on a worker thread (write `.tmp`, `fsync`, rename), with one save in flight at a time. `save_now` on exit stays synchronous.

### 5.8 Splitting `App`

The behaviour stays the same; the code moves into focused modules, and private-field reach-ins become small public methods:

| Module | Takes over from `app.py` |
|---|---|
| `registry.py` | note ↔ window ↔ pad index (replaces linear `window_for` scans), open/close/reopen |
| `settings_ctl.py` | the ~25 setters plus one "settings changed" notifier (replaces the 8 copied loops) |
| `screens.py` | monitor model, setups, per-setup copies, event-driven change detection |
| `layout.py` | space model, snap/magnet, find_spot, grow/close_up/give_back/settle_drop, tidy, arrange, respace (calls the pure planners) |
| `taskbar.py` | proxy window, syscommands, thumbnail |
| `persist.py` | save scheduling and writer thread (§5.7) |
| `app.py` | wiring and lifecycle only (target: under 600 lines) |

---

## 6. UI and UX revisions

Everything stays where it is. These changes make the app feel quicker and more consistent:

1. **One motion language.**
   - **Curves:** two. *Standard* (ease-out cubic) for things that move or appear. *Exit* (ease-in quad, shorter) for things that leave.
   - **Durations:** three. Fast 120 ms (fades, tooltips, menus, hover). Base 180 ms (calendar show, roll, toast, chip). Long 240 ms (glides, month paging, settings page).
   - **Mapping:** the 16 current constants map onto these. The tokens live in one place (`anim.py`).
2. **Interrupt and reverse, never restart.** Clicking again during any slide reverses it from where it is (settings page, calendar show/hide, month paging, roll/unroll). Fast month clicks continue the current slide toward the newest target instead of jump-cutting.
3. **Input is never blocked by animation.** A note can be grabbed mid-glide (this already works through `Motion.cancel`), and the same now holds for rolls, the calendar slide and the settings slide.
4. **Calendar single click acts at once.** The day is selected immediately, and a double-click within 260 ms adds the "new memo" action on top (E10).
5. **Calendar show/hide slides toward its docking side**, including above and below, instead of always horizontally.
6. **A shorter, lighter new-note flash.** It drops from 900 ms to 400 ms, and only the top bar background is tweened through the clock instead of about 20 widgets.
7. **No doubled chip on drop.** The flying copy lands *before* the chip is redrawn at its new day.
8. **HolidayCard fades in** like the other popups. The memo preview is reused rather than rebuilt on each hover, and it no longer restarts its 250 ms timer when the pointer moves between parts of the same card.
9. **Reduced motion.**
   - **Windows setting:** respect "Show animations in Windows" (`SPI_GETCLIENTAREAANIMATION`).
   - **App setting:** add Settings → *Animations: Full / Reduced / Off*. *Reduced* keeps fades at Fast and turns glides and rolls into short cross-fades. *Off* jumps.
10. **Live resize stays smooth.** A single-note resize shows the frozen cover while dragging and lays out once on release, the same way sized glides already do.

---

## 7. Migration plan

Each phase leaves a working app. Before and after each phase, run `preview.py` (separate data folder) against the measurements in §8.

| Phase | Contents | Risk |
|---|---|---|
| **0. Measure** | Add a debug-only `perf.py`: frame-interval histogram per animation, time per handler, process private bytes (`GetProcessMemoryInfo`), GDI/USER handles (`GetGuiResources`), live `NoteWindow` count. Record the baseline: 20 notes, tidy, group drag, calendar paging, a 500-memo list, open and close 50 notes. | None |
| **1. Quick wins** | Release closed windows (M1). Delete the unused `marked_days()` call. Early-out in the 30 ms drain. Take the fine timer in `Motion` and pace it on the grid. Header debounce. IME font cache. Folded-title trim. Restore the old bitmap in `snapshot`. `gc.freeze()` after startup. | Low |
| **2. Frame clock** | `anim.py`, Tween ownership, display pacing, DeferWindowPos batch. Move `Motion` onto it, then each `animate()` call site, then the fly and flash. Introduce the motion tokens. | Medium. DeferWindowPos with Tk's geometry tracking needs checking on multi-monitor and mixed DPI; keep a flag that falls back to `geometry()`. |
| **3. Input coalescing** | `interact.py` drag/resize sessions, frozen obstacles, per-frame `plan_growth`, resize cover, picture pan and zoom per frame. | Medium. The magnet and growth must give the same results as today: compare plans in debug builds. |
| **4. Rendering** | Calendar `DayIndex` and incremental items. List kept by id plus virtualization. Ranged re-tagging. | Medium (list virtualization touches keyboard focus and scroll). |
| **5. Images and snapshots** | `images.py` byte-bounded cache and decode worker, `shots.py`, viewer working copy, chevron sprites, thumbnail at reduced scale. | Low to medium |
| **6. Events and saving** | Window-message signalling, display and time events, dirty-generation save, writer thread with fsync, per-setup pruning. | Medium (single-instance handover and saving must be crash-safe: test killing the process mid-save). |
| **7. Split `App`** | Move code into §5.8 modules behind small public methods; no behaviour change. | Low per step; done last, when the earlier phases have already reduced `app.py`. |
| **8. UX polish** | The §6 items not already covered by phases 2-4, including the Animations setting. | Low |

---

## 8. Targets (checked with `perf.py` against the phase-0 baseline)

| Measure | Today (expected from the code) | Target |
|---|---|---|
| Idle wakeups | about 33/s plus polls | under 1/s |
| Glide frame interval | 15, 16 or 31 ms, unpaced | display period ±2 ms, 95th percentile |
| Frames over budget during a 12-note tidy | start delay plus repeated layout on landing | no frame over 2× period after the first |
| Group drag | windows a frame apart | all windows move in the same frame |
| Memory after opening and closing 50 notes | grows by every window (and its picture) | returns to within 5 MB of the start |
| Taskbar thumbnail peak | up to about 66 MB | under 4 MB |
| Save with no change | full serialisation (about 20 ms at 1000 notes) | about 0 ms |
| 500-memo list scroll | up to about 7,000 widgets | about 30 cards in the pool |

---

## 9. Decisions for you

1. **Approach.** A (restructure on Tk) is recommended. B and C are in §4.
2. **Animation durations.** Is it all right to move the 16 current durations onto Fast/Base/Long (120/180/240 ms)? This slightly shortens the 280 ms month slide and new-note slide, and the 900 ms flash.
3. **Animations setting.** Add *Full / Reduced / Off* to Settings (a new UI row and its text in both languages), or only follow the Windows setting?
4. **Calendar single click** acting immediately instead of after 260 ms: any reason the delay was wanted?
5. **Phase order.** Phase 1 (quick wins) is self-contained and fixes the biggest memory issue. Should it go first, as its own change?

Once these are settled, the next step is a detailed, task-by-task implementation plan for the first phase.
