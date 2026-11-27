# Self-update from GitHub Releases — design

## Why

Today a new version means sending people a new 21 MB `StickyNote.zip`, which they unzip and
run `install.cmd` from. People who never get or never run the new zip stay on old versions.
The app should be able to find a newer version on GitHub itself, and install it when the user
says so.

## What the user sees

Settings → **General** gets one more row: **Update** (`set_update`), whose value on the list
shows the installed version (`v1.1.0`). Its page shows:

```
Update
Installed version  v1.1.0
[ Check for updates ]

(after a check, one of:)
  You have the newest version.
  Couldn't reach GitHub. Check the internet connection and try again.
  New version v1.2.0
    <release notes, plain text, scrollable if long>
    [ Update now ]  [ Not now ]
  Downloading… 34%
  Installing — Sticky Note will close and open again.
```

- Nothing happens on its own: no check at start-up, no background polling. Only the button
  checks; only **Update now** downloads and installs.
- **Not now** just hides the offer; the next check shows it again.
- All text in Korean and English like every other string (`texts.py`).

## Goals / non-goals / anti-goals

- Goal: one click to check, one click to update; notes survive; app reopens on the new version.
- Non-goal: automatic or scheduled checks, skipping versions, going back to an older version
  by choice (a *failed* install is undone, see below), delta updates,
  updating copies run from somewhere other than the normal install folder (see below).
- Anti-goals (a failure even if it "works"):
  - losing or damaging a note, or leaving the app half-installed and unable to start;
  - freezing the note windows while checking or downloading;
  - a console window flashing up, or an admin (UAC) prompt;
  - installing anything that isn't the release's own asset.

## Approaches considered

- **A. GitHub Releases (chosen).** The developer publishes a Release tagged `vX.Y.Z` with
  release notes and `StickyNote.zip` attached. The app reads the latest release from the
  GitHub API. Only finished versions are offered, the notes come for free, and the zip stops
  being committed to git each time. Cost: one step on the GitHub website per release.
- B. A version file plus `dist/StickyNote.zip` on `main`. No new step, but every push to
  `main` goes live at once, the repo grows 21 MB per version, and raw files are cached for
  minutes. Rejected.
