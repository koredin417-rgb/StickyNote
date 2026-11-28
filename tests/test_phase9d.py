"""Phase 9, part D (2026-11-28): icons C (one size scale, one "on" chip) and Settings C (cards,
row icons, quick choices in the row). Spec: 2026-11-28-settings-icons-design.md."""
import tempfile
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
from texts import tr
from ui_common import (ICON_BOX, MIN_H, MIN_W, RAIL_ICON_BOX, SETTINGS_MIN_H, SETTINGS_MIN_W, SECTION_ICON_BOX, SMALL_ICON_BOX, TEXT_CONTRAST, PopupMenu,
                       chip_photo, contrast)
from geom import pad_box as _pad_box
from store import NoteStore
from ui_views import QUICK, SETTING_ICONS, card_colors


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.settle()

    def tearDown(self):
        PopupMenu.close_current()
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.3):
        pump(self.app, lambda: not self.app.motion.busy() and not self.app.clock.busy, timeout=3)
        pump(self.app, timeout=t)

    def click(self, w):
        w.event_generate("<ButtonRelease-1>", x=2, y=2)
        self.settle(0.1)


class IconScaleTest(Case):
    def test_sizes(self):
        self.assertEqual((RAIL_ICON_BOX, ICON_BOX, SMALL_ICON_BOX, SECTION_ICON_BOX), (16, 14, 12, 12))
        nw = self.nw
        for b in (nw.btn_memo, nw.btn_list, nw.btn_cal, nw.btn_pin, nw.btn_bold, nw.btn_more):
            self.assertEqual(b.box, RAIL_ICON_BOX)
        self.assertEqual(nw.btn_close.box, ICON_BOX)


class OnChipTest(Case):
    def chip_shown(self, b):
        photo = chip_photo(self.app, b.glyph, b._on_fg, b._on_bg, b.box)   # (on: the strong ink)
        return str(b.photo) == str(photo) and str(b.cget("bg")) == str(b._bg)

    def test_keep_on_top_shows_on(self):
        nw = self.nw
        self.assertFalse(nw.btn_pin.active)
        nw.toggle_pin()
        self.settle(0.1)
        self.assertTrue(nw.btn_pin.active)
        self.assertTrue(self.chip_shown(nw.btn_pin))
        nw.toggle_pin()
        self.settle(0.1)
        self.assertFalse(nw.btn_pin.active)

    def test_calendar_shows_on(self):
        nw = self.nw
        nw.toggle_calendar()
        self.settle()
        self.assertTrue(nw.btn_cal.active)
        self.assertTrue(self.chip_shown(nw.btn_cal))
        nw.toggle_calendar()
        self.settle()
        self.assertFalse(nw.btn_cal.active)

    def test_format_button_chip(self):
        nw = self.nw
        nw.body.focus_force()
        nw.body.insert("1.0", "굵게")
        nw.body.tag_add("sel", "1.0", "1.2")
        nw.toggle_format("b")
        self.settle(0.1)
        self.assertTrue(nw.btn_bold.active)
        self.assertTrue(self.chip_shown(nw.btn_bold))

    def test_chip_photo_cached(self):
        a = chip_photo(self.app, "", "#000000", "#DDDDDD", 14)
        self.assertIs(a, chip_photo(self.app, "", "#000000", "#DDDDDD", 14))

    def test_checked_menu_item_on_chip(self):
        nw = self.nw
        nw.toggle_pin()
        self.settle(0.1)
        menu = nw._note_menu(nw.win.winfo_rootx() + 40, nw.win.winfo_rooty() + 40)
        row = next(r for r, _t, item in menu.rows if item[0] == tr("menu_on_top"))
        mark, pic = row.winfo_children()[:2]
        self.assertEqual(str(mark.cget("text")), "")
        self.assertTrue(str(pic.cget("image")).startswith("pyimage"))
        self.assertEqual(getattr(pic, "chip", False), True)


