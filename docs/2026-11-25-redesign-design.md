# Sticky Note Redesign: Design

**Date:** 2026-11-25
**Status:** draft for review
**Diagnosis this builds on:** [2026-11-25-performance-redesign-report.md](2026-11-25-performance-redesign-report.md). It has the problem list, with file and line references; section numbers like §3.1 below point into it.
**Code:** `StickyNote/app/`. Python 3.15 and Tkinter, with Pillow 12.3, all in the bundled runtime.

---

## 1. Intent

The app works, and its behaviour rules (snapping, links, calendar docking, folding, auto layout) are worth keeping. But it **looks cheap**, and its **animations feel sloppy, slow and jittery**. The goal is an app that looks considered and moves smoothly, while using less memory and CPU.

The diagnosis found the causes:
- Animations run on several unsynchronised timers that aren't in step with the display.
- Animations cut each other off.
- Heavy work runs on every mouse move and keystroke.
- Closed windows are never freed.
- The look shows 16 controls on every note and has hard square edges with no shadow.

## 2. Goals, non-goals, anti-goals

**Goals**
1. **Smooth motion.** Every animation steps once per display frame, timed to the display. Starting a new animation on something that is already moving continues from where it is, so nothing jumps.
2. **Responsive input.** Dragging, resizing, typing, panning and calendar clicks never wait on per-event planning, or on an animation finishing.
3. **Lower memory and CPU.**
   - Closed notes are freed.
   - Image memory has a byte budget.
   - The idle app wakes up less than once per second.
   - A save costs nothing when nothing changed.
4. **The C look** for notes and the calendar (§6), with one motion language (§5.1.6).
5. Every current feature keeps working. The existing layout rules (S1/S4, C1/C2, L2-L5, M2, N2, N5, P1-P6) give the same results.

**Non-goals**
- Moving to Qt or another toolkit.
- A single composited overlay window.
- New note features.
- Changing the `notes.json` format beyond pruning old per-setup data (§5.5).
- Changing the installer or the bundled runtime.

**Anti-goals (a failure even if it works)**
- Notes jump, flicker or show half-drawn states anywhere they don't today.
- A behaviour rule silently changes: snapping, docking, growth, tidy or arrange give different results.
- Typing Korean gets worse: IME preedit, syllable finishing on click.
- Memory or CPU at rest ends up higher than today.
- The look depends on a Windows feature that silently fails and leaves notes worse than today. Every Windows 11 effect needs a checked fallback.

## 3. Constraints

- **Tk limits:**
  - Tk can only fade whole windows (`-alpha`), not widgets.
  - Each window move or resize is a native call.
  - Canvas items and PIL-rendered images are the tools for anything drawn.
- **One `Toplevel` per note and per calendar.** This stays.
- **Layered windows.** The calendar always has alpha below 1 (`CAL_MIN_ALPHA = 0.92`), and notes have per-note transparency (0–90 %).
- **Windows 10 and 11.**
  - Rounded corners and shadows come from DWM on Windows 11 only.
  - On Windows 10 the app must still look right, with the C layout and square corners.
  - Mixed-DPI multi-monitor setups must keep working, with today's `app.scale` handling.
- **Single-threaded Tk.** Worker threads may decode and encode images and write files. Only the UI thread touches Tk.
- **Two languages.** All new UI text exists in Korean and English (`texts.py`).
- **`preview.py`** runs a separate copy on its own data. All checking is done there, never on the user's real notes.

## 4. Approaches considered

### 4.1 Platform
| | Approach | Trade-off | Decision |
|---|---|---|---|
| A | Restructure in place on Tk | Keeps all behaviour, low risk, and ships in phases. Limits: only whole windows fade, and moves are per window (batched). | **Chosen** |
| B | Port to Qt (PySide6) | Per-widget opacity, an animation framework, a better text editor. But it costs 60–100 MB more memory at rest and 80–150 MB more on disk, and means rewriting about 9,000 UI lines. Python 3.15 support is unknown. | Rejected: memory use goes up, and it is a rewrite |
| C | One composited overlay window | The smoothest glides. But all rendering is duplicated, and IME and selection get hard. | Rejected: too much complexity |

### 4.2 Look
These were shown as mockups (`.superpowers/brainstorm/visual/look-directions-v2.html`):
- **A "Calm":** controls fade in on hover.
- **B "Banded":** a coloured strip with 4 icons.
- **C "Margin":** a side rail and a big date.

**C was chosen for both notes and the calendar, as one theme with no switch in Settings.** For the calendar's month heading, version 3 ("big numeral") was chosen (`calendar-header.html`).

### 4.3 Motion
These were shown side by side (`motion.html`). The proposed version was chosen:
- a screen-timed clock;
- reversing from where it is;
- stand-in pictures for folds;
- three durations.

---

## 5. Design: engine

### 5.1 Animation engine: `anim.py` (new)

This replaces `ui_common.animate`/`fade`, `Motion`'s own `after` loop, `_fly_to_bin`'s loop and the flash timer.

#### 5.1.1 FrameClock (one per App)

```
clock.request(fn)          # run fn once at the next frame (input coalescing, §5.2); same fn twice = once
clock.tween(...)           # §5.1.2
clock.idle(fn)             # run fn once the clock has been idle >= IDLE_S (gc, deferred work)
clock.active -> bool
```

**Each tick runs these steps in order:**
1. `now = perf_counter()`.
2. Run the frame requests queued since the last tick (each once).
3. Step every tween with the same `now`, and write the values to their channels.
4. Flush the window batch (§5.1.4).
5. Run the `done` callbacks of tweens that finished.
6. Schedule the next tick.

**Pacing.**
- **The target** is the next display refresh:
  - At startup and on `WM_DISPLAYCHANGE`, read `DwmGetCompositionTimingInfo`, which gives `qpcRefreshPeriod` and `qpcVBlank`.
  - Each tick's next deadline is the first vblank at least 4 ms away, minus 2 ms.
  - The delay is computed from the clock (on a grid from the first frame), never as "N ms after this tick's work".
  - If DWM timing is unavailable, use a grid of 16.67 ms from the first frame.
- **High-refresh displays.** On a display faster than 60 Hz, the clock may step every second vblank. This happens when the last 10 frames' measured work takes more than 50 % of the period: on a 144 Hz screen, 16 ms of work can't fit into a 6.9 ms frame.
- **Timer resolution.** The clock holds `timeBeginPeriod(1)` from the first active tick until it has been idle for 500 ms. This moves from `ui_common._keep_timer_fine`.
- **Not running at rest.** With no tweens and no requests, nothing is scheduled. `clock.request` and `clock.tween` start the loop.

