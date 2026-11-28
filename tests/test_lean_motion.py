"""The memory and motion pass (2026-11-28): pictures held only while they can be used, Settings
freed a while after it is left, covers that go with their note, the wheel's glide keeping its
speed, the scroll thumb as smooth pictures, the caret breathing on the frame clock."""
import tempfile
import unittest
from pathlib import Path


import ui_note
from _support import close_app, make_app, patched, pump
from ui_common import WheelGlide, animating


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.settle()

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.3):
        pump(self.app, lambda: not self.app.motion.busy() and not self.app.clock.busy, timeout=3)
        pump(self.app, timeout=t)


class PicturesTest(Case):
    def test_a_slide_picture_is_not_kept_for_a_lone_note(self):
        shots, nw = self.app.shots, self.nw
        self.assertIsNotNone(shots.fresh(nw, keep=False))
        self.assertNotIn(nw.pad.id, shots._shots)
        self.assertIsNotNone(shots.fresh(nw))               # (fold, minimize: kept)
        self.assertIn(nw.pad.id, shots._shots)

    def test_a_changed_look_drops_the_kept_picture(self):
        shots, nw = self.app.shots, self.nw
        shots.fresh(nw)
        nw.bump_look()
        self.assertNotIn(nw.pad.id, shots._shots)

    def test_the_rail_keeps_only_its_strip(self):
        nw = self.nw
        nw.rail_calm._swap(True)
        self.settle(0.6)
        cache = getattr(nw.rail_calm, "_rail_cache", None)
        if cache is None:                                   # (no slide where motion is cut)
            self.skipTest("no rail picture taken")
        strip, _key, size = cache
        self.assertEqual(strip.size[0], self.app.px(ui_note.RAIL_W))
        self.assertLess(strip.size[0], size[0])
        nw.rail_calm.close()
        self.assertIsNone(nw.rail_calm._rail_cache)


class SettingsFreedTest(Case):
    def test_freed_a_while_after_it_is_left(self):
        nw = self.nw
        with patched(ui_note, "SETTINGS_KEEP_MS", 200):
            nw.show_settings()
            self.settle()
            self.assertIsNotNone(nw._settings_view)
            nw.go_back()
            self.settle(0.6)
        self.assertIsNone(nw._settings_view)
        nw.show_settings()                                  # made again, and works
        self.settle()
        self.assertIsNotNone(nw._settings_view)
        self.assertTrue(nw.settings_view.frame.winfo_ismapped())

    def test_kept_when_opened_again_in_time(self):
        nw = self.nw
        with patched(ui_note, "SETTINGS_KEEP_MS", 400):
            nw.show_settings()
            self.settle()
            sv = nw._settings_view
            nw.go_back()
            self.settle(0.1)
            nw.show_settings()
            self.settle(0.6)
        self.assertIs(nw._settings_view, sv)


class CoversTest(Case):
    def test_a_slide_cover_fades_out_with_a_closing_note(self):
        nw = self.nw
        self.app.new_window(from_window=nw)
        self.settle()
        nw.rail_calm._swap(True)
        cover = nw.rail_calm._cover
        if cover is None:
            self.skipTest("no cover where motion is cut")
        nw.close()
        pump(self.app, timeout=0.05)
        self.assertTrue(animating(cover, "alpha"))
        self.settle(0.6)
        self.assertFalse(cover.winfo_exists())


class GroupDragCoversTest(Case):
    def test_a_neighbours_slide_picture_goes_when_the_group_moves(self):
        """The user: dragging linked notes left a neighbour's rail slide picture where it was."""
        a = self.nw
        b = self.app.new_window(from_window=a)
        self.settle()
        self.assertIn(b.pad.id, self.app.group_of(a.pad.id))
        b.rail_calm._swap(True)                              # its rail sliding out
        cover = b.rail_calm._cover
        if cover is None:
            self.skipTest("no cover where motion is cut")
        x, y = a.pad.x + 60, a.pad.y + 10
        a.row.event_generate("<ButtonPress-1>", x=60, y=10, rootx=x, rooty=y)
        self.assertIsNone(b.rail_calm._cover)
        self.assertFalse(cover.winfo_exists())
        self.assertTrue(b.rail_calm.hidden)                  # (laid out as the rail now is)
        a.row.event_generate("<B1-Motion>", x=90, y=30, rootx=x + 30, rooty=y + 20, state=0x100)
        a.row.event_generate("<ButtonRelease-1>", x=90, y=30, rootx=x + 30, rooty=y + 20)
        self.settle()


class WheelGlideTest(Case):
    def test_a_notch_meanwhile_keeps_the_speed(self):
        b = self.nw.body
        moved = []
        g = WheelGlide(b, moved.append)
        g.add(60)
        pump(self.app, timeout=0.06)
        self.assertTrue(g.active())
        before = sum(moved)
        g.add(60)                                           # a second notch, mid-glide
        pump(self.app, timeout=0.03)
        self.assertGreater(sum(moved), before)              # it never stops or goes back
        self.settle()
        self.assertEqual(sum(moved), 120)                   # every px of both notches, once
        self.assertEqual(g.left(), 0)


class ThumbTest(Case):
    def test_thumb_is_smooth_pictures(self):
        nw = self.nw
        nw.body.insert("1.0", "\n".join(f"line {i}" for i in range(150)))
        self.settle()
        sc = next(v for v in vars(nw).values() if type(v).__name__ == "OverlayScroll")
        sc.flash()
        self.settle(0.05)
        kinds = {sc.cv.type(i) for i in sc.cv.find_all()}
        self.assertIn("image", kinds)
        self.assertNotIn("line", kinds)                     # (no jagged round-capped line)


if __name__ == "__main__":
    unittest.main()
