import json
import unittest

from shared_chat_exporter.redact import redact_obj, redact_text

from helpers import TempDir, run_cli

KEY = "sk-ant-ABCDEFGHIJKLMNOPQRSTUVWX12345678"


class RedactTextTest(unittest.TestCase):
    def test_masks_anthropic_key(self):
        out, n = redact_text(f"use {KEY} now")
        self.assertEqual(n, 1)
        self.assertNotIn(KEY, out)
        self.assertIn("[REDACTED:anthropic-key]", out)

    def test_assigned_secret_keeps_name_masks_value(self):
        out, n = redact_text('API_KEY = "hunter2abcdef"')
        self.assertEqual(n, 1)
        self.assertIn("API_KEY", out)
        self.assertNotIn("hunter2abcdef", out)

    def test_plain_text_untouched(self):
        out, n = redact_text("just a normal sentence, nothing secret")
        self.assertEqual((out, n), ("just a normal sentence, nothing secret", 0))

    def test_recursive(self):
        obj = {"a": [f"x {KEY}", {"b": KEY}], "n": 3}
        red, n = redact_obj(obj)
        self.assertEqual(n, 2)
        self.assertNotIn(KEY, json.dumps(red))
        self.assertEqual(red["n"], 3)


class RedactCliTest(unittest.TestCase):
    def test_cli_redacts_and_warns(self):
        with TempDir() as d:
            p = d / "s.jsonl"
            p.write_text("\n".join(json.dumps(x) for x in [
                {"type": "user", "uuid": "u1", "parentUuid": None, "sessionId": "s",
                 "message": {"role": "user", "content": "deploy with key"}},
                {"type": "assistant", "uuid": "a1", "parentUuid": "u1", "sessionId": "s",
                 "message": {"role": "assistant", "content": [{"type": "text", "text": f"token {KEY}"}]}},
            ]), encoding="utf-8")
            r = run_cli(str(p), "-f", "md", "--redact")
            self.assertEqual(r.code, 0, r.err)
            self.assertNotIn(KEY, r.out)
            self.assertIn("[REDACTED:anthropic-key]", r.out)
            self.assertIn("redacted", r.err)


if __name__ == "__main__":
    unittest.main()