#### 5.1.2 Tweens and channels

```
clock.tween(owner, channel, to, token="long", curve=None, done=None, frm=None) -> Tween
```

- **Owner and channel.**
  - `owner` is a window or canvas object.
  - `channel` is a named property with a reader and a writer.
  - Channels:

| Channel | Value | Writer |
|---|---|---|
| `pos` | (x, y) | Queues into the window batch |
| `size` | (w, h) | Window batch; applied to a frozen window only (§5.3) |
| `alpha` | float | `attributes("-alpha")`, skipped if unchanged at 3 decimals |
| `clip` | visible height | `SetWindowRgn` (roll/fold) |
| `canvas:<tag>` | (dx, dy) | `canvas.move(tag, ...)` by the delta since the last frame |
| `place:<widget>` | relx/rely or x/y | `place_configure` (settings page slide) |
| `color:<item>` | hex | Canvas `itemconfigure(fill)` or widget `configure(bg)` |

- **One owner per (owner, channel).** A new tween on a busy channel **retargets**:
  - The new tween starts from the channel's *current* value.
  - For `pos`, `size` and `canvas`, the new curve also starts at the current velocity. The default curve is a critically damped blend: an ease-out cubic re-timed so its starting slope matches the current speed, capped at 1.5× the curve's normal starting slope. A reversal therefore slows and turns instead of snapping.
  - `frm=` forces a start value. Only used to start from somewhere else, such as a new note sliding out from behind its parent.
- **Done callbacks.**
  - A retargeted tween's `done` is **not** called; the new tween's is.
  - Callers that need "when everything in this action is done" use `Motion`'s plan-level end step, which already exists (`motion.py:_end`).
- **Stopping.**
  - `clock.stop(owner, channel=None)` stops at the current value without calling `done`.
  - When a window is destroyed, all its tweens are dropped, by a hook in `NoteWindow.destroy` and `CalendarPopup.destroy`.

#### 5.1.3 Motion on the clock

`Motion` stays the glide planner and keeps its rules:
- S1: the destination is known at once;
- S4: one plan, one glide;
- docked-calendar follow;
- jump-instead-of-sweep;
- freeze for sized notes;
- the end step: `settle_links`, then save, then `done`.

**Only how it runs changes.**
- **`run(targets)`** creates `pos` tweens, plus a `size` tween for a frozen note, on the clock.
- **`_tick`** is removed.
- **`drives(pid)`** becomes "has a live `pos`/`size` tween owned by Motion".
- **`cancel(ids)`** becomes `clock.stop` plus `_land` at the current value.
- **`finish()`** jumps every Motion tween to its end.
- **Taking over a glide.** A later plan for an id already gliding retargets its tween (§5.1.2) instead of replacing an `_Item`. That is the S4 "later plan wins" rule, now with no jump.

**Freezing happens before the clock starts the plan.**
- Shots come from the cache (§5.3), so freezing a dozen notes costs about nothing when their shots are current.
- Any stale shots are taken first, and the tweens' start time is set after that, as `run()` does today.

#### 5.1.4 Window batch

- **Batching.** In each frame, every `pos`/`size` write is collected as a dict from hwnd to its rectangle. At flush time they are applied in one `BeginDeferWindowPos` / `DeferWindowPos` / `EndDeferWindowPos` call, with `SWP_NOZORDER | SWP_NOACTIVATE`, plus `SWP_NOSIZE` when only the position changed.
- **Tk stays consistent.** Tk learns the new geometry from `WM_WINDOWPOSCHANGED`. After the flush, each moved `Toplevel`'s cached geometry is checked against what was written:
  - mismatch: that window falls back to `geometry()` from then on;
  - a debug log entry records it.
- **Off switch.** A module flag `BATCH_MOVES` (default on) switches back to plain `geometry()` calls.
- **Calendar bookkeeping.** `Motion._show` used to write `cal._xy` for a gliding calendar. Writers that do that now do it at flush time.

#### 5.1.5 Garbage collection and the clock

- **At the start of `App.__init__`**, before any window or memo exists: `gc.collect()` then `gc.freeze()`. *(Changed in Phase 1: freezing after the first windows were shown made those windows impossible to free when closed, since frozen objects are never collected.)*
- **The 30 ms `collect_garbage()` call is removed** (see §5.6). Instead, `clock.idle(collect)` runs a collection 1 s after the clock goes idle, and every 10 s at most while the app sits idle with no animation.
- **During animation:** no collection runs while the clock is active.
- **Cycles:** cycles made while animating are collected at the next idle.

#### 5.1.6 Motion tokens

| Token | ms | Curve |
|---|---|---|
| `fast` | 120 | ease-out cubic |
| `base` | 180 | ease-out cubic |
| `long` | 240 | ease-out cubic |
| `exit` | 0.67× the token used for entering (120 → 80, 180 → 120) | ease-in quad |

Each of today's constants maps onto a token (`ui_common.py:95-126`, `ui_views.py:763`, `ui_note.py:37`, `ui_common.py:1143`):

| Today | ms | New |
|---|---|---|
| TIP_FADE_MS, MENU_FADE_MS, HOVER_FADE_MS, STICKER_FADE_MS, OPEN_FADE_MS, CHIP_SETTLE_MS | 100–150 | `fast` |
| CLOSE_FADE_MS | 120 | `exit` of `fast` (80) |
| CAL_SHOW_MS (open) / close | 150 | `base` / `exit` (120) |
| ROLL_MS, DOCK_SLIDE_MS, TOAST_RISE_MS, HINT_DROP_MS, PEEK_DROP_MS, PICTURE_FADE_MS, DONE_FADE_MS | 140–200 | `base` |
| VIEW_DIP_MS | 90 | `fast` (both halves) |
| GLIDE_MS, NEW_SLIDE_MS, MONTH_SLIDE_MS, SETTING_SLIDE_MS | 220–280 | `long` |
| DELETE_FLY_MS | 350 | `long` + `fast` (fly, then the bin bounce) |
| FLASH_MS | 900 | 400 ms, date-row colour only (§6.4) |
| SCROLL_FADE_MS | 260 | `long` (a slow fade-out is intended) |

**Months now use cubic too.** `_ease_out_sine` for months goes away: §5.1.2 handles fast repeated paging by retargeting, which was the reason sine was used.

