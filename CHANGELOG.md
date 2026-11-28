# Changelog

## 1.2.0 — 2026-11-28

A UI/UX overhaul: calmer notes, smoother motion, a clearer Settings and list, a first-start
tour, and a lighter app. Notes and settings from 1.1 carry over as they are.

### New
- **Calm rail.** The left button rail rests when the pointer leaves a note: it slides out to
  the left and the memo takes its room, and slides back in when the pointer returns. On for new
  users; Settings → Hide the rail turns it off.
- **Colour dot.** A dot in the top bar opens the note's colours (smooth swatches, a ring on hover).
- **First-start tour.** Language choice, a welcome memo to tick off, then five short stops (home,
  top bar, rail, colour, more) with the rest of the screen dimmed. Skip any time; replay from
  Settings.
- **List: select many.** Select mode in the memo list ticks several memos (or all) and moves them
  to the bin together.
- **Saved dot.** After you stop typing and the memo is saved, a small dot lights up once.

### Changed
- **Settings, redesigned.** Grouped cards with icons; quick choices (switches, segments) right in
  the row; long names shortened with the full name in a tooltip; a Keys and gestures page.
  A small note opens Settings in a 320 × 420 window grown toward the side with fewer notes, and
  goes back to its own size afterwards. It is not resizable while in Settings, and it keeps its
  size while you drag it or expand its calendar.
- **List cards.** Card layout with a paper lift, the current memo in its own tone, hover lift and
  ring, and more room between the pin and bin icons. An empty memo's title shows greyed.
- **Wording.** "상단 바" (top bar) throughout.
- **Tips** show as a dark bar.

### Motion
- The caret glides to where you type and breathes instead of blinking (stops after a few seconds
  idle; follows Windows' blink setting).
- Scrolling glides per pixel, gives a little at the ends, and keeps its speed when you turn the
  wheel again (no kick on each notch). The scroll thumb is a smooth pill that widens under the
  pointer.
- Calendar: mini ↔ big morphs; a clicked day highlights at once.
- Tooltips fade out as well as in; a closing note's slide pictures fade out with it.
- Animations → Reduced: a moving window cross-fades over 180 ms instead of blinking.
- Every round shape (dots, swatches, checks, switches, the scroll thumb) is drawn anti-aliased.

### Fixed
- Korean IME: no white composition box; the note draws the syllable being typed.
- Settings with a docked calendar could lose its size and save it as the note's own; a drag in
  Settings shrank the window.
- The group outline could lag one frame behind at the start of a drag.
- Dragging linked notes left a neighbour's rail slide picture behind on screen.
- The resize grip no longer shows a second copy while the rail slides.
- A rail slide cut short (a drag, minimize, close) now leaves the note laid out correctly.
- Update check: with no published release yet (only pre-releases or drafts), it says you are up
  to date instead of "Couldn't read GitHub's reply".

### Lighter
- About 26 % less memory with 20 notes (68 → 50 MB): screenshots used for slides are no longer
  kept per note, the rail keeps only its own strip, stale pictures are dropped as soon as a note
  changes, and closed notes are freed right away.
- A note's Settings page is freed a minute after you leave it (about 2–3 MB a note).
- The shared picture cache is capped at 16 MB (was 64 MB).

### For developers
- `tools/hidden_tests.py` runs tests and captures on a hidden desktop.
- `tools/memory_bench.py` measures memory per step and across repeated cycles.
