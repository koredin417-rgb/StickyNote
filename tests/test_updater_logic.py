"""Self-update, the pure part: versions, picking a release from GitHub's reply, notes as plain text."""
import unittest

import version
from updater import api_url, parse_version, pick_release, plain_notes


def release(tag, asset="StickyNote.zip", digest=None, draft=False, prerelease=False):
    """A release as GitHub's API gives it (only the fields the updater reads)."""
    return {"tag_name": tag, "body": "notes", "draft": draft, "prerelease": prerelease,
            "assets": [{"name": asset, "browser_download_url": "https://example.test/StickyNote.zip",
                        "size": 123, "digest": digest}]}


class UpdaterLogicTest(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(parse_version("v1.2.0"), (1, 2, 0))
        self.assertEqual(parse_version("1.10"), (1, 10))
        self.assertIsNone(parse_version("latest"))
        self.assertIsNone(parse_version("v1.2-beta"))
        self.assertGreater(parse_version("1.10.0"), parse_version("1.9.0"))

    def test_version_constant_parses(self):
        self.assertEqual(parse_version(version.VERSION), (1, 2, 3))

    def test_pick_newer_release(self):
        r = pick_release(release("v1.2.0", digest="sha256:ab"), "1.1.0")
        self.assertEqual((r.version, r.tag, r.size, r.sha256), ("1.2.0", "v1.2.0", 123, "ab"))
        self.assertEqual(r.url, "https://example.test/StickyNote.zip")
        self.assertEqual(r.notes, "notes")

    def test_same_or_older_is_none(self):
        self.assertIsNone(pick_release(release("v1.1.0"), "1.1.0"))
        self.assertIsNone(pick_release(release("v1.0.9"), "1.1.0"))

    def test_no_asset_or_bad_tag_or_draft_is_none(self):
        self.assertIsNone(pick_release(release("v2.0.0", asset="Other.zip"), "1.1.0"))
        self.assertIsNone(pick_release(release("nightly"), "1.1.0"))
        self.assertIsNone(pick_release(release("v2.0.0", draft=True), "1.1.0"))

    def test_list_reply_takes_newest(self):     # the pre-release listing
        reply = [release("v1.2.0"), release("v1.3.0", prerelease=True), release("v9.0.0", draft=True)]
        self.assertEqual(pick_release(reply, "1.1.0").version, "1.3.0")

    def test_no_digest(self):
        self.assertIsNone(pick_release(release("v1.2.0"), "1.1.0").sha256)

    def test_plain_notes(self):
        self.assertEqual(plain_notes("## Fixes\n* **Faster** `drag`\n- calendar"),
                         "Fixes\n• Faster drag\n• calendar")

    def test_api_url(self):
        self.assertTrue(api_url({}).endswith("/releases/latest"))
        self.assertTrue(api_url({"STICKYNOTE_UPDATE_PRERELEASE": "1"}).endswith("/releases"))


if __name__ == "__main__":
    unittest.main()
