"""Install the unzipped Sticky Note folder for this user.

"install.cmd" runs this with the bundled Python. It copies runtime\\,
app\\ and licenses\\ to %LOCALAPPDATA%\\Programs\\StickyNote, puts a
"스티키 노트" shortcut on the Desktop and in the Start menu, and starts the app.
Notes live in %APPDATA%\\StickyNote and are never touched.
"""
from __future__ import annotations

import argparse
import os
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
QUIT_SIGNAL = "quit.signal"         # app.py polls for it (every 0.8 s), saves and closes

PARTS = ("runtime", "app", "licenses")
LINK_NAME = "스티키 노트.lnk"
HERE = Path(__file__).resolve().parent


class InstallError(Exception):
    pass


def default_dest() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "Programs" / "StickyNote"


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


def _sync_tree(src: Path, dst: Path) -> None:
    """Make ``dst`` the same as ``src``, touching only what differs. The runtime is the same
    from one version to the next, so its files (DLLs a program may still hold for a moment)
    are left alone; a half-done earlier install is completed. Files the new version no longer
    has are removed where Windows lets them go (a leftover file does no harm)."""
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
        target.parent.mkdir(parents=True, exist_ok=True)
        _retry(lambda p=path, t=target: _copy_file(p, t))
    if not dst.exists():
        return
    for path in sorted(dst.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.relative_to(dst) in wanted:
            continue
        try:
            if path.is_dir():
                path.rmdir()                # (only once empty)
            else:
                path.unlink()
        except OSError:
            pass


def _copy_file(path: Path, target: Path) -> None:
    """File contents only. The "downloaded from the internet" mark (the Zone.Identifier
    stream) stays behind, like with any installer, so the installed app does not ask "run
    this file?" every time it starts."""
    with open(path, "rb") as fin, open(target, "wb") as fout:
        shutil.copyfileobj(fin, fout, 1 << 20)


def install(source: Path, dest: Path, link_dirs) -> list[Path]:
    """Copy the program to ``dest`` (replacing an earlier install) and make the
    shortcuts. Returns the shortcut paths."""
    source, dest = Path(source), Path(dest)
    if source.resolve() != dest.resolve():
        ours = ((dest / "app" / "main.py").exists() or (dest / "app" / "app.ico").exists()
                or (dest.name.lower() == "stickynote" and (dest / "runtime" / "python.exe").exists()))
        if not ours and any((dest / part).exists() for part in PARTS):
            raise InstallError(f"{dest} 폴더에 다른 프로그램의 파일이 있어 설치하지 않았습니다.")
        for part in PARTS:
            if (source / part).is_dir():
                _sync_tree(source / part, dest / part)
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


def _app_processes(dest: Path) -> list[int]:
    """Process ids of Sticky Note runs (StickyNote.exe / pythonw ... main.py) from ``dest`` or from this folder."""
    roots = {str(Path(dest).resolve()).lower(), str(HERE.parent.resolve()).lower()}
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe' OR "
             f"Name='{EXE_NAME}'\" | "
             "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for line in out.splitlines():
        pid, _tab, cmd = line.partition("\t")
        low = cmd.lower()
        if pid.strip().isdigit() and "main.py" in low and any(r in low for r in roots) \
                and int(pid) != os.getpid():
            pids.append(int(pid))
    return pids


def close_running(dest: Path) -> bool:
    """A Sticky Note is running (perhaps on another monitor or behind other windows): ask, then
    close it. It is asked first (quit.signal: it saves and closes); an older one that does not
    know that signal is ended (it saves every change at once, so nothing is lost)."""
    print("스티키 노트가 실행 중입니다. (다른 모니터나 다른 창 뒤에 메모가 있을 수 있어요)")
    try:
        answer = input("닫고 설치할까요? [Y/n] ").strip().lower()
    except (EOFError, OSError):
        answer = "y"
    if answer not in ("", "y", "yes", "ㅛ", "예", "네"):
        return False
    folder = data_folder()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / QUIT_SIGNAL).touch()
    except OSError:
        pass
    print("스티키 노트를 닫는 중…")
    if not _wait_closed(4):
        for pid in _app_processes(dest):        # an older version: it does not read quit.signal
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
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
    args = parser.parse_args(argv)

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


if __name__ == "__main__":
    sys.exit(main())