class SettingsCardsTest(Case):
    def open(self):
        self.nw.show_settings()
        self.settle()
        return self.nw.settings_view

    def test_rows_on_cards_with_icons(self):
        sv, nw = self.open(), self.nw
        k = card_colors(nw.frame, nw.note.color, nw.colors.bg)
        self.assertEqual(len(sv.cards), 4)
        for key, (row, name, _value, _dot, _chev) in sv.list_rows.items():
            self.assertIn(row.master, [card for card, _strips in sv.cards], key)
            self.assertEqual(str(row.cget("bg")).upper(), k.rest.upper(), key)
            self.assertIn(key, SETTING_ICONS)
            self.assertTrue(str(sv.row_icons[key].cget("image")), key)
            self.assertGreaterEqual(contrast(nw.win, name.cget("fg"), name.cget("bg")), TEXT_CONTRAST - 0.01)

    def test_quick_choices_change_in_place(self):
        sv, prefs = self.open(), self.app.prefs
        for key in QUICK:
            self.assertNotIn(key, sv.pages, key)
        self.click(sv.motion_buttons["off"])
        self.assertEqual(prefs.motion, "off")
        self.click(sv.bin_buttons[30])
        self.assertEqual(prefs.bin_days, 30)
        self.click(sv.cursor_buttons["text"])
        self.assertEqual(prefs.cursor_color, "text")
        self.assertEqual(set(sv.lang_buttons), {"ko", "en"})
        self.assertIsNone(sv.opened)                    # nothing slid in

    def test_auto_layout_switch(self):
        sv, prefs = self.open(), self.app.prefs
        self.assertFalse(sv.auto_switch.on)
        self.click(sv.auto_switch)
        self.settle()
        self.assertTrue(prefs.auto_layout)
        self.assertTrue(sv.auto_switch.on)
        self.click(sv.auto_switch)
        self.settle()
        self.assertFalse(prefs.auto_layout)
        self.assertFalse(sv.auto_switch.on)

    def test_page_rows_still_open(self):
        sv = self.open()
        _row, name, *_ = sv.list_rows["set_font"]
        self.click(name)
        self.assertEqual(sv.opened, "set_font")

    def test_narrow_note_puts_the_choice_under_the_name(self):
        nw, px = self.nw, self.app.px
        sv = self.open()
        _row, name, *_ = sv.list_rows["set_language"]
        seg = sv.lang_buttons["ko"].master
        nw.win.geometry(f"{px(MIN_W)}x{px(400)}")     # (a screen too small for Settings' own size)
        self.settle()
        self.assertGreater(seg.winfo_rooty(), name.winfo_rooty() + name.winfo_height() // 2)
        nw.win.geometry(f"{px(420)}x{px(400)}")
        self.settle()
        self.assertLess(abs(seg.winfo_rooty() + seg.winfo_height() // 2
                            - (name.winfo_rooty() + name.winfo_height() // 2)), px(6))

    def test_quick_rows_say_what_they_do(self):
        sv = self.open()
        self.assertEqual(sv.list_rows["set_motion"][1].tooltip.text, tr("help_motion"))


class SettingsSizeTest(Case):
    """A small note opens Settings at SETTINGS_MIN_W x SETTINGS_MIN_H (the window only: its saved
    size and its place among the others stay), inside the screen, and is its size again after."""

    def small(self, x=200, y=200):
        nw, px = self.nw, self.app.px
        nw.set_size(px(MIN_W), px(MIN_H))
        self.settle()
        nw.win.geometry(f"+{x}+{y}")
        self.settle()
        return nw

    def box(self):
        w = self.nw.win
        return w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height()

    def test_grows_and_comes_back(self):
        nw, px = self.small(), self.app.px
        saved = _pad_box(nw.pad)
        nw.show_settings()
        self.settle()
        x, y, w, h = self.box()
        self.assertGreaterEqual(w, px(SETTINGS_MIN_W))
        self.assertGreaterEqual(h, px(SETTINGS_MIN_H))
        self.assertEqual((x, y), saved[:2])                 # (room to the right and below: grows there)
        self.assertEqual(_pad_box(nw.pad), saved)           # the saved size never changes
        self.app.save_now(force=True)
        pad = next(p for p in NoteStore(Path(self.tmp.name)).load().pads if p.id == nw.pad.id)
        self.assertEqual((pad.width, pad.height), (saved[2] - saved[0], saved[3] - saved[1]))
        nw.go_back()
        self.settle()
        self.assertEqual(self.box(), (saved[0], saved[1], saved[2] - saved[0], saved[3] - saved[1]))

    def test_big_note_stays(self):
        nw, px = self.nw, self.app.px
        nw.set_size(px(SETTINGS_MIN_W) + px(40), px(SETTINGS_MIN_H) + px(40))
        self.settle()
        before = self.box()
        nw.show_settings()
        self.settle()
        self.assertEqual(self.box(), before)

    def test_bottom_right_corner_grows_inward(self):
        px = self.app.px
        _l, _t, right, bottom = self.app.area_of((1900, 1000, 1910, 1010))   # where notes may be
        nw = self.small(right - px(MIN_W), bottom - px(MIN_H))
        before = self.box()
        nw.show_settings()
        self.settle()
        x, y, w, h = self.box()
        self.assertEqual((x + w, y + h), (before[0] + before[2], before[1] + before[3]))   # far edges stay
        self.assertLess((x, y), before[:2])
        self.assertGreaterEqual(w, px(SETTINGS_MIN_W))
        nw.show_home()
        self.settle()
        self.assertEqual(self.box(), before)

    def test_top_left_corner_grows_outward(self):
        left, top, right, _b = self.app.area_of((0, 0, 10, 10))
        nw = self.small(left, top)
        before = self.box()
        nw.show_settings()
        self.settle()
        x, y, w, h = self.box()
        self.assertEqual((x, y), before[:2])
        self.assertLessEqual(x + w, right)

    def test_leaving_by_any_page_restores(self):
        nw, px = self.small(), self.app.px
        for leave in (nw.show_list, nw.show_home):
            nw.show_settings()
            self.settle()
            leave()
            self.settle()
            self.assertEqual(self.box()[2:], (px(MIN_W), px(MIN_H)), leave.__name__)

    def test_folding_in_settings_restores(self):
        nw = self.small()
        nw.show_settings()
        self.settle()
        nw.toggle_collapse(instant=True)
        self.settle()
        self.assertEqual(self.box()[2], self.app.px(MIN_W))
        self.assertFalse(nw._wide)



class EmptyTitleTest(Case):
    """The user's idea (2026-11-28): "(빈 메모)" in the list reads as greyed out, not as a title."""

    def test_empty_memo_title_is_muted(self):
        from store import Note
        nw = self.nw
        empty = self.app.add_note(Note(body="", style="image", images=["gone.png"]))   # (pictures only)
        named = self.app.add_note(Note(body="장보기"))
        nw.show_list()
        self.settle()
        k = card_colors(nw.frame, empty.color, nw.colors.bg)

        def title_fg(note):
            _outer, card = nw.list_view.cards[note.id]
            row = card.winfo_children()[0]
            label = next(w for w in row.winfo_children() if w.winfo_class() == "Label" and str(w.cget("text")).strip())
            return str(label.cget("fg")).upper(), str(label.cget("text"))
        fg, text = title_fg(empty)
        self.assertEqual(text, tr("untitled"))
        self.assertEqual(fg, k.muted.upper())
        self.assertEqual(title_fg(named)[0], card_colors(nw.frame, named.color, nw.colors.bg).fg.upper())


class WideReviewTest(SettingsSizeTest):
    """The review of Settings' own size (2026-11-28): the bigger window never gets out of step."""

    def test_auto_layout_switch_in_settings(self):
        nw = self.small()
        nw.show_settings()
        self.settle()
        self.click(nw.settings_view.auto_switch)        # arrange() moves this very note
        self.settle(0.6)
        x0, y0, x1, y1 = _pad_box(nw.pad)
        if nw._wide:
            self.assertEqual(self.box(), tuple(nw._wide_box))
        else:
            self.assertEqual(self.box(), (x0, y0, x1 - x0, y1 - y0))
        self.click(nw.settings_view.auto_switch)
        self.settle(0.6)

    def test_a_click_keeps_it_wide(self):
        nw = self.small()
        nw.show_settings()
        self.settle()
        x, y = nw.row.winfo_rootx() + 30, nw.row.winfo_rooty() + 5
        nw.row.event_generate("<ButtonPress-1>", x=30, y=5, rootx=x, rooty=y)
        nw.row.event_generate("<ButtonRelease-1>", x=30, y=5, rootx=x, rooty=y)
        self.settle()
        self.assertTrue(nw._wide)

    def test_a_drag_keeps_it_wide(self):
        """The user: dragging a small note in Settings shrank the page. It moves as it is now, the
        pad under it, and Back puts the note where it was dragged."""
        nw = self.small()
        nw.show_settings()
        self.settle()
        wide = self.box()
        saved = _pad_box(nw.pad)
        x, y = nw.row.winfo_rootx() + 30, nw.row.winfo_rooty() + 5
        nw.row.event_generate("<ButtonPress-1>", x=30, y=5, rootx=x, rooty=y)
        for i in range(1, 7):
            nw.row.event_generate("<B1-Motion>", x=30 + 10 * i, y=5 + 6 * i,
                                  rootx=x + 10 * i, rooty=y + 6 * i, state=0x100)
            self.settle(0.03)
            self.assertTrue(nw._wide)
            self.assertEqual(self.box()[2:], wide[2:])          # never shrinks while it moves
        nw.row.event_generate("<ButtonRelease-1>", x=90, y=41, rootx=x + 60, rooty=y + 36)
        self.settle()
        self.assertTrue(nw._wide)
        self.assertEqual(self.box(), (wide[0] + 60, wide[1] + 36, *wide[2:]))
        self.assertEqual(_pad_box(nw.pad)[:2], (saved[0] + 60, saved[1] + 36))
        self.assertEqual(tuple(nw._wide_box), self.box())
        nw.go_back()
        self.settle()
        self.assertEqual(self.box(), (saved[0] + 60, saved[1] + 36, saved[2] - saved[0], saved[3] - saved[1]))

    def test_docked_calendar_keeps_it_wide(self):
        """The user's layout froze: with a docked calendar, a <Configure> came before the bigger
        size took, ended wide, and the pad saved Settings' size as its own."""
        nw = self.small(300, 200)
        nw.toggle_calendar()
        self.settle(0.6)
        self.assertIsNotNone(nw.calendar)
        saved = _pad_box(nw.pad)
        nw.show_settings()
        self.settle(0.6)
        self.assertTrue(nw._wide)
        self.assertEqual(self.box(), tuple(nw._wide_box))
        self.assertEqual(_pad_box(nw.pad), saved)
        nw.go_back()
        self.settle()
        self.assertEqual(self.box(), (saved[0], saved[1], saved[2] - saved[0], saved[3] - saved[1]))

    def test_expanding_its_calendar_keeps_it_wide(self):
        """The user: expanding the docked calendar while in Settings shrank the page."""
        nw = self.small(300, 200)
        nw.toggle_calendar()
        self.settle(0.6)
        saved = _pad_box(nw.pad)
        nw.show_settings()
        self.settle(0.6)
        self.assertTrue(nw._wide)
        wide = self.box()
        for _ in range(2):                              # big, then mini again
            nw.calendar.toggle_expand()
            self.settle(0.8)
            if _pad_box(nw.pad) == saved:               # (the note stayed: so does Settings' window)
                self.assertTrue(nw._wide)
                self.assertEqual(self.box(), wide)
            else:                                       # (it moved: big again once it is still)
                self.assertTrue(nw._wide)
                self.assertEqual(self.box()[2:], wide[2:])

    def test_folded_note_widens_after_unfolding(self):
        nw = self.small()
        nw.toggle_collapse(instant=True)
        self.settle()
        nw.show_settings()
        pump(self.app, lambda: nw._wide, timeout=3)          # (once the unfold is over: slower under load)
        self.settle()
        self.assertFalse(nw.pad.collapsed)
        self.assertTrue(nw._wide)
        self.assertGreaterEqual(self.box()[2], self.app.px(SETTINGS_MIN_W))

    def test_back_lays_the_note_out_for_its_size(self):
        nw = self.small()
        nw.show_settings()
        self.settle()
        sizes = []
        real = nw._sized
        nw._sized = lambda w, h=None: (sizes.append((w, h)), real(w, h))[1]
        nw.go_back()
        self.settle()
        x0, y0, x1, y1 = _pad_box(nw.pad)
        self.assertIn((x1 - x0, y1 - y0), sizes)


class ChipHoverTest(Case):
    def test_chip_stronger_under_hover(self):
        nw = self.nw
        nw.toggle_pin()
        self.settle(0.1)
        b = nw.btn_pin
        b._hover_to(True)
        self.assertEqual(str(b.photo), str(chip_photo(self.app, b.glyph, b._on_fg, b._on_hover, b.box)))
        b._hover_to(False)
        self.assertEqual(str(b.photo), str(chip_photo(self.app, b.glyph, b._on_fg, b._on_bg, b.box)))



class NoResizeInSettingsTest(Case):
    """The user (2026-11-28): Settings has its own size; the note is not resized there."""

    def test_no_grip_on_settings(self):
        nw = self.nw
        self.assertTrue(nw.grip.winfo_ismapped())
        nw.show_settings()
        self.settle()
        self.assertFalse(nw.grip.winfo_ismapped())
        nw.go_back()
        nw.show_home()
        self.settle()
        self.assertTrue(nw.grip.winfo_ismapped())
        nw.show_list()
        self.settle()
        self.assertTrue(nw.grip.winfo_ismapped())


if __name__ == "__main__":
    unittest.main()
