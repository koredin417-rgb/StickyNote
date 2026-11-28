# Self-update from GitHub Releases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settings → General → Update checks GitHub's latest release and, when the user says so, downloads and installs it, with the app reopening on the new version.

**Architecture:** `version.py` holds the version. `webget.py` does HTTP(S) through WinHTTP via `ctypes` (the bundled Python has no `ssl`). `updater.py` holds the pure release logic plus an `Updater` object, one per `App`, that runs the check/download on a worker thread and reports through a queue the Tk loop drains with `root.after`. It hands off to the new zip's own `install.py --yes`, which now swaps files with a backup it restores on failure, and writes `update-result.json` that the next start shows.

**Tech Stack:** Python 3.15 (bundled runtime), Tkinter, `ctypes` + `winhttp.dll`, `zipfile`, `hashlib`, `threading`/`queue`, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-27-self-update-design.md`

## Global Constraints

- Work in a worktree on branch `self-update`, started from `767f607` (the last commit of `phase8-feedback`). Never touch the main checkout's uncommitted `ui_calendar.py` / `tests/test_calendar_feedback.py`.
- Run tests from the worktree root with the bundled runtime: `.\StickyNote\runtime\python.exe -m unittest discover -s tests -v` (one file: add `-p test_x.py`). The runtime's `._pth` puts `StickyNote\app` on the path, so tests `import updater` directly.
- No new dependencies; no `_ssl.pyd`/OpenSSL in the runtime.
- `VERSION = "1.1.0"`; tags are `v` + version; the asset name is exactly `StickyNote.zip`.
- API: `https://api.github.com/repos/koredin417-rgb/StickyNote/releases/latest`; with env `STICKYNOTE_UPDATE_PRERELEASE=1`, `https://api.github.com/repos/koredin417-rgb/StickyNote/releases` instead. Headers `User-Agent: StickyNote-updater`, `Accept: application/vnd.github+json`.
- Nothing checks or downloads without a button press. Neither the app nor the installer shows a console window or a UAC prompt on the update path.
- Every user-facing string is in `texts.py` in Korean and English.
- Comments and docstrings follow the codebase's style: short, plain sentences saying what and why.

## Review Focus

1. **Installer killed mid-copy (power loss, task kill):** the next install, by hand or by update, finds `<dest>\.update-backup\journal.txt` and puts the old files back before it starts. → Task 3, `test_interrupted_install_is_recovered`.
2. **Another `StickyNote-update-*` folder from a failed update still in `%TEMP%`:** a new download into the same version's folder starts clean, not on top of the old files. → Task 5, `test_download_dir_starts_empty`.
3. **The user presses Check twice quickly, or in two notes' settings:** one worker only; both pages show the same state. → Task 5, `test_second_check_while_busy_is_ignored`; Task 6, `test_two_settings_pages_share_state`.
4. **The app is run from the repo checkout or an unzipped folder:** it never offers Update now and never starts an installer. → Task 5, `test_elsewhere_never_installs`.
5. **A release whose zip carries a different `VERSION` than its tag (mis-packaged):** refused before the installer runs. → Task 5, `test_zip_version_must_match_tag`.

---

### Task 1: Version and release logic (pure)

**Files:**
- Create: `StickyNote/app/version.py`
- Create: `StickyNote/app/updater.py` (pure part only in this task)
- Test: `tests/test_updater_logic.py`

**Interfaces:**
- Produces:
  - `version.VERSION: str = "1.1.0"`
  - `updater.parse_version(text: str) -> tuple[int, ...] | None` (`"v1.2.0"` → `(1, 2, 0)`; anything not `v?\d+(\.\d+)*` → `None`)
  - `@dataclass(frozen=True) updater.Release(version: str, tag: str, notes: str, url: str, size: int, sha256: str | None)` (`version` without `v`; `notes` already plain text)
  - `updater.pick_release(reply, current: str) -> Release | None`: `reply` is the decoded JSON, one release (dict) or a list of them. Skips drafts, unparseable tags and releases without a `StickyNote.zip` asset; returns the newest one newer than `current`, else `None`. `sha256` comes from the asset's `digest` when it starts with `sha256:`.
  - `updater.plain_notes(markdown: str) -> str`
  - `updater.api_url(environ=os.environ) -> str`: the two URLs from Global Constraints.

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_version(self):
    self.assertEqual(parse_version("v1.2.0"), (1, 2, 0))
    self.assertEqual(parse_version("1.10"), (1, 10))
    self.assertIsNone(parse_version("latest"))
    self.assertIsNone(parse_version("v1.2-beta"))
    self.assertGreater(parse_version("1.10.0"), parse_version("1.9.0"))

