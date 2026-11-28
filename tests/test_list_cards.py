"""Phase 9, list cards (2026-11-28): title first, paper-lift depth, the current memo in its own
tone, and a tint-and-lift on hover and arrow keys (spec: 2026-11-28-list-cards-design.md)."""
import colorsys
import tempfile
import time
import tkinter as tk
import tkinter.font
import unittest
from pathlib import Path

from _support import close_app, make_app, pump
from store import Note
from texts import tr
from ui_common import PALETTE, PopupMenu, _rgb, contrast, luminance
from ui_views import card_colors

PAGE = "#FFF4A3"


class CardColorsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_every_palette_colour_has_a_visible_tint(self):
        import ui_views
        for name, color in PALETTE:
            k = card_colors(self.root, color, PAGE)
            if ui_views.CARD_HOVER == "D":       # (D: the fill stays; the ring in the mid tone shows it)
                self.assertGreaterEqual(contrast(self.root, k.rest, k.edge), 1.5, name)
            else:                                  # (A: half the step, calm; the lift shows it too)
                self.assertGreaterEqual(contrast(self.root, k.rest, k.lit), 1.05, name)

    def test_same_colour_as_page_still_shows(self):
        self.assertNotEqual(card_colors(self.root, PAGE, PAGE).rest.upper(), PAGE)

    def test_label_and_footer_read(self):
        for name, color in PALETTE:
            k = card_colors(self.root, color, PAGE)
            self.assertGreaterEqual(contrast(self.root, k.label, k.lit), 4.5, name)
            self.assertGreaterEqual(contrast(self.root, k.muted, k.lit), 4.5, name)

    def test_edge_keeps_the_hue(self):
        k = card_colors(self.root, "#CFE6FF", PAGE)
        hue = lambda c: colorsys.rgb_to_hls(*_rgb(self.root, c))[0]
        self.assertLess(abs(hue(k.edge) - hue("#CFE6FF")), 0.05)

    def test_charcoal(self):
        k = card_colors(self.root, "#2E2E2E", "#2E2E2E")
        self.assertGreater(luminance(self.root, k.edge), luminance(self.root, k.rest))
        self.assertLess(luminance(self.root, k.rest_strips[0]), luminance(self.root, "#2E2E2E"))

    def test_ramp_ends(self):
        k = card_colors(self.root, "#FFD6E7", PAGE)
        self.assertEqual(len(k.ramp), 6)
        self.assertEqual(k.ramp[0], (k.rest, k.rest_strips))
        self.assertEqual(k.ramp[5], (k.lit, k.lit_strips))
        self.assertEqual(k.rest_strips[3], PAGE)


class ListCase(unittest.TestCase):
    memos = (("이번 주 할 일", "☐ 회의록 보내기\n☑ 장보기", "#FFF4A3"),
             ("장보기 목록", "우유, 달걀", "#FFE0B8"))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.tmp.name))
        pump(self.app, lambda: len(self.app.windows) == 1)
        self.nw = next(iter(self.app.windows.values()))
        self.fill(self.nw, "아이디어", "프레임 타이머 하나로 정리")     # (an empty memo is not listed)
        self.others = [self.app.add_note(Note(header=h, body=b, color=c, style="header"))
                       for h, b, c in self.memos]
        self.nw.show_list()
        self.settle(0.7)        # (past the 400 ms autosave after fill(): it refreshes the list once)
        self.lv = self.nw.list_view

    def tearDown(self):
        PopupMenu.close_current()
        close_app(self.app)
        self.tmp.cleanup()

    def settle(self, t=0.3):
        pump(self.app, lambda: not self.app.motion.busy() and not self.app.clock.busy, timeout=3)
        pump(self.app, timeout=t)

    @staticmethod
    def fill(nw, header, body):
        nw.set_style("header")
        nw.header_var.set(header)
        nw.body.delete("1.0", "end")
        nw.body.insert("1.0", body)
        nw.sync_from_widgets()

    def card(self, note):
        return self.lv.cards[note.id]

    def labels(self, widget):
        out = []
        for w in widget.winfo_children():
            if w.winfo_class() == "Label":
                out.append(w)
            out.extend(self.labels(w))
        return out


