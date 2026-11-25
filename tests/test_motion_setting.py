import tempfile
import time
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
import texts
import ui_views
import winapi


class MotionSettingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        pump(self.app, timeout=0.5)
        self.nw = next(iter(self.app.windows.values()))

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def move(self, dx=200):
        p = self.nw.pad
        self.app.motion.run({p.id: (p.x + dx, p.y, p.x + dx + p.width, p.y + p.height)})

    def test_default_follows_windows(self):
        self.assertIsNone(self.app.prefs.motion)
        self.assertEqual(self.app.clock.mode, "full" if winapi.client_animations_enabled() else "off")

    def test_off_mode_still_lands_and_saves(self):
        self.app.set_motion("off")
        x = self.nw.pad.x
        ends = []
        p = self.nw.pad
        self.app.motion.run({p.id: (x + 150, p.y, x + 150 + p.width, p.y + p.height)}, done=lambda: ends.append(1))
        pump(self.app, timeout=0.1)
        self.assertEqual((self.nw.pad.x, ends), (x + 150, [1]))
        self.app.save_now()
        self.assertIn('"motion": "off"', (Path(self.tmp.name) / "notes.json").read_text(encoding="utf-8"))

    def test_reduced_crossfades_instead_of_gliding(self):
        self.app.set_motion("reduced")
        x0 = self.nw.win.winfo_rootx()
        xs = []
        self.move(300)
        end = time.perf_counter() + 0.4
        while time.perf_counter() < end:
            self.app.root.update()
            xs.append(self.nw.win.winfo_rootx())
            time.sleep(0.003)
        self.assertEqual(set(xs) - {x0, x0 + 300}, set())   # never in between
        self.assertEqual(self.nw.pad.x, x0 + 300)
        self.assertAlmostEqual(float(self.nw.win.attributes("-alpha")), self.nw.pad.alpha, places=2)

    def test_back_to_default(self):
        self.app.set_motion("off")
        self.app.set_motion(None)
        self.assertIsNone(self.app.prefs.motion)
        self.assertEqual(self.app.clock.mode, "full" if winapi.client_animations_enabled() else "off")

    def test_settings_row_lists_three_modes(self):
        self.assertIn("set_motion", dict(ui_views.SETTING_GROUPS)["grp_place"])
        self.assertEqual(texts.tr("motion_reduced"), "줄이기" if texts.language() == "ko" else "Reduced")
        self.nw.toggle_settings()
        pump(self.app, timeout=0.3)
        sv = self.nw.settings_view
        self.assertEqual(set(sv.motion_buttons), {"full", "reduced", "off"})
        sv.open("set_motion")                          # its page, as a click on the row opens it
        pump(self.app, timeout=0.4)
        sv.motion_buttons["reduced"].event_generate("<ButtonRelease-1>", x=2, y=2)
        pump(self.app, timeout=0.1)
        self.assertEqual(self.app.prefs.motion, "reduced")


if __name__ == "__main__":
    unittest.main()
