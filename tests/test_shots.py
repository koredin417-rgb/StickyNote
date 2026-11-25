"""Phase 4, Tasks 3-5: stand-in pictures (ShotCache), always-covered unfold / restore, the fly."""
import tempfile
import unittest
from pathlib import Path

import winapi
from _support import Spy, close_app, make_app, patched, pump


class ShotsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.nw.close_hints()
        self.settle()

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.3):
        pump(self.app, lambda: not self.app.motion.busy(), timeout=2)
        pump(self.app, timeout=t)

    # ---- Task 3
    def test_shot_reused_until_changed(self):
        nw, shots = self.nw, self.app.shots
        with patched(winapi, "snapshot", Spy(wraps=winapi.snapshot)) as spy:
            a = shots.shot(nw)
            b = shots.shot(nw)
            self.assertIsNotNone(a)
            self.assertIs(a, b)
            self.assertEqual(spy.call_count, 1)
            nw.body.insert("1.0", "바뀐 글")
            nw.sync_from_widgets()
            pump(self.app, timeout=0.1)
            self.assertIsNone(shots.peek(nw))
            shots.shot(nw)
            self.assertEqual(spy.call_count, 2)
            nw.set_color("#CFE6FF")
            pump(self.app, timeout=0.1)
            self.assertIsNone(shots.peek(nw))
            shots.shot(nw)
            nw.set_size(nw.pad.width + 40, nw.pad.height)
            self.settle()
            self.assertIsNone(shots.peek(nw))

    def test_shot_dropped_on_close(self):
        b = self.app.new_window(self.nw)
        self.settle()
        self.app.shots.shot(b)
        pid = b.pad.id
        self.assertIn(pid, self.app.shots._shots)
        self.app.close_window(b)
        pump(self.app, lambda: not b.win.winfo_exists(), timeout=2)     # (destroyed after its fade)
        self.assertNotIn(pid, self.app.shots._shots)

    def test_freeze_uses_cache(self):
        nw = self.nw
        self.app.shots.shot(nw)
        with patched(winapi, "snapshot", Spy(wraps=winapi.snapshot)) as spy:
            nw.freeze()
            self.assertEqual(spy.call_count, 0)
        self.assertIsNotNone(nw._cover)
        nw.thaw()

    def test_linked_notes_warm_when_idle(self):
        a = self.nw
        b = self.app.new_window(a)
        self.settle()
        c = self.app.new_window(b)
        self.settle()
        self.assertGreaterEqual(len(self.app.group_of(a.pad.id)), 3)
        pump(self.app, lambda: all(self.app.shots.peek(w) is not None for w in (a, b, c)), timeout=6)
        for w in (a, b, c):
            self.assertIsNotNone(self.app.shots.peek(w))


class CoveredRollTest(ShotsTest):
    """Task 4: unfold and restore always roll with a current picture."""

    test_shot_reused_until_changed = test_shot_dropped_on_close = None
    test_freeze_uses_cache = test_linked_notes_warm_when_idle = None

    def test_unfold_without_kept_shot_is_covered(self):
        nw = self.nw
        nw.toggle_collapse(instant=True)
        self.settle()
        nw.body.insert("1.0", "접힌 동안 바뀐 글\n")   # (its picture from before is stale now)
        nw.sync_from_widgets()
        self.assertIsNone(nw._kept_shot(nw.pad.height))
        nw.toggle_collapse()
        cover = getattr(nw, "_rolling_cover", None)
        self.assertIsNotNone(cover)
        self.assertEqual(cover.full_h, nw.pad.height)
        pump(self.app, lambda: not nw.rolling, timeout=2)
        self.settle()
        self.assertFalse(nw.pad.collapsed)
        self.assertEqual(nw.win.winfo_height(), nw.pad.height)
        self.assertAlmostEqual(float(nw.win.attributes("-alpha")), nw.pad.alpha, places=2)

    def test_restore_without_kept_shot_is_covered(self):
        nw = self.nw
        nw.minimize(animate=False)
        pump(self.app, timeout=0.2)
        nw.body.insert("1.0", "숨은 동안 바뀐 글\n")
        nw.sync_from_widgets()
        nw.restore()
        cover = getattr(nw, "_rolling_cover", None)
        self.assertIsNotNone(cover)
        self.assertEqual(cover.full_h, nw.pad.height)
        pump(self.app, lambda: not nw.rolling, timeout=2)
        self.settle()
        self.assertEqual(nw.win.winfo_height(), nw.pad.height)
        self.assertAlmostEqual(float(nw.win.attributes("-alpha")), nw.pad.alpha, places=2)


if __name__ == "__main__":
    unittest.main()
