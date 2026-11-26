# Phase 5: Rendering Only What Changed, Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- A memo list of any length keeps at most 40 cards alive.
- Calendar hover, day selection and memo picks repaint only what changed.
- Typing re-tags only the lines it touched.

**Architecture:**
- **List:** the list becomes a virtual column. Every row (part head or memo card) has a y offset from a measured-height cache. Only rows within one screen of the view exist as widgets, `place`d at their offsets in the scroll area's inner frame. The rest are just height.
- **Calendar:** selection and picks re-style the tagged items of the days and chips involved.
- **Typing:** the formatting passes take a line range.

**Tech Stack:** Python 3.15, Tkinter. Tests use stdlib `unittest` with `tests/_support.py`.

**Spec:** `docs/2026-11-25-redesign-design.md` §5.4.1–§5.4.3 and §7 (Phase 5 row: "Calendar DayIndex/incremental/paging; virtualized list; ranged re-tagging"; done when "500-memo list holds ≤ 40 cards; calendar hover/selection makes no full redraw").

## Global Constraints

- **The list keeps today's behaviour:**
  - parts (pinned, others) with fold/unfold and the sort switch;
  - search (debounced);
  - the day filter;
  - ↑/↓/Enter picking;
  - hover preview;
  - the card menu, pin and trash icons, pictures on cards and the bin link.
- **The calendar draws the same pixels as today** for the same state.
- **Korean IME:** no re-tagging during preedit (today's guard stays).
- **Data:** never touch `%APPDATA%\StickyNote`.
- **Tests:** run with `.\StickyNote\runtime\python.exe -m unittest discover -s tests`. All 165 existing tests stay green.

## Measured before

From Phase 1:
- `list_500`: building all 500 cards took 6.0 s and +45 MB, with USER objects 649 → 5,277.
- Calendar day pick: a full `draw()`.

## Review Focus

1. **Arrow-key picking beyond the built rows:** the picked card must come into view (built) and Enter must open it.
2. **A card whose height changes when built** (pictures, long text): rows below must not overlap or leave gaps, and the scroll range must follow.
3. **Fold or unfold a part, sort switch, search, day filter, pin/unpin on a long list:** the right rows show, and the view is not left past the end.
4. **The list's width changes (note resized):** heights re-measure and nothing overlaps.
5. **Calendar selection with paging or a view switch:** no stale selection tile.

## Decisions

- **No `DayIndex` per store revision.**
  - The store has no revision counter, and notes are changed in place in many places, so an index keyed by one would go stale.
  - `_memos_by_day` stays per draw. Hover already repaints only its two days (since Phase 1).
  - This is ledgered as a ruling.
- **Picture viewer (§5.4.4)** goes with images in Phase 6, per the §7 phase table.
- **List geometry:**
  - `VROW_PAD = 8` (px at 100 %) is the gap under a card, as today's `pady`.
  - A row's estimated height before it is measured: 96 px for a card, 28 px for a head.
  - `KEEP_SCREENS = 1`: rows within one screen above and below the view are built.

---

### Task 1: Calendar selection and picks without a full redraw

**Files:**
- Modify: `StickyNote/app/ui_calendar.py` (`pick_day`, `_single`, chip pick and unpick, a new `_show_selected(old, new)`)
- Test: `tests/test_calendar_render.py`

- [ ] Test `test_pick_day_no_full_draw`: in the mini view, `pick_day(iso)` makes no `draw()` call (Spy), and one item tagged `selected` sits at that day's spot. Picking another day moves it.
- [ ] Test `test_pick_day_big_view_no_full_draw`: in the big view, `pick_day` makes no `draw()`, and the old and new day cells' fills equal `_big_fill(day, False)`.
- [ ] Test `test_chip_pick_no_full_draw`: in the big view, picking a memo chip (click) makes no `draw()`. Its rectangle's fill is the picked shade and the previous pick's is back to rest.
- [ ] Run, watch them fail, then implement and run until they pass. Run the full suite.
- [ ] Commit: `perf(calendar): picking a day or a memo repaints only those`.

### Task 2: The memo list is a virtual column

**Files:**
- Modify: `StickyNote/app/ui_views.py` (`ListView`: `refresh`, `_section`, `_card` building into a row container, the new `_rows`/`_layout_rows`/`_sync_window`, `shown_ids`/`step_pick`/`pick`, `_on_resize`, the scroll hook), `ui_common.py` (`ScrollArea`: a scroll callback)
- Test: `tests/test_list_virtual.py`

**Interfaces:**
- `ListView.rows`: a list of `Row(kind, key, height, measured, widget)`, where kind is `"head"` or `"card"` and key is a part name or note id.
- `_sync_window()` builds the rows within `KEEP_SCREENS` of the view and destroys the others (their measured heights are kept).
- `live_cards() -> int` (tests).
- `self.cards` keeps today's meaning for the cards that exist.

- [ ] Test `test_500_memos_keep_few_cards`: with 500 memos, after `show_list()` and scrolling top to bottom in 20 steps (pump each), `live_cards() <= 40` at every step, and at the end the last memo's card exists and is mapped.
- [ ] Test `test_rows_do_not_overlap`: after scrolling to the middle, every built row's y equals the previous row's y plus its height plus `px(VROW_PAD)`. The scroll region height equals the sum.
- [ ] Test `test_arrow_keys_reach_unbuilt_cards`: from the top, pressing ↓ 60 times picks the 60th memo, its card exists and is in view, and Enter opens that memo.
- [ ] Test `test_search_and_fold_on_long_list`: a search for one memo's unique word shows exactly that card. Clearing it, then folding "others", leaves no memo cards built. Unfolding brings them back.
- [ ] Test `test_width_change_remeasures`: resizing the note wider and pumping keeps `test_rows_do_not_overlap`'s rule.
- [ ] Update `tools/baseline.py` `list_500` to scroll instead of `_build_more`.
- [ ] Run, watch them fail, then implement and run until they pass. Run the full suite.
- [ ] Commit: `perf(list): a virtual column keeps only the cards near the view`.

### Task 3: Typing re-tags only the touched lines

**Files:**
- Modify: `ui_note.py` (`_refresh_bullets(first=None, last=None)`, `_refresh_combined(first=None, last=None)`, their callers: `_typed`, `_after_edit`, `_on_body_modified`)
- Test: `tests/test_ranged_tags.py`

- [ ] Test `test_typing_retags_only_near_lines`: in a 3000-line memo, a keystroke on line 1500 calls `body.tag_remove`/`tag_add` only with indexes on lines 1499–1501 (Spy on the Text widget's methods).
- [ ] Test `test_tags_still_right`: a scripted edit sequence gives the same tag ranges as a full refresh:
  - typing a bullet line;
  - joining two lines with Backspace;
  - pasting three lines;
  - toggling bold over two lines.
- [ ] Run, watch them fail, then implement and run until they pass. Commit: `perf(note): typing re-tags only the lines it touched`.

### Task 4: Measure and write results

- [ ] Run `tools/baseline.py`'s `list_500` and a calendar pick timing. Record live cards, list build time, USER objects and memory in a "Phase 5 results" section of the spec.
- [ ] Commit: `perf: phase 5 results`.