#### 5.1.7 Animation setting and reduced motion

- **New pref:** `prefs.motion` in `"full" | "reduced" | "off"`, default `"full"`.
- **Windows setting:** at startup and on `WM_SETTINGCHANGE`, read `SPI_GETCLIENTAREAANIMATION`. If Windows animations are off, the default becomes `"off"`; a value the user chose in the app still wins.
- **Reduced:**
  - `pos`/`size`/`clip`/`canvas` tweens of the `long` and `base` tokens become a `fast` alpha cross-fade (fade out, jump, fade in), or simply a jump where fading isn't possible (canvas items);
  - `fast` fades stay.
- **Off:** every tween completes in its first frame; `done` callbacks still run.
- **Settings UI:** one row, "Animations: Full / Reduced / Off" (`애니메이션: 전체 / 줄이기 / 끄기`), in the existing settings list.

### 5.2 Input: one unit of work per frame (`interact.py`, new)

- **Handlers only record.** Drag, resize, picture pan/zoom, calendar grip and calendar range-drag handlers store the latest event and call `clock.request(self._apply)`. `_apply` uses only the latest stored event.

**DragSession**, started on the button-down that begins a note drag:
- takes a snapshot of `space(exclude=group)` once and keeps it as frozen obstacles for the whole drag;
- sets `app.moving` (as today), so `NoteWindow._on_configure` does not call `space_changed()` or `request_save()` while it is set;
- runs `snap`/`hold_snap` against the frozen obstacles in `_apply`;
- moves the group's windows through the clock's window batch, so a group moves together;
- on release, behaves exactly as today: `_drag_end` → `settle_drop` / `link_drop` / `apply_plan`.

**ResizeSession** (single note and group):
- the note(s) freeze at start (shot from the cache), with the same cover as sized glides;
- `_apply` runs `app.plan_resize` at most once per frame:
  - skipped when the moved edge didn't change by at least 1 px;
  - skipped when it touches no neighbour's row or column band;
  - candidate shapes are pre-filtered to those whose row or column band overlaps the grower;
- pushed notes move through the window batch;
- on release, everything thaws and lays out once.

**`plan_growth` must give the same results as today.** In debug builds, every coalesced plan is also computed from the full input and compared; mismatches are logged.

**Others:**

| Gesture | Per frame |
|---|---|
| Picture pan/zoom | One `render()` per frame (§5.4.4) |
| Calendar grip resize | One redraw per frame |
| Calendar range drag | Count card rebuilt only when the date range changes |

### 5.3 Stand-in pictures: `shots.py` (new)

**`ShotCache`**, one per App:
- `shot(nw) -> PIL.Image`;
- `invalidate(nw)`;
- `drop(nw)`.

**Look version.** Each NoteWindow keeps a `look_version` integer, bumped on:
- text change (in the existing typing sync);
- colour, theme or font change;
- tab, view or memo switch;
- size change;
- fold state;
- pin or transparency change;
- language change.

`shot()` returns the cached image when the version matches; otherwise it captures.

**Capture.**
- Use `winapi.snapshot(win)` (PrintWindow) of that window only.
- **Snapshot correctness fix:** `old = SelectObject(mdc, bmp)`, then in `finally` call `SelectObject(mdc, old)` before `DeleteObject`.
- One copy: `frombuffer` straight from the ctypes buffer with `.copy()`, with no `buf.raw` round trip.

**Users of the cache:**

| User | How it uses the shot |
|---|---|
| `NoteWindow.freeze()` | Builds its 7 cover pieces from it |
| Roll/fold/minimize/restore | Uses it as the cover |
| Delete fly | Uses it in place of `ImageGrab` of the desktop. Keeps ½ and ¼ reductions and pastes into **one** PhotoImage per frame (`photo.paste`), never a new PhotoImage per frame. |
| Taskbar thumbnail (§5.5) | Uses it, reduced |

**Restore and unfold always have a cover.** If there's no current shot:
1. map the window at full size with alpha 0;
2. `update_idletasks()`;
3. take the shot;
4. clip to the folded height;
5. set alpha back;
6. roll.

**Memory.** Shots count against the image budget (§5.5) and are dropped when the window closes. `_roll_shot` is removed.

### 5.4 Rendering only what changed

#### 5.4.1 Calendar
- **`DayIndex`**: memos by day and the period lanes, built once per store revision (`store.revision`, bumped on any note change) and shared by `draw`, hover, peek and the right-click menu.
- Remove the unused `marked_days()` call in `draw()`.
- **Fonts:** module-level `tkfont.Font` objects per (family, size, weight), configured on scale or theme change.
- **`_fit`:** memoized by (text, width, font), with binary search.
- **Hover, selection and chip moves** update only their own items (tags per day cell: `d<yyyymmdd>`).
- **Paging:**
  - Draw the incoming month under the tag `incoming` and run the `canvas:paging` tween.
  - At the end, `delete("outgoing")` and `dtag`; no full redraw.
  - Clicks and peeks during paging use the incoming month's hit boxes and are guarded by `_paging` (fixes `_peek_at`).
  - Repeated paging retargets the tween (§5.1.2).
- **Click timing:** a day click acts at once. A second click within `DOUBLE_CLICK_MS` adds the double-click action (new memo on that day) on top.
- **Image caches:** the count card image is cached by (w, h, bg, border); tiles and dots go into the shared image cache (§5.5).

#### 5.4.2 List (`ui_views.ListView`)
- **Cards are kept by note id.** Pin or unpin moves one card. Title, body and date changes update that card's labels. A width change sets `wraplength` on the existing labels.
- **Virtualized.** A pool of card widgets covers the visible rows plus one screen above and below:
  - scrolling rebinds pool cards to notes;
  - heights come from a per-note measured-height cache, updated when a card is bound;
  - the total height is the sum of the cached heights, with an estimate for unmeasured cards.
- **Updates go only where needed.** `app.refresh_lists(note_id=None)`: with an id, only lists showing that note update that card; without one (sort, search, bin), a list re-sorts its id order and rebinds the pool.
- **The search box** filters the id list (debounced as today), then rebinds.
- **The bin** uses the same pooled list.
- **The memo preview** is one reused window per NoteWindow. Moving between child widgets of the same card no longer restarts its timer.

