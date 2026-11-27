# Feedback UI Implementation Plan (after Phase 8)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the calendar's edge bugs. Build the six UI choices the user picked on 2026-11-27: menus B, pages D, calendar hover B, minimize B, wording C, calendar size B plus an expand button.

**Architecture:**
- Every motion runs on Phase 2's frame clock with Phase 8's kinds, so Reduced and Off handle them as they do everything else.
- Tk can't fade widgets inside a window, so the page change animates a picture of the two pages on a cover canvas. This follows the pattern of Phase 4's freeze and roll covers.

**Spec:**
- The user's feedback list and picks (this conversation, 2026-11-27).
- The redesign spec `docs/2026-11-25-redesign-design.md` for everything these don't change.

## Global Constraints

- **No conflict with Phases 1–8.** These rules stay as they are:
  - the motion tokens (FAST, BASE, LONG = 120 / 180 / 240);
  - Phase 8's kinds (Reduced keeps fades and cuts moves; Off ends everything at once);
  - the C look's sizes: the calendar head keeps its width and the mini calendar its least size;
  - docked-calendar sides;
  - double-click on a calendar *day* makes a new memo;
  - double-click on the note's date row folds it;
  - Undo, links and the magnet.
- **Tests:** `.\StickyNote\runtime\python.exe -m unittest discover -s tests`. All existing tests stay green; new ones go in `tests/test_feedback_ui.py` and `tests/test_calendar_feedback.py`.
- **Data:** never touch `%APPDATA%\StickyNote`.

## Tasks

1. **Calendar big/small near an edge** (done, `cd1baef`): a docked view switch keeps its side; big is clamped to the room there, or stays mini when even its least size doesn't fit.
2. **Menus (B):**
   - `PopupMenu.popup` and `FontPicker.open` open with a 6 px drop (a move, `clock.glide`) and a fade over MENU_FADE_MS (120 ms, ease-out). A menu that flips upward rises 6 px instead.
   - `close()` lets go at once (`current = None`, the grab released, the window disabled), fades out over `exit_ms(MENU_FADE_MS)` (80 ms, ease-in), then destroys the window.
   - Tests: the drop starts 6 px above; close leaves `PopupMenu.current` None at once and destroys the window after the fade; in Off it is gone by the next frame.
3. **Calendar day hover (B):**
   - The hovered day fades in over FAST (120 ms, ease-out); the day left fades out over BASE (180 ms, ease-in), with `kind="fade"`.
   - Mini view: tiles from a ramp of 5 colours (cell background to hover), built once per theme and size.
   - Big view: the cell fill steps through the same ramp.
   - `draw()` stops any hover fades.
   - Tests: after entering a day the tile is mid-ramp at the first frame and full at the end; leaving fades out and removes the tile; the count of tiles stays bounded (at most 5 per size).
4. **Minimize button (B):**
   - `btn_min` (GLYPH "minimize", tooltip "최소화") sits left of × on the date row and calls `minimize_button`, so the "Top bar only" setting still folds.
   - Included in `_draw_row`'s room, in `recolor`, in the flash, and in the group-resize cover's right-hand piece.
   - Tests: clicking it minimizes the note (and with "bar" style it folds); the date text never runs under it.
5. **Wording (C):**
   - `none_on` becomes "메모 없음" / "No memos" (the big calendar icon stays above it; the day is in the filter bar).
   - `new_on_day` becomes "새 메모" / "New memo", with the add glyph drawn beside it.
   - Tests: the day page shows the short texts; the button carries an image.
6. **Calendar size (B and the expand button):**
   - Double-click on the calendar's head (frame or month label) runs `toggle_expand`.
   - A ⤢ button (GLYPH expand / shrink, tooltip "크게 보기" / "작게 보기") goes between › and ⋯.
   - All six head buttons become 20 px wide, so the head keeps its 220 px (6 × 20 = 5 × 24).
   - Tests: a double-click on the head toggles the view; the button toggles it and its glyph follows the view; the head's requested width is unchanged.
7. **Page change (D):**
   - `_show_view` animates a cover over the page area: the old page's picture and the new page's picture (from `shots.fresh`) blend over BASE (180 ms) while shifting 12 px (ease-out): forward to the left, back to the right.
   - Reduced: the fade only. Off, unmapped, folded, or no picture: instant, as today.
   - Tests: a switch puts a cover up and it is gone after 180 ms with the new page showing; in Off there is no cover.
8. **Final:** a fresh review of the branch, the fixes, and the full suite.