def test_version_constant_parses(self):
    self.assertEqual(parse_version(version.VERSION), (1, 1, 0))

def test_pick_newer_release(self):
    r = pick_release(release("v1.2.0", digest="sha256:ab"), "1.1.0")
    self.assertEqual((r.version, r.tag, r.size, r.sha256), ("1.2.0", "v1.2.0", 123, "ab"))
    self.assertEqual(r.url, "https://example.test/StickyNote.zip")

def test_same_or_older_is_none(self):
    self.assertIsNone(pick_release(release("v1.1.0"), "1.1.0"))
    self.assertIsNone(pick_release(release("v1.0.9"), "1.1.0"))

def test_no_asset_or_bad_tag_or_draft_is_none(self):
    self.assertIsNone(pick_release(release("v2.0.0", asset="Other.zip"), "1.1.0"))
    self.assertIsNone(pick_release(release("nightly"), "1.1.0"))
    self.assertIsNone(pick_release(release("v2.0.0", draft=True), "1.1.0"))

def test_list_reply_takes_newest(self):     # the pre-release listing
    reply = [release("v1.2.0"), release("v1.3.0", prerelease=True), release("v9.0.0", draft=True)]
    self.assertEqual(pick_release(reply, "1.1.0").version, "1.3.0")

def test_no_digest(self):
    self.assertIsNone(pick_release(release("v1.2.0"), "1.1.0").sha256)

def test_plain_notes(self):
    self.assertEqual(plain_notes("## Fixes\n* **Faster** `drag`\n- calendar"),
                     "Fixes\n• Faster drag\n• calendar")

def test_api_url(self):
    self.assertTrue(api_url({}).endswith("/releases/latest"))
    self.assertTrue(api_url({"STICKYNOTE_UPDATE_PRERELEASE": "1"}).endswith("/releases"))
```

`release(tag, asset="StickyNote.zip", digest=None, draft=False, prerelease=False)` is a test helper building the GitHub shape: `{"tag_name", "body": "notes", "draft", "prerelease", "assets": [{"name", "browser_download_url": "https://example.test/StickyNote.zip", "size": 123, "digest"}]}`.

- [ ] **Step 2: Run to verify it fails** — `.\StickyNote\runtime\python.exe -m unittest discover -s tests -p test_updater_logic.py -v` → `ModuleNotFoundError: No module named 'updater'`.
- [ ] **Step 3: Implement** `version.py` and the functions above in `updater.py`. `plain_notes`: per line, drop leading `#`s and their space, turn a leading `* `/`- ` into `• `, remove `**` and backticks, trim trailing blank lines.
- [ ] **Step 4: Run to verify it passes** — same command → all PASS.
- [ ] **Step 5: Commit** — `git add StickyNote/app/version.py StickyNote/app/updater.py tests/test_updater_logic.py; git commit -m "feat(update): version and release picking"`

---

### Task 2: HTTP(S) through WinHTTP

**Files:**
- Create: `StickyNote/app/webget.py`
- Test: `tests/test_webget.py`

**Interfaces:**
- Produces:
  - `class webget.WebError(Exception)` with `.status: int | None` (HTTP status, `None` for a connection failure) and `.disk: bool` (`True` when writing the file failed for lack of space, winerror 112 / `errno.ENOSPC`).
  - `webget.get(url: str, headers: dict[str, str], timeout: float = 15.0) -> bytes`: raises `WebError` on non-2xx or on any WinHTTP failure.
  - `webget.download(url: str, path: Path, headers: dict[str, str], on_progress: Callable[[int, int | None], None] | None = None, timeout: float = 30.0) -> int`: streams into `path` (written as `path` + `.part`, renamed when complete), calls `on_progress(done, total)` (total from `Content-Length`, else `None`), returns the byte count.

