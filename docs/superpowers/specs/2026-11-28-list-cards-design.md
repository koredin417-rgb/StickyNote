# List cards: calm cards with a bit of depth (design)

Part of Phase 9 (polish and fixes) of the UI/UX overhaul agreed on 2026-11-28. The other
Phase 9 items (the selected-day accent, the title rule, the keep-on-top icon, Q1–Q10, U1, U2)
come in their own plan; this one is only the memo list's cards, because the user asked to
apply them first.

## Intent

The list page is the loudest screen in the app: each card has a 1 px border, a header band in a
darker shade, and a saturated band for the current memo. The user wants calm cards that still
have "a bit of depth", a current-memo mark that belongs to the pastel palette, and soft motion
when moving between cards with the mouse or the arrow keys. Smoothness and cost stay where
Phase 8 left them.

## Goals

1. **Layout B, title first.** Title (bold, one line, cut with "…"), up to 3 preview lines,
   then a quiet footer with the date. Pictures stay under the preview.
2. **Paper lift.** No border, no header band. Under each card, three 1 px strips step from the
   page colour toward black (about 10 %, 6 %, 3 %), so the card reads as a sheet on the page.
3. **The current memo in its own tone.** A 3 px edge on the left in a mid tone of the card's
   own colour, and "현재 메모" in the footer in that colour's readable dark shade (≥ 4.5:1). The
   date stays grey. Nothing in ink or any colour outside the memo's own hue.
4. **Hover and arrow keys: the same lift.** The card's own colour deepens one step, the shadow
   deepens to 4 strips, and the card rises 1 px; the pin and trash show at the right of the
   title row. In over 120 ms (ease-out), back over 180 ms (ease-in), like the calendar's day
   hover. No ink ring.
5. **Done to-dos** on a card are dimmed and struck through, as in the note (Q6).
6. **Open in another window:** a small window icon and the words "다른 창에 열림" in the footer
   before the date (was an icon with a tooltip in the header band).

## Non-goals

- Rounded corners (each card would become a picture: memory and scroll cost).
- A gliding ring, or smooth scrolling of the list on arrow keys (dropped with the ring; can come
  later on its own).
- Changing the list's order, sections, search, preview pop-up, or the card menu.

## Anti-goals

- The list re-lays out when a card lifts (row heights must not change on hover).
- A card vanishes into a page of the same colour, or the hover tint is too faint to see on the
  palest colours (white, grey).
- New per-frame work beyond a handful of colour changes; new pictures per hover.

## Constraints

- Tk: widgets cannot fade; colours step through a fixed ramp of 5 (`CAL_HOVER_STEPS`), at most
  5 repaints per fade, as the calendar hover does.
- The list is a virtual column (Phase 5): rows are measured once and placed by y. A card's
  requested height must be the same at rest and lifted.
- Animations go through the frame clock with `kind="fade"` (Reduced keeps them, Off ends them).
- All words in Korean and English (`texts.py`).

## Approaches considered

| | Depth | Trade-off | Decision |
|---|---|---|---|
| A | Bevel: light top line, dark bottom line inside the card | Flat; little depth | No |
| B | Paper lift: 3 soft strips under the card | Reads as paper; 3 thin frames per card | **Chosen** |
| C | Stacked sheets | Heavy; competes with the text | No |

Current memo: ink edge (rejected by the user: outside the palette), a coloured ring (looks like
keyboard focus), always lifted (hover has nowhere to go), **own-tone edge and label (chosen)**.

Moving between cards: ink ring that glides (rejected: outside the palette), **darker tint of the
card's own colour plus the lift (chosen)**.

## Design

- **Colours (per card, worked out once when the card is made):**
  - `rest`: the memo's page colour; when it equals the list page's colour, mixed 45 % toward
    white (8 % on a dark colour) so the card stays visible.
  - `lit`: `shade(rest, 1)`, stepped further until `contrast(rest, lit) ≥ 1.12`.
  - shadow strips: the list page colour mixed toward black at (0.10, 0.06, 0.03) at rest and
    (0.14, 0.10, 0.06, 0.03) lifted; three times those weights on a dark page.
  - edge: from the memo's solid colour (or `shade(rest, 4)` for a pastel whose solid colour is
    its page) made `readable(…, rest, 2.2)`.
  - "현재 메모": `readable(edge, lit, 4.5)`. Date and footer words: `readable(muted, lit, 4.5)`,
    9 pt.
- **Constant height:** a 1 px spacer sits above the card at rest. Lifting forgets it and packs a
  1 px spacer at the bottom instead; the fourth shadow strip is always there (page colour at
  rest). The outer frame's requested height never changes.
- **Icons:** the pin and trash labels are always packed; at rest they show a transparent picture
  of the same size (a pinned memo's pin always shows). So the title row's height never changes.
- **Motion:** one animation per card (`animate(card, "lift", …, kind="fade")`) from the shown
  level to the target level (0 rest … 5 lit); the duration scales with the distance, so a quick
  in-and-out reverses from where it is. The rise (spacer swap) happens at level 3.
- **Arrow keys** use the same lift as hover; the picked card stays lit while the mouse is
  elsewhere.

## Left to the builder

- Exact strip weights on a dark page, and the "현재 메모" label weight (bold or regular 9 pt).
- How the title is measured and cut (one font object per family is enough).
- Test names and where the colour helpers live (`ui_views.py` unless reused elsewhere).

## Calls made in the conversation (for review)

- 45 % toward white for a card on a page of its own colour; 1.12 as the least hover contrast.
- The rise happens at level 3 of 5 (a 1 px step cannot be animated in between).
- The open-elsewhere words changed from "다른 노트에서 열림" to "다른 창에 열림".
