# Phase 3: the C Look, Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Notes and the calendar take the approved C ("Margin") look:
- a side rail and a big date row;
- a 36 px folded strip;
- secondary views with a back row;
- the variant-3 calendar header with a ⋯ menu;
- Windows 11 rounded corners and shadow, with a fallback.

**Architecture:**
- `NoteWindow`'s grab strip, two top bars and bottom format bar give way to two parts:
  - a left **rail**: nav buttons, format buttons while typing, and ⋯;
  - a **date row**: a canvas that draws the numeral and small text, the folded text or the view title, with a back button and ×.
- `CalendarPopup` loses its grab strip. Its header becomes a canvas (numeral, month, year) plus today ‹ › ⋯ ×.
- Window edges come from DWM on Windows 11. Elsewhere a 1 px border stays.

**Tech Stack:** Python 3.15, Tkinter, Pillow, and ctypes (DWM), all in the bundled runtime. Tests use stdlib `unittest` with `tests/_support.py`.

**Spec:** `docs/2026-11-25-redesign-design.md`, §6 (the C look), §7 (Phase 3 row), and §8 (the S1 result).

## Global Constraints

- **Languages:** all new UI text exists in Korean and English (`texts.TEXTS`), Korean first.
- **Sizes:**
  - All sizes are px at 100 % through `app.px()`.
  - Fonts given in px use a negative Tk size: `-app.px(n)`.
- **Behaviour rules:** they must give the same results (S1/S4, C1/C2, L2–L5, M2, N2, N5, P1–P6). The folded height stays `px(PILE_STEP)` (36 at 100 %).
- **Fallback:** Windows 10 or a failed DWM call keeps the 1 px border and square corners.
- **Unchanged:** note colours (`PALETTE`, custom colours), every shortcut and every right-click menu item.
- **Korean IME:** must not get worse. Nothing here may take focus from the memo text.
- **Data:** never touch `%APPDATA%\StickyNote`. Use a temp folder or `preview.py`.
- **Tests:** run with `.\StickyNote\runtime\python.exe -m unittest discover -s tests` from the project root. All 97 existing tests stay green.

## Review Focus

1. **A small note (MIN 260×170)** at 100 % and 150 %: every rail command is still reachable (shown, or in ⋯), and nothing overlaps or gets clipped. *(Task 3)*
2. **Typing Korean:** when the format buttons appear on focus, the focus and the preedit syllable stay intact, and clicking a format button keeps the body's focus. *(Task 3)*
3. **The folded height** is exactly `px(PILE_STEP)`, so piles, tidy and fold-all lay out as before. *(Task 5)*
4. **The calendar's size never changes while paging**, with the today icon appearing or disappearing (#17A). *(Task 7)*
5. **Strong (tinted) and dark note colours:** rail icons and date text meet `MARK_CONTRAST` on their surfaces. *(Task 2)*

---

## Decisions (shared by the tasks)

**Constants (`ui_common`):**
- `DATE_ROW_H = 36`: the folded strip's full height, including the edge. `assert PILE_STEP == DATE_ROW_H` replaces the old assert. `GRAB_H` is removed.
- `RAIL_W = 38`.
- `RAIL_BUTTON = (30, 26)` (w, h).
- `RAIL_PAD = 6`: above the first button and below ⋯.
- `RAIL_GAP = 9`: the gap between the nav group and the format group. It holds a 1 px line, 16 px wide, in `rail_colors.line`.
- Fonts: `DATE_NUM_PX = 22`, `DATE_SMALL_PX = 13`, `CAL_NUM_PX = 28`, `CAL_MONTH_PX = 13`, `CAL_YEAR_PX = 12`.
- `TOP_BUTTON_H` stays (28), for the calendar header buttons.

**Fonts:**
- Numerals use `(UI_BOLD, -px(n), "bold")`.
- The small date text and the year use `(UI_FONT, -px(n))` in muted ink.
- The calendar's month label is bold.
- No semibold face is bundled, and Tk can't turn on tabular digits. Both are builder's calls, noted.

