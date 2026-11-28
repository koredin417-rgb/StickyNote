# Phase 9, part B: closing, saving, menus, readable text, wording, tips (design)

Part of the UI/UX overhaul agreed on 2026-11-28. It follows part A
(`2026-11-28-phase9a-fixes-design.md`) and the list cards (`2026-11-28-list-cards-design.md`).
Item numbers refer to `docs/2026-11-27-improvement-proposals.md`. The behaviour below is what was
proposed to the user on 2026-11-28 ("continue phase 9"); anything marked *call* is the
builder's own and is listed for review at the end.

It ships in three steps, each with its own tests, so each can be checked on its own:

## B1: closing, saving, one menu (Q7, Q8, U2)

- **× on pages (Q7).** On the list, settings and bin pages the × is hidden; ← and Esc go back.
  Minimize stays. After a note closes (not the last one), the note the keyboard goes to shows
  "노트를 닫았어요 [다시 열기]" / "Note closed [Reopen]" for UNDO_MS; Reopen is Ctrl+Shift+T's
  `reopen_closed`. An empty note that closes shows nothing. The last note's × tooltip says the
  app will close: "닫기 (마지막 노트: 앱이 닫혀요)" / "Close (last note: the app closes)".
- **Save failures (Q8).** After 2 failed saves in a row, every note shows a notice that stays
  until a save works: "저장하지 못했어요 [폴더 열기]" / "Couldn't save [Open folder]". Loading
  from `notes.json.bak` shows a notice once at start: "백업에서 메모를 불러왔어요" / "Memos were
  loaded from the backup". Settings › General gets "메모 폴더 열기" / "Open memo folder".
- **One menu (U2).** ⋯ opens the same menu as a right-click on the top row, plus the rail buttons
  a short note has no room for. The memo text gets its own right-click menu: cut, copy, paste,
  select all, bullets, to-do (with their keys).

## B2: readable text and wording (Q9, Q10)

- **Readable grey (Q9).** `Colors.muted_text`: the muted colour pushed to ≥ 4.5:1 on the page.
  Text uses it (dates, list heads, settings help, menu key labels, the bin's notes); icons and
  lines keep `muted` (3:1). UI text is never below 9 pt.
- **Wording (Q10).** One pass over `texts.py`: the bar along a note's top is "상단 바" / "top bar" everywhere
  (first "날짜 줄", then put back: the user's call, B3); "접기" names one
  action; on/off as 켬/끔 throughout; English labels in sentence case; dialog titles follow the
  language; unused strings removed (the two useful ones are used).

## B3: tips at the right moment (U1)

- The first-run wall of 9 tips goes. Each gesture gets one short tip, once, at the moment it
  matters, shown in the bottom bar like a notice (with ×):
  - first link (two notes snapped together): "Alt를 누른 채 끌면 따로 움직여요";
  - first close: the Reopen bar says "노트를 닫았어요 · Ctrl+Shift+T로도 다시 열 수 있어요";
  - first fold: "두 번 누르면 다시 펼쳐져요" (in the folded strip itself, which is the top bar; no room there for the bar);
  - first calendar: "날짜를 누르면 그날 메모, 두 번 누르면 새 메모예요".
- Picked style A (2026-11-28): the dark bottom bar with ×, for TIP_MS (10 s).
- A "단축키와 조작" / "Keys and gestures" page lists everything: a row in Settings > General,
  and ⋯ opens Settings with that page open (it replaces "Show the tips again").
- Which tips were shown is saved in prefs, so a tip never repeats.

## Non-goals

- New features (search, reminders, dark mode).
- Changing what any key or gesture does (only how it is taught).

## Calls made (for review)

- Q7: the close toast goes to the note the keyboard moves to; with none shown, no toast.
- Q8: the notice shows on every shown note, not just one.
- B3's tips use the bottom bar, not a balloon by the control (Tk has no cheap balloon that
  follows a moving window).
