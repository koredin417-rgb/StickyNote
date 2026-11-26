"""Phase 6, Tasks 1-2: the app wakes on events (a wake channel), not on polls."""
import tempfile
import time
import unittest
from pathlib import Path

import waker
import winapi
from _support import Spy, close_app, make_app, patched, pump


class WakerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.nw.close_hints()
        pump(self.app, lambda: not self.app.motion.busy(), timeout=2)
        pump(self.app, timeout=0.4)

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    # ---- Task 1
    def test_ping_wakes_handler(self):
        ran = []
        w = waker.Waker(self.app.root, {"x": lambda: ran.append(1)})
        try:
            w.connect()                                 # (a ping never connects: done once, at start)
            w.ping("x")
            w.ping("nobody")
            pump(self.app, lambda: ran, timeout=1)
            self.assertEqual(ran, [1])
        finally:
            w.close()

    def test_no_drain_timer_when_idle(self):
        self.assertIsNone(self.app._sys_job)
        nw = self.nw
        nw.minimize(animate=False)
        pump(self.app, lambda: nw.minimized, timeout=1)
        self.app._syscommands.append(("restore", winapi.hwnd_of(nw.win), time.monotonic()))
        self.app.waker.ping("sys")
        pump(self.app, lambda: not nw.minimized and not nw.rolling, timeout=2)
        self.assertFalse(nw.minimized)

    def test_idle_wakeups_under_one_per_second(self):
        root = self.app.root
        fired = []
        real_after, real_idle = root.after, root.after_idle

        def counted(fn):
            def run(*a):
                fired.append(getattr(fn, "__name__", "?"))
                return fn(*a)
            return run

        def after(ms, fn=None, *args):
            return real_after(ms, counted(fn), *args) if fn is not None else real_after(ms)
        pump(self.app, timeout=1.5)                 # (the start's own settling)
        with patched(root, "after", after), patched(root, "after_idle", lambda fn, *a: real_idle(counted(fn), *a)):
            # the timers already pending were armed before the count: re-arm what repeats
            self.app._rearm_timers()
            end = time.perf_counter() + 10
            while time.perf_counter() < end:
                root.tk.dooneevent(0)
        self.assertLess(len(fired), 10, fired)


class EventWordsTest(WakerTest):
    """Task 2: show, quit, monitors and the date by events."""

    test_ping_wakes_handler = test_no_drain_timer_when_idle = test_idle_wakeups_under_one_per_second = None

    def test_second_launch_shows_via_port(self):
        nw = self.nw
        nw.minimize(animate=False)
        pump(self.app, lambda: nw.minimized, timeout=1)
        port_file = Path(self.tmp.name) / "wake.port"
        self.assertTrue(port_file.exists())
        self.assertTrue(waker.send(port_file, "show"))
        pump(self.app, lambda: not nw.minimized and not nw.rolling, timeout=2)
        self.assertFalse(nw.minimized)

    def test_quit_via_port_saves(self):
        self.nw.body.insert("1.0", "끝나기 전에 저장")
        self.assertTrue(waker.send(Path(self.tmp.name) / "wake.port", "quit"))
        pump(self.app, lambda: self.app.closed, timeout=2)
        self.assertTrue(self.app.closed)
        self.assertIn("끝나기 전에 저장", (Path(self.tmp.name) / "notes.json").read_text(encoding="utf-8"))

    def test_day_timer_aims_at_midnight(self):
        from datetime import datetime, timedelta
        now = datetime.now()
        midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
        want = (midnight - now).total_seconds() + 1
        self.assertAlmostEqual(self.app._day_due - time.monotonic(), want, delta=3)

    def test_screens_word_starts_check(self):
        with patched(self.app, "check_screens", Spy()) as spy:
            self.app.waker.ping("screens")
            pump(self.app, lambda: spy.call_count, timeout=1)
        self.assertGreaterEqual(spy.call_count, 1)


if __name__ == "__main__":
    unittest.main()
