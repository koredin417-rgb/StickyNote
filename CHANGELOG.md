# Changelog

## 1.2.4 — 2026-11-28

Every Settings page redesigned, from the mockups: one shape, clearer controls, live previews.

### Changed
- **Settings pages.** Each page has its name in the top bar (with "설정" beside it), a round icon
  and a one-line description on top, its controls in a clear card, and a preview where the setting
  changes how something looks.
  - Colours: round swatches in a card, the chosen colour's name in the title, "내 색" on its own
    row, a preview note (theme colour: today's mark and the text cursor).
  - Transparency: marks at 0 · 25 · 50 · 75 · 90 and a note fading over a desktop as you drag.
  - Font: − size + and a sample in the chosen font and size.
  - Date format: one row per format with today in it and a ✓, and a list card showing it.
  - Snap: two notes drawn the chosen gap apart.
  - Minimize: three options, each with a small drawing and one line.
  - Memo folder: the path cut in the middle (full path on hover), Open folder and Copy path, and
    how many memos, pictures and days of backups it holds.
  - Keys and gestures: cards by purpose, each key drawn as a keycap.
  - Update: the version large, its state with an icon, when it was last checked.
- **Pinned count** is a − n + stepper in the Settings list (no page of its own).
- Settings opens faster and holds less: a page is made the first time it is opened.

## 1.2.3 — 2026-11-28

Typing fixes: the caret keeps up with held keys, open lists follow edits, Korean shows in
the search bar and title line.

### Fixed
- A memo being written in one note now shows in another note's open memo list after the typing
  pause (it said "no memos yet"), keeping where that list was scrolled.
- Holding Backspace (or typing fast): the caret follows the text at once instead of trailing
  behind it until the key was let go.
- Korean in the list's search bar and a memo's title line: the syllable being typed shows at the
  cursor (it was invisible until finished).

## 1.2.2 — 2026-11-28

Settings gets clearer cards, and the docked calendar makes room wherever it is. (1.2.1 was
published with the 1.2.0 file by mistake; the updater refused it. 1.2.2 replaces it.)

### Changed
- **Settings, clear cards.** Cards read on every note colour (a set lift off the page and a fine
  edge); section captions are semibold; colour rows show a smooth round dot (it was a hollow
  square that looked like a checkbox); the palette's swatches are round, the chosen one ticked;
  the choice in use is a raised chip; a switch that is on takes the theme's colour with a white
  knob, off is a quiet ring; Export and Move to the bin are rows on a Memos card.

### Fixed
- In Settings, a small note's bigger window no longer sits on its own docked calendar: the
  calendar moves beside the window (other notes stay put), expanding it makes room there, and it
  comes back when Settings closes.
- Expanding a docked calendar by a screen edge or in a corner did nothing (no room for the big
  view on its side). The note and its calendar now slide in just far enough, keeping the side,
  and slide back when it goes back to mini; in Settings its bigger window slides instead.
- A rail slide's picture removed mid-slide could raise an error (seen in error.log).
- Update check: with no published release yet (only pre-releases or drafts), it says you are up
  to date instead of "Couldn't read GitHub's reply".

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

### Lighter
- About 26 % less memory with 20 notes (68 → 50 MB): screenshots used for slides are no longer
  kept per note, the rail keeps only its own strip, stale pictures are dropped as soon as a note
  changes, and closed notes are freed right away.
- A note's Settings page is freed a minute after you leave it (about 2–3 MB a note).
- The shared picture cache is capped at 16 MB (was 64 MB).

### For developers
- `tools/hidden_tests.py` runs tests and captures on a hidden desktop.
- `tools/memory_bench.py` measures memory per step and across repeated cycles.
