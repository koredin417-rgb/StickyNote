"""Self-update from GitHub Releases: Settings → General → Update.

Nothing here runs on its own: a check starts only from the Update page's button, and a
download only from its "Update now". The release logic below is pure; the Updater does the
network work on a thread and the Tk loop reads its results (see Updater.pump).
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

import install
import webget
from version import VERSION
from webget import WebError

REPO = "koredin417-rgb/StickyNote"
ASSET = "StickyNote.zip"
PRERELEASE_ENV = "STICKYNOTE_UPDATE_PRERELEASE"     # "1": pre-releases too (testing a release first)
HEADERS = {"User-Agent": "StickyNote-updater", "Accept": "application/vnd.github+json"}
TEMP_PREFIX = "StickyNote-update-"                  # %TEMP%\StickyNote-update-<version>: a download
# the installer starts on its own: no console window, and it outlives the app it closes
LAUNCH_FLAGS = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

_VERSION_RE = re.compile(r"v?(\d+(?:\.\d+)*)")


@dataclass(frozen=True)
class Release:
    version: str            # without the "v"
    tag: str
    notes: str              # plain text (plain_notes)
    url: str                # the zip's download address
    size: int
    sha256: str | None      # hex, when GitHub gives the asset's digest


def parse_version(text: str) -> tuple[int, ...] | None:
    """"v1.2.0" -> (1, 2, 0); anything else (a "-beta", a word) -> None."""
    m = _VERSION_RE.fullmatch(text.strip()) if isinstance(text, str) else None
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def api_url(environ=os.environ) -> str:
    base = f"https://api.github.com/repos/{REPO}/releases"
    return base if environ.get(PRERELEASE_ENV) == "1" else base + "/latest"


def _release(item: dict) -> Release | None:
    """One release of the reply, or None when it can't be offered (a draft, an odd tag, no zip)."""
    if item.get("draft"):
        return None
    tag = item.get("tag_name")
    number = parse_version(tag) if isinstance(tag, str) else None
    if number is None:
        return None
    asset = next((a for a in item.get("assets") or () if isinstance(a, dict) and a.get("name") == ASSET), None)
    if asset is None or not isinstance(asset.get("size"), int) or not isinstance(asset.get("browser_download_url"), str):
        return None
    digest = asset.get("digest")
    sha = digest[len("sha256:"):].lower() if isinstance(digest, str) and digest.startswith("sha256:") else None
    body = item.get("body")
    return Release(version=".".join(map(str, number)), tag=tag, notes=plain_notes(body if isinstance(body, str) else ""),
                   url=asset["browser_download_url"], size=asset["size"], sha256=sha)


def pick_release(reply, current: str) -> Release | None:
    """The newest release in ``reply`` (one release, or a list of them) that is newer than
    ``current``, else None. A reply that isn't a release at all raises ValueError."""
    if isinstance(reply, dict):
        if "tag_name" not in reply:
            raise ValueError("not a release")
        items = [reply]
    elif isinstance(reply, list):
        items = reply
    else:
        raise ValueError("not a release")
    now = parse_version(current) or (0,)
    best = None
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("not a release")
        r = _release(item)
        if r is not None and parse_version(r.version) > now and (
                best is None or parse_version(r.version) > parse_version(best.version)):
            best = r
    return best


def plain_notes(markdown: str) -> str:
    """Release notes as plain text: headings without their #s, "* "/"- " items as "• ",
    no ** or backticks."""
    lines = []
    for line in markdown.replace("\r\n", "\n").split("\n"):
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"^(\s*)[*-] ", r"\1• ", line)
        lines.append(line.replace("**", "").replace("`", "").rstrip())
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


# --------------------------------------------------------------------------- the Updater
class _BadZip(Exception):
    pass


