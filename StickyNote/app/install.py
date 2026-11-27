"""Install the unzipped Sticky Note folder for this user.

"install.cmd" runs this with the bundled Python. It copies runtime\\,
app\\ and licenses\\ to %LOCALAPPDATA%\\Programs\\StickyNote, puts a
"스티키 노트" shortcut on the Desktop and in the Start menu, and starts the app.
Notes live in %APPDATA%\\StickyNote and are never touched.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import shortcut
import winapi
from main import APP_ID, MUTEX_NAME, data_folder

EXE_NAME = "StickyNote.exe"         # an earlier build ran from this (still closed before an update)
LINK_ICON = "sticky_note.ico"       # the shortcuts' icon: a name of its own, so Windows' icon cache shows the new one
QUIT_SIGNAL = "quit.signal"         # for an older app (it polls for it); a newer one hears "quit" on its port

PARTS = ("runtime", "app", "licenses")
BACKUP_DIR = ".update-backup"           # under the install folder: the old files while an install runs
JOURNAL = "journal.txt"                 # in it: what was changed, one line per file (_Swap)
RESULT_FILE = "update-result.json"      # in the data folder, after --yes: what the app shows when it starts
NO_WINDOW = subprocess.CREATE_NO_WINDOW     # helpers (powershell, taskkill): the update's installer has no console
LINK_NAME = "스티키 노트.lnk"
HERE = Path(__file__).resolve().parent


class InstallError(Exception):
    pass


def default_dest() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "Programs" / "StickyNote"


def read_version(text: str) -> str | None:
    """The VERSION = "..." of a version.py's text (read, not imported: it may be another build's)."""
    m = re.search(r"""^VERSION\s*=\s*["']([^"']+)["']""", text, re.MULTILINE)
    return m.group(1) if m else None


def version_of(source: Path) -> str:
    try:
        return read_version((Path(source) / "app" / "version.py").read_text(encoding="utf-8")) or ""
    except OSError:
        return ""


def default_link_dirs() -> list[Path]:
    return [shortcut.known_folder("desktop"), shortcut.known_folder("programs")]


def _same_file(a: Path, b: Path) -> bool:
    if not b.is_file() or a.stat().st_size != b.stat().st_size:
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            x, y = fa.read(1 << 20), fb.read(1 << 20)
            if x != y:
                return False
            if not x:
                return True


def _retry(action, tries: int = 6, wait: float = 0.5):
    """Run ``action``; a file still held by a closing program is retried for a few seconds."""
    for i in range(tries):
        try:
            return action()
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(wait)


def _gone(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


class _Swap:
    """The files one install changes, each written in the journal before it is changed, so a
    failure (or, at the next run, a killed installer) can put the old version back: a replaced
    or removed file waits in the backup folder, an added one is deleted (recover)."""

    def __init__(self, dest: Path):
        self.dest, self.backup = dest, dest / BACKUP_DIR
        self._journal = None

    def _note(self, kind: str, rel: Path) -> None:
        if self._journal is None:
            self.backup.mkdir(parents=True, exist_ok=True)
            self._journal = open(self.backup / JOURNAL, "a", encoding="utf-8")
        self._journal.write(f"{kind}\t{rel.as_posix()}\n")
        self._journal.flush()
        os.fsync(self._journal.fileno())        # (on disk before the file it speaks of changes)

    def _save(self, rel: Path, tries: int = 6) -> None:
        saved = self.backup / rel
        saved.parent.mkdir(parents=True, exist_ok=True)
        _retry(lambda: os.replace(self.dest / rel, saved), tries=tries)

    def put(self, path: Path, rel: Path) -> None:
        """``path``'s contents to ``dest/rel``: written beside it as .new, then swapped in."""
        target = self.dest / rel
        new = target.with_name(target.name + ".new")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            _retry(lambda: _copy_file(path, new))
            if target.exists():
                self._note("replaced", rel)
                self._save(rel)
            else:
                self._note("added", rel)
            _retry(lambda: os.replace(new, target))
        except BaseException:
            try:
                _gone(new)
            except OSError:
                pass
            raise

    def remove(self, rel: Path) -> None:
        """A file the new version lacks goes to the backup, where Windows lets it go (a
        leftover file does no harm)."""
        self._note("removed", rel)
        try:
            self._save(rel, tries=1)
        except OSError:
            pass

    def _close(self) -> None:
        if self._journal is not None:
            self._journal.close()
            self._journal = None

    def commit(self) -> None:
        self._close()
        shutil.rmtree(self.backup, ignore_errors=True)

    def undo(self) -> None:
        self._close()
        recover(self.dest)


