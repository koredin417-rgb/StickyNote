# Phase 9 B2: Readable Grey and Wording Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Grey text that reads at 4.5:1 or better and at least 9 pt (Q9), and one consistent wording pass (Q10).

**Architecture:** `Colors` gains `muted_text`, the muted colour pushed to TEXT_CONTRAST on the page. Text widgets and canvas text switch to it, while icons and lines keep `muted` at 3:1. The text table in `texts.py` is edited in place: stale words fixed, unused keys removed.

**Tech Stack:** Python 3, Tk.

**Spec:** `docs/superpowers/specs/2026-11-28-phase9b-design.md` (B2).

## Global Constraints

- `muted_text`: `readable(widget, muted, bg, TEXT_CONTRAST)` (4.5).
- UI text ≥ 9 pt. **Kept at 8 pt** (the room is fixed and they are not reading text): the big calendar's period bands and weekday letters (`ui_calendar.py` 1939, 2125, 2129).
- Every word exists in Korean and English.
- Tests run on the hidden desktop: `.\StickyNote\runtime\python.exe tools\hidden_tests.py`.

## Review Focus

- Charcoal (dark) notes: `muted_text` must turn lighter, not darker. Test in Task 1.
- A strong colour kept solid (Settings): the text still reads. Test in Task 1 (every PALETTE colour, solid and not).
- Taller text in Settings rows and list heads: the virtual list measures rows, so nothing overlaps (existing `test_list_virtual` stays green).
- Removing a key that a dynamic `tr(f"...")` still builds: Task 3 checks every `tr(f"…{x}")` family before removing.
- Menu key chips (7 pt today) at 9 pt still fit the menu width (existing menu tests stay green).

---

### Task 1: `Colors.muted_text`

**Files:** Modify `StickyNote/app/ui_common.py` (`Colors.__init__`). Test: `tests/test_phase9b2.py`.

- [ ] **Test** `test_muted_text_reads`: for each PALETTE colour, `Colors.of(root, color)` and `Colors.of(root, color, solid=True)`: `contrast(c.muted_text, c.bg) >= 4.5`; for Charcoal, `luminance(c.muted_text) > luminance(c.bg)`.
- [ ] Run: FAIL (no attribute).
- [ ] Add `self.muted_text = readable(widget, self.muted, bg, TEXT_CONTRAST)` after `self.muted`.
- [ ] Run: PASS.

### Task 2: Text uses `muted_text`, at 9 pt

**Files:** Modify `ui_common.py` (menu key chip 1570, empty-page words 828, the preview's second lines 633), `ui_note.py` (date row's small text 1640, hint lines 2458, period text 762 to 9 pt), `ui_views.py` (list section heads 560/582, picture "+N" 924, preview counter 997/1055, settings group captions 1311, setting values 1413/1721, warnings 1560, help words 1729, units 1730/1731, update info 1909, bin card meta 1837/1841, 1783), `ui_calendar.py` (year 1246, "+N" 2159, holiday card 78/277), `ui_picture.py` (hints 174/185). Icons and lines (`paint_glyph`, `create_line`, `outline=`) stay `muted`.

- [ ] **Test** `test_text_is_readable`: open the list page with two memos, the settings page and the bin page. Walk every `Label` under `nw.frame` whose text is non-empty: `contrast(fg, bg) >= 4.5` and font size ≥ 9 (`tkfont.Font(font=…).actual("size")`, absolute value). Walk canvas text items of `nw.row` and the calendar head the same way.
- [ ] Run: FAIL (list heads at 8 pt, 3:1).
- [ ] Switch the listed sites; sizes 7 and 8 become 9.
- [ ] Run Task 1–2 tests, `test_list_virtual`, `test_note_look`, `test_calendar_look`: PASS.

### Task 3: Wording (Q10)

**Files:** Modify `StickyNote/app/texts.py`, `ui_note.py` (1897: dialog title). Test: `tests/test_phase9b2.py`.

Changes (Korean, English):
- `min_bar`: ("날짜 줄만 남기기", "Date row only"); `tip_minimize_style` and `hint_lines` say "날짜 줄" / "date row" for "상단 바" / "위쪽 줄" / "top bar".
- `min_fold`: ("작게 접기", "Fold away") so "접기" names only the fold of the date row (`menu_collapse`).
- On/off: `motion_off` and `snap_off` become ("끔", "Off"); `motion_reduced` becomes ("줄임", "Reduced").
- English sentence case: `current` ("Current"), `bin_soon` ("Deleting soon"). (`export_name` is a file name: stays.)
- The error dialog's title: `tr("app_title")`, not `APP_NAME`.
- Remove unused keys: `tip_unfold`, `tip_close_short`, `tip_minimize`, `tip_settings`, `tip_style`, `bin_empty_short`, `sort_date`, `sort_added`, `tip_theme_color`, `tip_auto_layout`, `tip_snap`, `tip_cal_locked`, `tip_cal_unlocked`, `tip_cal_expand`, `tip_cal_shrink`, `calendar_more`. Keep `calendar_hint` and `tip_trash` (the two useful ones): `calendar_hint` is used by B3's first-calendar tip; `tip_trash` becomes the ⋯ menu's "Move to the bin" tooltip text.
- [ ] **Test** `test_no_stale_words`: no value in `TEXTS` contains "상단 바" or "top bar"; `TEXTS["motion_off"][0] == TEXTS["auto_off"][0] == "끔"`.
- [ ] **Test** `test_every_key_is_used`: every key in `TEXTS` is named in the app's code as a literal, or belongs to a dynamic family (`hol_`, `title_`, `style_`, `tidy_`, `tidy_order_`, `cursor_`, `min_`, `motion_`, `color_`, `sort_`), or is `calendar_hint`.
- [ ] Run: FAIL.
- [ ] Edit `texts.py` and the dialog title.
- [ ] Run the whole suite hidden: PASS.