- [ ] **Step 1: Write the failing tests** against a local `http.server.ThreadingHTTPServer` on `127.0.0.1:0` run in a thread (plain `http://`; `webget` takes both schemes, the updater only ever passes `https`):

```python
def test_get_ok(self):           # /hello -> 200 b"hi"
    self.assertEqual(webget.get(self.url("/hello"), {"User-Agent": "t"}), b"hi")

def test_headers_sent(self):     # /echo-agent -> 200 with the User-Agent as body
    self.assertEqual(webget.get(self.url("/echo-agent"), {"User-Agent": "StickyNote-updater"}),
                     b"StickyNote-updater")

def test_redirect_followed(self):  # /moved -> 302 Location /hello
    self.assertEqual(webget.get(self.url("/moved"), {}), b"hi")

def test_status_error(self):     # /missing -> 404
    with self.assertRaises(webget.WebError) as cm:
        webget.get(self.url("/missing"), {})
    self.assertEqual(cm.exception.status, 404)

def test_no_server(self):        # a port nobody listens on
    with self.assertRaises(webget.WebError) as cm:
        webget.get("http://127.0.0.1:9/", {}, timeout=2)
    self.assertIsNone(cm.exception.status)

def test_download_progress(self):  # /big -> 300_000 bytes with Content-Length
    seen = []
    n = webget.download(self.url("/big"), self.tmp / "f.bin", {}, lambda d, t: seen.append((d, t)))
    self.assertEqual(n, 300_000)
    self.assertEqual((self.tmp / "f.bin").stat().st_size, 300_000)
    self.assertEqual(seen[-1], (300_000, 300_000))
    self.assertFalse((self.tmp / "f.bin.part").exists())

@unittest.skipUnless(os.environ.get("STICKYNOTE_NET_TESTS") == "1", "network")
def test_github_https(self):
    body = webget.get("https://api.github.com/repos/koredin417-rgb/StickyNote",
                      {"User-Agent": "StickyNote-updater"})
    self.assertIn(b'"full_name"', body)
```

- [ ] **Step 2: Run to verify it fails** — `-p test_webget.py` → `ModuleNotFoundError`.
- [ ] **Step 3: Implement** with `ctypes.WinDLL("winhttp", use_last_error=True)`: `WinHttpOpen(agent, WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY=4, None, None, 0)` → `WinHttpSetTimeouts` → `WinHttpConnect(host, port)` → `WinHttpOpenRequest("GET", path+query, …, WINHTTP_FLAG_SECURE=0x00800000 only for https)` → `WinHttpSendRequest` with the headers joined by `\r\n` → `WinHttpReceiveResponse` → `WinHttpQueryHeaders(WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER)` and `WINHTTP_QUERY_CONTENT_LENGTH` → `WinHttpQueryDataAvailable`/`WinHttpReadData` loop → `WinHttpCloseHandle` on every handle in `finally`. Set `argtypes`/`restype` (handles `c_void_p`, strings `c_wchar_p`). WinHTTP follows redirects by default, so there's no redirect code of our own. On Windows 8.1 and older (`AUTOMATIC_PROXY` → error 87), retry once with `WINHTTP_ACCESS_TYPE_DEFAULT_PROXY=0`.
- [ ] **Step 4: Run to verify it passes**, then once with `$env:STICKYNOTE_NET_TESTS = '1'` to cover real HTTPS → all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(update): HTTPS through WinHTTP"`

---

### Task 3: Installer swaps files with a backup it can restore

**Files:**
- Modify: `StickyNote/app/install.py` (`_sync_tree`, `_copy_file`, `install`)
- Test: `tests/test_install_swap.py`

**Interfaces:**
- Produces:
  - `install.BACKUP_DIR = ".update-backup"` (under `dest`), journal `journal.txt` in it.
  - `install.install(source, dest, link_dirs) -> list[Path]`: same signature. On any exception during the copy, it restores and re-raises.
  - `install.recover(dest: Path) -> bool`: if a backup is there, puts it back (newest journal entry first) and deletes it. Returns whether it did anything. `install()` calls it first.

