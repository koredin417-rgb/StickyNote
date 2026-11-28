# Backlog: the user's ideas (2026-11-28), with Claude's order and notes

Order agreed by the user (2026-11-28). Status:

| # | Item | Status |
|---|---|---|
| 1 | "(빈 메모)" greyed out | built (tests/test_phase9d.py, EmptyTitleTest) |
| 2 | Scrolling | built in phase 10 (tests/test_phase10_scroll.py) |
| 3 | Colour from the note | built in phase 11 (tests/test_phase11_color.py) |
| 4 | Memo list: delete many | built (tests/test_list_select.py; spec 2026-11-28-list-select-design.md) |
| 5 | First start | built (tests/test_first_start.py; spec 2026-11-28-first-start-design.md) |

Proposed order (each its own phase or part, spec and tests first):

1. **"(빈 메모)" greyed out** (phase 9 tail, small). An empty memo's title in the list, the bin
   and menus shows in the muted ink (readable at 4.5:1), not the normal ink.
2. **Scrolling** (with phase 10, motion). The theme-coloured thumb (`OverlayScroll`, today 5 px,
   shown while scrolling) thickens when the pointer is on it and can be dragged; smooth scroll
   (J) for the list, Settings and the bin; a small bounce at the ends of those pages only (they are
   canvases; the memo text is a Tk Text and gets smooth scroll, no bounce).
3. **Colour from the note itself** (with phase 11, the calm rail). A colour dot on the top bar
   (it stays when the rail hides) opens a small palette popover: the 10 colours and the personal
   ones; also a row of swatches in the right-click / ⋯ menu. Not a hover strip at an edge: hard to
   find and easy to set off by accident.
4. **Memo list: delete many** (its own part). A select mode (a check on each card, select all),
   then "휴지통으로" with one Undo; "delete all" means all to the bin, never gone for good.
5. **First start** (last: it points at the final controls, after phases 10–11 change them).
   The desktop dims; first the language choice, then a short spotlight tour (each stop cuts a
   hole in the dimmed layer around one control and says what it does; 4–6 stops), with "건너뛰기"
   on every stop; the tour can be replayed from Settings > 단축키와 조작. Only for a new data
   folder: people updating get no tour (at most one "새로 바뀐 점" card).

Extra ideas from Claude (not yet agreed):

- A welcome memo that teaches by doing ("이 줄을 체크해 보세요"), lighter than a tour.
- The spotlight uses the clip-with-holes the page change already has (`winapi.clip_box(holes=)`).

Also from the user while testing (2026-11-28): the calendar's click felt like two steps. It was the
DOUBLE_CLICK_MS wait before the day lit up; the day now lights up on the click itself and only its
list waits (tests/test_calendar_click_now.py).
