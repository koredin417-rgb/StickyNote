# StickyNote — working rules

A Tk desktop sticky-note app for Windows (Korean / English). The app is in `StickyNote/app/`,
tests in `tests/`, tools in `tools/`. Run Python with the bundled runtime:
`.\StickyNote\runtime\python.exe` (Python 3.15; no `unittest.mock`, no `cProfile` — use
`tests/_support.py`'s `patched` and `Spy`).

## Data and safety
- Never touch `%APPDATA%\StickyNote` (the user's real notes). Tests, captures and benches use
  scratch folders; the developer preview uses `StickyNote/preview-data/` (git-ignored).

## Tests
- GUI tests and captures run on a hidden desktop only, never on the user's screen:
  `.\StickyNote\runtime\python.exe tools\hidden_tests.py` (whole suite, `-v` for names),
  `-p "test_x.py"` for one file, `-k name` to filter, `--script path args` for a capture script.
- The full suite takes ~19 minutes: post a progress bar with an ETA in the chat while it runs,
  and do the work that doesn't depend on its result meanwhile.
- A test about input must send real events through Tk's queue (`event_generate(..., when="tail")`
  on a timer), not call handlers directly: a key the text binds itself hides from `<KeyPress>`.

## Look
- Smooth look comes first. Round or curved shapes (dots, swatches, checks, rings, pills) are
  anti-aliased pictures (PIL, drawn 8x and shrunk, cached), like `dot_photo`, `chip_photo`,
  `switch_photo`, `thumb_caps` in `ui_common.py` — never Tk `create_oval`/`create_arc`/round caps.
- Check visual changes with a zoomed hidden-desktop capture before calling them done.

## Every phase ends shipped: suite → PR → release
1. Full suite green on the hidden desktop.
2. Raise `VERSION` in `StickyNote/app/version.py`; move CHANGELOG.md's "Unreleased" to that
   version; update the tests that pin VERSION (`test_update_settings`, `test_updater_logic`).
3. Commit on a branch, push, open the PR (`gh pr create`), merge it when the user has asked for
   the release.
4. On main, level with origin: `.\StickyNote\runtime\python.exe tools\release.py --title "…"`.
   It builds `dist\StickyNote.zip` from that commit, checks it with the updater's own unpack,
   tags `v<VERSION>`, publishes the release with the CHANGELOG section, and checks the uploaded
   file's sha256. A zip whose VERSION is not its tag's is refused by the apps (v1.2.1 was).
- GitHub CLI: if `gh` is not on PATH (a shell started before it was installed), use
  `"C:\Program Files\GitHub CLI\gh.exe"`. Sign-in is the user's (`gh auth login`), never ours.
