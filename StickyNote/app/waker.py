"""A wake channel for the event loop (the design's §5.6): a loopback socket that Tcl reads with
``fileevent``. ``Waker.ping(word)`` from anywhere wakes the loop, which then runs that word's
handler. "Anywhere" includes a Windows message procedure, where tkinter must never be called
(the Tcl lock is held there): ping is a plain socket send. Another process can ping too: it
connects to the port written in the port file and sends a word and a newline.

It replaces polls: the taskbar hook's 30 ms drain, the signal files' 800 ms check, the monitors'
1 s check and the day's 30 s check."""
from __future__ import annotations

import socket
import tkinter as tk
from pathlib import Path

_TCL = r"""
namespace eval ::sticky {}
proc ::sticky::wake_read {chan callback} {
    if {[catch {set data [read $chan]}] || [eof $chan]} {
        catch {close $chan}
        return
    }
    if {$data ne ""} {$callback $data}
}
proc ::sticky::wake_accept {callback chan addr port} {
    if {$addr ne "127.0.0.1"} {
        catch {close $chan}
        return
    }
    fconfigure $chan -blocking 0 -translation binary
    fileevent $chan readable [list ::sticky::wake_read $chan $callback]
}
"""


class Waker:
    """``handlers``: word -> function, run on the event loop (words a ping brings, one per line)."""

    def __init__(self, root: tk.Misc, handlers: dict, port_file: Path | None = None):
        self.root, self.handlers, self.port_file = root, dict(handlers), port_file
        self._buffer = ""
        self._sock: socket.socket | None = None
        self.port = 0
        t = root.tk
        if not t.call("info", "procs", "::sticky::wake_read"):
            t.eval(_TCL)
        self._callback = root.register(self._received)
        self._server = t.eval(f"socket -server [list ::sticky::wake_accept {self._callback}] "
                              "-myaddr 127.0.0.1 0")
        self.port = int(t.eval(f"lindex [fconfigure {self._server} -sockname] 2"))
        if port_file is not None:
            try:
                port_file.parent.mkdir(parents=True, exist_ok=True)
                port_file.write_text(str(self.port), "ascii")
            except OSError:
                pass

    def _connect(self) -> socket.socket | None:
        if self._sock is None:
            try:
                s = socket.create_connection(("127.0.0.1", self.port), timeout=1.0)
                s.setblocking(False)
                self._sock = s
            except OSError:
                return None
        return self._sock

    def ping(self, word: str) -> None:
        """Wake the loop and run ``word``'s handler there. Never calls tkinter: safe in a
        Windows message procedure. (The first ping connects: once, at start, see App.)"""
        s = self._connect()
        if s is None:
            return
        try:
            s.send(word.encode("ascii", "ignore") + b"\n")
        except BlockingIOError:
            pass                            # (the buffer is full: a wake is already waiting)
        except OSError:
            self._sock = None

    def _received(self, data):
        self._buffer += str(data)
        *words, self._buffer = self._buffer.split("\n")
        for word in dict.fromkeys(w.strip() for w in words if w.strip()):      # (each once, in order)
            fn = self.handlers.get(word)
            if fn is not None:
                fn()

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        try:
            self.root.tk.call("close", self._server)
        except tk.TclError:
            pass
        if self.port_file is not None:
            try:
                if self.port_file.read_text("ascii").strip() == str(self.port):
                    self.port_file.unlink()
            except OSError:
                pass


def send(port_file: Path, word: str) -> bool:
    """From another process (a second launch, the installer): ``word`` to the running app. False
    when there is no port file or nothing listens there (an older app: the caller falls back)."""
    try:
        port = int(port_file.read_text("ascii").strip())
        with socket.create_connection(("127.0.0.1", port), timeout=1.0) as s:
            s.sendall(word.encode("ascii") + b"\n")
        return True
    except (OSError, ValueError):
        return False
