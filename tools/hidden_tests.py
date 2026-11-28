"""Run the tests (or any of this project's Python scripts) on a hidden Windows desktop.

The tests open real Tk windows, take the focus and flash notes on screen. Here they run on a
desktop of their own that is never shown, so the user's desktop stays as it is.

    .\\StickyNote\\runtime\\python.exe tools\\hidden_tests.py                    (the whole suite)
    .\\StickyNote\\runtime\\python.exe tools\\hidden_tests.py -p test_list_cards.py
    .\\StickyNote\\runtime\\python.exe tools\\hidden_tests.py --script tools\\look_capture.py OUT ko

With no ``--script``, the arguments go to ``unittest discover -s tests``. The output is printed
when the run ends, and the exit code is the run's.
"""
import ctypes
import msvcrt
import os
import subprocess
import sys
import tempfile
import uuid
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERIC_ALL = 0x10000000
STARTF_USESTDHANDLES = 0x00000100
CREATE_NO_WINDOW = 0x08000000
INFINITE = 0xFFFFFFFF

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


user32.CreateDesktopW.restype = wintypes.HANDLE
user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
                                  wintypes.DWORD, ctypes.c_void_p]
user32.CloseDesktop.argtypes = [wintypes.HANDLE]
kernel32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                    wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                                    ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def run_hidden(args: list[str]) -> tuple[int, str]:
    """Run ``args`` (a command line) on a new hidden desktop; (exit code, output)."""
    name = f"StickyNoteTests-{uuid.uuid4().hex[:8]}"
    desk = user32.CreateDesktopW(name, None, None, 0, GENERIC_ALL, None)
    if not desk:
        raise ctypes.WinError(ctypes.get_last_error())
    log_path = Path(tempfile.mkdtemp(prefix="sticky-hidden-")) / "out.txt"
    try:
        with open(log_path, "wb") as log, open(os.devnull, "rb") as nul:
            out, inp = msvcrt.get_osfhandle(log.fileno()), msvcrt.get_osfhandle(nul.fileno())
            os.set_handle_inheritable(out, True)
            os.set_handle_inheritable(inp, True)
            si = STARTUPINFOW()
            si.cb = ctypes.sizeof(si)
            si.lpDesktop = f"WinSta0\\{name}"
            si.dwFlags = STARTF_USESTDHANDLES
            si.hStdInput, si.hStdOutput, si.hStdError = inp, out, out
            pi = PROCESS_INFORMATION()
            line = ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            block = ctypes.create_unicode_buffer("\0".join(f"{k}={v}" for k, v in env.items()) + "\0\0")
            if not kernel32.CreateProcessW(None, line, None, None, True, CREATE_NO_WINDOW | 0x00000400,
                                           block, str(ROOT), ctypes.byref(si), ctypes.byref(pi)):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                kernel32.WaitForSingleObject(pi.hProcess, INFINITE)
                code = wintypes.DWORD()
                kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
            finally:
                kernel32.CloseHandle(pi.hThread)
                kernel32.CloseHandle(pi.hProcess)
        return code.value, log_path.read_text(encoding="utf-8", errors="replace")
    finally:
        user32.CloseDesktop(desk)
        try:
            log_path.unlink()
            log_path.parent.rmdir()
        except OSError:
            pass


def main(argv: list[str]) -> int:
    python = sys.executable
    if argv[:1] == ["--script"]:
        args = [python, *argv[1:]]
    else:
        args = [python, "-m", "unittest", "discover", "-s", "tests", *argv]
    code, output = run_hidden(args)
    sys.stdout.buffer.write(output.encode("utf-8", "replace"))
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
