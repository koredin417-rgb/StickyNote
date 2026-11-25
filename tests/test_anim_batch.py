import time
import tkinter as tk
import unittest

import _support  # noqa: F401  (DPI setup, app path)
import anim


class BatchTest(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.clock = anim.install(self.root)
        self.a, self.b = tk.Toplevel(self.root), tk.Toplevel(self.root)
        for w in (self.a, self.b):
            w.overrideredirect(True)
            w.geometry("120x90+100+100")
        self.root.update()

    def tearDown(self):
        anim.BATCH_MOVES = True
        self.clock.close()
        self.root.destroy()

    def frame(self, n=5):
        for _ in range(n):
            self.root.update()
            time.sleep(0.01)

    def test_moves_land_in_same_flush(self):
        self.clock.move(self.a, 300, 200)
        self.clock.move(self.b, 430, 200)
        self.frame()
        self.assertEqual((self.a.winfo_rootx(), self.b.winfo_rootx()), (300, 430))

    def test_last_move_per_window_wins(self):
        self.clock.move(self.a, 300, 200)
        self.clock.move(self.a, 310, 210)
        self.frame()
        self.assertEqual((self.a.winfo_rootx(), self.a.winfo_rooty()), (310, 210))

    def test_glide_lands_and_reports_box(self):
        self.clock.glide(self.a, (500, 300, 620, 390), 120)
        self.frame(40)
        self.assertEqual((self.a.winfo_rootx(), self.a.winfo_rooty()), (500, 300))
        self.assertEqual(self.clock.box_now(self.a), (500, 300, 620, 390))

    def test_sized_glide_resizes(self):
        self.clock.glide(self.a, (200, 200, 400, 360), 60, sized=True)
        self.frame(20)
        self.assertEqual((self.a.winfo_width(), self.a.winfo_height()), (200, 160))

    def test_write_extra_sees_each_box(self):
        seen = []
        self.clock.glide(self.a, (300, 100, 420, 190), 60, write_extra=seen.append)
        self.frame(20)
        self.assertEqual(seen[-1], (300, 100, 420, 190))

    def test_batch_off_uses_geometry(self):
        anim.BATCH_MOVES = False
        self.clock.move(self.a, 222, 111, 150, 100)
        self.frame()
        self.assertEqual((self.a.winfo_rootx(), self.a.winfo_rooty(), self.a.winfo_width()), (222, 111, 150))

    def test_destroyed_window_skipped(self):
        self.clock.move(self.b, 300, 300)
        self.b.destroy()
        self.frame()                                      # no TclError


if __name__ == "__main__":
    unittest.main()
