# Memo list: select many, move them to the bin (backlog item 4, draft, 2026-11-28)

The user's idea: "memo list all delete". Proposed: a select mode in the list; whatever goes, goes to
the bin with one Undo (never deleted for good from the list; the bin keeps them BIN_DAYS).

## How it works

- A "선택" (Select) icon in the list's head, beside the sort switch. In select mode:
  - each card shows a round check at its left edge (its title moves right by the check's width;
    the card keeps its height, so the virtual list does not re-measure);
  - a click on a card ticks it (no memo opens); Shift+click ticks the run between; Ctrl+A ticks
    every memo shown (the search filter counts: "all" means all you can see);
  - the bottom of the list (where the bin row is) becomes an action bar: "N개 선택됨",
    "모두 선택" / "선택 해제", and "휴지통으로" (danger ink);
  - Esc or the Select icon again leaves select mode, ticks cleared.
- "휴지통으로" moves every ticked memo to the bin at once and leaves select mode; the bottom bar
  says "메모 N개를 휴지통으로 옮겼어요" with Undo, which brings every one of them back (one Undo for
  the lot, not one per memo).
- A ticked memo open in a note window: that window shows its next memo, as a single delete does.
- Pinned memos can be ticked like any other.

## Tests first

- select mode shows the checks and the action bar; leaving clears the ticks;
- a click ticks, Shift+click ticks a run, Ctrl+A ticks all shown (with a search: only the matches);
- "휴지통으로" with 3 ticked: all 3 in the bin, one notice, one Undo brings all 3 back;
- an open memo among them: its window moves to another memo;
- the card heights are the same in and out of select mode (no re-measure);
- texts read at 4.5:1 and 9 pt (the B2 rule).

## Settled (2026-11-28)

- The Select icon: E762 (a list with checks, from the glyph sheet).
- No one-click "모두 휴지통으로" outside select mode (the user agreed): select mode plus Ctrl+A covers
  it with one more click and is harder to do by accident.
