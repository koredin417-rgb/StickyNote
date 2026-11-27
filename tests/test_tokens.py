import unittest

import _support  # noqa: F401  (DPI setup, app path)
import ui_common as u
import ui_note as n
import ui_views as v


class TokenTest(unittest.TestCase):
    def test_durations_on_tokens(self):
        fast = ("TIP_FADE_MS", "MENU_FADE_MS", "HOVER_FADE_MS", "CHIP_SETTLE_MS", "VIEW_DIP_MS", "CLOSE_FADE_MS")
        base = ("CAL_SHOW_MS", "ROLL_MS", "DOCK_SLIDE_MS", "TOAST_RISE_MS", "HINT_DROP_MS", "PEEK_DROP_MS",
                "PICTURE_FADE_MS", "DONE_FADE_MS")
        long_ = ("GLIDE_MS", "NEW_SLIDE_MS", "MONTH_SLIDE_MS", "SCROLL_FADE_MS", "DELETE_FLY_MS")
        self.assertEqual({getattr(u, k) for k in fast} | {n.STICKER_FADE_MS}, {120})
        self.assertEqual({getattr(u, k) for k in base}, {180})
        self.assertEqual({getattr(u, k) for k in long_} | {v.SETTING_SLIDE_MS}, {240})
        self.assertEqual((u.OPEN_FADE_MS, u.FLASH_MS), (160, 400))      # (Phase 8, B7: open 160, close 120)
        self.assertFalse(hasattr(u, "_ease_out_sine"))


if __name__ == "__main__":
    unittest.main()