- (Downloading only the changed `app\` files from the repo tree: many requests, fragile.
  Dropped early.)

## How it works

### Version

- New module `app/version.py`: `VERSION = "1.1.0"` (the first build with the updater).
  Versions compare as tuples of ints (`"1.10.0" > "1.9.0"`); a leading `v` on tags is ignored.
  A tag that doesn't parse is treated as "no update".
- The release tag must equal `v` + `VERSION` inside the zip it carries.

### Checking

- `GET https://api.github.com/repos/koredin417-rgb/StickyNote/releases/latest`
  (newest non-draft, non-prerelease release), with a generic `User-Agent: StickyNote-updater`
  and `Accept: application/vnd.github+json`. No login: the repo is public, and the
  unauthenticated limit (60 requests/hour per IP) is plenty for a button.
- From the reply: `tag_name`, `body` (release notes), and the asset named exactly
  `StickyNote.zip` (`browser_download_url`, `size`, and `digest` = `sha256:<hex>` when present).
  A newer release without that asset counts as "no update".
- **Testing against a pre-release** *(my call)*: when the environment variable
  `STICKYNOTE_UPDATE_PRERELEASE=1` is set, the app reads `/releases` instead and takes the
  newest non-draft release, pre-releases included. Ordinary users never see pre-releases.
- **Release notes** *(my call)*: shown as written (one language, the developer's choice;
  Korean recommended since that's who uses it), with simple Markdown marks (`#`, `*`, `-`,
  `` ` ``) stripped to plain text. No per-language splitting.

### HTTPS without Python's `ssl`

The bundled runtime has no `_ssl` module, so `urllib` can't do HTTPS. Requests go through
**WinHTTP via `ctypes`** (in the style of `winapi.py`): system proxy settings, system
certificates, redirects followed (asset downloads redirect to another GitHub host), no extra
process, no console. *(Builder's call if WinHTTP proves painful: `curl.exe` from System32 with
`CREATE_NO_WINDOW` is an acceptable fallback; adding `_ssl.pyd` + OpenSSL DLLs to the runtime is
not.)*

### Not freezing the UI

The app is single-threaded Tk. The check and the download run on a `threading.Thread`; the
thread never touches Tk. It puts results/progress into a `queue.Queue`, and the settings page
reads it from a short `root.after` poll while a check or download is running. Only one check or
download at a time; closing the settings page doesn't cancel a download (the result is shown
next time the page opens, or simply applied on **Update now** finishing).

### Downloading and applying

1. Download to `%TEMP%\StickyNote-update-<version>\StickyNote.zip`. Check the size, and the
   SHA-256 when the release gives a digest; on mismatch, delete and report an error.
2. Extract with `zipfile` into the same temp folder. Reject entries with absolute paths or `..`.
   The zip's top folder is `StickyNote\` (as today); confirm it has `runtime\python.exe` and
   `app\install.py`.
3. Start the **new** installer with the **new** runtime, detached and with no window:
   `<tmp>\StickyNote\runtime\python.exe <tmp>\StickyNote\app\install.py --yes --dest <install dir>`
   with `CREATE_NO_WINDOW | DETACHED_PROCESS`.
4. The installer does what it already does: asks the running app to quit through `waker`
   ("quit": the app saves and closes), waits, syncs only changed files, remakes the shortcuts,
   launches the app.
5. The app does nothing else to itself; it is closed by step 4 like any install.

### Installer changes (`install.py`)

- New `--yes`: no `input()` question (closing the app is already agreed), no `_pause`.
- Writes the outcome to `%APPDATA%\StickyNote\update-result.json`
  (`{"version": ..., "ok": true|false, "error": "..."}`) when run with `--yes`.
- **A failed install puts the old version back** *(my call)*. Today `_copy_file` truncates
  each target and writes it in place, so a disk-full error or a lock lasting past `_retry` could
  leave old and new files mixed. Instead: each file is written to `<target>.new`, the file it
  replaces is moved into a backup folder next to the install (`<dest>\.update-backup\`), then
  `.new` is renamed into place; files removed by the new version also go to the backup. On any
  error, everything in the backup goes back and new-only files are deleted. On success the
  backup is deleted. This applies to the manual `install.cmd` path too (it gets safer as well).
- After success or a restored failure, the installer relaunches the app, so the user is never
  left with no app.
- Under `--yes` its helper calls (`powershell` process listing, `taskkill`) run with
  `CREATE_NO_WINDOW`, so nothing flashes up.
- The temp folder is cleaned up by the next app start (it can't delete itself while running).

### After restart

At start-up the app reads and deletes `update-result.json`. Success: a brief confirmation
("Updated to v1.2.0") through the existing toast, `NoteWindow.show_notice`. Failure: the error on the Update page. It also deletes leftover
`%TEMP%\StickyNote-update-*` folders.

### Which copies can update

Only an app running from the normal install folder (`%LOCALAPPDATA%\Programs\StickyNote`)
offers **Update now**. Run from anywhere else (the repo checkout, an unzipped folder), the page
still checks and shows the new version, but says to install it from GitHub instead — so a
developer run never overwrites the repo.

### Errors to handle

No network / DNS / proxy failure; GitHub rate limit (HTTP 403/429); unexpected JSON; asset
missing; download cut off; digest mismatch; bad zip; installer failed to start; disk full.
Each ends in a short plain message on the Update page; none leaves the app closed.

## Releasing (developer side)

- New `tools/make_release.py`: reads `VERSION`, builds `dist/StickyNote.zip` from
  `StickyNote\` (skipping `__pycache__`), prints the tag to use (`v1.2.0`) and the file's
  SHA-256.
- Then on GitHub: **Releases → Draft a new release**, tag `v1.2.0`, write the notes, attach
  `StickyNote.zip`, publish. (Could later be scripted with a token; not part of this work.)
- `dist/StickyNote.zip` no longer needs committing for each version.
- Existing installs have no updater: everyone reinstalls `v1.1.0` from its zip once; from then
  on, updates come through Settings.

## Testing

- Unit tests (no network): version parsing/compare; picking the asset and handling a release
  reply with/without asset/digest; zip-safety checks; installer `--yes` path with a temp
  `--dest` and the result file.
- The HTTP layer behind one small function so tests can fake replies.
- Installer: a forced failure mid-copy (patched copy that raises) restores the old files exactly.
- One manual end-to-end run against a real pre-release on the repo (with
  `STICKYNOTE_UPDATE_PRERELEASE=1`) before publishing it as a full release.

## Left to the builder

Exact layout and wording of the Update page within the existing settings style; module split
(`updater.py` for check/download/apply is the expectation); WinHTTP details; how long the poll
interval is.

The work goes on its own branch, `self-update`, in its own worktree, started from the last
commit of `phase8-feedback` (so v1.1.0 ships with the phase 8 work; the uncommitted calendar
changes in the main checkout stay untouched).
