# List Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Calm list cards: title first, paper-lift depth, the current memo in its own tone, and a tint-and-lift on hover and arrow keys.

**Architecture:** A pure colour helper works out each card's colours once. `ListView._card` builds the new layout with fixed-height spacers so a lift never changes a row's height. One frame-clock animation per card steps through a 5-level ramp.

**Tech Stack:** Python 3, Tk, the app's `anim` frame clock.

**Spec:** `docs/superpowers/specs/2026-11-28-list-cards-design.md`

## Global Constraints

- Ramp of `CAL_HOVER_STEPS` (5) levels; in `CAL_HOVER_IN_MS` (120 ms, ease-out), out `CAL_HOVER_OUT_MS` (180 ms, ease-in); `kind="fade"`.
- Shadow weights toward black: rest (0.10, 0.06, 0.03), lifted (0.14, 0.10, 0.06, 0.03); ×3 on a dark page.
- Least hover contrast `contrast(rest, lit) >= 1.12`; label and footer text ≥ 4.5:1 on `lit`; edge `readable(…, rest, 2.2)`.
- A card's requested height is the same at rest and lifted.
- Tests: `.\StickyNote\runtime\python.exe -m unittest discover -s tests`; all 281 existing tests stay green.
- Never touch `%APPDATA%\StickyNote`.

## Review Focus

- A memo the same colour as the note's page: the card must still show (rest ≠ page). Test in Task 1.
- White and grey memos: the hover tint must still be visible. Test in Task 1 (every PALETTE colour).
- Charcoal (dark) memo: edge and label light, shadow darker than the page. Test in Task 1.
- Hover in and out quickly: the lift reverses from where it is and ends at rest. Test in Task 3.
- 500 memos, arrow keys past unbuilt cards: the picked card is lit once built (existing `test_list_virtual` stays green; Task 3 adds the lit check).

---

### Task 1: Card colours

**Files:**
- Modify: `StickyNote/app/ui_views.py` (new module-level helper near the top)
- Test: `tests/test_list_cards.py`

**Interfaces:**
- Produces: `card_colors(widget, note_color: str, page_bg: str) -> CardColors`, a NamedTuple with `rest, lit, fg, muted, edge, label, rest_strips: tuple[str, str, str, str], lit_strips: tuple[str, str, str, str], ramp: list[tuple[str, tuple[str, ...]]]` (ramp[i] = (bg, strips) for level i = 0..5). `rest_strips[3] == page_bg`.

- [ ] **Step 1: Write the failing tests** — `CardColorsTest`:
  - `test_every_palette_colour_has_a_visible_tint`: for each `PALETTE` colour on page `#FFF4A3`, `contrast(rest, lit) >= 1.12`.
  - `test_same_colour_as_page_still_shows`: `card_colors(w, "#FFF4A3", "#FFF4A3").rest != "#FFF4A3"`.
  - `test_label_and_footer_read`: `contrast(label, lit) >= 4.5` and `contrast(muted, lit) >= 4.5` for each PALETTE colour.
  - `test_edge_keeps_the_hue`: for `#CFE6FF`, the edge's HLS hue is within 0.05 of the memo's.
  - `test_charcoal`: for `#2E2E2E` on a `#2E2E2E` page, `luminance(edge) > luminance(rest)` and the first rest strip is darker than the page.
  - `test_ramp_ends`: `ramp[0] == (rest, rest_strips)` and `ramp[5] == (lit, lit_strips)`, length 6.
- [ ] **Step 2: Run** `.\StickyNote\runtime\python.exe -m unittest tests.test_list_cards -v` (from `tests` on the path, as `discover` does): FAIL, `card_colors` not defined.
- [ ] **Step 3: Implement `card_colors`** with `Colors.of`, `shade`, `_mix`, `readable` and `contrast` from `ui_common`, using the spec's values.
- [ ] **Step 4: Run the tests:** PASS.

### Task 2: The new card

**Files:**
- Modify: `StickyNote/app/ui_views.py` (`ListView._card`, `card_preview`), `StickyNote/app/texts.py` (`open_elsewhere`)
- Test: `tests/test_list_cards.py`

