# Sticky Note: improvement proposals (review of main, 2026-11-27)

**What was reviewed:**
- `main` at `a4d4a9f`: all of phases 0–7. This is the same version that is installed on this PC.
- Three read-only code reviews: the animation engine, the calendar, and the overall UI/UX.
- Fresh measurements on a 72 Hz display (13.9 ms per frame), on a scratch data folder.
- Screenshots of the current look.

**How sure each item is:**
- **✓** I checked it myself: measured it, tested it, saw it on screen, or read the code.
- **·** It comes from a reviewer's reading of the code and is not yet re-checked.
- **?** It is an inference about Windows or Tk behaviour that needs a quick test before building.

**Effort:** S = hours, M = a day or two, L = more.

---

## 1. Where things stand (measured today)

| What | Number | Verdict |
|---|---|---|
| Glides (tidy, drag settle, open, fold) | frames 14.0 ms median, on the display's pace | Good |
| Group drag, 16 linked notes, 8 mouse events per frame | p50 6.5 / p95 9.3 ms work per frame | Good |
| **Group resize** (16 linked notes) | p50 18.4 ms; **59 of 60 frames over budget**, so it runs at about 36 fps | Weak spot |
| Single resize (Alt) | p50 12.9 ms; 16 of 60 frames over budget | Borderline |
| Opening 20 notes in a row | glide frames p95 27 ms (window creation blocks a frame) | Known |
| **New note fade-in** | first frame lands 24 ms late, already **48% opaque**, so it pops in | Fix (B1) |
| Fold / unfold / calendar open | first frame at 5% or less of the curve | Good |
| Calendar open | 34 ms before the first frame (cold), 20 ms (warm) | OK |
| Month paging | frames p95 15 ms; fast clicks stay smooth | Good |
| Mini ↔ big switch | frames fine; the work is hidden inside the dip | OK (see C5) |
| **First day pick after start** | 138 ms, plus a 47 ms layout pass (builds the day list); later picks 9 ms | Fix (C11) |
| **Calendar redraw with 500 memos** | 106 ms (one draw, because it flushes Tk's pending layout) | Fix (C1) |
| Idle with 5 notes | no timer wakeups (from Phase 6) | Good |

---

## 2. Bugs and quick wins (all small; do these first)

| # | Problem | Evidence | Fix | Effort |
|---|---|---|---|---|
| Q1 ✓ | **With Caps Lock on, Ctrl+C turns the line into a to-do and copies nothing.** Ctrl+N opens a new window instead of a new memo. Ctrl+W and Ctrl+D do nothing. | Tested: "hello" became "☐ hello" and the clipboard was unchanged. The cause is that `<Control-C>` / `<Control-L>` / `<Control-N>` are bound without Shift (`ui_note.py:303-304, 343`). | Bind `<Control-Shift-C>`, `<Control-Shift-L>` and `<Control-Shift-N>`; add Lock variants for n, w and d; add a test with Control+Lock. | S |
| Q2 ✓ | **The big calendar hides a day's only title.** A day with 2 memos shows "+2개 더" and no title. | Screenshot. In a 52 px cell `room` is 1, so slot 0 becomes the "+N" label (`ui_calendar.py:2031-2035`). | Draw "+N" small and right-aligned in the day-number row, so every chip row keeps a title. | S |
| Q3 ✓ | **The calendar button and the pin disappear while typing.** The rail gives up pin, then calendar, then list, before any format button. | Screenshot (typing): `+ ⧉ ≡ │ B I U S • ☐ 🖼 ⋯`. Order at `ui_note.py:196, 1385-1394`. | Give up format buttons first (picture, strike, underline, italic, bold, bullets, to-do); B/I/U/S already have shortcuts. Always show the calendar button: opening it already moves the calendar over. | S |
| Q4 ✓ | **One pin icon with two meanings.** The rail pin means "always on top"; the pin on list cards means "pin to the top of the list". "모든 노트 고정 풀기" really means always-on-top. | Screenshot (list) shows both pins; `texts.py:195, 247, 301`. | Give always-on-top its own icon and the wording "맨 앞에 두기 / Keep on top"; keep 📌 and "고정" for the list only. | S |
| Q5 ✓ | **The month-icon fade leaks images.** Each frame's in-between colour becomes a new PhotoImage, cached forever. | `IconPainter.photo` keys on colour (`ui_common.py:681-688`); `_draw_head` fades through mixed colours (`ui_calendar.py:1196`). | Step through a 6-colour ramp built once per theme. | S |
| Q6 ✓ | **Done to-dos look unfinished on list cards.** "장보기" is ☑ but not struck through or dimmed. | Screenshot (list) vs the note. | Use the done style in the card's text. | S |
| Q7 · | **On the list, settings and bin pages, × closes the whole note**, not the page. Closing the last note quits the app, with no undo. | `ui_note.py:207, 404-411`; `registry.py:296-321`. | On pages, × goes back (or hide it; Esc already goes back). After a close, show a toast "노트를 닫았어요 [다시 열기]". The last note's × tooltip says the app will close. | S |
| Q8 · | **A failed save is silent.** It only goes to `error.log`. A broken `notes.json` silently loads the backup. | `persist.py:108-109`, `store.py:697-702`. | After 2 failures in a row, show a toast that stays until a save works, with "폴더 열기". Show a notice when loaded from backup. Add "메모 폴더 열기" in Settings. | S–M |
| Q9 · | **Grey hint text is too faint.** It measures 3.4–3.7:1 on the light colours, and is used for real text at 7–8 pt (dates, list heads, settings help, menu key labels). | `ui_common.py:414` (muted is only guaranteed 3:1). | Add a `muted_text` colour at ≥4.5:1 for text; keep 3:1 for icons and lines; use 9 pt minimum. | S |
| Q10 · | **Stale or inconsistent wording.** "상단 바" names a bar that no longer exists. "접기" names two actions. 끔/켬 is mixed with 끄기. English labels are lowercase. The dialog title is English in Korean mode. 15 strings are never used, two of them useful. | `texts.py` (lines in the review). | One wording pass. | S |

---

## 3. Animation: fine-tuning and optimization

### B. The engine (affects every animation)

**Done in Phase 8 (motion polish), 2026-11-27:** B1–B9, and C4's close easing. The results are in the redesign spec under "Phase 8 results". B10–B12 are still open.

| # | Proposal | Today | Change | Benefit | Effort |
|---|---|---|---|---|---|
| B1 ✓ | **Start each animation's clock at its first visible frame** | The clock starts when the animation is requested (`anim.py:168, 203`). A new note's other work (linking, glide, flash, a synchronous save) delays the first frame, which shows at 48% opacity. | `t0 = None` until the first tick, then `now − one period`. Also turn on the 1 ms timer when waking from idle. | Entrances show their whole curve; the new-note pop goes away. | S |
| B2 ✓ | **Fix the half-rate trigger** | Half rate (every second vblank) kicks in when the mean work of the last 10 ticks exceeds 50% of a frame. That window includes `done` callbacks and is never cleared when the clock goes idle (`anim.py:280-283, 340, 416`). One heavy finishing frame can put the next glide, even seconds later, at 36 fps. | Clear on idle; don't count `done`; skip each animation's first tick; decide on the median of 6, with hysteresis (enter above 0.8 × period, leave below 0.55 ×). | Glides after heavy moments run at full rate. | S |
| B3 ✓ | **Group resize at full frame rate** | 59/60 frames over budget (p50 18.4 ms), so it runs at about 36 fps. | Profile the per-frame cost (covers resized + pushed notes moved). Candidates: batch the covers' size changes into the same DeferWindowPos, skip unchanged covers, and coarsen cover redraws to every 2 px. | A smooth 72 fps group resize. | M |
| B4 ✓ | **Keep disk saves out of animation starts** | `save_now()` (JSON + fsync + 2 renames, about 5 ms with 500 memos, spikes higher) runs right where animations start: new note (`registry.py:222`), reopen, trash, close. | `save_soon()`: save when the clock goes quiet, at most 1 s later. On close, start the fade first and do the bookkeeping after. | 5–10+ ms less click-to-motion delay, and no fsync in the first frames. | S |
| B5 · | **Overlap chained phases** | Fold is a 180 ms roll, then a 240 ms close-up (420 ms in all). Minimize is 180 + 180. Group drop is 240, then a timer, then 240 (about 520 ms). Each phase stops dead, then restarts. | Fold: neighbours glide while the roll runs (about 240 ms in all). Minimize/restore: one 280 ms curve with overlapping height, slide and fade. Group drop: run the push as the plan's `done`, not on a timer. | Folding feels about 40% quicker and continuous. | M |
| B6 · | **Move the drag's companions in the same window batch** | The group ring and a docked calendar follow through `geometry()` at Tk idle, after the batched move (`ui_common.py:522`, `ui_note.py:2851`). They may trail by one frame in fast drags (?). | Queue them in the same DeferWindowPos (`clock.move`). | Note, ring and calendar move as one rigid piece. | S–M |
| B7 · | **Retune durations and curves** | Close fade is 80 ms (pops). Minimize's exit uses ease-out. Flash's colour is 97% done at 300 of 400 ms, but still configures 4 widgets per frame. Every glide is 240 ms whatever the distance. The scroll thumb fades out with ease-out. | Close 120 ms ease-in. Open 160 ms, optionally with a 6 px rise. Exits use ease-in. Flash uses smoothstep, skipping unchanged colours. Glide duration `clamp(140 + 6·√d, 180, 320)`: 100 px → 200 ms, 600 px → 287 ms. Ease-in for fade-outs. | More natural: short hops are snappy, long moves don't rush. | S |
| B8 · | **Ease snapping instead of teleporting; keep fling speed** | A snap jumps up to 24 px (engage) or 36 px (release) in one frame (`magnet.py:111-130`). The drop glide starts from zero speed. | A critically damped offset (τ ≈ 28 ms, 90% in 65 ms, no overshoot). Pass the release velocity into the drop glide (`start_slope` already supports it). | Snaps feel magnetic rather than jumpy; throws continue naturally. | M |
| B9 · | **Make the Reduced and Off modes correct** | Reduced skips by duration, so it cuts fades (which it should keep) and keeps short motions (which it should cut). Minimize in Reduced just vanishes. Off still takes shots, builds covers and pictures, and shows the start state for one frame. | Decide by kind (`move` vs `fade`). In Off, call sites take their instant paths and tweens write the end value at once. | The accessibility setting does what it says, and Off is cheaper. | S–M |
| B10 ? | **Don't fade to exactly 1.0** | At alpha 1.0, Tk removes the layered style and repaints the whole note. That lands mid-slide for a new note (inferred from Tk's source). | Fade to 0.999; set 1.0 later at idle; write alpha only when the 8-bit value changes. Verify first with a span on the last frame, and check the caret, IME and shots. | Removes a repaint hitch at the end of fades. | S |
| B11 · | **Pre-warm and per-frame trims** | The group ring window is built on the first group drag. The minimize sticker does 4× LANCZOS work in `finish`. The roll's cover PhotoImage is built in frame 1. `clip_height` re-declares the ctypes signature every frame. `_flush` makes 4 Tcl calls per window per frame. The picture cross-fade blends at full size every frame. | Build these at idle; declare ctypes once; cache the hwnd; quantize the blend to 8 steps. | Fewer first-frame hitches; less CPU per frame. | S each |
| B12 · | **Measure what reaches the screen** | perf logs one interval stream per key across all windows, so separate fades count as "gaps" (the 234 ms `alpha` figure in open_close_50 is this artifact). | Key frames by (window, key), log first-frame delay, and record DWM present stats. Then try aiming ticks just after the vblank for pure animations. | Proves B1/B10 and finds leftover judder. | S |

