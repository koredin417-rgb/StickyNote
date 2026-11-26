import tempfile
import time
import unittest
from pathlib import Path

import winapi
from _support import Spy, close_app, make_app, patched, pump


class DrainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        first = next(iter(self.app.windows.values()))
        for _ in range(4):
            self.app.new_window(from_window=first)
        pump(self.app, timeout=0.5)

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def test_idle_drain_does_no_per_window_lookups(self):
        self.app._syscommands.clear()
        with patched(self.app, "_check_thumbnail", Spy()), \
                patched(winapi, "hwnd_of", Spy(wraps=winapi.hwnd_of)) as spy:
            self.app._drain_syscommands()
        notes = [nw.win for nw in self.app.windows.values()]
        looked_up = [a[0] for a, _kw in spy.calls if a and any(a[0] is w for w in notes)]
        self.assertEqual(looked_up, [], "an idle drain should not look up any note window")

    def test_multi_minimize_still_handled(self):
        wins = list(self.app.windows.values())[:2]
        t = time.perf_counter()
        self.app._syscommands += [("min", winapi.hwnd_of(w.win), t) for w in wins]
        with patched(type(wins[0]), "minimize", Spy()) as m:
            self.app._drain_syscommands()           # (a burst is gathered for MULTI_MIN_MS since Phase 6)
            pump(self.app, lambda: m.call_count == 2, timeout=0.5)
        self.assertEqual(m.call_count, 2)
        self.assertTrue(all(kw.get("animate") is False for _a, kw in m.calls))


if __name__ == "__main__":
    unittest.main()