class CardLookTest(ListCase):
    def test_no_border_or_band(self):
        outer, card = self.card(self.others[0])
        page = self.nw.colors.bg
        self.assertEqual(outer.cget("bg"), page)
        rest = card.lifts.colors.rest

        def frames(w):
            for ch in w.winfo_children():
                if ch.winfo_class() == "Frame":
                    yield ch
                    yield from frames(ch)
        for f in frames(card):
            if f is not card.lifts.edge:
                self.assertEqual(f.cget("bg"), rest)

    def test_current_has_own_tone_edge(self):
        _, cur = self.card(self.nw.note)
        self.assertIsNotNone(cur.lifts.edge)
        self.assertEqual(cur.lifts.edge.cget("bg"), cur.lifts.colors.edge)
        self.assertIsNone(self.card(self.others[0])[1].lifts.edge)

    def test_four_shadow_strips(self):
        _, card = self.card(self.others[0])
        self.assertEqual(len(card.lifts.strips), 4)
        self.assertEqual(tuple(s.cget("bg") for s in card.lifts.strips), card.lifts.colors.rest_strips)

    def test_lift_keeps_height(self):
        outer, card = self.card(self.others[0])
        self.app.root.update_idletasks()
        h0 = outer.winfo_reqheight()
        card.lifts.set(5)
        self.app.root.update_idletasks()
        self.assertEqual(outer.winfo_reqheight(), h0)
        card.lifts.set(0)
        self.app.root.update_idletasks()
        self.assertEqual(outer.winfo_reqheight(), h0)

    def test_done_todo_is_struck(self):
        _, card = self.card(self.others[0])
        done = [w for w in self.labels(card) if "장보기" in str(w.cget("text"))]
        self.assertTrue(done)
        font = tk.font.Font(font=done[0].cget("font"))
        self.assertTrue(font.actual("overstrike"))
        self.assertEqual(done[0].cget("fg"), card.lifts.colors.muted)

    def test_title_one_line(self):
        long = self.app.add_note(Note(header="긴 제목 " * 40, body="x", style="header"))
        self.lv.refresh()
        self.settle()
        _, card = self.card(long)
        title = card.lifts.title
        self.assertTrue(str(title.cget("text")).endswith("…"))
        self.assertNotIn("\n", str(title.cget("text")))
        self.assertLess(title.winfo_reqheight(), 2 * tk.font.Font(font=title.cget("font")).metrics("linespace"))

    def test_pin_sits_left_of_the_trash(self):
        self.app.prefs.pin_limit = self.app.prefs.pin_limit or 5
        self.lv.refresh()
        self.settle()
        outer, card = self.card(self.others[0])
        card.lifts.set(5)
        self.app.root.update_idletasks()
        pin, trash = self.lv.pin_icons[self.others[0].id], self.lv.bin_icons[outer]
        self.assertLess(pin.winfo_x(), trash.winfo_x())

    def test_new_note_colour_repaints_the_cards(self):
        self.nw.set_color("#2E2E2E")
        self.settle()
        outer, card = self.card(self.others[0])
        self.assertEqual(outer.cget("bg").upper(), self.nw.colors.bg.upper())
        _, cur = self.card(self.nw.note)
        self.assertEqual(cur.lifts.colors.rest, card_colors(self.app.root, "#2E2E2E", self.nw.colors.bg).rest)

    def test_open_elsewhere_wording(self):
        import texts
        self.assertEqual(texts.TEXTS["open_elsewhere"], ("다른 창에 열림", "Open in another window"))

    def test_opening_a_memo_does_not_rebuild_the_list(self):     # (review: 150-250 ms per click)
        calls = []
        orig = self.lv.refresh
        self.lv.refresh = lambda: (calls.append(1), orig())
        self.nw.open_note(self.others[1])
        self.settle()
        self.assertEqual(calls, [])

    def test_trash_is_red_when_reached_first(self):              # (review: the lift painted it grey)
        from ui_common import GLYPH, SMALL_ICON_BOX
        outer, card = self.card(self.others[0])
        trash = self.lv.bin_icons[outer]
        card.event_generate("<Enter>")
        trash.event_generate("<Enter>")
        self.settle()
        hover = [h for lb, _g, _c, h, _a in card.lifts.icons if lb is trash][0]
        want = self.app.icons.photo(GLYPH["trash"], hover, self.app.px(SMALL_ICON_BOX))
        self.assertEqual(str(trash.cget("image")), str(want))

    def test_open_elsewhere_words(self):
        other = self.app.new_window(from_window=self.nw)
        self.settle()
        self.fill(other, "다른 창", "본문")
        self.lv.refresh()
        self.settle()
        _, card = self.card(other.note)
        self.assertIn(tr("open_elsewhere"), [str(w.cget("text")) for w in self.labels(card)])