def _is_disk_full(e: OSError) -> bool:
    return e.errno == errno.ENOSPC or getattr(e, "winerror", None) == webget.ERROR_DISK_FULL


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _unpack(zpath: Path, folder: Path, version: str) -> Path:
    """The zip into ``folder``; returns its StickyNote folder. _BadZip for a broken zip, a name
    that would land outside ``folder``, missing files or a VERSION other than the release's."""
    try:
        with zipfile.ZipFile(zpath) as z:
            for name in z.namelist():
                unified = name.replace("\\", "/")
                if unified.startswith("/") or ":" in name or ".." in PurePosixPath(unified).parts:
                    raise _BadZip(name)
            z.extractall(folder)
    except (zipfile.BadZipFile, EOFError, ValueError) as e:
        raise _BadZip(str(e)) from e
    root = folder / "StickyNote"
    if not ((root / "runtime" / "python.exe").is_file() and (root / "app" / "install.py").is_file()):
        raise _BadZip("not a Sticky Note folder")
    found = install.version_of(root)
    if parse_version(found) is None or parse_version(found) != parse_version(version):
        raise _BadZip(f"version {found!r}, not {version}")
    return root


class Updater:
    """One per App. ``check`` and ``start_install`` run on a worker thread that never touches
    Tk or the state below: it puts its changes on a queue, and ``pump`` (on the Tk thread, from
    App._update_poll) applies them and tells the ``listeners`` (the open Update pages)."""

    def __init__(self, app_dir: Path, *, get=webget.get, download=webget.download, popen=subprocess.Popen,
                 temp_dir: Path | None = None, install_dir: Path | None = None, data_folder: Path | None = None):
        self.app_dir = Path(app_dir)
        self.data_folder = Path(data_folder) if data_folder is not None else None    # (the installer's result file)
        self._get, self._download, self._popen = get, download, popen
        self.temp_dir = Path(temp_dir) if temp_dir is not None else Path(tempfile.gettempdir())
        self.install_dir = Path(install_dir) if install_dir is not None else install.default_dest()
        self.state = "idle"     # idle | checking | latest | available | downloading | installing | error
        self.release: Release | None = None
        self.progress = 0.0
        self.error = ""         # a texts key (upd_err_*)
        self.error_detail = ""  # the {e} of upd_err_install
        self.listeners: list[Callable[[], None]] = []
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None

    @property
    def can_install(self) -> bool:
        """Only the copy in the normal install folder updates itself (a run from the repo or an
        unzipped folder must never be overwritten)."""
        try:
            return self.app_dir.parent.resolve() == self.install_dir.resolve()
        except OSError:
            return False

    @property
    def busy(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    # -- on the Tk thread
    def check(self) -> None:
        if self.busy or self.state not in ("idle", "latest", "available", "error"):
            return
        self._apply({"state": "checking", "error": "", "error_detail": ""})
        self._start(self._check_work, "upd_err_reply")

    def start_install(self) -> None:
        if self.busy or self.state != "available" or self.release is None or not self.can_install:
            return
        release = self.release
        self._apply({"state": "downloading", "progress": 0.0, "error": "", "error_detail": ""})
        self._start(lambda: self._install_work(release), "upd_err_download")

    def dismiss(self) -> None:
        """Not now: the offer goes; the next check shows it again."""
        if self.state == "available":
            self._apply({"state": "idle"})

    def pump(self) -> bool:
        """Apply what the worker sent; True while it still works (call again soon)."""
        alive = self.busy                       # (first: what it sent before ending is all queued)
        changes = {}
        while True:
            try:
                changes.update(self._queue.get_nowait())
            except queue.Empty:
                break
        if changes:
            self._apply(changes)
        return alive or not self._queue.empty()

    def _apply(self, changes: dict) -> None:
        changed = False
        for attr, value in changes.items():
            if getattr(self, attr) != value:
                setattr(self, attr, value)
                changed = True
        if changed:
            for listener in list(self.listeners):
                listener()

    def _start(self, work, fallback: str) -> None:
        def run():
            try:
                work()
            except Exception:                   # never left "checking" or "downloading"
                self._send(state="error", error=fallback)
        self._worker = threading.Thread(target=run, daemon=True, name="updater")
        self._worker.start()

    # -- on the worker thread
    def _send(self, **changes) -> None:
        self._queue.put(changes)

    def _check_work(self) -> None:
        try:
            reply = json.loads(self._get(api_url(), HEADERS).decode("utf-8"))
            found = pick_release(reply, VERSION)
        except WebError as e:
            self._send(state="error", error=("upd_err_network" if e.status is None else
                                             "upd_err_rate" if e.status in (403, 429) else "upd_err_reply"))
        except ValueError:                      # (bad JSON, bad UTF-8, not a release)
            self._send(state="error", error="upd_err_reply")
        else:
            self._send(state="available" if found else "latest", release=found)

    def _fresh_folder(self, version: str) -> Path:
        """An empty folder for this version's download (a failed earlier one is cleared first;
        one Windows won't let go of yet gets a folder of its own)."""
        for n in range(10):
            folder = self.temp_dir / (f"{TEMP_PREFIX}{version}" + (f"-{n}" if n else ""))
            shutil.rmtree(folder, ignore_errors=True)
            if not folder.exists():
                folder.mkdir(parents=True)
                return folder
        raise OSError("no empty folder for the download")

    def _install_work(self, release: Release) -> None:
        last = [0.0]

        def progress(done, total):
            k = min(1.0, done / (total or release.size or 1))
            if k - last[0] >= 0.01 or k >= 1.0:     # (a message per percent, not per piece)
                last[0] = k
                self._send(progress=k)
        try:
            folder = self._fresh_folder(release.version)
            zpath = folder / ASSET
            self._download(release.url, zpath, HEADERS, progress)
        except WebError as e:
            self._send(state="error", error="upd_err_disk" if e.disk else "upd_err_download")
            return
        except OSError as e:
            self._send(state="error", error="upd_err_disk" if _is_disk_full(e) else "upd_err_download")
            return
        if zpath.stat().st_size != release.size or (release.sha256 and _sha256(zpath) != release.sha256):
            zpath.unlink()
            self._send(state="error", error="upd_err_verify")
            return
        try:
            root = _unpack(zpath, folder, release.version)
        except _BadZip:
            self._send(state="error", error="upd_err_zip")
            return
        except OSError as e:
            self._send(state="error", error="upd_err_disk" if _is_disk_full(e) else "upd_err_zip")
            return
        self._send(state="installing", progress=1.0)
        try:                                    # it closes this app over waker ("quit") and reopens it
            proc = self._popen([str(root / "runtime" / "python.exe"), str(root / "app" / "install.py"),
                                "--yes", "--dest", str(self.install_dir)],
                               cwd=str(root / "app"), close_fds=True, creationflags=LAUNCH_FLAGS,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            self._send(state="error", error="upd_err_start")
            return
        # Normally this app is closed while waiting here. An installer that ends first never got
        # that far (it died, or couldn't close the app and said so in its result file).
        if proc.wait() == 0:
            return
        result = read_result(self.data_folder) if self.data_folder is not None else None
        if result is not None and not result["ok"]:
            self._send(state="error", error="upd_err_install", error_detail=str(result.get("error", "")))
        else:
            self._send(state="error", error="upd_err_start")


def read_result(data_folder: Path) -> dict | None:
    """What the last --yes install wrote (install.RESULT_FILE), read once: the file is deleted."""
    path = Path(data_folder) / install.RESULT_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        path.unlink()
    except OSError:
        pass
    try:
        result = json.loads(text)
    except ValueError:
        return None
    return result if isinstance(result, dict) and isinstance(result.get("ok"), bool) else None


def clean_temp(temp_dir: Path | None = None) -> None:
    """Delete the downloads of earlier updates (an installer can't delete the folder it runs from)."""
    base = Path(temp_dir) if temp_dir is not None else Path(tempfile.gettempdir())
    try:
        folders = [p for p in base.glob(TEMP_PREFIX + "*") if p.is_dir()]
    except OSError:
        return
    for folder in folders:
        shutil.rmtree(folder, ignore_errors=True)