**Window edge:**
- `NoteWindow.edge` / `CalendarPopup.edge` is 0 when `winapi.can_round()` (Windows build ≥ 22000), else 1. The frame is packed with `padx=edge, pady=edge`.
- The date row (and the calendar head) is `px(DATE_ROW_H) - 2 * edge` tall, so the folded height is `px(DATE_ROW_H)` either way.
- At first show, `winapi.round_corners(win)` runs. If it returns False, `edge` becomes 1 and the frame is re-packed.
- With edge 1 the window background is `colors.frame` (today's border).

**Surfaces:**
- The date row is the page (`colors.bg`).
- The rail is `c.color` for a tinted colour (its strong colour, like today's top bar), else `_mix(c.bg, c.fg, 0.07)`.
- `rail_colors = Colors.of(win, rail_bg, solid=True)`. Rail buttons are recoloured with `rail_colors`; date-row buttons with `colors`.

**Widget tree (note):**
```
frame ─┬─ rail (Frame, width RAIL_W, pack left fill y, no propagate)
       │    ├─ rail_top (Frame, pack top)     buttons in show order, sep line between groups
       │    └─ btn_more (pack bottom, pady RAIL_PAD)
       └─ main (Frame, pack left fill both expand)
            ├─ bar (Frame, height as above, pack fill x, no propagate)
            │    ├─ btn_back (pack left; secondary views only)
            │    ├─ btn_close (pack right)          IconButton 30 × bar height
            │    └─ row (Canvas, pack left fill both expand)   numeral + small / folded text / view title
            └─ views (as today: home / list / settings / bin)
grip (place se of frame), toast and hints (placed in main)
```

**Rail order:**
- Nav: `btn_memo`, `btn_window`, `btn_list`, `btn_cal`, `btn_pin`.
- Then the separator and the format group: bold, italic, underline, strike, bullets, todo, picture. The group shows only while `view == "home"` and the body has focus.
- `btn_more` sits at the bottom.
- When the rail is too short, buttons move into ⋯ in this order:
  - pin, calendar, list;
  - then the format buttons from the end (picture, todo, bullets, strike, underline, italic, bold);
  - then window.
  - `btn_memo` and `btn_more` always stay.
- `btn_cal` is also hidden while another note has the calendar (today's rule).

**⋯ menu (note):**
- Layout (style) opens today's style menu at the same point.
- Then move to bin (`Ctrl+D`), settings, and minimize. Each has today's icon.
- Then a separator and the hidden rail buttons in rail order, each with its glyph and the first line of its tooltip.

**Date row text:**
- `texts.date_row(d)` returns `("25", "11월 수요일")` in Korean and `("25", "Wed, Nov")` in English.
- The numeral and small text sit on one baseline, 16 px from the row's left.
- The small text is cut with `fit_text`, or dropped when even "…" won't fit.
- **Folded:** the rail is hidden. The row shows the numeral, then the memo lines joined with " · ", in 13 px ink, cut with the cached `fit_text` (as `_fold_fit` today).
- **Secondary view:** ‹ back, then the view title in `(UI_BOLD, -px(13), "bold")` ink.
- The row canvas tags its text items `"text"` in drawing order, so tests read them.

**Calendar header:**
- The head canvas shows the month numeral, then two stacked labels: month (bold) over year (muted). Korean is "11월" / "2026년"; English is "November" / "2026". `texts.month_head(y, m)` returns `(numeral, month, year)`.
- Buttons are packed right in this order: `btn_close`, `btn_more`, `btn_next`, `btn_prev`, `btn_today`.
- `btn_today` is always packed (its slot never changes the width). On the current month its ink tweens to the head background over `anim.FAST` and its command does nothing. Otherwise its ink tweens to muted.
- The calendar ⋯ menu:
  - This month;
  - Detach from note / Attach to note (`toggle_lock`);
  - Big view / Small view (`click_view`).
- `btn_lock` and `btn_expand` are removed.

---

### Task 1: Window corners

**Files:**
- Modify: `StickyNote/app/winapi.py`, `ui_common.py` (constants), `ui_note.py`, `ui_calendar.py`
- Test: `tests/test_corners.py`

**Interfaces:**
- Produces:
  - `winapi.can_round() -> bool`: Windows build ≥ 22000, cached.
  - `winapi.round_corners(win) -> bool`: `DwmSetWindowAttribute(hwnd_of(win), 33, c_int(2), 4) == 0`; False when there is no hwnd.
  - `NoteWindow.edge`, `CalendarPopup.edge`, and `_pack_frame()` on both.

- [ ] Test `test_round_corners_on_mapped_window`: a mapped Toplevel gives `round_corners` True when `can_round()`, and False for one never mapped (no frame).
- [ ] Test `test_note_edge_follows_corners`: with corners working, `nw.edge == 0` and the frame's pack `padx` is 0. With `winapi.round_corners` patched to return False, a new note gets `edge == 1`, padx 1 and `win.cget("bg") == colors.frame`.
- [ ] Test `test_calendar_edge_follows_corners`: the same for an open calendar.
- [ ] Run, watch them fail, then implement.
- [ ] Run the tests until they pass, then commit: `feat(look): Windows 11 rounded corners and shadow, 1 px border fallback`.

### Task 2: Rail and date row (home view)

**Files:**
- Modify: `ui_common.py` (constants, `DATE_ROW_H` assert), `texts.py` (`date_row`, `tip_more`), `ui_note.py` (`__init__`, `apply_look`, `_arrange_chrome`, `_draw_row`, `_more_menu`, `flash`, `_place_toast`, `show_hints`, `_inline_width`), `ui_picture.py` (`_area`), `app.py` (`calendar_buttons`, `update_date` callers)
- Test: `tests/test_note_look.py`

**Interfaces:**
- Produces:
  - `NoteWindow.rail`, `rail_top`, `main`, `bar`, `row`, and `btn_more` (the rest keep their names).
  - `_arrange_chrome(width=None, height=None)`, which replaces `_fit_date`.
  - `rail_shown() -> tuple[IconButton, ...]`.
  - `_more_menu(x=None, y=None) -> PopupMenu`: it pops up and returns the menu.
  - `row_texts() -> list[str]`.
- Removed: `grab`, `home_bar`, `sub_bar`, `sub_title`, `date_label`, `format_bar`, `format_row`, `format_line`, `btn_min`, `btn_min2`, `btn_close2`, `btn_gear`, `btn_style`, `btn_trash`, `btn_unfold`, `_draw_grab`, `_arrange_bar`, `_fit_date`. Callers in `app.py` move to `_arrange_chrome`. `_draw_grab` calls in `app.py` go.

- [ ] Test `test_rail_order`: on a 320×320 note, not typing, `rail_shown()` is memo, window, list, calendar, pin; `btn_more` is mapped at the rail's bottom; the rail is `px(RAIL_W)` wide.
- [ ] Test `test_date_row_texts`: `row_texts()` equals `list(texts.date_row(date.today()))`. `texts.date_row(date(2026, 11, 25))` gives `("25", "11월 수요일")` in Korean and `("25", "Wed, Nov")` in English.
- [ ] Test `test_more_menu_items`: `_more_menu().labels()` starts with `menu_style`, `menu_trash`, `menu_settings`, `menu_minimize` (via `tr`).
- [ ] Test `test_row_drag_and_fold`: a double-click on `row` folds the note (`pad.collapsed`). A right-click on `row` opens a menu whose labels include `menu_collapse`.
- [ ] Test `test_rail_contrast`: for every `PALETTE` colour and `#1E1E1E`, each rail button's ink has contrast ≥ `MARK_CONTRAST` against the rail background, and the numeral's ink has contrast ≥ `TEXT_CONTRAST` against `colors.bg`.
- [ ] Test `test_flash_only_date_row`: during `flash()`, `bar.cget("bg")` differs from `colors.bg` and `rail.cget("bg")` doesn't change. After `FLASH_MS` plus a little, `bar.cget("bg") == colors.bg`.
- [ ] Update `tests/test_fit_text.py` and `tools/baseline.py`, which read `date_label`, to use `row_texts()`.
- [ ] Run, watch them fail, then implement. Then run the whole suite until it passes.
- [ ] Commit: `feat(look): note side rail and big date row`.

### Task 3: Rail overflow and format buttons while typing

**Files:**
- Modify: `ui_note.py` (`_arrange_chrome`, focus bindings, `_more_menu`)
- Test: `tests/test_note_look.py`

- [ ] Test `test_format_group_on_body_focus`: `body.focus_force()` plus a pump shows bold…picture in `rail_shown()` (or overflowed into ⋯). Focusing `header_entry` hides them. Focus is still on the body after a click on `btn_bold`.
- [ ] Test `test_overflow_order`: on a 320×320 note with the body focused, `rail_shown()` is memo, window, list, bold, italic, underline, strike, bullets, todo, picture; ⋯ holds calendar and pin (calendar first). On a 260×170 note with the body focused, every rail command is in either `rail_shown()` or the ⋯ menu's extra items, and `btn_memo` is shown.
- [ ] Test `test_rail_fits_at_150`: with `app.scale = 1.5` (whatever `make_app` allows) on a 260×170 note, the bottom of the last shown button is above `btn_more`'s top.
- [ ] Run, watch them fail, then implement and run until they pass.
- [ ] Commit: `feat(look): rail gives way to ⋯ on small notes; format buttons while typing`.

### Task 4: Secondary views

**Files:**
- Modify: `ui_note.py` (`_show_view`, `_draw_row`)
- Test: `tests/test_note_look.py`

- [ ] Test `test_list_view_row`: after `show_list()`, `btn_back` is mapped at the row's left, `row_texts() == [tr("title_list")]`, `btn_close` is still mapped and the rail is still mapped. After `go_back()`, the row shows the date again.
- [ ] Run, watch it fail, then implement and run until it passes.
- [ ] Commit: `feat(look): secondary views keep the rail; back and title in the date row`.

### Task 5: Folded strip and the resize cover

**Files:**
- Modify: `ui_note.py` (`collapsed_height`, `_apply_collapsed`, `_draw_row`, `freeze`, `minimize`, `restore`, `_drop_roll_cover`, `thaw`)
- Test: `tests/test_note_look.py`

- [ ] Test `test_folded_strip`: after `toggle_collapse(instant=True)`:
  - `win.winfo_height() == px(PILE_STEP)`;
  - the rail is not mapped;
  - `row_texts()[0]` is today's numeral and `row_texts()[1]` starts with the memo's first line;
  - `btn_close` is mapped.
  Unfolding brings the rail back.
- [ ] Test `test_freeze_cover_keeps_rail`: `freeze()`, then a geometry change to (+60, +40) px and a pump. In the cover canvas, the rail-background rectangle spans the full new height, and the × piece sits within px(40) of the right edge. `thaw()` restores the widgets.
- [ ] Test `test_minimize_bar_style_rolls_to_strip`: `minimize()` then `restore()` with Motion settling leaves `pad.height` unchanged and raises no errors.
- [ ] Run, watch them fail, then implement and run until they pass.
- [ ] Commit: `feat(look): 36 px folded strip with today's numeral and the memo's lines`.

### Task 6: Calendar header (variant 3) and its ⋯ menu

**Files:**
- Modify: `texts.py` (`month_head`, `menu_this_month`, `menu_cal_detach`, `menu_cal_attach`, `menu_cal_big`, `menu_cal_small`), `ui_calendar.py` (`__init__`, `_show_state`, `draw`, `_draw_head`, `_more_menu`, `recolor`; remove `_draw_grab`)
- Test: `tests/test_calendar_look.py`

**Interfaces:**
- Produces:
  - `CalendarPopup.head_cv`, `btn_more`;
  - `head_texts() -> list[str]`;
  - `_more_menu(x=None, y=None) -> PopupMenu`.

- [ ] Test `test_head_texts`: on an open calendar, `head_texts()` is `list(texts.month_head(y, m))`. `texts.month_head(2026, 11)` gives `("11", "11월", "2026년")` in Korean and `("11", "November", "2026")` in English.
- [ ] Test `test_head_buttons_order`: the mapped head buttons, sorted by x, are today, prev, next, more, close. There is no grab strip, and the head is `px(DATE_ROW_H) - 2*edge` tall.
- [ ] Test `test_cal_more_menu`: the labels are this month, detach (when docked), and big view (when mini). Running the detach item toggles `docked`.
- [ ] Run, watch them fail, then implement and run until they pass.
- [ ] Commit: `feat(look): calendar header with the big month numeral and a ⋯ menu`.

### Task 7: The today icon fades; paging keeps the size

**Files:**
- Modify: `ui_calendar.py` (`_draw_head`, `this_month`), `ui_common.py` (`IconButton.set_ink`)
- Test: `tests/test_calendar_look.py`

- [ ] Test `test_today_icon_fades`: on the current month, after a pump, `btn_today.ink_color == colors.bg` (the head's). After `next_month()` and `anim.FAST` plus a little, it is `colors.muted`. Clicking it on the current month changes nothing.
- [ ] Test `test_paging_keeps_size`: across `next_month()` ×3 and `this_month()`, `top.winfo_width()` and `winfo_height()` never change (mini and big view).
- [ ] Run, watch them fail, then implement and run until they pass.
- [ ] Commit: `feat(look): this-month icon fades in when away from today`.

### Task 8: §6.4 items: chip drop and holiday card

**Files:**
- Modify: `ui_calendar.py` (`_drop_chip`, `HolidayCard.show`)
- Test: `tests/test_calendar_look.py`

- [ ] Test `test_chip_drop_never_twice`: in the big view, drop a chip onto another day. While `"settle"` items exist, the redrawn chip items for that note are hidden. After the settle they are shown and no `"settle"` items remain.
- [ ] Test `test_holiday_card_fades_in`: showing a holiday tweens the card's alpha from 0 up to `CLICK_THROUGH_ALPHA` (mid-way, it is below that value).
- [ ] Run, watch them fail, then implement and run until they pass.
- [ ] Commit: `feat(look): dropped chip lands once; holiday card fades in`.

### Task 9: Screenshot parity and results

**Files:**
- Create: `tools/look_capture.py`. It is the capture driver: a scratch data folder, two notes (yellow with a to-do list, blue short), the calendar docked, a folded note and the list view. It saves PNGs under `docs/perf/look-*.png`, which are git-ignored.
- Modify: `docs/2026-11-25-redesign-design.md` (a "Phase 3 results" section).

- [ ] Run the capture. Compare it against §6.1–§6.3 and the mockups:
  - the rail, numeral and small text, ×;
  - the folded strip;
  - the back row;
  - the calendar head;
  - rounded corners.
- [ ] Fix any mismatch and re-capture.
- [ ] Write the results and the calls made into the spec, then commit: `docs: phase 3 results`.
