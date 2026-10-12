import unittest

from helpers import BASIC_ID, FIXTURES, TempDir, fixture_text

from shared_chat_exporter.snapshot import (
    NotAShareLink,
    SnapshotError,
    load_snapshot_file,
    parse_snapshot_text,
    share_id_from,
    snapshot_api_url,
)

SID = "f2f59cb2-8857-4808-a650-2712e80290fd"


class ShareIdTest(unittest.TestCase):
    def test_accepts_common_forms(self):
        for v in [
            f"https://claude.ai/share/{SID}",
            f"https://claude.ai/share/{SID}/",
            f"https://www.claude.ai/share/{SID}",
            f"https://CLAUDE.AI/share/{SID}",
            f"https://claude.ai/share/{SID}?utm_source=x#top",
            f"claude.ai/share/{SID}",
            f"  <https://claude.ai/share/{SID}>  ",
            f"https://claude.ai/api/chat_snapshots/{SID}?rendering_mode=messages",
            SID,
            SID.upper(),
        ]:
            with self.subTest(v=v):
                self.assertEqual(share_id_from(v).lower(), SID)

    def test_rejects_other_hosts(self):
        for v in [f"https://claude.ai.evil.test/share/{SID}", f"https://evil.test/claude.ai/share/{SID}",
                  f"https://notclaude.ai/share/{SID}", f"https://chatgpt.com/share/{SID}", "hello", ""]:
            with self.subTest(v=v), self.assertRaises(NotAShareLink):
                share_id_from(v)

    def test_private_chat_link_explains(self):
        with self.assertRaises(NotAShareLink) as cm:
            share_id_from(f"https://claude.ai/chat/{SID}")
        self.assertIn("share", str(cm.exception))

    def test_snapshot_url(self):
        self.assertEqual(snapshot_api_url(SID),
                         f"https://claude.ai/api/chat_snapshots/{SID}?rendering_mode=messages&render_all_tools=true")


class ParseTest(unittest.TestCase):
    def test_trims_browser_chrome(self):
        snap = parse_snapshot_text("Pretty-print □\n" + fixture_text("basic.json") + "\n")
        self.assertEqual(snap["uuid"], BASIC_ID)

    def test_errors(self):
        cases = {
            "hello": "No JSON found",
            '{"chat_messages": [ {': "truncated",
            '{"a": 1}': "chat_messages",
            '{"type":"error","error":{"message":"Not found"}}': "Not found",
            '{"chat_messages": [1, }': "Invalid JSON",
        }
        for text, needle in cases.items():
            with self.subTest(text=text), self.assertRaises(SnapshotError) as cm:
                parse_snapshot_text(text)
            self.assertIn(needle, str(cm.exception))

    def test_reads_utf16_and_bom_files(self):
        raw = fixture_text("basic.json")
        with TempDir() as d:
            for name, data in {"u16.json": raw.encode("utf-16"), "bom.json": b"\xef\xbb\xbf" + raw.encode("utf-8")}.items():
                p = d / name
                p.write_bytes(data)
                with self.subTest(name=name):
                    self.assertEqual(load_snapshot_file(p)["uuid"], BASIC_ID)

    def test_fixtures_load(self):
        for p in FIXTURES.glob("*.json"):
            with self.subTest(p=p.name):
                load_snapshot_file(p)


if __name__ == "__main__":
    unittest.main()
