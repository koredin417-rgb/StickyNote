# Settings C and icons C (phase 9, part D) — 2026-11-28

Picked by the user from the mockups: Settings option C (cards, row icons, quick choices in the
row) and icons option C (one size scale, one "on" chip).

## Icons C

- **Size scale.** Rail buttons draw their icon at `RAIL_ICON_BOX = 16` (was 14). Everything else
  in a bar or a row stays `ICON_BOX = 14`; list icons `SMALL_ICON_BOX = 12`. The 9 px arrows by
  the list's part heads and the Settings chevrons go to `SECTION_ICON_BOX = 12`.
- **One "on" look.** A button that is on (a format that applies, the calendar open, keep on top)
  shows its icon on a small rounded chip in `Colors.active`, instead of shading its whole
  square. Keep on top and the calendar had no on look at all (Q4 dropped the pin swap): now
  they do.
- **Menus.** A checked item that has an icon shows that icon on the same chip, and no ✓; a
  checked item without an icon keeps its ✓.
- The chip is drawn into the icon's picture (`chip_photo`), cached by (glyph, ink, chip colour,
  size) like every icon, so nothing is drawn per frame.

## Settings C

- Each group's rows sit on one paper card, in the list cards' colours (`card_colors` of the
  memo's colour on the page) with the same 1 px strips under it. Thin lines between rows.
- Each row starts with its icon (ink `muted`, readable at 3:1 on the card):

  | row | glyph | row | glyph |
  |---|---|---|---|
  | set_color | E790 palette | set_auto_layout | E8A9 grid |
  | set_font | E8D2 font | set_minimize | E921 minimize |
  | set_default_color | E771 brush | set_motion | E9F3 motion |
  | set_theme_color | E7A1 contrast | set_language | E775 language |
  | set_cursor | E933 text cursor | set_date_format | E787 date |
  | set_transparency | E746 half square | set_pin_limit | E718 pin |
  | set_snap | E71B link | set_bin_days | E74D bin |
  | set_keys | E765 keyboard | set_folder | E8B7 folder |
  | set_update | E896 download | | |

- **Quick choices in the row** (no page): language (한국어 / English), cursor (테마 보색 /
  글자색), motion (전체 / 줄임 / 끔), bin days (1일 / 7일 / 30일) as a small segmented choice;
  auto layout as an on/off switch. What their pages said goes in the row's tooltip.
- A row too narrow for its choice puts the choice on a second line, under the name.
- Everything else opens its page as now (colours, font, transparency, snap gap, minimize, date
  format, pin limit, keys, memo folder, update).
- Hovering a row that opens a page lights it like a list card (`lit`); quick rows don't light up
  (only their choices do).

## Settings' own size (the user's call)

- A note smaller than `SETTINGS_MIN_W x SETTINGS_MIN_H` (320 x 420 px at 100 %) opens Settings in
  a window that big, so a row's right side never runs into its name. Leaving Settings (any page,
  ← or Esc) puts the window back to the note's size.
- Only the window grows: the pad (saved size, place among the others, links) never changes, so
  nothing is pushed and a save meanwhile keeps the note's own size. It shows over its neighbours.
- It grows right and down. At a right or bottom edge (a corner) it grows left or up, its far
  edges staying where they were; with its calendar docked on the right it grows left; always
  inside the work area (a screen too small: as big as fits, and the quick choices wrap).
- Folding, minimizing, closing, or starting a drag or resize first puts the window back.
- No slide between the pages when the size changes (the old page's picture would not match).
- After the review (2026-11-28): everything that moves or sizes notes puts the bigger window back
  first (Motion's plans, a group drag's neighbours, a group resize, a screen setup switch), and a
  size made by anything else ends it; a plain click keeps it (only a drag that really moves
  shrinks it back, the note under the pointer); a folded note widens once it has unfolded; back
  to its own size, the note is laid out again (date row, rail, picture). The "on" chip is a step
  stronger under the hover; menus use the strong one. The off switch is a pale track ringed in
  ink with an ink knob (on: an ink track with a pale knob).

## Non-goals

- New settings, new pages, changing what any setting does.
- Dark mode (U6) and the calendar's own icons.