#### 5.4.3 Note text
- **Formatting passes cover only the touched lines.** `_refresh_bullets` and `_refresh_combined` take a line range: the lines touched by the last insert or delete, from `_typed`'s indices or the insert mark ±1 line. Tags are added or removed only where a line's mark changed.
- **The header field** uses the same typing debounce (`TYPING_SYNC_MS`) as the body, through `_sync_soon`.
- **Folded title:**
  1. cut the text to `room / min_char_width + 2` characters;
  2. binary-search the fit;
  3. cache by (text, room, font).
- **`calendar_buttons()`** only touches windows whose button state changes.
- **Preedit font:** `_show_preedit` caches its font by style and updates the overlay only when the text or position changed.

#### 5.4.4 Picture viewer (`ui_picture.py`)
- **Working copy:**
  - Keep a working copy at most 2× the note's longest side: `Image.draft()` for JPEG, `reduce()` otherwise.
  - The full-resolution source is loaded only for zoom above 1:1 and released when zooming back out.
  - Decoding runs on the image worker (§5.5), with a placeholder in the note's colour.
- **Chevrons:** sprites cached by (side, hover, colours, scale) and composited into their own small box only.
- **Rendering:**
  - one render per frame (`clock.request`);
  - `_load_note` renders once, not twice;
  - `recolor` skips re-rendering when only the pin changed.

### 5.5 Memory

**Release on close.** `NoteWindow.destroy()` and `ListView.destroy()`:
- `trace_remove` every variable trace, keeping the names `trace_add` returns (`ui_note.py:302`, `ui_views.py:55`);
- `clock.stop(owner)` for the window and its canvases;
- cancel all `_later` jobs;
- drop `viewer._source`, the working copy, inline photos, thumbnails and the shot;
- clear `App.last_note` if it points at the window.

Debug builds keep a `weakref` per closed window and log any still alive 2 s after the next idle collection.

**`images.py` (new): one `ImageCache`.**
- **Budget:** an LRU capped by **bytes** of decoded pixels. Default 64 MB; shots and working copies count too.
- **Key:** (kind, name, bucketed box, colours, scale). Boxes are rounded up to 32 px buckets.
- **Contents:**
  - pictures (`App.picture`, which replaces `_pictures`);
  - inline photos;
  - thumbnails;
  - icon photos (replaces `IconPainter._photos`);
  - calendar tiles and dots;
  - card images.
- **Theme:** a theme or accent change evicts the old theme's icon and tile entries.
- **Image worker:** one thread for decode and resize (`draft`/`reduce`/`thumbnail`) and PNG encode on paste. Results come back via `root.after(0, ...)`, and the PhotoImage is created on the UI thread.

**Taskbar thumbnail.**
- Compute the scale from the window rectangles first.
- Reduce each window's shot (`reduce` or BOX) and paste it into a canvas that is already thumbnail-sized.
- Do the corner mask on the reduced image.
- Drop `note.modified` from the signature.

**Per-setup data.** Keep the 8 most recent monitor setups (by last-seen time) in `pad.setups`, `calendar_setups`, `prefs.setup_scales` and `grid_homes`, pruned at load and when a new setup appears.

**Session lists.** `_closed` and `_recently_closed` keep only what reopen (Ctrl+Shift+T) and "close all" need: the last 20 closed pads, and the closes within `CLOSE_ALL_S`.

### 5.6 Events instead of polling (`taskbar.py`, `screens.py`)

| Today | New |
|---|---|
| `_drain_syscommands` every 30 ms | The `hook_syscommand` window proc queues the command and, if no drain is pending, schedules one `after_idle(drain)`. `hwnd → NoteWindow` is a dict kept up to date on map/destroy. The proxy's own minimize is caught as `WM_SIZE`/`SIZE_MINIMIZED` in its existing hook. The thumbnail signature check runs only when something that affects it changes (window moved, sized, shown, closed, look version), throttled to once per 500 ms. |
| `show.signal` file polled every 800 ms | `main.py`'s second instance calls `FindWindowW(PROXY_CLASS, None)` and `PostMessageW(hwnd, WM_STICKY_SHOW, 0, 0)` with `RegisterWindowMessageW("KMH.StickyNote.Show")`. The proxy hook queues a "show" like a syscommand. Fallback if the proxy window isn't found: touch the signal file, which the app checks once at startup and on each `WM_ACTIVATEAPP`. |
| Monitor poll every 1 s | `WM_DISPLAYCHANGE`, `WM_SETTINGCHANGE` with `SPI_SETWORKAREA`, and `WM_DPICHANGED`, caught by the proxy hook, start the existing settle logic (600 ms settle, 3 s max). A 15 s safety poll stays. `MONITORINFO` and argtypes are declared once at import. |
| Day check every 30 s | One `after` to the next local midnight + 1 s, plus `WM_TIMECHANGE` and `WM_POWERBROADCAST`/`PBT_APMRESUMEAUTOMATIC`. |

**Window hooks.** The ctypes `hook_ime` is installed only on windows with a text field (notes); calendars and popups don't get it. Whether `hook_syscommand` can move to the proxy alone is checked in Phase 1: it depends on whether taskbar minimize/restore of individual notes still reaches the proxy. If not, it stays per note.

### 5.7 Saving (`persist.py`, new)

- **Dirty generation.** `request_save()` bumps `dirty_gen`. The save timer serialises only when `dirty_gen != saved_gen`. Motion's end step calls `request_save()` only if the plan changed any pad.
- **`sync_from_widgets`** runs only for windows with a pending typing sync (`_later["sync"]` scheduled), not all windows.
- **Per-note cache.** Each note's and pad's dict is cached and invalidated when that note or pad changes (setters bump a per-object `rev`).
- **Compact JSON** (`separators=(",", ":")`, `ensure_ascii=False`). Loading accepts both forms.
- **Writing:**
  - The string is built on the UI thread and handed to a writer thread: write `.tmp`, `flush` + `os.fsync`, `.bak` rotate, `replace`.
  - One write is in flight at a time. A newer string replaces a queued one that hasn't started.
  - `save_now()` (exit, bin operations) waits for the writer and writes synchronously.
- **Failure handling:** a failed write is retried at the next save, and the existing error log records it.

### 5.8 Module split

The behaviour stays the same. Private reach-ins become small public methods on the owning class.

| New module | Takes from `app.py` |
|---|---|
| `registry.py` | note/pad/window indexes (`window_for` becomes a dict), open/close/reopen, `_closed` |
| `settings_ctl.py` | the ~25 setters; one `settings_changed(key)` broadcast replaces the copied "sync every Settings page" loops |
| `screens.py` | monitor model, setups, per-setup copies, change events (§5.6) |
| `layout.py` | space model, snap/magnet, find_spot, grow/close_up/give_back/settle_drop, tidy, arrange, respace |
| `taskbar.py` | proxy window, syscommands, thumbnail |
| `persist.py` | §5.7 |
| `anim.py`, `interact.py`, `shots.py`, `images.py` | §5.1–5.5 |

