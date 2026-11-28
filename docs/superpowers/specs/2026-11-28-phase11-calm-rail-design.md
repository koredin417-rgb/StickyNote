# Phase 11: the calm rail, and colour from the note (2026-11-28, draft)

Two parts, both about the note's own chrome. Decided so far: the rail shows while the note has
the keyboard focus **or** the pointer is over it, and hides only when neither is true; it comes
back with a quick fade (`anim.FAST`, 120 ms). Colour from the note: a colour dot on the top bar,
not a hover strip (backlog item 3).

## The calm rail

- **What hides:** the rail's buttons and its tinted strip. The top bar (date, −, ×) always stays:
  it is how the note is moved, folded and closed.
- **Proposed (to confirm): the rail's room stays, its contents fade to the page.** The memo text
  keeps its width, so nothing reflows when you click away (Korean text re-wrapping on every focus
  change would be the opposite of calm). The strip fades to the page colour, so a resting note
  reads as one quiet sheet.
  - Alternative: the text widens into the rail's room (more reading room, but every line may
    re-wrap at each focus change, and the note's look jumps).
- **When:** hides `RAIL_REST_MS` (about 0.6 s) after the note has neither the focus nor the
  pointer, so passing the mouse across does not flicker it; shows at once when either comes.
- **Never hides:** while a menu, a tooltip, a drag, a resize, or the bottom bar's message is up;
  on pages (list, Settings, bin); for a note that is folded (no rail then anyway).
- **Keyboard:** focus in the note shows it, so keyboard-only use always has it.
- **Format confirm (phase 10 I):** with the rail hidden, no pulse; the tint alone (settled).
- **Setting:** Settings > 배치 gets "레일 숨기기" (켬 / 끔), on by default for new users, so
  anyone who prefers the always-there rail keeps it.
- **Motion:** Reduced keeps the fade; Off shows and hides at once.

## Colour from the note (built 2026-11-28: tests/test_phase11_color.py)

- A small colour dot on the top bar, left of −, in the memo's own colour a step deeper (1.35:1 on
  the page) and ringed (MARK_CONTRAST), so it reads as a colour chip on its own colour. It shows
  on the memo only (not on pages, not folded); the date row leaves room for it.
- Click: a popover palette under it: the 10 colours and the personal ones, the memo's colour
  ticked; a click sets it at once (Undo not needed: it is one click back). Esc or a click outside
  closes it.
- The right-click / ⋯ menu gets the same swatches as one row at its top.
- It stays when the rail hides (it is on the top bar).

## Non-goals

- Changing what any rail button does or their order (phase 9 settled that).
- Moving the rail to another side.

## Settled (the user's calls, 2026-11-28)

1. Resting, the rail gives its room to the memo (changed by the user after seeing it: the empty
   strip "looks very off"). The swap happens under a picture of the note in a click-through window
   fading out over RAIL_FADE_MS (as page changes do): one cached shot and one fade a swap, nothing
   in between; the text re-wraps under that fade. (First built as a veil keeping the room: dropped.)
2. "레일 숨기기" is on for new users and off for people updating (their notes look as before until
   they turn it on in Settings > 배치).