### C. Calendar animation and feel

| # | Proposal | Today | Change | Benefit | Effort |
|---|---|---|---|---|---|
| C1 ✓ | **Stop the calendar's draw from flushing all pending layout** | Every `draw()` → `_fit_cells()` → `update_idletasks()` (`ui_calendar.py:412`) runs every pending layout in the app: 106 ms with 500 memos (268 ms at Phase 2). Opening does 3 full draws and about 12 flushes before frame 1; a view switch draws twice. | Measure the chrome size once per view (and on recolor or scale change) and reuse it. One draw per open or switch. Holidays looked up once per draw. Keep the draw's day→memos map for hover and the menu. | Draws stay around 2 ms whatever else is happening; quicker opens and switches. | S–M |
| C2 ✓ | **The month heading moves with the page** | The numeral and year snap at the click while the grid slides 240 ms (`_draw_head` deletes and recreates them, `ui_calendar.py:1176-1182`). The year jumps sideways at 9↔10 and 12↔1. | "Odometer": the old numeral and year slide ∓10 px and fade; the new ones come in (next month from below). 120 ms ease-out; the year's x position glides. | The head and grid change as one; no sideways jump. | S |
| C3 ✓ | **Every month change slides** | Clicking a grey day of another month, double-clicking one, or clicking a note's period band changes the month with no animation (`_single`, `ui_calendar.py:1581-1585`; `ui_note.py:647-657`). | Route all of them through `_page_to`, with the direction from the date. | One consistent spatial model. | S |
| C4 ✓ | **Calendar closing, minimizing and hand-over** | Closing slides with ease-in but fades with ease-out, so 70% of the opacity is gone before it has moved: the slide is invisible (`ui_calendar.py:321-323`). On minimize, the calendar vanishes instantly while the note rolls 360 ms. Handing over to a linked note jumps. | `fade()` gets an `ease` parameter: opacity linear 80 ms, position ease-in 120 ms. Minimize plays the exit during the roll. Hand-over glides 240 ms. | The calendar visibly tucks back into its note; no pops. | S–M |
| C5 · | **Mini ↔ big without a blink** | The dip fades out with ease-out, so it is near-invisible from about 60 ms; then planning and two draws happen at the bottom. About 100+ ms of near-empty desktop shows through. | Plan before the dip (cheap after C1). Fade out with ease-in 120 ms; at the bottom one draw and the resize; wait one frame; fade in 120 ms. Morph as an option: glide the box and reveal the rows top-down (needs a spike on resizing a layered window). | The switch reads as one motion, not a flicker. | S (morph: L) |
| C6 · | **The selection glides; a "here is today" cue** | Picking a day deletes and recreates the selection tile. `clear_day` redraws the whole month to remove it. | Tween the tile to the new day (120 ms). Big view: tween the two cell fills. Clear without a full draw. When jumping to this month, a ring pulses around today (240 ms). | The eye follows the pick; today is easy to find. | S |
| C7 · | **Paging under rapid input** | Old pages are deleted only when a slide ends, so k quick clicks move k+1 pages every frame. Any outside redraw (the autosave 400 ms after typing, list refresh) cuts the slide short. Hover isn't restored after paging. | Drop pages that are fully off-canvas each frame; while sliding, outside draws only set a "redraw later" flag; restore hover at the end. Optional big-view variant: a short slide plus fade (the push moves up to 700 px). | Paging stays smooth and never snaps mid-slide. | S–M |
| C8 · | **The calendar rides in the note's window batch** | A docked calendar follows a dragged note through `<Configure>` → `geometry()`, after the batch. Dragging an undocked calendar by its head snaps and moves every linked note per mouse event, not per frame. A calendar docked below its note jumps at fold and unfold. | Move it with `clock.move` in `_apply_drag`; the head drag runs once per frame; during rolls the calendar is moved by the roll's step. | The note and calendar move as one piece. | M |
| C9 · | **Wheel, trackpad and keyboard paging** | The wheel over the grid only steps through a day's memos. Delete is the only key. ‹ › don't repeat when held. | Wheel over the head (or over an empty day) pages, one page per 120 delta, at most one per frame. Keys: PageUp/PageDown, Home (+ C6 pulse), arrows move the selection, Enter opens, Ctrl+N makes a memo on that day, Esc closes. Holding ‹ › repeats (400 ms, then every 150 → 90 ms). | Fast navigation without aiming at small arrows. | M |
| C10 · | **Memo drags: per frame, and across months** | The dragged memo's ghost is deleted and rebuilt on every mouse event. You can't drag a memo into another month. | Build the ghost once and move it per frame. Rest near the edge (or on ‹ ›) for 500 ms to page while dragging. | Smoother drags; rescheduling to next month works. | M |
| C11 ✓ | **A fast first day pick** | The first pick after start takes 138 ms + a 47 ms layout pass (it builds the day list); later picks take 9 ms. | Build the day-list view at idle after the calendar opens. | The first click feels like every other click. | S |
| C12 · | **Day preview: glide between days, fade out** | Moving to another day replays the 10 px drop; leaving destroys the preview at once. | Glide the open preview to the next day (120 ms); fade out over 80 ms and reuse the window. | Sweeping across days feels fluid. | S |
| C13 · | **Calendar content** | The mini view caps memo dots at 3 with no sign of more. A holiday's name appears only after clicking the day, which also switches the note to that day's list. | With 4+ memos: 2 dots and a wider pill. A red day shows its holiday card on hover. | Denser information without clicks. | S |

