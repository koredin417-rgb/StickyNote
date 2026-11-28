"""Phase 11, the calm rail (2026-11-28). The rail shows while the note has the focus or the pointer,
and fades into the page RAIL_REST_MS after it has neither; its room stays (no re-wrap). "레일
숨기기" in Settings: on for new users, off for people updating."""
import json
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
from ui_common import RAIL_REST_MS, PopupMenu


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name), rail=True)
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.settle()
        self.rail = self.nw.rail_calm
        self.focus, self.hover = False, True       # (the pointer decides: on the note to start)
        self.rail._focused = lambda: self.focus             # (a hidden desktop has no real pointer)
        self.rail._hovered = lambda: self.hover
        self.rail.check()                                   # (it may have rested already in setup, with the
        pump(self.app, lambda: not self.rail.hidden, timeout=3)     # focus elsewhere: every test starts shown)
        self.settle()

    def tearDown(self):
        PopupMenu.close_current()
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.2):
        pump(self.app, lambda: not self.app.motion.busy() and not self.app.clock.busy, timeout=3)
        pump(self.app, timeout=t)

    def leave(self):
        self.focus = self.hover = False
        self.rail.check()
        pump(self.app, lambda: self.rail.hidden, timeout=RAIL_REST_MS / 1000 + 3)   # (slower under load)
        self.settle()


class PrefTest(unittest.TestCase):
    def test_new_users_get_it(self):
        tmp = tempfile.TemporaryDirectory()
        app = make_app(Path(tmp.name), rail=True)
        try:
            self.assertTrue(app.prefs.rail_hide)
        finally:
            close_app(app)
            tmp.cleanup()

    def test_people_updating_do_not(self):
        tmp = tempfile.TemporaryDirectory()
        folder = Path(tmp.name)
        (folder / "notes.json").write_text(json.dumps({"version": 3, "notes": [], "pads": [], "prefs": {}}),
                                           encoding="utf-8")
        app = make_app(folder, rail=True)
        try:
            self.assertFalse(app.prefs.rail_hide)
        finally:
            close_app(app)
            tmp.cleanup()


class CalmTest(Case):
    def test_rests_and_gives_its_room_to_the_memo(self):
        nw = self.nw
        width = nw.main.winfo_width()
        self.leave()
        self.assertTrue(self.rail.hidden)
        self.assertFalse(nw.rail.winfo_ismapped())              # out of the layout (the user's call)
        self.assertGreater(nw.main.winfo_width(), width)        # the memo has its room
        pump(self.app, lambda: self.rail._cover is None, timeout=1)
        self.assertIsNone(self.rail._cover)                     # the picture over the swap is gone

    def test_not_at_once(self):
        self.focus = self.hover = False
        self.rail.check()
        self.assertFalse(self.rail.hidden)                      # (a pass of the mouse: no flicker)
        self.assertIsNotNone(self.rail._job)                    # it rests only once RAIL_REST_MS has passed

    def test_the_pointer_brings_it_back(self):
        self.leave()
        self.hover = True
        self.rail.check()
        self.settle(0.3)
        self.assertFalse(self.rail.hidden)
        self.assertTrue(self.nw.rail.winfo_ismapped())
        self.leave()
        self.focus = True                                       # the focus alone keeps it resting (the
        self.rail.check()                                       # user: the pointer decides, 2026-11-28)
        self.settle(0.3)
        self.assertTrue(self.rail.hidden)

    def test_stays_on_pages_and_with_a_menu(self):
        nw = self.nw
        nw.show_list()
        self.settle()
        self.focus = self.hover = False
        self.rail.check()
        pump(self.app, timeout=RAIL_REST_MS / 1000 + 0.3)
        self.assertFalse(self.rail.hidden)
        nw.show_home()
        self.settle()
        nw._more_menu()
        self.rail.check()
        pump(self.app, timeout=RAIL_REST_MS / 1000 + 0.3)
        self.assertFalse(self.rail.hidden)

    def test_setting_off_keeps_it(self):
        self.app.set_rail_hide(False)
        self.focus = self.hover = False
        self.rail.check()
        pump(self.app, timeout=RAIL_REST_MS / 1000 + 0.3)
        self.assertFalse(self.rail.hidden)

    def test_setting_off_shows_a_hidden_rail(self):
        self.leave()
        self.app.set_rail_hide(False)
        self.settle(0.3)
        self.assertFalse(self.rail.hidden)

    def test_no_pulse_while_hidden(self):
        from ui_common import animating
        nw = self.nw
        nw.body.insert("1.0", "굵게")
        self.leave()
        nw.body.tag_add("sel", "1.0", "1.2")
        nw.toggle_format("b")
        self.assertFalse(animating(nw.btn_bold, "pulse"))
        self.assertTrue(nw.body.tag_ranges("confirm"))

    def test_in_settings(self):
        nw = self.nw
        nw.show_settings()
        self.settle()
        sv = nw.settings_view
        self.assertIn("set_rail_hide", sv.list_rows)
        self.assertTrue(sv.rail_switch.on)
        sv.rail_switch.event_generate("<ButtonRelease-1>", x=2, y=2)
        self.settle(0.1)
        self.assertFalse(self.app.prefs.rail_hide)


