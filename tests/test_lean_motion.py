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


class OpenListFollowsTest(Case):
    """The user's recording: a memo written in one note never showed in another note's open list
    ("no memos yet"), though the calendar showed it. The list follows after the typing pause, and
    stays where it was scrolled."""

    def test_open_list_shows_a_memo_being_written(self):
        a = self.nw
        b = self.app.new_window(from_window=a)
        self.settle()
        b.show_list()
        self.settle()
        self.assertEqual(b.list_view.titles(), [])
        a.body.insert("1.0", "ssss")
        a.sync_from_widgets()
        pump(self.app, lambda: b.list_view.titles() != [], timeout=3)
        self.assertEqual(len(b.list_view.titles()), 1)


class EntryKoreanTest(Case):
    """The user: Korean typing in the search bar. The syllable being put together shows at the cursor
    (the IME's own box is off for the note window; only the memo text drew it before)."""

    def test_search_shows_the_syllable_being_typed(self):
        import winapi
        nw = self.nw
        nw.show_list()
        self.settle()
        e = nw.list_view.search_entry
        e.focus_force()
        e.insert("end", "ab")
        pump(self.app, lambda: e.focus_get() is e, timeout=1)
        with patched(winapi, "composition", lambda hwnd, take=False: "한"):
            e.event_generate("<KeyRelease>", keysym="a")
            pump(self.app, timeout=0.05)
            lbl = nw.list_view.search_preedit.label
            self.assertTrue(lbl.winfo_ismapped())
            self.assertEqual(lbl.cget("text"), "한")
            b = e.bbox(1)
            self.assertEqual(int(lbl.place_info()["x"]), b[0] + b[2])     # right after "ab"
        e.event_generate("<KeyRelease>", keysym="a")
        pump(self.app, timeout=0.05)
        self.assertFalse(lbl.winfo_ismapped())                          # finished: gone


class CaretFastKeysTest(Case):
    """The user: with Backspace held, the caret trailed behind the text (measured: ~10 characters, and
    still off after the key was let go). The text's own <BackSpace> binding hid the key from the
    caret; it listens on a binding tag of its own now. Real key events through Tk's queue."""

    def held(self, keysym, n=12, period_ms=33):
        b = self.nw.body
        for i in range(n):
            b.after(i * period_ms, lambda: b.event_generate("<KeyPress>", keysym=keysym, when="tail"))
        pump(self.app, timeout=n * period_ms / 1000 + 0.15)

    def assert_at_insert(self):
        nw = self.nw
        nw.update_idletasks() if hasattr(nw, "update_idletasks") else nw.win.update_idletasks()
        box, caret = nw.body.bbox("insert"), nw.caret
        self.assertIsNotNone(caret._place)
        self.assertAlmostEqual(caret._place[0], box[0] - caret.tk_width // 2, delta=1)

    def test_held_backspace_keeps_up(self):
        b = self.nw.body
        b.insert("1.0", "s" * 40)
        b.mark_set("insert", "end-1c")
        b.focus_force()
        self.settle()
        self.held("BackSpace")
        self.assertEqual(len(b.get("1.0", "end-1c")), 40 - 12)
        self.assert_at_insert()

    def test_held_return_and_delete_keep_up(self):
        b = self.nw.body
        b.insert("1.0", "abc def ghi")
        b.mark_set("insert", "1.3")
        b.focus_force()
        self.settle()
        self.held("Return", n=3)
        self.assert_at_insert()
        self.held("Delete", n=3)
        self.assert_at_insert()


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
