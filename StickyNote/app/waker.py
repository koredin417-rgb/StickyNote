"""A wake channel for the event loop (the design's §5.6): a loopback socket that Tcl reads with
``fileevent``. ``Waker.ping(word)`` from anywhere wakes the loop, which then runs that word's
handler. "Anywhere" includes a Windows message procedure, where tkinter must never be called
(the Tcl lock is held there): ping is a plain send on a socket connected beforehand, and never
waits. Another process (a second launch, the installer) pings through ``send``: it reads the port
and a random token from the port file (in the user's own data folder) and sends a line with both;
a line without the token is ignored, so no other program or web page can drive the app.

It replaces polls: the taskbar hook's 30 ms drain, the signal files' 800 ms check, the monitors'
1 s check and the day's 30 s check."""
from __future__ import annotations

import secrets
import socket
import tkinter as tk
from pathlib import Path

_TCL = r"""
namespace eval ::sticky {}
proc ::sticky::wake_read {chan callback} {
    if {[catch {set data [read $chan]}]} {
        catch {close $chan}
        $callback $chan ""
        return
    }
    if {$data ne ""} {$callback $chan $data}
    if {[eof $chan]} {
        catch {close $chan}
        $callback $chan ""
    }
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
    """``handlers``: word -> function, run on the event loop (one word a line, after the token)."""

    def __init__(self, root: tk.Misc, handlers: dict, port_file: Path | None = None):
        self.root, self.handlers, self.port_file = root, dict(handlers), port_file
        self.token = secrets.token_hex(16)
        self._buffers: dict = {}            # channel -> what came of a line so far
        self._sock: socket.socket | None = None
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
                port_file.write_text(f"{self.port} {self.token}", "ascii")
            except OSError:
                pass

    def connect(self) -> None:
        """The app's own connection, made once at start (a ping never connects: it never waits).
        Raises OSError when it can't be made: the app polls instead."""
        s = socket.create_connection(("127.0.0.1", self.port), timeout=1.0)
        s.setblocking(False)
        self._sock = s

    def ping(self, word: str) -> None:
        """Wake the loop and run ``word``'s handler there. Never calls tkinter and never waits:
        safe in a Windows message procedure. Without a connection it does nothing."""
        s = self._sock
        if s is None:
            return
        try:
            s.send(f"{self.token} {word}\n".encode("ascii", "ignore"))
        except BlockingIOError:
            pass                            # (the buffer is full: a wake is already waiting)
        except OSError:
            self._sock = None

    def _received(self, chan, data):
        chan = str(chan)
        if data == "":                      # the connection closed
            self._buffers.pop(chan, None)
            return
        text = self._buffers.get(chan, "") + str(data)
        *lines, rest = text.split("\n")
        self._buffers[chan] = rest[-256:]   # (a line never gets long: a stray client stays harmless)
        words = []
        for line in lines:
            token, _sep, word = line.strip().partition(" ")
            if secrets.compare_digest(token, self.token) and word not in words:
                words.append(word)
        for word in words:                  # (each once, in order)
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
                if self.port_file.read_text("ascii").split()[0] == str(self.port):
                    self.port_file.unlink()
            except (OSError, IndexError):
                pass


def send(port_file: Path, word: str) -> bool:
    """From another process (a second launch, the installer): ``word`` to the running app. False
    when there is no port file or nothing listens there (an older app: the caller falls back)."""
    try:
        port, token = port_file.read_text("ascii").split()[:2]
        with socket.create_connection(("127.0.0.1", int(port)), timeout=1.0) as s:
            s.sendall(f"{token} {word}\n".encode("ascii"))
        return True
    except (OSError, ValueError):
        return False
