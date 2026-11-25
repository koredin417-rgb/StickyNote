import tempfile
import unittest
from pathlib import Path

import winapi
from _support import Spy, close_app, make_app, patched, pump


class GcIdleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def test_drain_does_not_collect(self):
        with patched(winapi, "collect_garbage", Spy()) as spy:
            self.app._drain_syscommands()
        self.assertEqual(spy.call_count, 0)

    def test_collects_when_idle_not_while_animating(self):
        clock = self.app.clock
        pump(self.app, lambda: not clock.busy, timeout=3)
        clock._gc_at = 0.0                              # (as if never collected)
        with patched(winapi, "collect_garbage", Spy()) as spy:
            nw = next(iter(self.app.windows.values()))
            p = nw.pad
            self.app.motion.run({p.id: (p.x + 100, p.y, p.x + 100 + p.width, p.y + p.height)})
            pump(self.app, timeout=0.2)
            self.assertEqual(spy.call_count, 0)
            pump(self.app, timeout=1.5)
            self.assertGreaterEqual(spy.call_count, 1)


if __name__ == "__main__":
    unittest.main()
