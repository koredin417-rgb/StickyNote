"""Settings → General → Update: the page, its texts, and what the app shows after an update."""
import gc
import json
import tempfile
import tkinter as tk
import unittest
import weakref
from pathlib import Path

from _support import Spy, close_app, make_app, pump
import texts
import ui_views
import updater
import version
from texts import tr


def reply(tag="v9.0.0") -> bytes:
    return json.dumps({"tag_name": tag, "body": "## New\n* faster drag", "draft": False,
                       "assets": [{"name": "StickyNote.zip", "browser_download_url": "https://example.test/z",
                                   "size": 10, "digest": None}]}).encode()


def shown_texts(widget) -> list[str]:
    """The text of every label and button on show under ``widget``."""
    out = []
    for w in widget.winfo_children():
        if not w.winfo_manager():
            continue
        try:
            text = w.cget("text")
        except tk.TclError:
            text = ""
        if text:
            out.append(text)
        out += shown_texts(w)
    return out


class UpdateSettingsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.install_dir = self.folder / "Programs" / "StickyNote"
        self.app = None

    def tearDown(self):
        if self.app is not None:
            close_app(self.app)
        self._tmp.cleanup()

    def start(self, installed=True):
        self.app = make_app(self.folder)
        pump(self.app, lambda: len(self.app.windows) == 1)
        app_dir = self.install_dir / "app" if installed else self.folder / "repo" / "StickyNote" / "app"
        self.get = Spy(wraps=lambda url, headers: reply())
        self.app.updater = updater.Updater(app_dir, get=self.get, download=Spy(), popen=Spy(),
                                           temp_dir=self.folder / "temp", install_dir=self.install_dir)
        return next(iter(self.app.windows.values()))

    def open_page(self, nw):
        nw.show_settings()
        pump(self.app, timeout=0.3)
        sv = nw.settings_view
        sv.open("set_update")
        pump(self.app, timeout=0.4)
        return sv

    def press(self, button):
        button.event_generate("<ButtonRelease-1>", x=2, y=2)

    def check(self, sv):
        self.press(sv.update_check)
        self.assertTrue(pump(self.app, lambda: self.app.updater.state == "available", timeout=2))
        pump(self.app, timeout=0.1)

    def test_update_row_in_general(self):
        self.assertEqual(dict(ui_views.SETTING_GROUPS)["grp_general"][-1], "set_update")
        self.assertEqual(ui_views.SETTING_HELP["set_update"], "help_update")
        nw = self.start()
        nw.show_settings()
        pump(self.app, timeout=0.2)
        self.assertEqual(nw.settings_view.list_rows["set_update"][2].cget("text"), f"v{version.VERSION}")
        self.assertEqual(version.VERSION, "1.2.3")

    def test_check_shows_new_version(self):
        sv = self.open_page(self.start())
        page = sv.pages["set_update"]
        self.assertIn(tr("upd_installed", v=version.VERSION), shown_texts(page))
        self.check(sv)
        shown = shown_texts(page)
        self.assertIn(tr("upd_new", v="9.0.0"), shown)
        self.assertIn("New\n• faster drag", shown)
        self.assertIn(tr("upd_now"), shown)
        self.assertIn(tr("upd_later"), shown)
        self.press(sv.update_later)                     # Not now: the offer goes
        pump(self.app, timeout=0.1)
        self.assertEqual(self.app.updater.state, "idle")
        self.assertNotIn(tr("upd_now"), shown_texts(page))

    def test_update_now_hidden_elsewhere(self):
        sv = self.open_page(self.start(installed=False))
        self.check(sv)
        shown = shown_texts(sv.pages["set_update"])
        self.assertNotIn(tr("upd_now"), shown)
        self.assertIn(tr("upd_elsewhere"), shown)

    def test_two_settings_pages_share_state(self):
        first = self.start()
        second = self.app.new_window(from_window=first)
        pump(self.app, timeout=0.3)
        a, b = self.open_page(first), self.open_page(second)
        self.check(a)
        for sv in (a, b):
            self.assertIn(tr("upd_new", v="9.0.0"), shown_texts(sv.pages["set_update"]))
        self.assertEqual(self.get.call_count, 1)

    def test_long_notes_cut_at_twelve_lines(self):
        nw = self.start()
        body = json.loads(reply())
        body["body"] = "\n".join(f"line {i}" for i in range(20))
        self.get.wraps = lambda url, headers: json.dumps(body).encode()
        sv = self.open_page(nw)
        self.check(sv)
        notes = sv.update_notes.cget("text").split("\n")
        self.assertEqual(notes[:12], [f"line {i}" for i in range(12)])
        self.assertEqual(notes[12:], ["…"])

    def test_closed_window_drops_its_listener(self):
        first = self.start()
        second = self.app.new_window(from_window=first)
        pump(self.app, timeout=0.3)
        self.open_page(second)
        self.assertEqual(len(self.app.updater.listeners), 1)
        ref = weakref.ref(second)
        self.app.close_window(second)
        del second
        pump(self.app, lambda: len(self.app.windows) == 1, timeout=2)
        pump(self.app, timeout=0.3)
        gc.collect()
        self.assertEqual(self.app.updater.listeners, [])
        self.assertIsNone(ref())

    def test_startup_result_notice(self):
        (self.folder / "update-result.json").write_text('{"version": "9.0.0", "ok": true, "error": ""}', "utf-8")
        nw = self.start()
        pump(self.app, lambda: nw.toast_text.cget("text") == tr("upd_done", v="9.0.0"), timeout=2)
        self.assertEqual(nw.toast_text.cget("text"), tr("upd_done", v="9.0.0"))
        self.assertFalse((self.folder / "update-result.json").exists())

    def test_startup_failed_result(self):
        (self.folder / "update-result.json").write_text('{"version": "9.0.0", "ok": false, "error": "disk"}', "utf-8")
        self.app = make_app(self.folder)                # (its own Updater: it holds the failure)
        pump(self.app, lambda: len(self.app.windows) == 1)
        nw = next(iter(self.app.windows.values()))
        self.assertEqual((self.app.updater.state, self.app.updater.error), ("error", "upd_err_install"))
        pump(self.app, lambda: nw.toast_text.cget("text") == tr("upd_failed"), timeout=2)
        self.assertEqual(nw.toast_text.cget("text"), tr("upd_failed"))
        sv = self.open_page(nw)
        self.assertIn(tr("upd_err_install", e="disk"), shown_texts(sv.pages["set_update"]))

    def test_app_updater_reads_its_data_folder(self):    # where a failed installer's result file lands
        self.app = make_app(self.folder)
        self.assertEqual(self.app.updater.data_folder, self.folder)

    def test_texts_complete(self):
        keys = ["set_update", "help_update", "upd_installed", "upd_check", "upd_checking", "upd_latest",
                "upd_new", "upd_now", "upd_later", "upd_downloading", "upd_installing", "upd_elsewhere",
                "upd_done", "upd_failed", "upd_err_network", "upd_err_rate", "upd_err_reply",
                "upd_err_download", "upd_err_disk", "upd_err_verify", "upd_err_zip", "upd_err_start",
                "upd_err_install"]
        for key in keys:
            ko, en = texts.TEXTS[key]
            self.assertTrue(ko and en, key)


if __name__ == "__main__":
    unittest.main()
