"""Findings of the Phase 6 whole-branch review, pinned before they were fixed."""
import ctypes
import json
import socket
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

import waker
import winapi
from _support import Spy, close_app, make_app, patched, pump
from store import Note


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.app = make_app(self.folder)
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        pump(self.app, lambda: not self.app.motion.busy(), timeout=2)
        pump(self.app, timeout=0.3)

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def saved(self):
        return json.loads((self.folder / "notes.json").read_text(encoding="utf-8"))

    # Critical 1: the app minimized without a WM_SYSCOMMAND (Win+M) is noticed
    def test_proxy_minimized_without_syscommand(self):
        hwnd = winapi.hwnd_of(self.app.proxy)
        ctypes.windll.user32.ShowWindow(hwnd, 6)        # SW_MINIMIZE, as Win+M does
        pump(self.app, lambda: not winapi.is_iconic(self.app.proxy) and self.nw.minimized, timeout=2)
        self.assertFalse(winapi.is_iconic(self.app.proxy))
        self.assertTrue(self.nw.minimized or self.nw.pad.collapsed)

    # Important 1: deleting from the bin, emptying it and the midnight purge are written at once
    def bin_note(self):
        note = self.app.add_note(Note(header="지울 것", body="본문"))
        note.deleted = (date.today() - timedelta(days=60)).isoformat() + "T00:00:00"
        self.app.save_now()
        self.assertIn(note.id, [n["id"] for n in self.saved()["notes"]])
        return note

    def test_delete_forever_is_saved(self):
        note = self.bin_note()
        self.app.delete_forever(note.id)
        self.assertNotIn(note.id, [n["id"] for n in self.saved()["notes"]])

    def test_empty_bin_is_saved(self):
        note = self.bin_note()
        self.app.empty_bin()
        self.assertNotIn(note.id, [n["id"] for n in self.saved()["notes"]])

    def test_purge_is_saved(self):
        note = self.bin_note()
        self.app._today = date.today() - timedelta(days=1)
        self.app._check_day()
        self.assertNotIn(note.id, [n["id"] for n in self.saved()["notes"]])

    # Important 2: a ping never waits; a dead wake channel falls back to a drain poll
    def test_ping_without_connection_returns_at_once(self):
        w = waker.Waker(self.app.root, {})
        w.close()
        t = time.perf_counter()
        w.ping("sys")
        self.assertLess((time.perf_counter() - t) * 1000, 50)

    def test_no_waker_falls_back_to_polling(self):
        close_app(self.app)
        with patched(waker.Waker, "__init__", Spy(raises=OSError("no socket"))):
            self.app = make_app(self.folder)
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.assertIsNotNone(self.app._sys_job)          # the old drain poll, as before Phase 6
        nw = next(iter(self.app.windows.values()))
        nw.minimize(animate=False)
        pump(self.app, lambda: nw.minimized, timeout=1)
        self.app._syscommands.append(("restore", winapi.hwnd_of(nw.win), time.monotonic()))
        pump(self.app, lambda: not nw.minimized and not nw.rolling, timeout=2)
        self.assertFalse(nw.minimized)

    # (re-graded) a burst of minimizes (Win+D) is one batch, as before
    def test_minimize_burst_is_one_batch(self):
        b = self.app.new_window(self.nw)
        pump(self.app, lambda: not self.app.motion.busy(), timeout=2)
        c = self.app.new_window(b)
        pump(self.app, lambda: not self.app.motion.busy(), timeout=2)
        pump(self.app, timeout=0.3)
        calls = []
        for w in (self.nw, b, c):
            w.minimize = Spy(wraps=w.minimize)
            calls.append(w.minimize)
        hw = [winapi.hwnd_of(w.win) for w in (self.nw, b, c)]
        self.app._syscommands.append(("min", hw[0], time.monotonic()))
        self.app.waker.ping("sys")
        pump(self.app, timeout=0.005)
        for h in hw[1:]:
            self.app._syscommands.append(("min", h, time.monotonic()))
        self.app.waker.ping("sys")
        pump(self.app, timeout=0.5)
        for spy in calls:
            self.assertEqual(spy.calls[0][1].get("animate"), False)

    # (re-graded) only the app's own clients: a connection without the token is not obeyed
    def test_port_needs_the_token(self):
        port = int((self.folder / "wake.port").read_text("ascii").split()[0])
        with socket.create_connection(("127.0.0.1", port), timeout=1) as s:
            s.sendall(b"quit\n")
        pump(self.app, timeout=0.4)
        self.assertFalse(self.app.closed)
        self.assertTrue(waker.send(self.folder / "wake.port", "quit"))
        pump(self.app, lambda: self.app.closed, timeout=2)
        self.assertTrue(self.app.closed)

    # (re-graded) Windows shutting down: everything is saved
    def test_shutdown_saves(self):
        self.app.prefs.custom_colors.append("#654321")      # (changed in place: only a full save writes it)
        cmd = self.app.root.tk.call("wm", "protocol", self.app.proxy._w, "WM_SAVE_YOURSELF")
        self.assertTrue(str(cmd))
        self.app.root.tk.call(cmd)
        self.assertIn("#654321", self.saved()["prefs"]["custom_colors"])

    # (re-graded) the date is looked at by the 15 s check too (a sleep with no resume message)
    def test_screen_check_looks_at_the_date(self):
        self.app._today = date.today() - timedelta(days=1)
        self.app._poll_screens()
        self.assertEqual(self.app._today, date.today())


if __name__ == "__main__":
    unittest.main()