class ReviewTest(Case):
    """The phase 11 review (2026-11-28)."""

    def test_rests_once_a_notice_goes(self):
        nw = self.nw
        nw.show_notice("잠깐")
        self.focus = self.hover = False
        self.rail.check()
        pump(self.app, timeout=RAIL_REST_MS / 1000 + 0.2)
        self.assertFalse(self.rail.hidden)                  # (the notice holds it)
        nw.hide_undo()
        pump(self.app, lambda: self.rail.hidden, timeout=RAIL_REST_MS / 1000 * 2 + 4)
        self.assertTrue(self.rail.hidden)                    # and it rests once the notice has gone

    def test_closing_never_brings_it_back(self):
        nw = self.nw
        self.leave()
        nw._closing = True
        self.hover = True
        self.rail.check()
        pump(self.app, timeout=0.1)
        self.assertTrue(self.rail.hidden)
        nw._closing = False

    def test_own_calendar_counts_as_the_note(self):
        nw = self.nw
        nw.toggle_calendar()
        self.settle(0.5)
        self.assertTrue(self.rail._mine(nw.calendar.top))
        self.assertFalse(self.rail._mine(self.app.root))

    def test_many_notes_rest_apart(self):
        self.focus = self.hover = False
        self.app._rail_swapped = __import__("time").monotonic()     # (another note swapped just now)
        self.rail._rested()                                         # (this one's rest ends this tick)
        self.assertFalse(self.rail.hidden)                          # not in the same tick: a little later
        pump(self.app, lambda: self.rail.hidden, timeout=4)
        self.assertTrue(self.rail.hidden)

    def test_custom_colours_once(self):
        self.app.prefs.custom_colors = ["#123456", "#123456", "#abcdef"]
        colors = self.nw._swatch_colors()
        self.assertEqual(colors.count("#123456"), 1)
        self.assertIn("#ABCDEF", colors)


class FreshTest(unittest.TestCase):
    def test_old_backups_only_is_not_a_new_user(self):
        tmp = tempfile.TemporaryDirectory()
        folder = Path(tmp.name)
        (folder / "backups").mkdir()
        (folder / "backups" / "notes-2026-11-01.json").write_text("{}", encoding="utf-8")
        app = make_app(folder, rail=True)
        try:
            self.assertFalse(app.prefs.rail_hide)
        finally:
            close_app(app)
            tmp.cleanup()


class Review2Test(Case):
    """The second phase 11 review (the swap version, 2026-11-28)."""

    def test_buttons_wait_a_moment_after_coming_back(self):
        nw = self.nw
        self.leave()
        self.hover = True
        self.rail.check()
        pump(self.app, lambda: not self.rail.hidden, timeout=1)
        before = len(self.app.windows)
        nw.btn_window._command()                 # a click that was meant for the text (right as it came)
        self.settle(0.05)
        self.assertEqual(len(self.app.windows), before)
        pump(self.app, lambda: self.rail.armed(), timeout=3)
        self.assertTrue(self.rail.armed())

    def test_see_through_note_swaps_without_a_picture(self):
        nw = self.nw
        nw.pad.transparency = 30
        nw.apply_look()
        self.settle()
        self.focus = self.hover = False
        self.rail.check()
        pump(self.app, lambda: self.rail.hidden, timeout=5)
        self.assertIsNone(self.rail._cover)

    def test_a_swap_mid_fade_keeps_its_picture(self):
        self.focus = self.hover = False
        self.rail.check()
        pump(self.app, lambda: self.rail.hidden, timeout=5)
        first = self.rail._cover
        if first is None:
            self.skipTest("no picture here (no shot of the note)")
        self.rail.show()
        self.assertIs(self.rail._cover, first)

    def test_a_page_brings_the_rail_back_first(self):
        nw = self.nw
        self.leave()
        nw.show_list()
        self.settle()
        self.assertFalse(self.rail.hidden)
        self.assertTrue(nw.rail.winfo_ismapped())

class GripNotInTheMovingTextTest(unittest.TestCase):
    """The user: the grip showed while the rail faded. The text that slides has no grip in it."""

    def test_grip_spot_is_the_page(self):
        from PIL import Image
        from rail_calm import CalmRail
        before = Image.new("RGB", (120, 90), "#202020")
        grip = (100, 70, 112, 82)
        img = CalmRail._moving_text(before, (30, 20, 118, 88), grip, "#FFEEAA")
        self.assertEqual(img.size, (88, 68))
        self.assertEqual(img.getpixel((75, 55)), (0xFF, 0xEE, 0xAA))     # the grip's spot
        self.assertEqual(img.getpixel((10, 10)), (0x20, 0x20, 0x20))     # the text as it was
        self.assertEqual(CalmRail._moving_text(before, (30, 20, 118, 88), None, "#FFEEAA").getpixel((75, 55)),
                         (0x20, 0x20, 0x20))



if __name__ == "__main__":
    unittest.main()
