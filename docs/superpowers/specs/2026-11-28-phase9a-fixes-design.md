# Phase 9, part A: small fixes and look picks (design)

Part of the UI/UX overhaul agreed on 2026-11-28. The list cards are their own spec
(`2026-11-28-list-cards-design.md`). Readable grey (Q9), the wording pass (Q10), × on pages
(Q7), save failures (Q8), one menu (U2) and contextual tips (U1) come in part B.

The item numbers refer to `docs/2026-11-27-improvement-proposals.md`.

## What and why

| # | Today | Change (as agreed) |
|---|---|---|
| Q1 | With Caps Lock on, Ctrl+C makes a to-do and copies nothing; Ctrl+N opens a window; Ctrl+W and Ctrl+D do nothing. | Bullets, to-do and new window need Shift (`<Control-Shift-L/l>`, `<Control-Shift-C/c>`, `<Control-Shift-N/n>`). With Lock: Ctrl+C copies, Ctrl+N makes a memo, and Ctrl+W and Ctrl+D work as without Lock. |
| Q2 | A big-calendar day with more memos than room shows "+N" in place of a title; a day with 2 memos can show no title. | "+N" goes small, right-aligned in the day-number row; every chip slot keeps a title. A holiday name in that row is cut to make room. |
| Q3 | While typing, a short note gives up pin, then calendar, then list, before any format button. Another note's open calendar hides this note's calendar button. | The format buttons give way first (picture, strike, underline, italic, bold, bullets, to-do), then pin, list, new window; the calendar button goes last and always shows (opening it moves the calendar over, as `toggle_calendar` already does). |
| Q4 | One pin icon means "always on top" on the rail and "pinned to the top" in the list. | Keep on top gets Windows' own icon, `U+EE49` (a small window in a corner), and the words "맨 앞에 두기 / Keep on top". The pin stays for the list only. |
| Q5 | The month head's "this month" icon fades through new colours each time, and each colour makes a picture that is cached forever. | It steps through a fixed ramp of 7 colours (page to muted), so the cache stays bounded. |
| Look 3 | A grey rule under a memo's title. | Space only: the rule takes the page colour; the spacing stays. |
| Swatch | In Settings, a colour dot on a page of the same colour looks empty. | The dot's outline is readable on the page (3:1). |

## Non-goals

- The selected-day accent: the user asked for an ink pill, then turned ink down for the list cards. It is put back to the user before it is built.
- Any wording beyond the keep-on-top strings (part B does the wording pass).

## Approaches

- Q1: bind by modifier (chosen). A key handler that reads `event.state` was the alternative; bindings keep Tk's own precedence and need no new code path.
- Q5: a fixed ramp (chosen), as the calendar day hover does. A cache with a size limit would still make a new picture every frame.

## Calls made (for review)

- "+N" uses 9 pt in the muted colour, matching the holiday names in that row.
- Ctrl+Shift+T with Caps Lock (keysym `t`) also reopens the last closed note.