Journal lines (UTF-8, one per action, flushed and `os.fsync`ed before the action): `replaced\t<rel>` (old file moved to `<backup>/<rel>`), `added\t<rel>` (no old file), `removed\t<rel>` (old file the new version lacks, moved to backup). Undo: `replaced`/`removed` → move back from backup; `added` → delete. Files only; directories created stay (empty leftovers are harmless, as the docstring of `_sync_tree` already says).

Per file: write `<target>.new` (contents only, as `_copy_file` does now), then journal, then move the old file into the backup, then `os.replace(<target>.new, target)`, all inside `_retry`. On success: delete the backup folder.

- [ ] **Step 1: Write the failing tests** (temp `source`/`dest` trees with `runtime/`, `app/main.py`, `licenses/`; `link_dirs=[]`; monkeypatch `install._icons_changed` to a no-op):

```python
def test_fresh_install_and_update(self):     # files copied; an update replaces and removes; no backup left
def test_failure_restores_old_files(self):
    # dest has app/a.py = b"old", app/gone.py; source has app/a.py = b"new", app/b.py = b"add".
    # patch install.os.replace to raise OSError on the 2nd call
    with self.assertRaises(OSError):
        install.install(self.src, self.dest, [])
    self.assertEqual((self.dest / "app/a.py").read_bytes(), b"old")
    self.assertTrue((self.dest / "app/gone.py").exists())
    self.assertFalse((self.dest / "app/b.py").exists())
    self.assertFalse((self.dest / install.BACKUP_DIR).exists())
    self.assertEqual(sorted(p.name for p in (self.dest / "app").glob("*.new")), [])

def test_interrupted_install_is_recovered(self):
    # build a backup + journal by hand as a killed install would leave it
    # (a.py replaced: new in place, old in backup; b.py added), then:
    self.assertTrue(install.recover(self.dest))
    self.assertEqual((self.dest / "app/a.py").read_bytes(), b"old")
    self.assertFalse((self.dest / "app/b.py").exists())
    self.assertFalse(install.recover(self.dest))

def test_unchanged_files_not_touched(self):  # same bytes: no journal entry, mtime unchanged
```