**Interfaces:**
- Consumes: `card_colors`.
- Produces: `self.cards[note_id] == (outer, card)` (unchanged); `card.lifts` is a `CardLift` object (Task 3 fills its motion) with `set(level: int)`, `level: int`, `edge` (the edge Frame or None), `strips: list[Frame]` (4).

- [ ] **Step 1: Write the failing tests** — `CardLookTest` (list of 3 memos, the window's own memo current):
  - `test_no_border_or_band`: `outer.cget("bg") == page bg`; no child Frame of `card` has a `bg` different from `rest` except the edge.
  - `test_current_has_own_tone_edge`: the current card's `lifts.edge` exists with bg `edge`; others have None.
  - `test_four_shadow_strips`: `len(card.lifts.strips) == 4`, colours `rest_strips`.
  - `test_lift_keeps_height`: `outer.winfo_reqheight()` is the same after `lifts.set(5)` and `lifts.set(0)`.
  - `test_done_todo_is_struck`: a memo with "☑ 장보기" shows a Label with an overstrike font and `fg == muted`.
  - `test_title_one_line`: a 200-character header shows as one line ending in "…".
  - `test_open_elsewhere_words`: a memo open in another window shows `tr("open_elsewhere")` in its footer.
- [ ] **Step 2: Run:** FAIL.
- [ ] **Step 3: Rebuild `_card`:** outer (page bg) → top spacer (1 px) → card (`rest`) → 4 strips → bottom gap (`px(4)`). Card: title row (title label; pin and trash labels always packed, a transparent same-size picture when hidden), preview lines (one label per line; "☑" lines overstrike and `muted`), pictures, footer ("현재 메모" in `label` + " · date" in `muted`, or the window icon and words). Edge: `place(x=0, y=0, width=px(3), relheight=1)`, `keep_bg`. `open_elsewhere` becomes ("다른 창에 열림", "Open in another window").
- [ ] **Step 4: Run** the new tests and `tests.test_list_virtual`: PASS.

### Task 3: Tint-and-lift motion

**Files:**
- Modify: `StickyNote/app/ui_views.py` (`CardLift`, hover and `picked` in `_card`)
- Test: `tests/test_list_cards.py`

**Interfaces:**
- Consumes: `CardLift` from Task 2.
- Produces: `CardLift.to(target: int, fade: bool = True)`.

- [ ] **Step 1: Write the failing tests** — `CardMotionTest`:
  - `test_hover_lifts_through_the_ramp`: after `<Enter>` the first frame shows a level in 1..4; after settling, level 5, card bg `lit`, pin and trash shown.
  - `test_leave_returns_to_rest`: after `<Leave>` and settling, level 0, bg `rest`, icons hidden (a pinned memo's pin stays).
  - `test_quick_in_and_out_reverses`: enter, one frame, leave: it settles at level 0 and never reached 5.
  - `test_arrow_pick_lifts`: `step_pick(1)` lifts the first card; `step_pick(1)` again lifts the second and returns the first to 0.
  - `test_off_is_instant`: with motion "off", `<Enter>` gives level 5 at the next frame.
  - `test_picked_card_built_later_is_lit`: with 60 memos, 40 × `step_pick(1)`; the picked card, once built, has level 5.
- [ ] **Step 2: Run:** FAIL.
- [ ] **Step 3: Implement `CardLift.to`:** `animate(card, "lift", ms * abs(target - level) / 5, step, done, ease=…, kind="fade")`, where step sets `round(start + (target - start) * k)` only when it changes; `set(level)` paints card widgets (not `keep_bg`), strips and icons from `ramp[level]` and swaps the spacers at level ≥ 3. Hover and `picked` call `to(5 if hovered or picked else 0)`; `_make_row` keeps calling the painter for a picked card.
- [ ] **Step 4: Run** the whole suite: PASS (281 + new).
- [ ] **Step 5: Look** with `tools/look_capture.py` (list screen) on scratch data.
