import copy
import base64
import unittest

from claude_share_extract.chatgpt import (
    chatgpt_share_id,
    extract_chatgpt,
    find_structured_conversation,
    parse_json_scripts,
    validate_chatgpt_url,
    _assets_from_capture,
)


def node(node_id, parent, role=None, text=""):
    return {
        "id": node_id,
        "parent": parent,
        "children": [],
        "message": None if role is None else {
            "id": "m-" + node_id,
            "author": {"role": role},
            "content": {"content_type": "text", "parts": [text]},
        },
    }


class UrlTest(unittest.TestCase):
    def test_canonical_url(self):
        value = "https://chatgpt.com/share/6749af1c-0e14-8012-8830-ce0554744fc3/?x=1#y"
        self.assertEqual(validate_chatgpt_url(value),
                         "https://chatgpt.com/share/6749af1c-0e14-8012-8830-ce0554744fc3")
        self.assertEqual(chatgpt_share_id(value), "6749af1c-0e14-8012-8830-ce0554744fc3")

    def test_rejects_unsafe_urls(self):
        for value in (
            "http://chatgpt.com/share/12345678",
            "https://example.com/share/12345678",
            "https://chatgpt.com.evil.test/share/12345678",
            "https://u:p@chatgpt.com/share/12345678",
            "https://chatgpt.com:444/share/12345678",
            "https://chatgpt.com/c/12345678",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_chatgpt_url(value)


class StructuredTest(unittest.TestCase):
    def fixture(self):
        root = node("root", None)
        user = node("u", "root", "user", "hello")
        old = node("old", "u", "assistant", "old")
        new = node("new", "u", "assistant", "new")
        root["children"] = ["u"]
        user["children"] = ["old", "new"]
        return {"title": "Branched", "current_node": "new",
                "mapping": {"root": root, "u": user, "old": old, "new": new}}

    def test_preserves_all_branches_and_marks_active(self):
        source = self.fixture()
        original = copy.deepcopy(source)
        found = find_structured_conversation({"data": source})
        self.assertEqual(source, original)
        self.assertEqual([m["text"] for m in found["messages"]], ["hello", "new"])
        self.assertEqual(len(found["branches"]), 2)
        self.assertEqual(next(b["leaf_id"] for b in found["branches"] if b["is_active"]), "new")
        self.assertEqual({m["text"] for m in found["all_messages"]}, {"hello", "old", "new"})

    def test_json_scripts_do_not_evaluate_code(self):
        values = parse_json_scripts(['{"title":"x"}', 'window.bad = alert(1)'])
        self.assertEqual(values, [{"title": "x"}])


class ExtractTest(unittest.TestCase):
    def capture(self):
        return {
            "provider": "chatgpt",
            "source_url": "https://chatgpt.com/share/12345678",
            "final_url": "https://chatgpt.com/share/12345678",
            "title": "Example",
            "body_text": "hello",
            "page_html": "<html></html>",
            "scripts": [],
            "responses": [],
            "assets": [{"id": "asset-x", "url": "asset://x", "fetched": False,
                        "reason": "private pointer"}],
            "records": [
                {"role": "user", "source_id": "u1", "turn_index": 1,
                 "plain_text": "line 1\n\nline 3", "text_content": "line 1\n\nline 3",
                 "html": '<div class="whitespace-pre-wrap">line 1\n\nline 3</div>',
                 "outer_html": "<div>...</div>", "resources": [], "source": "test"},
                {"role": "assistant", "source_id": "a1", "turn_index": 2,
                 "plain_text": "answer", "text_content": "answer", "html": "<p><strong>answer</strong></p>",
                 "outer_html": "<div>...</div>", "resources": [], "source": "test"},
            ],
            "traversal": {"toc_prompt_count": 1, "toc_prompts_visited": 1, "deadline_reached": False},
        }

    def test_preserves_user_newlines_and_raw_dom(self):
        conv = extract_chatgpt(self.capture())
        self.assertEqual(conv["turns"][0]["user_input"], "line 1\n\nline 3")
        self.assertEqual(conv["turns"][0]["agent_output"], "**answer**")
        self.assertIn("raw_html", conv["messages"][0])
        self.assertTrue(conv["preservation"]["uncertain"])
        self.assertEqual(conv["stats"]["attachments"], 1)

    def test_text_mismatch_does_not_replace_dom(self):
        capture = self.capture()
        payload = {
            "messages": [
                {"id": "u", "author": {"role": "user"}, "content": {"parts": ["wrong"]}},
                {"id": "a", "author": {"role": "assistant"}, "content": {"parts": ["also wrong"]}},
            ]
        }
        capture["responses"] = [{"mime": "application/json", "json": payload}]
        conv = extract_chatgpt(capture)
        self.assertEqual(conv["turns"][0]["user_input"], "line 1\n\nline 3")
        self.assertTrue(any("not message text" in w for w in conv["warnings"]))


class AssetTest(unittest.TestCase):
    class Page:
        url = "https://chatgpt.com/share/example"

    def test_png_data_url_is_preserved_byte_for_byte(self):
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        ref = {"url": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
               "name": "pixel.png", "kind": "img", "mime": "image/png"}
        assets = _assets_from_capture(self.Page(), [ref], [], 1024 * 1024)
        self.assertTrue(assets[0]["fetched"])
        self.assertEqual(base64.b64decode(assets[0]["content_base64"]), png)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_relative_asset_matches_captured_browser_response(self):
        body = b"\x89PNG\r\n\x1a\nbytes"
        response = {"url": "https://chatgpt.com/image.png", "mime": "image/png",
                    "size": len(body), "sha256": "x",
                    "body_base64": base64.b64encode(body).decode("ascii")}
        assets = _assets_from_capture(self.Page(), [{"url": "/image.png", "kind": "img"}],
                                      [response], 1024 * 1024)
        self.assertEqual(assets[0]["url"], "https://chatgpt.com/image.png")
        self.assertEqual(assets[0]["original_url"], "/image.png")
        self.assertEqual(base64.b64decode(assets[0]["content_base64"]), body)


if __name__ == "__main__":
    unittest.main()