- [ ] **Step 2: Run to verify it fails** — `-p test_install_swap.py` → failures (no `recover`, no restore).
- [ ] **Step 3: Implement** as described. Keep `_same_file` skipping, the `__pycache__` skip, and the "only remove what Windows lets go" leniency for removals (a removal that fails is skipped, not an error).
- [ ] **Step 4: Run to verify it passes**, plus the whole suite (the installer is used by other tests' fixtures only indirectly, but check) → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(install): swap files with a backup restored on failure"`

---

### Task 4: Installer `--yes` (quiet, result file, always relaunch)

**Files:**
- Modify: `StickyNote/app/install.py` (`main`, `close_running`, `_app_processes`, `_pause`)
- Test: `tests/test_install_quiet.py`

**Interfaces:**
- Consumes: Task 3's `install`, `recover`.
- Produces:
  - CLI: `install.py --yes [--dest D] [--no-launch]`.
  - `install.RESULT_FILE = "update-result.json"` in `data_folder()`: `{"version": "<VERSION of the installer's own folder>", "ok": bool, "error": "<str, empty when ok>"}`, written only with `--yes`.
  - `install.NO_WINDOW = subprocess.CREATE_NO_WINDOW`, passed as `creationflags` to the `powershell` and `taskkill` runs when quiet.

With `--yes`: `close_running` doesn't ask (`input` is never called), `_pause` does nothing, every exit path writes the result file. After a failed `install()` (already restored by Task 3) it still calls `launch(dest, [])` so an app is running again. If the app couldn't be closed: result `ok: false`, `error: "still running"`, nothing installed, and no relaunch (it's still running). Without `--yes`, behaviour is as today.

- [ ] **Step 1: Write the failing tests** (call `install.main([...])` with `--dest` in a temp folder, `--link-dir` a temp folder, `--source` a temp tree; patch `install.data_folder`, `install.launch`, `winapi.instance_running` → `False`, `shortcut.create` → no-op, `builtins.input` → raises `AssertionError`):

```python
def test_yes_writes_ok_result(self):
    self.assertEqual(install.main(["--yes", *self.args]), 0)
    self.assertEqual(json.loads((self.data / "update-result.json").read_text("utf-8")),
                     {"version": version_of(self.src), "ok": True, "error": ""})
    self.launch.assert_called_once()

def test_yes_failure_writes_error_and_relaunches(self):  # install.install raises OSError("disk")
    self.assertEqual(install.main(["--yes", *self.args]), 1)
    result = json.loads((self.data / "update-result.json").read_text("utf-8"))
    self.assertFalse(result["ok"]); self.assertIn("disk", result["error"])
    self.launch.assert_called_once()

def test_yes_still_running(self):   # instance_running True, close_running returns False
    self.assertEqual(install.main(["--yes", *self.args]), 1)
    self.assertEqual(json.loads(...)["error"], "still running")
    self.launch.assert_not_called()

def test_without_yes_no_result_file(self):
    install.main(self.args)
    self.assertFalse((self.data / "update-result.json").exists())
```

`version_of(src)` reads `VERSION` from `src/app/version.py` (the fixture writes one: `VERSION = "9.9.9"`). The installer reads it the same way from `--source`, never by importing `version` (the importable one is the installer's own, which is the same file in real use, but the test proves it reads the source's).

- [ ] **Step 2: Run to verify it fails** → `unrecognized arguments: --yes`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to verify it passes** (+ Task 3's tests) → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(install): --yes for the in-app update"`

---

### Task 5: The `Updater`: check, download, verify, unpack, hand off

**Files:**
- Modify: `StickyNote/app/updater.py`
- Test: `tests/test_updater_flow.py`

**Interfaces:**
- Consumes: Task 1 (`pick_release`, `api_url`, `Release`, `parse_version`), Task 2 (`webget.get`, `webget.download`, `WebError`), Task 4's CLI.
- Produces:
  - `class Updater(app_dir: Path, *, get=webget.get, download=webget.download, popen=subprocess.Popen, temp_dir: Path | None = None, install_dir: Path | None = None)`. `install_dir` defaults to `install.default_dest()`, `temp_dir` to `tempfile.gettempdir()`.
  - State attributes, read on the Tk thread only: `state: str` ∈ `"idle" | "checking" | "latest" | "available" | "downloading" | "installing" | "error"`, `release: Release | None`, `progress: float` (0–1), `error: str` (a `texts` key, below), `error_detail: str` (the `{e}` of `upd_err_install`, else empty). The page shows `tr(error, e=error_detail)`.
  - `can_install: bool`: `app_dir.parent.resolve() == install_dir.resolve()`.
  - `check() -> None`, `start_install() -> None`, `dismiss() -> None` (`"available"` → `"idle"`). Each is ignored when the state doesn't allow it: `check` only from `idle/latest/available/error`, `start_install` only from `available` and only when `can_install`.
  - `pump() -> bool`: applies the worker's queued messages on the Tk thread, calls every `listeners` callback once if anything changed, and returns whether a worker is still busy.
  - `listeners: list[Callable[[], None]]`.
  - `HEADERS = {"User-Agent": "StickyNote-updater", "Accept": "application/vnd.github+json"}`.
  - Module functions: `read_result(data_folder: Path) -> dict | None` (reads and deletes `update-result.json`; bad JSON → `None`, the file is still deleted) and `clean_temp(temp_dir: Path | None = None) -> None` (`shutil.rmtree(..., ignore_errors=True)` on every `StickyNote-update-*`).
  - Error keys: `upd_err_network` (WebError, status `None`), `upd_err_rate` (403/429), `upd_err_reply` (bad JSON/shape, any other status), `upd_err_download` (download WebError), `upd_err_disk` (`.disk` or `OSError` ENOSPC), `upd_err_verify` (size or sha256 mismatch), `upd_err_zip` (bad zip, unsafe name, missing files, version mismatch), `upd_err_start` (`popen` raised).

Install flow on the worker (after `start_install`):
1. `folder = temp_dir / f"StickyNote-update-{release.version}"`: `rmtree` it first, then `mkdir`.
2. `download(release.url, folder / "StickyNote.zip", HEADERS, on_progress)`; progress messages go on the queue.
3. Check size == `release.size`, and the SHA-256 when `release.sha256` is set; on mismatch delete the zip → `upd_err_verify`.
4. Extract. Refuse (`upd_err_zip`) any name that is absolute, has a drive, or has a `..` part. Require `StickyNote/runtime/python.exe` and `StickyNote/app/install.py`, and `StickyNote/app/version.py` whose `VERSION = "..."` equals `release.version`.
5. State `"installing"`; `popen([<x>/runtime/python.exe, <x>/app/install.py, "--yes", "--dest", str(install_dir)], cwd=<x>/app, close_fds=True, creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)`. The installer then quits the app over `waker` ("quit"); the Updater does nothing more.

- [ ] **Step 1: Write the failing tests** with fakes for `get`/`download`/`popen`, and a helper `make_zip(path, version="1.2.0", extra=None)` building a valid release zip:

```python
def test_check_finds_new(self):        # get returns a release v1.2.0 JSON
    u = self.updater(); u.check(); self.drain(u)
    self.assertEqual((u.state, u.release.version), ("available", "1.2.0"))
def test_check_latest(self):           # release v1.1.0 -> "latest"
def test_check_network_error(self):    # get raises WebError(None) -> ("error", "upd_err_network")
def test_check_rate_limited(self):     # WebError(403) -> "upd_err_rate"
def test_check_bad_json(self):         # b"<html>" -> "upd_err_reply"
def test_second_check_while_busy_is_ignored(self):  # get blocks on an Event; 2 checks -> get called once
def test_listeners_called_on_change(self):
def test_install_runs_new_installer(self):
    # download writes make_zip(...); popen recorded
    args = self.popen.call_args
    self.assertEqual(args.args[0][1:], [str(x / "app/install.py"), "--yes", "--dest", str(self.install_dir)])
    self.assertEqual(u.state, "installing")
def test_size_mismatch(self):          # -> "upd_err_verify", zip deleted, popen not called
def test_sha_mismatch(self):
def test_unsafe_zip_name(self):        # member "StickyNote/../../evil.txt" -> "upd_err_zip", nothing written outside
def test_zip_version_must_match_tag(self):  # zip VERSION "1.3.0", release 1.2.0 -> "upd_err_zip"
def test_download_dir_starts_empty(self):   # a stale file in the folder is gone after a new install
def test_disk_full(self):              # download raises WebError(disk=True) -> "upd_err_disk"
def test_elsewhere_never_installs(self):    # app_dir not under install_dir: can_install False; start_install no-op
def test_read_result_once(self):
def test_clean_temp(self):
```

`drain(u)` calls `u.pump()` until it returns `False` (2 s cap).

- [ ] **Step 2: Run to verify it fails** → `AttributeError: module 'updater' has no attribute 'Updater'`.
- [ ] **Step 3: Implement.** One `threading.Thread(daemon=True)` per check/install; `queue.Queue` of `(attr, value)` pairs; the worker never touches Tk or the state attributes directly.
- [ ] **Step 4: Run to verify it passes** (+ Task 1 tests) → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(update): check, download and hand off to the installer"`

---

### Task 6: Settings page, texts, App wiring

**Files:**
- Modify: `StickyNote/app/app.py` (create `self.updater`; start-up result and temp cleanup)
- Modify: `StickyNote/app/ui_views.py` (`SETTING_GROUPS`, `SETTING_HELP`, the `set_update` page, `_value_text`)
- Modify: `StickyNote/app/texts.py`
- Test: `tests/test_update_settings.py`

**Interfaces:**
- Consumes: Task 5's `Updater`, `read_result`, `clean_temp`; `NoteWindow.show_notice(text)`.
- Produces: `App.updater: Updater` (made in `App.__init__` with `app_dir=Path(updater.__file__).resolve().parent`; tests replace it with a faked `Updater` before opening settings). `App._update_poll()` reschedules itself every 100 ms with `root.after` while `updater.pump()` returns `True`. `check()`/`start_install()` from the page start it.

Wiring:
- `SETTING_GROUPS` `grp_general` gets `"set_update"` last; `SETTING_HELP["set_update"] = "help_update"`; `_value_text("set_update")` → `f"v{version.VERSION}"`.
- The page (built with the existing `page()` helper, `FlatButton`, labels added to `self.labels`/`self.muted`/`self.flat` so recolouring works): an "installed version" line, the **Check** button, and a status area redrawn from `app.updater` by a listener the view adds on build and removes when its window closes. Per state: `checking` → `upd_checking`; `latest` → `upd_latest`; `error` → `tr(error)`; `available` → `upd_new` + the notes (a wrapped `Label`, at most 12 lines shown, the rest cut with `…`), then **Update now** + **Not now** (when `can_install`), or `upd_elsewhere` instead of those two buttons; `downloading` → `upd_downloading` with the percent; `installing` → `upd_installing`. The Check button is disabled while `checking/downloading/installing`.
- At the end of `App.__init__`: `updater.clean_temp()`, then `read_result(folder)`. Success → `show_notice(tr("upd_done", v=...))` on the first window, after 600 ms. Failure → `show_notice(tr("upd_failed"))`, and `updater.state = "error"`, `updater.error = "upd_err_install"`, `updater.error_detail = <the result's error>`, so the Update page shows it.

Texts (key: ko / en):

| key | 한국어 | English |
|---|---|---|
| `set_update` | 업데이트 | Update |
| `help_update` | GitHub에 새 버전이 있는지 확인합니다. 설치는 직접 고를 때만 합니다. | Checks GitHub for a new version. It installs only when you choose to. |
| `upd_installed` | 설치된 버전 v{v} | Installed version v{v} |
| `upd_check` | 업데이트 확인 | Check for updates |
| `upd_checking` | 확인하는 중… | Checking… |
| `upd_latest` | 최신 버전입니다. | You have the newest version. |
| `upd_new` | 새 버전 v{v} | New version v{v} |
| `upd_now` | 지금 업데이트 | Update now |
| `upd_later` | 나중에 | Not now |
| `upd_downloading` | 내려받는 중… {pct}% | Downloading… {pct}% |
| `upd_installing` | 설치하는 중 — 스티키 노트가 닫혔다가 다시 열립니다. | Installing — Sticky Note will close and open again. |
| `upd_elsewhere` | 이 사본은 설치 폴더 밖에서 실행 중이라 직접 업데이트할 수 없습니다. GitHub에서 새 zip을 받아 설치해 주세요. | This copy runs outside the install folder, so it can't update itself. Get the new zip from GitHub and install it. |
| `upd_done` | v{v}(으)로 업데이트했습니다. | Updated to v{v}. |
| `upd_failed` | 업데이트하지 못했습니다. 이전 버전 그대로입니다. | The update didn't finish. The previous version is still installed. |
| `upd_err_network` | GitHub에 연결하지 못했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요. | Couldn't reach GitHub. Check the internet connection and try again. |
| `upd_err_rate` | GitHub 요청이 너무 많습니다. 잠시 뒤에 다시 시도해 주세요. | GitHub is getting too many requests. Try again in a while. |
| `upd_err_reply` | GitHub의 답을 읽지 못했습니다. 나중에 다시 시도해 주세요. | Couldn't read GitHub's reply. Try again later. |
| `upd_err_download` | 내려받다가 끊겼습니다. 다시 시도해 주세요. | The download was cut off. Try again. |
| `upd_err_disk` | 디스크 공간이 부족합니다. | There isn't enough disk space. |
| `upd_err_verify` | 받은 파일이 올바르지 않습니다. 다시 시도해 주세요. | The downloaded file isn't right. Try again. |
| `upd_err_zip` | 이 버전의 파일에 문제가 있어 설치하지 않았습니다. | This version's file has a problem, so it wasn't installed. |
| `upd_err_start` | 설치 프로그램을 시작하지 못했습니다. | Couldn't start the installer. |
| `upd_err_install` | 설치하지 못했습니다: {e} | Couldn't install: {e} |

(`upd_err_install` is what the page shows after a failed `--yes` run, with the result file's `error`.)

- [ ] **Step 1: Write the failing tests** (real `App` via `_support.make_app`; replace `app.updater` with an `Updater` whose `get`/`download`/`popen` are fakes; open a note's settings and the `set_update` page):

```python
def test_update_row_in_general(self):      # "set_update" in SETTING_GROUPS general; list value "v1.1.0"
def test_check_shows_new_version(self):    # press Check -> pump -> page text contains tr("upd_new", v="1.2.0") and the notes
def test_update_now_hidden_elsewhere(self):  # can_install False -> no upd_now button, upd_elsewhere shown
def test_two_settings_pages_share_state(self):  # two notes' pages both show "available" after one check
def test_startup_result_notice(self):      # write update-result.json ok before make_app -> notice text tr("upd_done", v=...); file gone
def test_startup_failed_result(self):      # ok false -> page shows tr("upd_err_install", e="disk")
def test_texts_complete(self):             # every upd_* key and set_update/help_update has ko and en
```

- [ ] **Step 2: Run to verify it fails.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file and then the whole suite → all PASS (existing settings tests like `test_feedback_ui.py` included).
- [ ] **Step 5: Commit** — `git commit -m "feat(update): Settings → Update page"`

---

### Task 7: Release tool and readme

**Files:**
- Create: `tools/make_release.py`
- Modify: `StickyNote/readme.txt` (the "새 버전으로 바꿀 때" part)
- Test: `tests/test_make_release.py`

**Interfaces:**
- Produces: `make_release.build(root: Path, out: Path) -> tuple[str, str]`: zips `root/StickyNote/{app,runtime,licenses,install.cmd,readme.txt}` under a top folder `StickyNote/`, skipping every `__pycache__` (and `preview.py`, which isn't in today's zip), and returns `(tag, sha256_hex)`. CLI `.\StickyNote\runtime\python.exe tools\make_release.py` writes `dist\StickyNote.zip` and prints:

```
dist\StickyNote.zip  (21.3 MB)
tag:     v1.1.0
sha256:  <hex>
Next: GitHub → Releases → Draft a new release → tag v1.1.0, write the notes, attach dist\StickyNote.zip, Publish.
To test first: tick "Set as a pre-release", then run the installed app with STICKYNOTE_UPDATE_PRERELEASE=1.
```

- [ ] **Step 1: Write the failing test** — build from a small fake tree; assert top-level entries are exactly the five above under `StickyNote/`, no `__pycache__` or `preview.py`, `tag == "v" + VERSION` read from the tree, sha matches `hashlib.sha256` of the file.
- [ ] **Step 2: Run to verify it fails.**
- [ ] **Step 3: Implement**; update `readme.txt`: from v1.1.0 on, new versions come through 설정 → 일반 → 업데이트; a zip install over the top still works as before.
- [ ] **Step 4: Run** the test, then the real tool once; compare the entry count with today's zip (636 entries, plus the new modules) and unzip-install it into a temp `--dest` with `install.py --yes --no-launch` → exits 0.
- [ ] **Step 5: Commit** — `git commit -m "feat(release): make_release tool; readme on updating"`

---

### Task 8: End-to-end check on the real app (manual, with the user)

- [ ] Build the zip (Task 7), install it for real with `install.cmd` (gives v1.1.0 in `%LOCALAPPDATA%\Programs\StickyNote`).
- [ ] Bump `VERSION` to `1.1.1` in a scratch copy only, build that zip, and **ask the user** to publish it as a GitHub **pre-release** `v1.1.1` (publishing is theirs to do).
- [ ] Start the installed app with `STICKYNOTE_UPDATE_PRERELEASE=1`; Settings → General → Update → Check → v1.1.1 shown with notes → Update now → app closes and reopens, notice "Updated to v1.1.1", notes intact, no console window seen.
- [ ] Ask the user to delete the test pre-release (and its tag) afterwards, and reinstall v1.1.0 so the version on disk matches what gets published.