`app.py` keeps wiring and lifecycle. Also remove the duplicate `calendar()` definition and `import calgeom`, and replace `from ui_note import *` with explicit imports.

---

## 6. Design: the C look

### 6.1 Note window

```
┌──┬────────────────────────────┐
│ +│ 25 11월 수요일           ×  │  date row: 36 px at 100 % (keeps PILE_STEP = 36)
│ ⧉│ 이번 주 할 일               │  memo title: bold, 16 px
│ ≡│ • 디자인 시안 정리           │
│ ▦│ ☐ 회의록 보내기              │
│ ⌖│                            │
│  │                            │
│ ⋯│                            │
└──┴────────────────────────────┘
 rail 38 px
```

**Rail, top to bottom:**
- new memo (+);
- new note window (⧉);
- list;
- calendar;
- pin;
- flexible space;
- ⋯.

The ⋯ menu holds layout (style), move to bin, settings and minimize, in that order, each with its icon and shortcut as in today's menus.

**While the text field has focus (typing):**
- the rail's lower part shows the format buttons: bold, italic, underline, strikethrough, bullets, to-do, picture;
- the nav icons above stay.

**If the rail is too short** (small notes; `MIN_H` is 170):
- buttons that don't fit move into ⋯;
- priority, lowest first to move: pin, then calendar, then list; then format buttons from the end (picture, to-do, ...);
- new memo and ⋯ always stay.

**Date row:**
- **Contents:** **today's date, as now** (`date.today()`, refreshed at midnight). The day numeral, then the weekday and month in small type, then × on the right.
  - The numeral is bold, 22 px, tabular digits.
  - The small text is semibold, 12.5 px, muted, in the app's language ("11월 수요일" / "Wed, Nov").
  - The date-format setting (`prefs.date_format`) keeps applying everywhere dates appear as text (list cards, chips, period band, tooltips). The date row's numeral layout is fixed by the C look. *(Call made after the builder check.)*
  - The memo's own date and period stay where they are today (`period_band`, list, calendar).
  - `tip_date` keeps its meaning ("Today · drag to move the note · double-click: fold up").
- The date row and the rail's empty space are the drag handles. This replaces the 6 px grab strip (`GRAB_H`), so the `GRAB_H + TOP_BUTTON_H + 2` assert is updated to the new 36 px row.
- **Double-click on the date row folds/unfolds**, as today's top bar does.
- Right-click gives today's top-bar menu.

**Secondary views (list, settings, bin):**
- the date row becomes back (‹), the view title and ×;
- the rail stays.
- This replaces today's second bar (`btn_back`, `btn_close2`, `btn_min2`).

**Corners and shadow:**
- `DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND` on every note and calendar `Toplevel`;
- a DWM shadow if it can be had for these borderless, layered windows (§8, spike S1);
- the 1 px dark border goes away when DWM corners work, and stays when they don't.

**Colours:**
- Note colours (`PALETTE`, custom colours) are unchanged.
- The rail is the note colour mixed 7 % toward the ink colour.
- Icons use the existing readable-ink helpers.

### 6.2 Folded note

```
┌───────────────────────────────┐
│ 25 이번 주 할 일             ×  │   36 px; rail hidden; today's numeral + the memo's first lines
└───────────────────────────────┘
```

- **Text:** what today's folded bar shows (`_fold_lines`, joined and cut to fit, with the faster trim of §5.4.3), after today's day numeral.

- **Fold and unfold** roll on the `clip` channel with the cached shot as cover (§5.3).
- **The rail** fades with the roll: it is part of the cover picture, so nothing extra is needed.
- **Minimize, "bar" style:** rolls to this strip, then slides down and fades, as today, on the clock.
- **Minimize, sticker style:** unchanged except for timing tokens.

### 6.3 Calendar window

```
┌──────────────────────────────┐
│ 11  11월           ‹  ›      │   numeral 28 px bold; "11월" 12.5 px bold;
│     2026년                    │   "2026년" 11.5 px muted, under it
│ 일 월 화 수 목 금 토             │
│ ...                          │
└──────────────────────────────┘
```

- **Head, changed by the user after Phase 3 (2026-11-26):** the month's name is left out, because the big numeral already names the month. The year sits beside the numeral on its baseline, in 13 px muted ("11 2026년" / "11 2026"), as the note's date row does.
- **Mini view:**
  - Today's day gets a filled circle in the theme colour with white text (as now).
  - Memo dots go under the number, in the theme colour; their spacing is fixed so they never touch the number.
  - Weekend colours stay.
- **Big view:** the same top row. Chips, bands and cells keep today's layout, but use the shared fonts and caches (§5.4.1).
- **Window:** rounded corners and shadow as for notes. `CAL_MIN_ALPHA` stays.
- **Show/hide:** slides from the docking side, along that side's axis: left, right, above or below.
  - Open: `base`, 8 px slide plus fade-in.
  - Close: `exit` (120 ms).