def recover(dest: Path) -> bool:
    """A backup left by an install that failed or was killed: its files go back (the newest
    journal entry first) and the backup is deleted. Returns whether there was one."""
    dest = Path(dest)
    backup = dest / BACKUP_DIR
    if not backup.exists():
        return False
    try:
        lines = (backup / JOURNAL).read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in reversed(lines):
        kind, _tab, rel = line.partition("\t")
        if not rel or kind not in ("replaced", "added", "removed"):
            continue                            # (a line cut short by the kill)
        target, saved = dest / rel, backup / rel
        _gone(target.with_name(target.name + ".new"))
        if kind == "added":
            _retry(lambda t=target: _gone(t))
        elif saved.exists():                    # (not there: the old file never moved)
            target.parent.mkdir(parents=True, exist_ok=True)
            _retry(lambda s=saved, t=target: os.replace(s, t))
    shutil.rmtree(backup, ignore_errors=True)
    return True


def _sync_tree(src: Path, dst: Path, swap: _Swap, base: Path) -> None:
    """Make ``dst`` (``base`` under the install folder) the same as ``src``, touching only what
    differs. The runtime is the same from one version to the next, so its files (DLLs a program
    may still hold for a moment) are left alone. Files the new version no longer has are removed
    where Windows lets them go; directories made stay (an empty leftover does no harm)."""
    wanted = set()
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        if "__pycache__" in rel.parts:
            continue
        target = dst / rel
        wanted.add(rel)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if _same_file(path, target):
            continue
        swap.put(path, base / rel)
    if not dst.exists():
        return
    for path in sorted(dst.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        rel = path.relative_to(dst)
        if rel in wanted:
            continue
        if path.is_dir():
            try:
                path.rmdir()                # (only once empty)
            except OSError:
                pass
        else:
            swap.remove(base / rel)


def _copy_file(path: Path, target: Path) -> None:
    """File contents only. The "downloaded from the internet" mark (the Zone.Identifier
    stream) stays behind, like with any installer, so the installed app does not ask "run
    this file?" every time it starts."""
    with open(path, "rb") as fin, open(target, "wb") as fout:
        shutil.copyfileobj(fin, fout, 1 << 20)


def install(source: Path, dest: Path, link_dirs) -> list[Path]:
    """Copy the program to ``dest`` (replacing an earlier install) and make the
    shortcuts. Returns the shortcut paths. A failure while copying puts the old files back
    (and is raised); so does the next run after a killed one (recover)."""
    source, dest = Path(source), Path(dest)
    recover(dest)
    if source.resolve() != dest.resolve():
        ours = ((dest / "app" / "main.py").exists() or (dest / "app" / "app.ico").exists()
                or (dest.name.lower() == "stickynote" and (dest / "runtime" / "python.exe").exists()))
        if not ours and any((dest / part).exists() for part in PARTS):
            raise InstallError(f"{dest} 폴더에 다른 프로그램의 파일이 있어 설치하지 않았습니다.")
        swap = _Swap(dest)
        try:
            for part in PARTS:
                if (source / part).is_dir():
                    _sync_tree(source / part, dest / part, swap, Path(part))
        except BaseException:
            swap.undo()
            raise
        swap.commit()
    made = []
    exe = app_exe(dest)
    icon = dest / "app" / LINK_ICON
    if not icon.exists():
        icon = dest / "app" / "app.ico"
    for folder in link_dirs:
        link = Path(folder) / LINK_NAME
        shortcut.create(link, exe, arguments=f'"{dest / "app" / "main.py"}"',
                        workdir=dest / "app", icon=icon, app_id=APP_ID, description="스티키 노트")
        made.append(link)
    _icons_changed()
    return made


def app_exe(dest: Path) -> Path:
    """What runs the app: Python's own pythonw.exe, as signed by the Python Software Foundation.
    (A copy carrying the app's icon and name loses that signature, and Smart App Control then
    blocks it, even for an administrator.)"""
    return Path(dest) / "runtime" / "pythonw.exe"


def _icons_changed() -> None:
    """Tell Explorer that icons changed, so the desktop and Start menu show the new one."""
    try:
        import ctypes
        ctypes.WinDLL("shell32").SHChangeNotify(0x08000000, 0, None, None)     # SHCNE_ASSOCCHANGED
    except (OSError, AttributeError):
        pass


def launch(dest: Path, links=()) -> None:
    """Start the installed app. When the installer runs as administrator, Explorer opens the
    shortcut instead, so the app runs with normal rights (an elevated app would, for example,
    not take pictures dragged from Explorer)."""
    if links and winapi.is_admin():
        subprocess.Popen(["explorer.exe", str(links[0])])
        return
    subprocess.Popen([str(app_exe(dest)), str(dest / "app" / "main.py")],
                     cwd=dest / "app", close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


def _wait_closed(seconds: float) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not winapi.instance_running(MUTEX_NAME):
            return True
        time.sleep(0.25)
    return not winapi.instance_running(MUTEX_NAME)


def _powershell(command: str) -> str:
    """What a PowerShell command prints ("" when it can't run). Without a window it gets a console
    of its own in the system's code page (CP949 here), not install.cmd's UTF-8 one: UTF-8 is asked
    for, so paths with Hangul in them still match."""
    command = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; " + command
    try:
        return subprocess.run(["powershell", "-NoProfile", "-Command", command],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                              creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _app_processes(dest: Path) -> list[int]:
    """Process ids of Sticky Note runs (StickyNote.exe / pythonw ... main.py) from ``dest`` or from this folder."""
    roots = {str(Path(dest).resolve()).lower(), str(HERE.parent.resolve()).lower()}
    out = _powershell("Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe' OR "
                      f"Name='{EXE_NAME}'\" | "
                      "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
    pids = []
    for line in out.splitlines():
        pid, _tab, cmd = line.partition("\t")
        low = cmd.lower()
        if pid.strip().isdigit() and "main.py" in low and any(r in low for r in roots) \
                and int(pid) != os.getpid():
            pids.append(int(pid))
    return pids


def close_running(dest: Path, ask: bool = True) -> bool:
    """A Sticky Note is running (perhaps on another monitor or behind other windows): ask (unless
    the user already agreed: the in-app update), then close it. It is asked first ("quit": it
    saves and closes); an older one that does not know that signal is ended (it saves every
    change at once, so nothing is lost)."""
    print("스티키 노트가 실행 중입니다. (다른 모니터나 다른 창 뒤에 메모가 있을 수 있어요)")
    if ask:
        try:
            answer = input("닫고 설치할까요? [Y/n] ").strip().lower()
        except (EOFError, OSError):
            answer = "y"
        if answer not in ("", "y", "yes", "ㅛ", "예", "네"):
            return False
    folder = data_folder()
    import waker
    if not waker.send(folder / "wake.port", "quit"):     # the app saves and closes at once
        try:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / QUIT_SIGNAL).touch()      # (an older app: it checks this file)
        except OSError:
            pass
    print("스티키 노트를 닫는 중…")
    if not _wait_closed(4):
        for pid in _app_processes(dest):        # an older version: it does not read quit.signal
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=NO_WINDOW)
    closed = _wait_closed(4)
    if closed:
        _wait_exited(dest, 10)                  # its files are let go only once the process is gone
    try:
        (folder / QUIT_SIGNAL).unlink()
    except OSError:
        pass
    return closed


def _wait_exited(dest: Path, seconds: float) -> None:
    """Wait until no Sticky Note runs from ``dest`` any more (the lock goes a moment before the
    process does, and its runtime files stay in use until then)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end and _app_processes(dest):
        time.sleep(0.3)


def _pause(message: str = "", seconds: float | None = None) -> None:
    """Keep the console window open long enough to read it."""
    if message:
        print(message)
    if seconds is not None:
        time.sleep(seconds)
        return
    try:
        if sys.stdin and sys.stdin.isatty():
            input("Enter 키를 누르면 창이 닫힙니다.")
    except (EOFError, OSError):
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Install Sticky Note for this user.")
    parser.add_argument("--source", type=Path, default=HERE.parent, help="unzipped StickyNote folder")
    parser.add_argument("--dest", type=Path, help="install folder (default: %%LOCALAPPDATA%%\\Programs\\StickyNote)")
    parser.add_argument("--link-dir", type=Path, action="append", help="folder for a shortcut (repeatable)")
    parser.add_argument("--no-launch", action="store_true", help="do not start the app afterwards")
    parser.add_argument("--yes", action="store_true",
                        help="the in-app update: no questions, the outcome in update-result.json")
    args = parser.parse_args(argv)
    if args.yes:
        return _quiet(args)

    print("스티키 노트 설치")
    dest = args.dest or default_dest()
    if winapi.instance_running(MUTEX_NAME) and not close_running(dest):
        _pause("스티키 노트가 실행 중이라 설치하지 않았습니다. 메모 창을 모두 닫은 뒤 다시 설치해 주세요.")
        return 1
    try:
        links = install(args.source, dest, args.link_dir or default_link_dirs())
    except Exception as error:          # show it in the console window instead of a traceback
        _pause(f"설치하지 못했습니다: {error}")
        return 1
    print(f"설치 위치: {dest}")
    for link in links:
        print(f"바로가기: {link}")
    if not args.no_launch:
        launch(dest, links)
        print("스티키 노트를 시작합니다.")
    _pause(seconds=3)
    return 0



def _quiet(args) -> int:
    """--yes: the in-app update runs this with no console (the user already chose Update now).
    No question, no pause; every way out writes the result file the app shows at its next start,
    and an app is running afterwards: the new version, or the old one put back."""
    dest = args.dest or default_dest()
    version = version_of(args.source)

    def result(ok: bool, error: str = "") -> None:
        folder = data_folder()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / RESULT_FILE).write_text(json.dumps({"version": version, "ok": ok, "error": error}),
                                              encoding="utf-8")
        except OSError:
            pass

    def start(links) -> None:
        if not args.no_launch:
            try:
                launch(dest, links)
            except OSError:
                pass

    try:
        if winapi.instance_running(MUTEX_NAME) and not close_running(dest, ask=False):
            result(False, "still running")      # (and it still is: nothing to start)
            return 1
        links = install(args.source, dest, args.link_dir or default_link_dirs())
    except Exception as error:                  # (already put back by install)
        result(False, str(error) or type(error).__name__)
        start([])
        return 1
    result(True)
    start(links)
    return 0


if __name__ == "__main__":
    sys.exit(main())
