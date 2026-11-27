"""HTTP(S) GET through Windows' own WinHTTP (via ctypes).

The bundled Python has no ssl module, so urllib can't do HTTPS. WinHTTP uses the system's
certificates and proxy settings, follows redirects by itself, and runs in this process: no
extra program, no console window. Used by the updater only.
"""
from __future__ import annotations

import ctypes
import errno
import os
from ctypes import wintypes
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

ACCESS_AUTOMATIC_PROXY = 4      # Windows 8.1 and later
ACCESS_DEFAULT_PROXY = 0
FLAG_SECURE = 0x00800000
QUERY_STATUS_CODE = 19
QUERY_CONTENT_LENGTH = 5
QUERY_FLAG_NUMBER = 0x20000000
ERROR_INVALID_PARAMETER = 87
ERROR_DISK_FULL = 112
CHUNK = 1 << 16
DEFAULT_AGENT = "StickyNote"


class WebError(Exception):
    """A request that failed: ``status`` is the HTTP status (None when no answer came), ``disk``
    is True when the file couldn't be written for lack of space."""

    def __init__(self, message: str, status: int | None = None, disk: bool = False):
        super().__init__(message)
        self.status, self.disk = status, disk


_lib = None


def _winhttp():
    global _lib
    if _lib is None:
        w = ctypes.WinDLL("winhttp", use_last_error=True)
        H, S, D, B = ctypes.c_void_p, wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL
        PD = ctypes.POINTER(wintypes.DWORD)
        for name, args, res in (
                ("WinHttpOpen", (S, D, S, S, D), H),
                ("WinHttpSetTimeouts", (H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int), B),
                ("WinHttpConnect", (H, S, wintypes.WORD, D), H),
                ("WinHttpOpenRequest", (H, S, S, S, S, ctypes.c_void_p, D), H),
                ("WinHttpSendRequest", (H, S, D, ctypes.c_void_p, D, D, ctypes.c_size_t), B),
                ("WinHttpReceiveResponse", (H, ctypes.c_void_p), B),
                ("WinHttpQueryHeaders", (H, D, S, ctypes.c_void_p, PD, PD), B),
                ("WinHttpQueryDataAvailable", (H, PD), B),
                ("WinHttpReadData", (H, ctypes.c_void_p, D, PD), B),
                ("WinHttpCloseHandle", (H,), B)):
            fn = getattr(w, name)
            fn.argtypes, fn.restype = args, res
        _lib = w
    return _lib


def _fail(what: str) -> WebError:
    return WebError(f"{what} failed (WinHTTP error {ctypes.get_last_error()})")


def _number(w, request, level) -> int | None:
    value, size = wintypes.DWORD(), wintypes.DWORD(4)
    if not w.WinHttpQueryHeaders(request, level | QUERY_FLAG_NUMBER, None, ctypes.byref(value),
                                 ctypes.byref(size), None):
        return None
    return value.value


def _request(url: str, headers: dict[str, str], timeout: float, sink: Callable[[bytes, int | None], None]) -> None:
    """GET ``url`` and hand each piece of the body to ``sink(data, content_length)``."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise WebError(f"not a web address: {url}")
    secure = parts.scheme == "https"
    port = parts.port or (443 if secure else 80)
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    headers = dict(headers)
    agent = next((headers.pop(k) for k in list(headers) if k.lower() == "user-agent"), DEFAULT_AGENT)
    extra = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    w = _winhttp()
    handles = []
    try:
        session = w.WinHttpOpen(agent, ACCESS_AUTOMATIC_PROXY, None, None, 0)
        if not session and ctypes.get_last_error() == ERROR_INVALID_PARAMETER:     # Windows 8 and older
            session = w.WinHttpOpen(agent, ACCESS_DEFAULT_PROXY, None, None, 0)
        if not session:
            raise _fail("WinHttpOpen")
        handles.append(session)
        ms = max(1, int(timeout * 1000))
        w.WinHttpSetTimeouts(session, ms, ms, ms, ms)
        connection = w.WinHttpConnect(session, parts.hostname, port, 0)
        if not connection:
            raise _fail("WinHttpConnect")
        handles.append(connection)
        request = w.WinHttpOpenRequest(connection, "GET", target, None, None, None, FLAG_SECURE if secure else 0)
        if not request:
            raise _fail("WinHttpOpenRequest")
        handles.append(request)
        if not w.WinHttpSendRequest(request, extra or None, len(extra), None, 0, 0, 0):
            raise _fail("WinHttpSendRequest")
        if not w.WinHttpReceiveResponse(request, None):
            raise _fail("WinHttpReceiveResponse")
        status = _number(w, request, QUERY_STATUS_CODE)
        if status is None or not 200 <= status < 300:
            raise WebError(f"HTTP {status}", status=status)
        total = _number(w, request, QUERY_CONTENT_LENGTH)
        buf = ctypes.create_string_buffer(CHUNK)
        got, done = wintypes.DWORD(), 0
        while True:
            if not w.WinHttpReadData(request, buf, CHUNK, ctypes.byref(got)):
                raise _fail("WinHttpReadData")
            if got.value == 0:
                break
            done += got.value
            sink(buf.raw[:got.value], total)
        if total is not None and done != total:
            raise WebError(f"cut off after {done} of {total} bytes")
    finally:
        for h in reversed(handles):
            w.WinHttpCloseHandle(h)


def get(url: str, headers: dict[str, str], timeout: float = 15.0) -> bytes:
    """The body of ``url``; WebError on a non-2xx answer or any failure on the way."""
    pieces = []
    _request(url, headers, timeout, lambda data, _total: pieces.append(data))
    return b"".join(pieces)


def download(url: str, path: Path, headers: dict[str, str],
             on_progress: Callable[[int, int | None], None] | None = None, timeout: float = 30.0) -> int:
    """Stream ``url`` into ``path`` (written as path.part first, renamed once complete). Calls
    ``on_progress(done, total)`` as it goes (total None without a Content-Length). Returns the size."""
    path = Path(path)
    part = path.with_name(path.name + ".part")
    done = 0
    try:
        with open(part, "wb") as f:
            def sink(data, total):
                nonlocal done
                try:
                    f.write(data)
                except OSError as e:
                    if e.errno == errno.ENOSPC or getattr(e, "winerror", None) == ERROR_DISK_FULL:
                        raise WebError("disk full", disk=True) from e
                    raise
                done += len(data)
                if on_progress is not None:
                    on_progress(done, total)
            _request(url, headers, timeout, sink)
        os.replace(part, path)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    return done
