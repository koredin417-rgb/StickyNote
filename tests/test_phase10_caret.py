"""Phase 10, tasks 2-3 (2026-11-28): the overlay caret glides (A) and breathes (B).
Spec: docs/superpowers/specs/2026-11-28-phase10-motion-design.md."""
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
from caret import CARET_BREATH

CARET = "caret"


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.settle()
        nw = self.nw
        nw.body.focus_force()
        nw.body.insert("1.0", "첫 줄은 꽤 길게 써 둔 글이에요\n둘째")
        nw.body.mark_set("insert", "1.end")
        nw.caret.follow()
        self.settle()

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.2):
        pump(self.app, lambda: not self.app.motion.busy() and not self.app.clock.busy, timeout=3)
        pump(self.app, timeout=t)

    def overlay_x(self):
        return self.nw.caret.frame.winfo_x() + self.nw.caret.tk_width // 2   # (drawn centred on the point, as Tk's)

    def insert_x(self):
        return self.nw.body.bbox("insert")[0]


class GlideTest(Case):
    def test_rests_on_the_insert_point(self):
        nw = self.nw
        self.assertTrue(nw.caret.frame.winfo_ismapped())
        self.assertLessEqual(abs(self.overlay_x() - self.insert_x()), 1)
        self.assertEqual(nw.caret.frame.winfo_height(), nw.body.dlineinfo("insert")[3])   # (the line, as Tk's)
        self.assertEqual(str(nw.body.cget("insertbackground")).upper(), str(nw.caret.bg).upper())   # unseen

    def test_glides_between(self):
        nw = self.nw
        start = self.overlay_x()
        nw.body.mark_set("insert", "1.0")
        nw.caret.follow()
        pump(self.app, timeout=0.03)                               # (about 2 frames of CARET_GLIDE_MS)
        mid = self.overlay_x()
        self.assertLess(mid, start)
        self.assertGreater(mid, self.insert_x())
        self.settle()
        self.assertLessEqual(abs(self.overlay_x() - self.insert_x()), 1)
        self.assertFalse(self.app.clock.busy)                      # nothing left running

    def test_off_jumps(self):
        self.app.set_motion("off")
        nw = self.nw
        nw.body.mark_set("insert", "1.0")
        nw.caret.follow()
        pump(self.app, timeout=0.01)
        self.assertLessEqual(abs(self.overlay_x() - self.insert_x()), 1)


class HandBackTest(Case):
    def test_composing_keeps_ours_after_the_syllable(self):
        nw = self.nw
        box = nw.body.bbox("insert")
        nw.preedit.configure(text="한", font=nw.body.cget("font"))       # (what _show_preedit shows)
        nw.preedit.place(x=box[0], y=box[1], height=box[3], bordermode="ignore")
        nw.caret.composing(True)
        self.settle()
        self.assertTrue(nw.caret.frame.winfo_ismapped())                # ours, never Tk's before the syllable
        self.assertEqual(str(nw.body.cget("insertbackground")).upper(), str(nw.caret.bg).upper())
        want = box[0] + nw.preedit.winfo_reqwidth()
        self.assertLessEqual(abs(self.overlay_x() - want), 1)           # just after the syllable
        nw.preedit.place_forget()
        nw.caret.composing(False)
        self.settle()
        self.assertLessEqual(abs(self.overlay_x() - self.insert_x()), 1)

    def test_selection_hides(self):
        nw = self.nw
        nw.body.tag_add("sel", "1.0", "1.3")
        nw.caret.follow()
        pump(self.app, timeout=0.05)
        self.assertFalse(nw.caret.frame.winfo_ismapped())

    def test_focus_out_hides(self):
        nw = self.nw
        nw.win.focus_force()                    # (the keyboard leaves the memo text)
        pump(self.app, timeout=0.1)
        self.assertFalse(nw.caret.frame.winfo_ismapped())

    def test_pages_hide(self):
        nw = self.nw
        nw.show_list()
        self.settle()
        self.assertFalse(nw.caret.frame.winfo_ismapped())


class BreathTest(Case):
    def test_breathes_after_a_rest(self):
        nw, caret = self.nw, self.nw.caret
        self.assertEqual(len(caret.ramp), CARET_BREATH)
        seen = set()
        pump(self.app, lambda: (seen.add(str(caret.frame.cget("bg"))), len(seen) >= 4)[1], timeout=caret.rest_ms / 1000 + 2)
        self.assertGreaterEqual(len(seen), 4)
        self.assertTrue(seen <= {str(c) for c in caret.ramp})

    def test_solid_while_typing(self):
        nw, caret = self.nw, self.nw.caret
        nw.body.event_generate("<KeyPress>", keysym="a")
        pump(self.app, timeout=0.05)
        self.assertEqual(str(caret.frame.cget("bg")), str(caret.ramp[0]))

    def test_unfocused_costs_nothing(self):
        nw = self.nw
        self.app.root.focus_force()
        pump(self.app, timeout=0.2)
        self.assertFalse(self.app.clock.active(self.nw.caret.frame, CARET))

    def test_theme_change_rebuilds_the_ramp(self):
        nw = self.nw
        before = list(nw.caret.ramp)
        self.app.set_cursor_mode("text" if self.app.prefs.cursor_color == "opposite" else "opposite")
        self.settle()
        self.assertNotEqual(list(nw.caret.ramp), before)


class ReviewTest(Case):
    """The phase 10 review (2026-11-28)."""

    def test_a_press_on_the_caret_goes_to_the_text(self):
        nw, f = self.nw, self.nw.caret.frame
        self.assertTrue(f.winfo_ismapped())
        f.event_generate("<ButtonPress-1>", x=1, y=2)
        f.event_generate("<ButtonRelease-1>", x=1, y=2)
        pump(self.app, timeout=0.05)
        self.assertFalse(f.winfo_ismapped())                    # the mouse: Tk's own caret
        self.assertEqual(str(nw.body.cget("insertbackground")).upper(), str(nw.caret.color).upper())
        nw.body.event_generate("<KeyPress>", keysym="Right")
        self.settle()
        self.assertTrue(f.winfo_ismapped())                     # a key: ours again

    def test_code_moving_the_insert_point_is_followed(self):
        nw = self.nw
        nw.body.mark_set("insert", "2.end")
        nw.caret.follow()
        self.settle()
        nw.toggle_bullets()                                     # (puts "• " in front: the point moves)
        self.settle()
        self.assertLessEqual(abs(self.overlay_x() - self.insert_x()), 1)

    def test_tk_caret_keeps_its_width_for_the_ime(self):
        b = self.nw.body                                                 # still drawn (the IME needs it), unseen
        self.assertGreater(int(b.cget("insertwidth")), 0)
        self.assertGreater(int(b.cget("insertontime")), 0)
        self.assertEqual(int(b.cget("insertofftime")), 0)               # steady: nothing flickers
        self.assertEqual(str(b.cget("insertbackground")).upper(), str(self.nw.caret.bg).upper())

    def test_breathing_stops_when_idle(self):
        caret = self.nw.caret
        caret._since = 0.0                                      # (no key for a long time)
        caret._breathe(0)
        pump(self.app, lambda: caret._breath_job is None, timeout=caret.rest_ms / 1000 * 2 + 1)
        self.assertIsNone(caret._breath_job)
        self.assertEqual(str(caret.frame.cget("bg")), str(caret.ramp[0]))     # solid


if __name__ == "__main__":
    unittest.main()