class CardMotionTest(ListCase):
    def first_frames(self, card=None):
        """Run Tk until the card's lift has taken its first step (or 0.3 s)."""
        card = card or self.card(self.others[0])[1]
        end = time.perf_counter() + 0.3
        while card.lifts.level == 0 and time.perf_counter() < end:
            self.app.root.update()

    def enter(self, note):
        outer, card = self.card(note)
        card.event_generate("<Enter>")

    def leave(self, note):
        outer, card = self.card(note)
        card.event_generate("<Leave>", rootx=0, rooty=0)

    def test_hover_lifts_through_the_ramp(self):
        note = self.others[0]
        _, card = self.card(note)
        self.enter(note)
        self.first_frames(card)
        self.assertIn(card.lifts.level, range(1, 5))
        self.settle()
        self.assertEqual(card.lifts.level, 5)
        self.assertEqual(card.cget("bg"), card.lifts.colors.lit)
        self.assertTrue(card.lifts.icons_shown)

    def test_leave_returns_to_rest(self):
        note = self.others[0]
        _, card = self.card(note)
        self.enter(note)
        self.settle()
        self.leave(note)
        self.settle()
        self.assertEqual(card.lifts.level, 0)
        self.assertEqual(card.cget("bg"), card.lifts.colors.rest)
        self.assertFalse(card.lifts.icons_shown)

    def test_quick_in_and_out_reverses(self):
        note = self.others[0]
        _, card = self.card(note)
        seen = []
        orig = card.lifts.set
        card.lifts.set = lambda level: (seen.append(level), orig(level))
        self.enter(note)
        self.first_frames()
        self.leave(note)
        self.settle()
        self.assertEqual(card.lifts.level, 0)
        self.assertNotIn(5, seen)

    def test_arrow_pick_lifts(self):
        self.lv.step_pick(1)
        self.settle()
        ids = self.lv.shown_ids()
        first = self.lv.cards[ids[0]][1]
        self.assertEqual(first.lifts.level, 5)
        self.lv.step_pick(1)
        self.settle()
        self.assertEqual(first.lifts.level, 0)
        self.assertEqual(self.lv.cards[ids[1]][1].lifts.level, 5)

    def test_off_is_instant(self):
        self.app.set_motion("off")
        note = self.others[0]
        _, card = self.card(note)
        self.enter(note)
        self.first_frames()
        self.assertEqual(card.lifts.level, 5)

    def test_picked_card_built_later_is_lit(self):
        for i in range(60):
            self.app.add_note(Note(header=f"메모 {i}", body="본문 " * 6, style="header"))
        self.lv.refresh()
        self.settle()
        for _ in range(40):
            self.lv.step_pick(1)
        self.settle()
        picked = self.lv._picked
        self.assertIn(picked, self.lv.cards)
        self.assertEqual(self.lv.cards[picked][1].lifts.level, 5)


if __name__ == "__main__":
    unittest.main()
