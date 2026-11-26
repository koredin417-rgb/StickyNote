"""Phase 6, Task 4: the taskbar thumbnail from reduced shots; the picture cache's byte budget;
bounded per-setup data and closed list."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import winapi
from _support import Spy, close_app, make_app, patched, pump


class BoundedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.nw.close_hints()
        pump(self.app, timeout=0.3)

    def tearDown(self):
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self):
        pump(self.app, lambda: not self.app.motion.busy(), timeout=2)
        pump(self.app, timeout=0.2)

    def test_thumbnail_never_full_size(self):
        last = self.nw
        for _ in range(5):
            last = self.app.new_window(from_window=last)
            self.settle()
        sizes = []
        real_new = Image.new

        def new(mode, size, *a, **k):
            sizes.append(tuple(size))
            return real_new(mode, size, *a, **k)
        with patched(Image, "new", new), \
                patched(winapi, "set_iconic_thumbnail", Spy(wraps=lambda win, pic: 0)) as sent:
            self.app._send_thumbnail((200, 120))
        self.assertEqual(sent.call_count, 1)
        pic = sent.calls[0][0][1]
        self.assertLessEqual(pic.width, 200)
        self.assertLessEqual(pic.height, 120)
        tops = self.app._thumb_windows()             # one window's own picture at a time, at most
        one = max(t.winfo_width() * t.winfo_height() for t in tops)
        x0 = min(t.winfo_rootx() for t in tops)
        x1 = max(t.winfo_rootx() + t.winfo_width() for t in tops)
        y0 = min(t.winfo_rooty() for t in tops)
        y1 = max(t.winfo_rooty() + t.winfo_height() for t in tops)
        for w, h in sizes:
            self.assertLessEqual(w * h, max(one, 200 * 120), sizes)
        self.assertLess(max(w * h for w, h in sizes) * 4, 4 * 1024 * 1024)       # the peak: under 4 MB
        self.assertNotIn((x1 - x0, y1 - y0), sizes)  # never the whole desktop at full size

    def test_picture_cache_budget(self):
        import app as app_module
        budget = app_module.PICTURE_BUDGET
        store = self.app.store
        names = [store.add_image(Image.new("RGB", (1000, 1000), (i, 50, 90))) for i in range(30)]
        for name in names:
            self.app.picture(name, (1000, 1000))
        self.assertLessEqual(self.app._picture_bytes, budget)
        self.assertEqual(self.app._picture_bytes,
                         sum(p.width() * p.height() * 4 for p in self.app._pictures.values()))

    def test_setups_pruned_to_eight(self):
        pad, prefs = self.nw.pad, self.app.prefs
        for i in range(12):
            key = f"test-setup-{i}"
            self.app._stamp(pad, key)
            self.app._remember_setup(key)
        for d in (pad.setups, pad.calendar_setups, prefs.setup_scales):
            kept = [k for k in d if k.startswith("test-setup-")]
            self.assertEqual(kept, [f"test-setup-{i}" for i in range(4, 12)], d.keys())

    def test_closed_list_bounded(self):
        for i in range(30):
            nw = self.app.new_window(from_window=self.nw)
            nw.body.insert("1.0", f"닫힐 메모 {i}")
            nw.sync_from_widgets()
            self.settle()
            self.app.close_window(nw)
            pump(self.app, lambda: not nw.win.winfo_exists(), timeout=2)
        self.assertLessEqual(len(self.app._closed), 20)


if __name__ == "__main__":
    unittest.main()
