# Phase 10: motion (2026-11-28, draft)

Picked by the user: the calendar's real grow/shrink, and five typing touches. A gliding caret,
B breathing caret, D to-do settle, I format confirm, K saved dot. Everything runs on the frame
clock (`anim.animate` / `stop_animation`), obeys the Motion setting (Reduced keeps fades and drops
moves; Off ends everything at once), and costs nothing between animations.

## The calendar grow/shrink (big <-> mini)

- Today the switch dips out and fades back (VIEW_DIP_MS). It becomes one morph: a picture of the
  old view stands in (a picture cover, as page changes do), the window's box tweens from the old
  size to the new one, the picture scales with it and cross-fades to a picture of the new view,
  then the live calendar swaps in at the end with no jump.
- Per frame: one window resize and one small blend (the mini view's size): about 1–2 ms of a
  13.9 ms frame. The text is never stretched in the live window, so nothing blurs.
- **Spike first:** the calendar window is layered at 92 % opacity; resizing a layered window
  every frame must be measured before building (the plan's first task). If it stutters, the
  fallback is a click-through cover window doing the scaling while the calendar stays still.
- **Spike result (2026-11-28, hidden desktop, 40 frames 300x260 -> 620x520):** resizing at 92 %
  alpha costs the same as opaque (mean 1.65 vs 1.63 ms, p90 2.4 ms). Scaling the picture with a
  new PhotoImage a frame adds about 4 ms (mean 5.65, p90 7.2, max 8.9 ms): within the 13.9 ms
  frame, and cheaper again by pasting into one PhotoImage (as `_fly_to_bin` does) from a half-size
  source. A hidden desktop is not composited like the shown one: confirm on the real screen once.
- A docked calendar keeps its side and its top in line with the note through the morph.
- Reduced: a cross-fade, no size tween (the box jumps under the fade). Off: instant.

## A · gliding caret

- Tk's own caret is hidden; a 2 px overlay caret (a thin frame placed over the text box) moves to
  the insert position, eased over 70 ms. Only a move costs anything.
- Korean: while a syllable is being composed (the IME's preedit), Tk's own caret comes back and
  the overlay hides, so composition looks exactly as today.
- Selection, focus loss, scrolling and a hidden caret (pages, folded) hide the overlay.

## B · breathing caret

- The overlay caret fades out and in through a 6-step colour ramp instead of blinking on/off
  (cached colours: one colour change every couple of frames during a fade, nothing between).
- It rests solid while typing, and breathes again after a pause (the blink rhythm Windows uses).

## D · to-do settle

- Ticking a to-do: the line fades to the done colour and takes its strike over 180 ms (one line
  recoloured through a few cached tags). Unticking reverses it.

## I · format confirm

- Ctrl+B / I / U / T, bullets and to-do from a key: the rail button pulses once (its "on" chip,
  icons C, grows in) and the changed text gets a brief tint that fades (one range, a few steps).

## K · saved dot

- After an autosave, a 6 px dot by the date fades in and out (one canvas item). A failed save
  shows it in the danger colour and keeps it until a save works (with the Q8 notice).

## Scrolling (backlog item 2, the user's idea, 2026-11-28)

- Today's thumb (`OverlayScroll`): 5 px in the theme colour while the view moves, 8 px under the
  mouse, draggable, fading out SCROLL_HIDE_MS after the last move. What changes:
  - the pointer near the right edge (within 12 px) of a page that scrolls shows the thumb, so it
    can be found without scrolling first;
  - 5 -> 8 px and back eases over `anim.FAST` (no jump), one redraw a frame only while it eases;
  - smooth scrolling: a wheel notch moves the view over about 4 frames (`anim.FAST`, ease-out)
    instead of in one jump, for the list, Settings, the bin and the memo text (J);
  - a small bounce at the ends of the list, Settings and the bin (canvases: the content eases
    past by up to 12 px and back): never in the memo text (a Tk Text; it would fight typing).
- Reduced: no bounce, scrolling jumps; Off: as Reduced, and the thumb shows and hides at once.

## Non-goals

- Moving, rising or scaling letters; anything per character while composing.
- H (selection fade-in), G (rail motion: phase 11).

## After the review (2026-11-28)

- The mouse uses Tk's own caret: a press in the text hides the overlay (double-clicks, drags and
  right-clicks are Tk's, never caught by the 2 px overlay); the overlay comes back at the next key,
  which is where the glide matters. A press that lands on the overlay itself goes to the text.
- It follows code that moves the insert point (bullets / to-do from the rail, Undo, a picture tab,
  an inline picture): `_after_edit` and `_update_format_buttons` ask it to.
- It stands where Tk's own stands (x - width/2, the display line's height); at the faded end of a
  breath it is gone, never a page-coloured bar over a glyph.
- Breathing rests solid a blink's time between breaths and stops CARET_IDLE_MS (5 s, Windows' own
  caret timeout) after the last key: nothing runs while a note just sits there. Tk's own blink
  timer is off while ours shows (`insertofftime` 0 in the same configure).
- The pages' wheel glide scrolls by relative pixels, so the list's row measuring is never undone;
  a jump by code (to the top, to a picked row) stops a glide first. The wheel over the list's
  thumb goes through the list (an open preview first).
- The saved dot: a flash already due never covers a red dot; another memo in the window starts
  without the last one's dot.
- The morph's cover goes where the calendar is going now (re-planned meanwhile); Reduced keeps the
  old view at its own size under the fade (no stretched picture); closing the calendar mid-morph
  never snaps it into view.

## Settled (the user's calls, 2026-11-28)

- Saved dot: only after a pause in typing (the save that follows a pause), never flickering on
  every autosave while typing; a failed save shows it in red at once and keeps it.
- Format confirm: when the button is not on the rail (in ⋯, or the rail hidden in phase 11), no
  pulse: the changed text's tint alone confirms it.