---

## 4. UI/UX: further polish

| # | Proposal | Today | Change | Effort |
|---|---|---|---|---|
| U1 ✓ | **Contextual tips instead of the first-run wall** | 9 tips in one box. It fits a new note at 100% scaling, with "알겠어요" right at the bottom edge; at 125–150% it likely spills off (?). "Double-click a day for a new memo" is taught nowhere. | Short term: cap the height (scroll inside) and add × at the top. Better: one-time tips at the moment they matter: first link ("Alt로 따로 끌기"), first close (Ctrl+Shift+T), first fold, first calendar. Add a "단축키와 조작" page in ⋯ and Settings. | M |
| U2 · | **One menu everywhere, and a text menu** | ⋯ shows 4 items; tidy, fold all, reopen closed and others live only in the right-click menu. The memo text has no context menu. A picture pasted into a text memo does nothing. | ⋯ = the right-click menu. Text menu: cut, copy, paste, paste picture, select all, bullets, to-do. Paste a picture at the cursor (inline pictures already exist). | S–M |
| U3 · | **Keyboard gaps and a focus cue** | No keys for search, the calendar, settings, keep-on-top or minimize; no way to move between notes from the keyboard. Tk's leftovers are live: Ctrl+K deletes to the end of the line, Ctrl+O inserts a line, Ctrl+H is Backspace. Nothing shows which note has the keyboard. | Ctrl+F (search), Ctrl+Tab (next note), Ctrl+Enter (tick a to-do), Ctrl+M (minimize), Ctrl+, (settings), Shift+F10 (menu). Turn off Ctrl+K/O/H. The active note's rail is a shade stronger. | M |
| U4 · | **Formatting is not undoable** | Ctrl+Z after Ctrl+B undoes the previous typing, not the bold (Tk's undo records text only). | Record format changes on the app's own undo stack. | M |
| U5 · | **Resize from the edges** | Only the 12 px corner grip resizes. | Add 4 px edge hit zones (right, bottom), with matching cursors. | S |
| U6 · | **Dark theme** | Charcoal is the only dark colour; nothing follows the Windows theme. | A "follow Windows" option: dark variants of the palette, with the calendar and menus included. | M–L |

---

## 5. New ideas that fit the app

| # | Idea | How it builds on what exists | Effort |
|---|---|---|---|
| N1 | **Start with Windows** | A Startup-folder shortcut via the existing `shortcut.create`, plus a toggle in Settings › General. A second launch already just wakes the running app. | S |
| N2 | **Quick-capture hotkey** (Ctrl+Alt+N, configurable) | Register the hotkey on the taskbar window; handle it in the existing window-message hook; open a new note from the last one and focus it. Show a notice if another app owns the key. | M |
| N3 | **Markdown-style line starts** | "- " → bullet, "[] " → to-do, "[x] " → done, using the existing line-mark toggle. Backspace right after already undoes it. Skipped during Korean IME composition. | S |
| N4 | **Better search** | Several words match as AND; 초성 matching (ㄱㄴㄷ…) when the query is all consonants; a "최근 수정순" sort (the code says "last edited" but sorts by created date); colour chips to filter. | S–M |
| N5 | **Dates that mean something** | When a memo's date isn't today, the big numeral shows the memo's date with "D-2" / "3일 전". At midnight or wake: "오늘 메모 n개", opening today's list. Later: an optional reminder time that brings the note forward and flashes its taskbar button. | S (reminders M) |

---

## 6. Suggested order

1. **Phase 8: motion polish** (B1–B9; done 2026-11-27, chosen first). The biggest gain in feel per hour.
2. **Phase 9: quick fixes** (Q1–Q10, C3, C11; C4a was done in Phase 8). Mostly an afternoon each; Q1 and Q2 are real bugs.
3. **Phase 10: calendar motion** (C1, C2, C5, C6, C7, then C8, C9, C10, C12, C13).
4. **Phase 11: features** (N1, N3, N4 are small and high value; N2 and N5 next; U-items as they fit).

Each phase would run like the earlier ones: a plan, tests first, a fresh review, then the results recorded in the spec.