- **Header controls (docked and undocked alike):**
  - ‹ ›, ⋯ and × are always visible, right-aligned.
  - **⋯ menu:**
    - "This month";
    - "Detach from note" / "Attach to note" (today's lock, `toggle_lock`);
    - "Big view" / "Small view" (today's expand, `toggle_expand`, which still feeds the C2 hold rule).
  - A "this month" icon appears by itself next to ‹ › whenever the shown month isn't the current one, and fades out (`fast`) when it is.
  - Dragging the top row works as today: an undocked calendar moves; a docked one moves its note.
  - *(Decided by the user after the builder check.)*

### 6.4 Smaller UX changes

1. New-note flash: 400 ms, tweening only the date-row background colour from the theme colour to the note colour.
2. Chip drop: the flying copy lands, then the chip is redrawn at its new day, so it never appears twice.
3. HolidayCard fades in (`fast`), like other popups.
4. The settings page and month paging reverse or continue from where they are (§5.1.2).
5. Hovering during the calendar's view dip no longer fights it: alpha has one owner.

---

## 7. Phases

Each phase ends with a working app, checked in `preview.py` against the perf harness.

| Phase | Contents | Done when |
|---|---|---|
| **0. Harness and spikes** | `perf.py` (debug only): frame-interval histogram per channel, handler times, private bytes (`GetProcessMemoryInfo`), GDI/USER handles, live NoteWindow count. A baseline recording script (20 notes; tidy; group drag; resize; calendar paging; 500-memo list; open/close 50 notes). Spikes S1–S3 (§8). | Baseline numbers recorded; spike results written into this doc |
| **1. Quick fixes** (nothing visible changes) | Release on close (§5.5). Remove `marked_days()`. Snapshot fix. Early-out drain (the kept hwnd dict comes with the event-driven drain in Phase 6). Header debounce. Preedit font cache. Folded-title trim. `gc.freeze()`. Motion holds the fine timer and steps on a grid. | Open/close 50 notes returns to within 5 MB of start; no other behaviour change |
| **2. Frame clock** | `anim.py`; Motion on the clock; every `animate`/`fade` call site moved; fly and flash moved; window batch; tokens; motion pref and Settings row; reduced/off modes. | Glide frame intervals within ±2 ms of the display period at p95; no Tk `after` animation loops left outside `anim.py` |
| **3. C look** | Rail, date row, fold strip, secondary views, calendar header, DWM corners/shadow or fallback, slide from dock side, §6.4 items. The fold uses today's cover mechanism (`_shot`/`_kept_shot`) until Phase 4 replaces it. | Mockup parity checked by screenshot in `preview.py` on Windows 11 (and Windows 10 if available) |
| **4. Input and stand-in pictures** | `interact.py` sessions; `shots.py`; resize cover; restore and unfold always covered; picture viewer per frame. | No frame over 2× the period during group drag and resize with 20 notes; `plan_growth` comparison shows no mismatch |
| **5. Rendering** | Calendar DayIndex/incremental/paging; virtualized list; ranged re-tagging. | 500-memo list holds ≤ 40 cards; calendar hover/selection makes no full redraw |
| **6. Images, events, saving** | `images.py` and the worker; thumbnail reduced; events in place of polls; `persist.py`; per-setup pruning. | Idle wakeups < 1/s; save with no change ≈ 0 ms; thumbnail peak < 4 MB; kill-during-save test leaves a loadable file |
| **7. Module split** | §5.8 | `app.py` < 600 lines; all phases' checks still pass |

---

## 8. Risks and spikes (Phase 0)

| # | Question | Why it matters | If the answer is no |
|---|---|---|---|
| S1 | Do DWM rounded corners and the DWM shadow apply to Tk `overrideredirect` (WS_POPUP) windows that are **layered** (`-alpha` < 1)? Try `DWMWA_WINDOW_CORNER_PREFERENCE`, and for the shadow `DwmExtendFrameIntoClientArea` with 1 px margins, or `CS_DROPSHADOW` on the class. | The calendar is always layered, and notes are layered when transparency > 0. | **Decided policy:** S1 runs in Phase 0, and its screenshots go to the user before Phase 3 starts. Unless the user then picks otherwise, the fallback ships everywhere, the same on every window whether or not it is layered, so corners never change with transparency: `SetWindowRgn` rounded corners (hard-edged), an app-drawn 1 px border, no shadow. If DWM works only on non-layered windows, the fallback is used everywhere. Phase 3's "mockup parity" means layout, type and colour; the shadow is required only if S1 succeeds. |
| S1 result | **Works (2026-11-25, Windows build 26300, `tools/spikes/s1_dwm_corners.py`).** Setting only `DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND` on the frame hwnd gives anti-aliased rounded corners **and** the DWM shadow on Tk `overrideredirect` windows, both opaque and layered (`-alpha` 0.92). `DwmExtendFrameIntoClientArea` and `CS_DROPSHADOW` add nothing; don't use them. Screenshots: `docs/perf/s1-*.png` (local, git-ignored). | | Phase 3 uses the DWM attribute. On Windows 10 the attribute is ignored and windows stay square, so keep the 1 px border there (detect via build < 22000). |
| S2 | Does `DeferWindowPos` on Tk toplevels keep Tk's geometry bookkeeping right (`winfo_rootx`, `<Configure>`), including across monitors with different DPI? | §5.1.4 | Keep `geometry()` per window (`BATCH_MOVES = False`); group moves stay one call per window, but in the same frame. |
| S2 result | **Batch OK (2026-11-25, `tools/spikes/s2_defer_window_pos.py`).** One `BeginDeferWindowPos`/`DeferWindowPos`/`EndDeferWindowPos` call moved 4 Tk toplevels; `winfo_rootx/rooty` matched and each got `<Configure>`; a 120-frame glide had 0 px drift. **Not checked:** crossing to a second monitor (only one monitor here), nor mixed DPI. | | Phase 2 uses the batch with `BATCH_MOVES` on; re-run this script on a multi-monitor setup before shipping Phase 2, and keep the `geometry()` fallback. |
| S3 | Can `DwmGetCompositionTimingInfo` be read reliably via ctypes, and do `after` delays computed from it land within ±2 ms with `timeBeginPeriod(1)`? | §5.1.1 pacing | Fall back to a 16.67 ms grid from the first frame; still a big improvement on today's free-running loop. |
| S3 result | **Works (2026-11-25, `tools/spikes/s3_frame_timing.py`).** `DwmGetCompositionTimingInfo` succeeds (packed struct, `cbSize` 292); `perf_counter` and QPC/freq share an epoch (offset 0.001 ms). This display runs at **71.9 Hz (13.9 ms)**, not 60 Hz, so the app's fixed 15 ms step beats against it. `after()` callbacks aimed at vblank − 2 ms with the 1 ms timer held landed p50 0.48 / p95 1.16 / max 4.59 ms late (target p95 ≤ 2 ms: met). | | Phase 2 paces on DWM vblank targets as designed; the 16.67 ms grid stays only as the fallback. |

**Other risks:**
- **List virtualization** touches keyboard navigation (↑/↓/Enter in search results) and scroll position. Both must be kept: test with search, pin and the bin.
- **Writer thread:** exit must wait for a pending write. `save_now` is synchronous by design.
- **Korean IME:** ranged re-tagging must not run during preedit, as today's code guards.

## 9. Left to the builder

- Exact retarget curve maths (§5.1.2), within "slows and turns, no snap".
- Internal structure of `anim.py`, `interact.py`, `shots.py`, `images.py` and `persist.py`.
- The card measured-height strategy for the virtual list.
- Exact icon glyphs (the existing icon font) and their sizes in the rail.
- Whether `hook_syscommand` moves to the proxy alone (§5.6).
- Image budget default (64 MB) tuning from Phase 0 numbers.

## 10. Calls made in the conversation (for review)

- C for both notes and the calendar, no theme switch. Version 3 calendar heading.
- Calendar day click acts at once; double-click adds the new-memo action on top.
- Animations setting: Full / Reduced / Off, defaulting from the Windows setting.
- Phase order: invisible fixes → frame clock → C look → input/pictures → rendering → images/events/saving → module split.
- Mine, not discussed:
  - the rail's button order and the ⋯ menu contents (§6.1);
  - which buttons move to ⋯ first on small notes;
  - the folded strip showing date and title;
  - the 400 ms flash;
  - keeping 8 monitor setups;
  - the 64 MB image budget.

---

## Baseline (Phase 0)

Recorded 2026-11-25 with `tools/baseline.py baseline` (`docs/perf/baseline.json`): real monitors, a scratch data folder, `STICKY_PERF=1`. Frame figures are intervals between frames, in ms (60 Hz ≈ 16.7).

| Scenario | Wall | Δ private memory | Frames (p95 / max ms) | Spans (p95 ms) | Notes |
|---|---|---|---|---|---|
| open_20 | 3.2 s | +11.7 MB | fade 24.5 / 108, flash 14.6 / 27.6, motion 30.2 / 34.8 | save 3.0 | Glides step at about 30 ms (no fine timer: A2) |
| tidy | 0.5 s | 0 | motion 19.3 / 19.3 | – | |
| group_drag (8 notes) | 1.4 s | 0 | – | drag_move 0.7 | |
| resize | 2.8 s | +0.1 MB | show 75.3 / 75.3, motion 23.4 | resize_move 0.3 | |
| calendar_paging | 3.0 s | +1.9 MB | slide 54.8, motion 54.9, page 19.6 / 71.6 | calendar_draw 14.1 | Frames of up to 55–72 ms while paging |
| typing (300 chars) | 5.7 s | +0.1 MB | – | body_modified ≈ 0 | Inserts by script, not key events: per-key handlers (`_typed`) aren't exercised. Limitation of this scenario. |
| list_500 | 6.3 s | **+45.1 MB** | – | list_refresh 148.6, calendar_draw 271.4 | Building all 500 cards took 6.0 s; **USER objects 649 → 5,277** |
| open_close_50 | 27.1 s | +8.2 MB | fade 67.3 / **200**, flash 24.3 / **207** | save 5.0 (n=101) | **70 note windows alive with 20 open: all 50 closed windows leaked (M1)** |

## Phase 1 results

Recorded 2026-11-25 with `tools/baseline.py phase1` (`docs/perf/phase1.json`), same machine and scenarios as the baseline.

| Scenario | Baseline | Phase 1 |
|---|---|---|
| open_close_50: live note windows (20 open) | **70** (all 50 closed windows leaked) | **20** (every closed window freed) |
| open_close_50: Δ private memory | +8.2 MB | +5.1 MB. A separate 200-cycle run stays flat (30.0 → 30.8 → 31.4 → 31.0 → 31.5 MB per 50 cycles): no growth per close, the rest is the allocator's high-water mark |
| Glide frames (motion p95 / max ms): open_20 | 30.2 / 34.8 | 26.0 / 31.0 |
| resize | 23.4 / 23.4 | 16.5 / 16.5 |
| open_close_50 | 20.5 / 25.6 | 18.5 / 21.7 |
| tidy | 19.3 / 19.3 | 19.2 / 19.2 |
| Folded title, 20,000-character memo (`_fit_date`) | 21,104 ms | < 50 ms (test) |
| Idle 30 ms drain, 5 notes | 7 window lookups per tick | 0 note lookups (test) |

Still slow, for later phases: fade/flash frames up to ~200 ms while windows are being built (Phase 2 clock; fade p95 in open_close_50 ranged 67–147 ms between runs, so it is noisy), calendar paging frames ~54 ms (Phase 5), and the 500-memo list (6 s, +45 MB, ~5,300 USER objects; Phase 5). Glide frames in open_20 stay above the display period because window creation blocks the loop (Phase 2).

## Phase 2 results

Recorded 2026-11-26 with `tools/baseline.py phase2` (`docs/perf/phase2.json`). Display period on this machine: **13.9 ms (71.9 Hz)**, from `DwmGetCompositionTimingInfo`. Glides are now `box` tweens on the frame clock. Frame logging counts each animation name once per tick (fixed in this phase: several windows gliding together used to log 0 ms gaps).

| Glide frames (ms) | Baseline (motion p95 / max) | Phase 1 | Phase 2 (box p50 / p95 / max) |
|---|---|---|---|
| open_20 | 30.2 / 34.8 | 26.0 / 31.0 | 13.0 / 27.0 / 31.9 |
| tidy (keep size) | 19.3 / 19.3 | 19.2 / 19.2 | 14.0 / 17.4 / 17.4 |
| resize | 23.4 / 23.4 | 16.5 / 16.5 | 13.0 / 17.3 / 17.3 |
| open_close_50 | 20.5 / 25.6 | 18.5 / 21.7 | 13.1 / 20.2 / 31.3 |

**Reading these numbers:**
- **Medians sit on the display period** (13.0–14.0 ms): frames are paced to the vblank.
- **The p95 figures include the measuring harness.** `tools/baseline.py` sleeps 4 ms between event-loop passes, which the app's own mainloop doesn't. The tidy and resize p95 values come from only 17 samples, so p95 equals the single slowest frame.
- **Done criterion (p95 within ±2 ms of the period):** met for glides that only move windows, allowing for the harness's 4 ms. **Not met** when many notes are *resized* at once:
  - With a mainloop-like pump, `tidy` to a new size moves 20 frozen notes and steps at about 27–34 ms. The clock has switched to every second vblank by design (§5.1.1), because each frame's work is over half a period.
  - That cost (resizing 20 frozen covers a frame) is Phase 4's (snapshot cache, cheaper covers).
- **`open_20` p95 of 27 ms:** windows being built block the loop for a frame. That goes away with Phase 4's cached shots.
- **Not real frame gaps:** `canvas:paging` max 128.7 ms, calendar `box`/`alpha` 58 ms, and `alpha` p95 102 ms in `open_close_50`. These are gaps *between* separate animations that start less than 250 ms apart, which the harness counts as intervals. Real paging frames: p50 14.6, p95 17.4.

**S2 re-run (2026-11-26):** batch OK on one monitor (0 px drift). A second monitor is still untested.

**Re-measured after the review fixes (2026-11-26):** this time with a mainloop-like pump (no harness sleep), on 20 open notes, 6 glides of ±120 px each:

| Glide | n | p50 | p95 | max |
|---|---|---|---|---|
| 1 note moving | 102 | 14.0 | 14.0 | 14.1 |
| 20 notes moving together | 103 | 14.0 | 14.0 | 14.6 |

**Done criterion:** met for moving glides (p95 14.0 ms against the 13.9 ms period). Mass *resize* glides still step at every second vblank (about 28 ms); this is accepted for Phase 2 and left to Phase 4. S2 on a second monitor is still untested.

## Phase 3 results

Checked 2026-11-26 on Windows 11 (build 26300, 100 %), with `tools/look_capture.py` (scratch data folder; PNGs in `docs/perf/look-*.png`, git-ignored) and a real screen grab over a plain backdrop window for the corners.

**Mockup parity (§6.1–§6.3):**

| Part | Result |
|---|---|
| Note rail | 38 px; new memo, new window, list, calendar and pin, then ⋯ at the bottom. While typing: a short line, then bold … picture. |
| Date row | Today's day in 22 px bold, with "11월 목요일" / "Thu, Nov" beside it on one baseline, and × on the right. |
| Folded strip | Exactly `px(PILE_STEP)` (36 at 100 %): the day, then the memo's lines (" · ") cut to fit, and ×. |
| List, settings, bin | ‹ back, the page's name and × in the date row; the rail stays. |
| Calendar head | "11" in 28 px bold with the year beside it ("2026년" / "2026"), then ‹ › ⋯ ×; the month name is dropped (the user's call: the numeral names it). The this-month icon shows only on another month. |
| Corners | DWM rounds the corners and draws its shadow on notes and the calendar (layered too). The 1 px border is used only where that fails. |
| Smallest note (260 × 170) | Typing: new memo, new window, bold and italic stay; the rest are in ⋯. Not typing: all five nav buttons fit. |

**§6.4:**
- The dropped chip stays hidden until its flying copy lands.
- The holiday card fades in (`fast`).
- The other three items (flash, paging, the dip) were done in Phase 2; the flash now tints only the date row.

**Calls made in this phase** (see the ledger rulings in the PR):
- A strong (tinted) note colour keeps the colour itself on the rail, as its top bar did; the others get the 7 % mix.
- **Memo dots** in the mini view keep each memo's own colour. §6.3 says the theme colour, but the colour is information (goal 5), and the mockup showed one colour.
- **"Move to the bin":**
  - it lives in ⋯, so a deleted memo now flies into ⋯;
  - the right-click menu always lists settings, layout, move to the bin and minimize.
- **Format buttons** follow the focus inside the note. Switching to another app or note keeps them as they were, so the rail doesn't jump on every window switch.
- **Fonts:**
  - no semibold face is bundled, so the small date text is Pretendard Medium;
  - Tk can't turn on tabular digits.
- **Resize grips** sit 3 px in from a corner that DWM rounds.

**Review:** a fresh whole-branch review found 0 critical, 2 important and 5 minor issues. Graded by what a user would see, five were fixed with failing tests first (`625caa9`):
- the rail emptied after an instant unfold;
- the English head was too wide (later made moot by dropping the month name);
- a back arrow was left in a folded page strip;
- every activation of a note re-laid out its rail;
- the right-click menu could bin a hidden memo.

Two rare ones are deferred (see the PR).

**Not checked:** Windows 10 (none here). The fallback path, a 1 px border with square corners, is covered by tests that force `round_corners` to fail.

## Phase 4 results

**How it was measured.** Recorded 2026-11-26 with `tools/interact_bench.py`:
- Phase 3 code: `docs/perf/phase4-before.json`.
- Phase 4 code: `docs/perf/phase4.json`.
- Each gesture runs on 20 fresh notes, made from each other so they are linked; the group is 16 notes.
- Every display frame gets 8 mouse moves through Tk's real bindings, as from a 500–1000 Hz mouse.
- Figures are the main thread's work per frame. The display period is **13.9 ms**, so 2× is 27.8 ms.

| Gesture | Before: p50 / p95 / max (ms) | After: p50 / p95 / max (ms) | Frames over 2× the period, before → after |
|---|---|---|---|
| Group drag | 14.3 / 19.8 / 21.3 | 6.4 / 7.0 / 7.4 | 0 → 0 (over 1×: 41 → 0) |
| Single-note resize (live plan) | 14.9 / 18.6 / 24.0 | 13.6 / 17.2 / 18.7 | 0 → 0 |
| Group resize (covers) | 38.4 / 44.9 / 176 | 17.9 / 20.8 / 26.3 | 60 → 0 |

**Done criterion met:** no frame over 2× the period in any gesture.

**Planning is consistent.** The live plan is computed from the boxes at the start, as before, for the latest pointer. A test checks that the coalesced plan equals the plan from the full input.

**What did it:**
- **The clock and the batch.** Handlers note the pointer and the frame clock applies it once per frame. Every window a frame moves or resizes goes into one `DeferWindowPos`.
- **Quiet `<Configure>` during gestures.** A note's `<Configure>` no longer saves mid-gesture. A frozen note is laid out once, when thawed.
- **The group ring was the largest single cost.** It is a see-through window as big as the group (1784 × 992 px). Resizing it took 11 ms a frame and redrawing it 6 ms. It now keeps room to grow, and on a plain drag it moves without redrawing.
- **Stand-in pictures:**
  - `ShotCache` keeps each note's picture by look version.
  - Linked notes are photographed while the app is idle, never during a gesture.
  - The notes in the resized note's row or column freeze at the press.
  - A single resize makes its outline window at the press.
  - Before this, the first frame of a group resize photographed 16 notes (107–176 ms).
- **Also on the clock:**
  - Unfold and restore always roll with a current picture: one is taken at alpha 0 when none is kept.
  - The delete fly is cut from the picture and pastes into one PhotoImage.
  - Picture pan/zoom and the calendar grip redraw once per frame.
  - The calendar range drag rebuilds its card only when the days change.

**Not done, by decision:**
- `plan_growth` candidates are not pre-filtered. `plan_resize` costs 0.4 ms with 20 notes, and the filter would risk the results.
- The gesture code stays in `NoteWindow` instead of a new `interact.py`; Phase 7 splits modules.
- The single resize's remaining 13.6 ms p50 is mostly the pushed notes' own window moves.
