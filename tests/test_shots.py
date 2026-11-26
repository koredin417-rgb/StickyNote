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


class WarmTest(ShotsTest):
    """Pictures are never taken ahead while a drag or resize runs."""

    test_shot_reused_until_changed = test_shot_dropped_on_close = None
    test_freeze_uses_cache = test_linked_notes_warm_when_idle = None

    def test_no_warming_mid_gesture(self):
        a = self.nw
        b = self.app.new_window(a)
        self.settle()
        shots = self.app.shots
        shots._stale |= {a.pad.id, b.pad.id}
        self.app.moving = True
        try:
            with patched(winapi, "snapshot", Spy(wraps=winapi.snapshot)) as spy:
                shots._warm()
                shots._again()
                self.assertEqual(spy.call_count, 0)
        finally:
            self.app.moving = False
        pump(self.app, lambda: shots.peek(a) is not None and shots.peek(b) is not None, timeout=6)
        self.assertIsNotNone(shots.peek(b))


class FlyTest(ShotsTest):
    """Task 5: the delete fly is cut from the note's picture and pastes into one PhotoImage."""

    test_shot_reused_until_changed = test_shot_dropped_on_close = None
    test_freeze_uses_cache = test_linked_notes_warm_when_idle = None

    def test_fly_reuses_one_photo(self):
        from PIL import ImageGrab
        nw = self.nw
        nw.body.insert("1.0", "지울 메모")
        nw.sync_from_widgets()
        with patched(ImageGrab, "grab", Spy(raises=RuntimeError("no screen grab"))):
            nw.trash_current()
            cv = nw._fly_canvas
            photos = set()
            for _ in range(15):
                if not cv.winfo_exists():
                    break
                self.app.root.update()
                if cv.winfo_exists():
                    photos.add(id(cv._photo))
                pump(self.app, timeout=0.012)
        self.assertEqual(len(photos), 1)


def close_to(a, b, share=0.01):
    """Two pictures alike: under ``share`` of their pixels differ visibly (a blinking caret may)."""
    from PIL import ImageChops
    if a is None or b is None or a.size != b.size:
        return False
    hist = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L").histogram()
    return sum(hist[24:]) <= share * a.size[0] * a.size[1]


def mostly_black(img):
    hist = img.convert("L").histogram()
    return sum(hist[:16]) > 0.5 * img.size[0] * img.size[1]


class RollPictureTest(ShotsTest):
    """Review fix: rolls use only pictures of a painted note; never one taken at alpha 0."""

    test_shot_reused_until_changed = test_shot_dropped_on_close = None
    test_freeze_uses_cache = test_linked_notes_warm_when_idle = None

    def fill(self):
        nw = self.nw
        nw.set_style("header")
        nw.header_var.set("접기 시험")
        nw.body.insert("1.0", "첫째 줄\n둘째 줄\n셋째 줄")
        nw.sync_from_widgets()
        nw.win.focus_force()                    # (no blinking caret in the pictures)
        self.settle(0.4)
        nw.close_hints()                        # (the first-start tips come back after a while)
        self.settle(0.2)

    def test_fold_all_then_unfold_rolls_the_painted_picture(self):
        import shots
        nw = self.nw
        self.fill()
        before = shots.capture(nw.win)
        self.app.fold_all(True)
        self.settle()
        kept = nw._kept_shot(nw.pad.height)
        self.assertTrue(close_to(kept, before), "the picture kept at the fold is not the note as it showed")
        nw.toggle_collapse()
        cover = getattr(nw, "_rolling_cover", None)
        self.assertIsNotNone(cover)
        pump(self.app, lambda: not nw.rolling, timeout=2)
        self.settle()
        self.assertTrue(close_to(shots.capture(nw.win), before))

    def test_unfold_with_stale_picture_rolls_live(self):
        import shots
        nw = self.nw
        self.fill()
        nw.toggle_collapse(instant=True)
        self.settle()
        nw.body.insert("1.0", "접힌 동안 바뀐 글\n")
        nw.sync_from_widgets()
        with patched(shots, "capture", Spy(wraps=shots.capture)) as spy:
            nw.toggle_collapse()
            self.assertIsNone(getattr(nw, "_rolling_cover", None))     # the widgets roll, as before
            self.assertEqual(spy.call_count, 0)                         # nothing photographed unpainted
        pump(self.app, lambda: not nw.rolling, timeout=2)
        self.settle()
        self.assertAlmostEqual(float(nw.win.attributes("-alpha")), nw.pad.alpha, places=2)
        kept = self.app.shots.peek(nw)
        if kept is not None:
            self.assertFalse(mostly_black(kept))
            self.assertTrue(close_to(kept, shots.capture(nw.win)))

    def test_restore_after_colour_change_rolls_live(self):
        nw = self.nw
        self.fill()
        nw.minimize(animate=False)
        pump(self.app, timeout=0.2)
        nw.set_color("#CFE6FF")
        nw.restore()
        self.assertIsNone(getattr(nw, "_rolling_cover", None))
        pump(self.app, lambda: not nw.rolling, timeout=2)
        self.settle()
        self.assertEqual(nw.win.winfo_height(), nw.pad.height)
        self.assertAlmostEqual(float(nw.win.attributes("-alpha")), nw.pad.alpha, places=2)

    def test_fold_and_fly_take_fresh_pictures(self):
        import shots
        nw = self.nw
        self.fill()
        self.app.shots.shot(nw)                         # a picture is kept ...
        with patched(shots, "capture", Spy(wraps=shots.capture)) as spy:
            nw.toggle_collapse()                        # ... but a fold photographs it afresh
            self.assertEqual(spy.call_count, 1)
        pump(self.app, lambda: not nw.rolling, timeout=2)
        self.settle()


class StaleLookTest(ShotsTest):
    """Review fix: what changes a note's look marks its picture stale; what does not, does not."""

    test_shot_reused_until_changed = test_shot_dropped_on_close = None
    test_freeze_uses_cache = test_linked_notes_warm_when_idle = None

    def test_zoom_marks_stale(self):
        from PIL import Image
        nw = self.nw
        nw.set_style("image")
        nw.add_image(Image.new("RGB", (1600, 1200), "#3366AA"))
        self.settle()
        self.app.shots.shot(nw)
        nw.viewer.zoom_at(40, 40, 2.0)
        pump(self.app, timeout=0.1)
        self.assertIsNone(self.app.shots.peek(nw))

    def test_list_page_never_reused(self):
        nw = self.nw
        nw.show_list()
        pump(self.app, timeout=0.2)
        self.app.shots.shot(nw)
        self.assertIsNone(self.app.shots.peek(nw))

    def test_caret_move_keeps_the_picture(self):
        nw = self.nw
        nw.body.insert("1.0", "가나다 라마바")
        nw.sync_from_widgets()
        self.settle()
        v = nw.look_version
        nw.body.mark_set("insert", "1.2")
        nw._update_format_buttons()
        nw.body.mark_set("insert", "1.4")
        nw._update_format_buttons()
        self.assertEqual(nw.look_version, v)


if __name__ == "__main__":
    unittest.main()
