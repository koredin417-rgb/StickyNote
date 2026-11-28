# First start (backlog item 5, draft, 2026-11-28)

The user's idea: the first time the app opens, the background dims, the language is chosen, and a
short tour highlights the controls (everything else dark), with a way to skip and to see it again
later. Only for a new data folder (`NoteStore.fresh`): people updating never see it.

## Order (Claude's)

1. **The dim.** A click-through-free, topmost window over the note's screen at about 55 % black,
   with a hole cut round the spotlight (`winapi.clip_box(..., holes=[...])`, already used by the
   page change). One window for the whole tour; only its hole moves.
2. **Language first.** A small card on the dim: "한국어 / English", two big buttons (the app's
   language follows `texts.DEFAULT` until then), and "건너뛰기 / Skip tour" under them.
3. **The tour, 5 stops** (each: the hole eases to the control over `anim.BASE`, a card beside it
   with one or two lines, "다음" and "건너뛰기"; ← → and Enter / Esc work):
   1. the note itself: "여기에 바로 쓰면 저장돼요" (typing saves by itself);
   2. the top bar: "끌어서 옮기고, 두 번 누르면 접혀요" (drag to move, double-click to fold);
   3. the rail: "새 메모, 목록, 달력, 맨 앞에 두기" (and, with the calm rail: "쓰지 않을 때는 숨어요");
   4. the colour dot: "메모 색을 바로 바꿔요";
   5. ⋯: "나머지는 모두 여기, 단축키는 설정 > 단축키와 조작".
4. **The end.** The dim fades out (`anim.LONG`) and the note has the focus, ready to type.
   A welcome memo (Claude's extra idea, to agree on) could hold a to-do to tick: "이 줄을 체크해
   보세요".

## Again later

- Settings > 일반 > "둘러보기 다시 보기" (replay the tour), beside "단축키와 조작".
- The one-time tips (B3) stay as they are; the tour does not mark them seen.

## Rules

- Never for people updating (`fresh` False), never twice (`prefs.tour_done`).
- Skippable at every step (Esc, "건너뛰기", a click outside the card on the dim).
- Motion: Reduced keeps the fades, the hole jumps; Off: everything at once.
- Readable at 4.5:1 and 9 pt (B2); the cards in the main theme colour, like menus and tips.
- Tests first (on the hidden desktop): fresh shows it, updating does not; skip at each stop ends
  it and saves `tour_done`; the hole is over each stop's control; replay from Settings.

## Settled (the user's calls, 2026-11-28)

1. **The flow:** the dim and the language card first ("한국어 / English": everything after is in the
   language picked), then the welcome memo, then the tour.
2. **The welcome memo** opens with one to-do line: "시작합니다. 박스를 체크해 주세요" /
   "Let's start. Tick the box to begin." Ticking it starts the tour (the to-do settles as done,
   phase 10 D, and the first stop's hole eases in). "건너뛰기" stays on the dim for anyone who
   would rather not.
3. **Five stops**, as listed above.
