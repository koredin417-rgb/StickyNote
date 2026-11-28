"""Backlog item 5 (2026-11-28): the first start. The screen dims, the language comes first, then a
welcome memo whose to-do ("시작합니다. 박스를 체크해 주세요") starts a five-stop tour; skippable at
every step; again from Settings. Spec: 2026-11-28-first-start-design.md."""
import json
import tempfile
import unittest
from pathlib import Path

import texts
from _support import close_app, make_app, pump
from texts import tr
from tour import STOPS
from ui_common import TODO


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name), tour=True)
        pump(self.app, lambda: getattr(self.app, "tour", None) is not None, timeout=3)
        self.tour = self.app.tour

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.3):
        pump(self.app, lambda: not self.app.motion.busy() and not self.app.clock.busy, timeout=3)
        pump(self.app, timeout=t)

    def nw(self):
        return next(iter(self.app.windows.values()))

    def to_tour(self):
        self.tour.choose_language("ko")
        self.settle()
        nw = self.nw()
        nw.set_done(1, True)
        self.settle()


class StartTest(Case):
    def test_new_user_gets_the_language_first(self):
        self.assertIsNotNone(self.tour)
        self.assertEqual(self.tour.step, "language")
        self.assertTrue(self.tour.dim.winfo_ismapped())
        self.assertTrue(self.tour.card.winfo_ismapped())

    def test_language_then_the_welcome_memo(self):
        self.tour.choose_language("en")
        self.settle()
        self.assertEqual(texts.language(), "en")
        self.assertEqual(self.tour.step, "welcome")
        nw = self.nw()
        self.assertIn(tr("welcome_todo"), nw.body.get("1.0", "end"))
        self.assertEqual(nw._line_mark(1), TODO)                       # (a to-do line)
        texts.set_language("ko")

    def test_ticking_starts_the_tour(self):
        self.to_tour()
        self.assertEqual(self.tour.step, 1)
        self.assertEqual(len(STOPS), 5)

    def test_through_every_stop(self):
        self.to_tour()
        for i in range(1, 6):
            self.assertEqual(self.tour.step, i)
            self.tour.next()
            self.settle(0.1)
        self.assertIsNone(self.app.tour)
        self.assertTrue(self.app.prefs.tour_done)

    def test_hole_over_each_stop(self):
        self.to_tour()
        t = self.tour
        for i in range(1, 6):
            self.settle(0.3)
            want = t.target_box(i)
            got = t.hole
            self.assertIsNotNone(got)
            self.assertLessEqual(abs(got[0] - want[0]), self.app.px(10))
            self.assertLessEqual(abs(got[1] - want[1]), self.app.px(10))
            t.next()

    def test_skip_at_any_step(self):
        for where in ("language", "welcome", 3):
            if where == "welcome":
                self.tour.choose_language("ko")
                self.settle()
            elif where == 3:
                self.nw().set_done(1, True)
                self.settle()
                self.tour.next()
                self.tour.next()
            self.assertIsNotNone(self.app.tour)
            break
        self.app.tour.skip()
        self.settle()
        self.assertIsNone(self.app.tour)
        self.assertTrue(self.app.prefs.tour_done)

    def test_escape_skips(self):
        self.tour.card.focus_force()
        pump(self.app, timeout=0.05)
        self.tour.card.event_generate("<Escape>")
        self.settle()
        self.assertIsNone(self.app.tour)

    def test_rail_shows_during_the_tour(self):
        self.to_tour()
        self.assertTrue(self.nw().rail_calm._busy())


class NotTwiceTest(unittest.TestCase):
    def test_updating_users_get_no_tour(self):
        tmp = tempfile.TemporaryDirectory()
        folder = Path(tmp.name)
        (folder / "notes.json").write_text(json.dumps({"version": 3, "notes": [], "pads": [], "prefs": {}}),
                                           encoding="utf-8")
        app = make_app(folder, tour=True)
        try:
            pump(app, timeout=1.0)
            self.assertIsNone(getattr(app, "tour", None))
        finally:
            close_app(app)
            tmp.cleanup()

    def test_replay_from_settings(self):
        tmp = tempfile.TemporaryDirectory()
        app = make_app(Path(tmp.name))
        try:
            pump(app, lambda: len(app.windows) == 1)
            nw = next(iter(app.windows.values()))
            nw.show_settings()
            pump(app, timeout=0.3)
            self.assertIn("set_tour", nw.settings_view.list_rows)
            nw.settings_view.open("set_tour")
            pump(app, timeout=0.3)
            self.assertIsNotNone(app.tour)
            self.assertEqual(app.tour.step, 1)                      # (no language, no welcome memo)
            app.tour.skip()
        finally:
            close_app(app)
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
