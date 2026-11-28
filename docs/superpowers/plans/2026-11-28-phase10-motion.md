# Phase 10: motion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the calendar's real grow/shrink morph, and five typing touches (A gliding caret, B breathing caret, D to-do settle, I format confirm, K saved dot), all on the frame clock and free between animations.

**Architecture:** every effect is a short `anim.animate(widget, key, ms, step, done, ease, kind=...)` run with cached colours or pictures; nothing runs while idle. The caret is one overlay Frame over the text box (Tk's own caret hidden), handing back to Tk's caret while the IME composes (`_show_preedit`). The calendar morph is a picture cover scaled into the resizing window (spike: 92 % alpha resize costs the same as opaque).

**Tech Stack:** Python 3 + Tk (bundled runtime), PIL. Tests: unittest, always run with `tools/hidden_tests.py`.

**Spec:** docs/superpowers/specs/2026-11-28-phase10-motion-design.md

## Global Constraints

- Motion setting: Reduced keeps fades and drops moves (`kind="move"` jumps); Off ends every effect at once.
- No timer or redraw while nothing animates (the idle bench must stay where phase 8 left it).
- Korean composition looks exactly as today: no effect touches the text while a syllable is composed.
- Never touch %APPDATA%\StickyNote; tests and captures on the hidden desktop only.

## Review Focus

1. Typing fast (key repeat, 30+ chars/s): the glide never lags the real insert point by more than one frame's move.
2. IME composition start/end mid-glide: the overlay hides and Tk's caret shows the same frame.
3. Clicking the calendar's size button twice quickly: the second click turns the morph back, never two morphs.
4. A note's colour or theme changing mid-animation: the next frame uses the new colours (no stale ramp).
5. Closing a window mid-animation: no TclError, no job left on the clock.

---

### Task 1: Calendar grow/shrink morph

**Files:** Modify `StickyNote/app/ui_calendar.py` (`click_view`, new `_morph_view`); Test `tests/test_phase10_morph.py`.

**Interfaces:** Produces `CalendarPopup._morph_view(view: str) -> None` (replaces the dip in `click_view`); key `"morph"` on the calendar's top; `CAL_MORPH_MS = anim.BASE` in ui_common.

- [ ] Tests: after `click_view("big")` and settling, the window box equals the big view's box and the live view is big; mid-morph (`pump` half of CAL_MORPH_MS) the window is between the two sizes and a cover canvas is mapped; after the end no cover remains; Reduced: no in-between size (box jumps, alpha fades); Off: instant, no cover ever; a second click mid-morph ends at the first view; a docked calendar's top stays level with its note through the morph.
- [ ] Run (hidden): expect FAIL.
- [ ] Implement: picture of the old view (`shots`), live view switched at once under a cover canvas in the calendar's own window; per frame `geometry` tween plus paste of the scaled picture into one PhotoImage (half-size source below 0.5 scale, as `_fly_to_bin`); cross-fade to the new view's picture in the last third; cover destroyed at the end.
- [ ] Run (hidden): PASS; run `tools/interact_bench.py` on the hidden desktop: frame p90 under 8 ms.

### Task 2: Overlay caret, gliding (A)

**Files:** Create `StickyNote/app/caret.py` (`class GlideCaret`); Modify `ui_note.py` (make it, hook focus/keys/preedit); Test `tests/test_phase10_caret.py`.

**Interfaces:** `GlideCaret(nw)`, `.follow()` (to `bbox("insert")`, eased over `CARET_GLIDE_MS = 70`), `.hide()`, `.show()`, `.recolor(color)`; `body.configure(insertwidth=0)` while it shows.

- [ ] Tests: typing then settling puts the overlay at `bbox("insert")` x and height; mid-glide it is between; preedit shown → overlay unmapped and `insertwidth` back to normal; selection or focus out → overlay unmapped; Off → overlay jumps; no clock job after the glide ends.
- [ ] Implement; run hidden: PASS.

### Task 3: Breathing caret (B)

**Files:** Modify `caret.py`; Test `tests/test_phase10_caret.py`.

**Interfaces:** `CARET_BREATH = 6` colour steps from the caret colour to the page; `GlideCaret.breathe()` started after `CARET_REST_MS` (Windows' blink time) without keys.

- [ ] Tests: while typing the overlay is the solid caret colour; after the rest it steps through exactly the 6 cached colours; unfocused: no job on the clock; a theme change rebuilds the ramp.
- [ ] Implement; run hidden: PASS.

### Task 4: To-do settle (D)

**Files:** Modify `ui_note.py` (`_todo_click` / `toggle_todo` done path); Test `tests/test_phase10_todo.py`.

**Interfaces:** `TODO_SETTLE_MS = 180`; tags `settle0..settle4` (cached colours from text to done).

- [ ] Tests: ticking a line ends with the done look (same tags as today) after TODO_SETTLE_MS; mid-way the line carries one `settle` tag; unticking reverses; Off: final look at once; saved text identical to today's.
- [ ] Implement; run hidden: PASS.

### Task 5: Format confirm (I)

**Files:** Modify `ui_note.py` (`toggle_format`, bullets/to-do from keys); Test `tests/test_phase10_confirm.py`.

**Interfaces:** `CONFIRM_MS = anim.BASE`; the rail button's chip grows in (`IconButton.pulse()`), the changed range gets a fading tint tag `confirm`.

- [ ] Tests: Ctrl+B on a selection pulses `btn_bold` and ends with no `confirm` tag left; with the button in ⋯ (or the rail hidden, phase 11) no pulse, the tint still shows (settled); Off: no tint.
- [ ] Implement; run hidden: PASS.

### Task 6: Saved dot (K)

**Files:** Modify `ui_note.py` (date row canvas), `persist.py` (`_save_result` hook); Test `tests/test_phase10_saved.py`.

**Interfaces:** `SAVED_DOT = 6` px, `SAVED_DOT_MS = anim.LONG`; `NoteWindow.saved_dot(ok: bool)`.

- [ ] Tests: a working save after typing shows the dot on the typed-in note and it fades away; not on the autosaves while typing, only the one after a pause (settled); a failed save shows it in `danger` and it stays until a save works; folded and page views: no dot.
- [ ] Implement; run hidden: PASS.

### Task 7: Scrolling (thumb, smooth, bounce)

**Files:** Modify `StickyNote/app/ui_common.py` (`OverlayScroll`, `ScrollArea`), `ui_views.py` (`ListView` wheel), `ui_note.py` (body wheel); Test `tests/test_phase10_scroll.py`.

**Interfaces:** `SCROLL_EDGE = 12` px reveal zone; `SCROLL_SMOOTH_MS = anim.FAST`; `SCROLL_BOUNCE = 12` px; `OverlayScroll.reveal()`; `ScrollArea.scroll_by(units)` (smooth), `ListView.wheel(event)` (smooth).

- [ ] Tests: the pointer at the right edge of a long list shows the thumb; the width eases 5 -> 8 px (mid-way between); a wheel notch ends at the same place as today's jump, passing through in-between positions; at the top, a wheel up moves the content down at most SCROLL_BOUNCE px and back to 0; the memo text never bounces; Reduced: jumps and no bounce; a wheel mid-scroll continues from where it is (no jump back).
- [ ] Implement; run hidden: PASS; interact bench hidden: list scrolling p90 frame unchanged or better.

### Task 8: Whole-phase check

- [ ] Full suite hidden (progress posted in the chat), `tools/idle_bench.py` and `tools/interact_bench.py` hidden (no idle regression), captures of each effect mid-way, a fresh whole-phase review, a safety stash.
