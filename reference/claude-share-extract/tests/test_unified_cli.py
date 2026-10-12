import base64
import json
from unittest import TestCase, mock

from helpers import TempDir, run_cli

from claude_share_extract.cli import resolve_inputs


URL = "https://chatgpt.com/share/6749af1c-0e14-8012-8830-ce0554744fc3"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def capture():
    return {
        "provider": "chatgpt", "source_url": URL, "final_url": URL, "http_status": 200,
        "title": "Multiline", "body_text": "first line second line", "page_html": "<html></html>",
        "scripts": [], "responses": [], "assets": [{
            "id": "asset-1", "name": "pixel.png", "mime": "image/png", "url": "https://example/pixel.png",
            "fetched": True, "sha256": "ignored-here",
            "content_base64": base64.b64encode(PNG).decode("ascii"),
        }], "observations": [2, 2],
        "traversal": {"toc_prompt_count": 1, "toc_prompts_visited": 1, "deadline_reached": False},
        "records": [
            {"role": "user", "source_id": "u", "turn_index": 1,
             "plain_text": "first line\n\nsecond line", "text_content": "first line\n\nsecond line",
             "html": '<div class="whitespace-pre-wrap">first line\n\nsecond line</div>',
             "outer_html": "<div>user</div>", "resources": [], "source": "test"},
            {"role": "assistant", "source_id": "a", "turn_index": 2,
             "plain_text": "answer", "text_content": "answer", "html": "<p>answer</p>",
             "outer_html": "<div>assistant</div>", "resources": [], "source": "test"},
        ],
    }


class UnifiedCliTest(TestCase):
    def test_resolves_both_providers(self):
        items, errors = resolve_inputs([URL, "https://claude.ai/share/3b8f2c1e-5a6d-4e7f-9a0b-1c2d3e4f5a6b"], None)
        self.assertFalse(errors)
        self.assertEqual([item.kind for item in items], ["chatgpt", "claude"])

    def test_chatgpt_markdown_and_json(self):
        with TempDir() as folder, mock.patch("claude_share_extract.cli.capture_chatgpt", return_value=capture()):
            md_path = folder / "chat.md"
            result = run_cli(URL, "--headless", "-o", str(md_path))
            self.assertEqual(result.code, 0, result.err)
            text = md_path.read_text(encoding="utf-8")
            self.assertIn("first line\n\nsecond line", text)
            self.assertIn("### ChatGPT", text)

            json_path = folder / "chat.json"
            result = run_cli(URL, "--headless", "-o", str(json_path))
            self.assertEqual(result.code, 0, result.err)
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["source"]["provider"], "chatgpt")
            self.assertIn("capture", payload)

    def test_complete_bundle_and_verify(self):
        with TempDir() as folder, mock.patch("claude_share_extract.cli.capture_chatgpt", return_value=capture()):
            bundle = folder / "bundle"
            result = run_cli(URL, "--headless", "--bundle", str(bundle))
            self.assertEqual(result.code, 0, result.err)
            for name in ("capture.json", "conversation.json", "transcript.md", "page.html",
                         "manifest.json", "audit.json", "checksums.sha256"):
                self.assertTrue((bundle / name).is_file(), name)
            self.assertTrue((bundle / "assets" / "pixel.png").is_file())
            self.assertEqual((bundle / "assets" / "pixel.png").read_bytes(), PNG)
            verified = run_cli("verify", str(bundle))
            self.assertEqual(verified.code, 0, verified.err)


if __name__ == "__main__":
    import unittest
    unittest.main()
