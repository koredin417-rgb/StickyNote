"""Phase 10, task 5 (2026-11-28): format confirm (I). A format, bullets or a to-do switched on or off
pulses its rail button once (when the rail shows it) and tints the changed text for a moment."""
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
from ui_common import MIN_H, MIN_W, animating

PULSE, TINT = "pulse", "confirm"


class ConfirmTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = nw = next(iter(self.app.windows.values()))
        nw.body.focus_force()
        nw.body.insert("1.0", "굵게 할 글자")
        self.settle()

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.2):
        pump(self.app, lambda: not self.app.motion.busy() and not self.app.clock.busy, timeout=3)
        pump(self.app, timeout=t)

    def select(self):
        b = self.nw.body
        b.tag_add("sel", "1.0", "1.2")

    def test_bold_pulses_and_tints(self):
        nw = self.nw
        self.select()
        nw.toggle_format("b")
        self.assertTrue(animating(nw.btn_bold, PULSE))
        self.assertTrue(nw.body.tag_ranges(TINT))
        pump(self.app, lambda: not nw.body.tag_ranges(TINT), timeout=1.5)
        self.assertFalse(nw.body.tag_ranges(TINT))           # gone again
        self.assertFalse(animating(nw.btn_bold, PULSE))

    def test_todo_pulses(self):
        nw = self.nw
        nw.toggle_todo()
        self.assertTrue(animating(nw.btn_todo, PULSE))
        self.assertTrue(nw.body.tag_ranges(TINT))
        self.settle()

    def test_button_not_on_the_rail_no_pulse(self):
        nw, px = self.nw, self.app.px
        nw.set_size(px(MIN_W), px(MIN_H))
        self.settle()
        nw.body.focus_force()
        self.settle()
        hidden = [b for b in nw.format_buttons[:4] if b in nw.rail_hidden()]
        if not hidden:
            self.skipTest("every format button fits here")
        b = hidden[-1]
        kind = "bius"[nw.format_buttons.index(b)]
        self.select()
        nw.toggle_format(kind)
        self.assertFalse(animating(b, PULSE))
        self.assertTrue(nw.body.tag_ranges(TINT))            # the tint alone confirms it

    def test_off_no_effects(self):
        self.app.set_motion("off")
        nw = self.nw
        self.select()
        nw.toggle_format("b")
        self.assertFalse(animating(nw.btn_bold, PULSE))
        self.assertFalse(nw.body.tag_ranges(TINT))
        self.assertTrue(nw.btn_bold.active)                   # (the format itself is applied)


if __name__ == "__main__":
    unittest.main()
