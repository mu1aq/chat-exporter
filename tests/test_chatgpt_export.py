import json
import unittest
import zipfile

from shared_chat_exporter.chatgpt_export import (
    detect_chatgpt_export,
    export_to_snapshot,
    finalize_export,
    iter_export_conversations,
)
from shared_chat_exporter.extract import Options, extract

from helpers import FIXTURES, TempDir, run_cli

EXPORT = FIXTURES / "exports" / "conversations.json"


def conv(raw):
    return finalize_export(extract(export_to_snapshot(raw), Options()), EXPORT)


class DetectTest(unittest.TestCase):
    def test_detects_conversations_json(self):
        self.assertTrue(detect_chatgpt_export(EXPORT))

    def test_snapshot_is_not_an_export(self):
        self.assertFalse(detect_chatgpt_export(FIXTURES / "basic.json"))

    def test_detects_zip(self):
        with TempDir() as d:
            z = d / "export.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("conversations.json", EXPORT.read_text(encoding="utf-8"))
            self.assertTrue(detect_chatgpt_export(z))


class ConversionTest(unittest.TestCase):
    def test_two_conversations(self):
        self.assertEqual(len(list(iter_export_conversations(EXPORT))), 2)

    def test_mapping_active_path(self):
        c = conv(list(iter_export_conversations(EXPORT))[0])
        self.assertEqual(c["provider"], "chatgpt")
        self.assertEqual(c["source"]["title"], "Py sort")
        self.assertIsNone(c["source"]["share_url"])
        turns = c["turns"]
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]["user_input"], "Sort a list?")
        self.assertEqual(turns[0]["agent_output"], "Use sorted().")
        self.assertEqual(turns[1]["user_input"], "Descending?")
        self.assertEqual(turns[1]["agent_output"], "Add reverse=True.")

    def test_system_message_skipped(self):
        c = conv(list(iter_export_conversations(EXPORT))[1])
        self.assertEqual(len(c["turns"]), 1)
        self.assertEqual(c["turns"][0]["user_input"], "Hi")


class ImageTest(unittest.TestCase):
    def _zip_with_image(self, d):
        conv = {
            "title": "With image", "conversation_id": "c-img", "current_node": "n2",
            "mapping": {
                "n1": {"id": "n1", "parent": None, "children": ["n2"], "message": {
                    "id": "m1", "author": {"role": "user"}, "create_time": 1,
                    "metadata": {"attachments": [{"id": "file-IMG1", "name": "pic.png", "mime_type": "image/png"}]},
                    "content": {"content_type": "multimodal_text",
                                "parts": [{"content_type": "image_asset_pointer", "asset_pointer": "file-service://file-IMG1"}, "look"]}}},
                "n2": {"id": "n2", "parent": "n1", "children": [], "message": {
                    "id": "m2", "author": {"role": "assistant"}, "create_time": 2,
                    "content": {"content_type": "text", "parts": ["nice"]}}},
            },
        }
        z = d / "export.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("conversations.json", json.dumps([conv]))
            zf.writestr("file-IMG1-pic.png", b"PNGDATA")
        return z

    def test_image_resolved_and_bundled(self):
        with TempDir() as d, TempDir() as out:
            z = self._zip_with_image(d)
            from shared_chat_exporter.chatgpt_export import export_to_snapshot, finalize_export, zip_asset_index
            from shared_chat_exporter.extract import Options, extract
            idx = zip_asset_index(z)
            raw = list(iter_export_conversations(z))[0]
            snap = export_to_snapshot(raw, idx)
            c = finalize_export(extract(snap, Options()), z, snap)
            self.assertEqual(len(c["assets"]), 1)
            self.assertEqual(c["assets"][0]["name"], "pic.png")
            self.assertIn("content_base64", c["assets"][0])
            r = run_cli(str(z), "--bundle", str(out))
            self.assertEqual(r.code, 0, r.err)
            saved = out / "assets" / "pic.png"
            self.assertTrue(saved.is_file())
            self.assertEqual(saved.read_bytes(), b"PNGDATA")


class CliTest(unittest.TestCase):
    def test_export_file_makes_many_files(self):
        with TempDir() as out:
            r = run_cli(str(EXPORT), "-f", "md", "-o", str(out) + "/")
            self.assertEqual(r.code, 0, r.err)
            self.assertEqual(len(list(out.glob("*.md"))), 2)

    def test_zip_input(self):
        with TempDir() as d:
            z = d / "export.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("conversations.json", EXPORT.read_text(encoding="utf-8"))
            r = run_cli(str(z), "-f", "md")
            self.assertEqual(r.code, 0, r.err)
            self.assertIn("# Py sort", r.out)
            self.assertIn("### ChatGPT", r.out)


if __name__ == "__main__":
    unittest.main()
