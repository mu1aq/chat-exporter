import csv
import io
import json
import unittest

from helpers import fixture

from shared_chat_exporter.exporters import export
from shared_chat_exporter.extract import extract


def convs(**kw):
    return [extract(fixture(n), **kw) for n in ("basic.json", "rich.json")]


class ExportTest(unittest.TestCase):
    def test_jsonl(self):
        lines = export(convs(), "jsonl").strip().split("\n")
        self.assertEqual(len(lines), 4)
        row = json.loads(lines[0])
        self.assertEqual(list(row), ["share_id", "title", "turn", "user_input", "agent_output"])

    def test_jsonl_only(self):
        row = json.loads(export(convs(), "jsonl", only="user").split("\n")[0])
        self.assertNotIn("agent_output", row)
        row = json.loads(export(convs(), "jsonl", only="assistant").split("\n")[0])
        self.assertNotIn("user_input", row)

    def test_csv_roundtrip(self):
        text = export(convs(tools=True), "csv")
        self.assertTrue(text.startswith("﻿"))
        rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[2]["user_input"].split("\n")[0], '아래 메모로 주간 보고서 써줘, "따옴표", 쉼표 포함')
        self.assertEqual(json.loads(rows[2]["tool_calls"])[0]["name"], "web_search")

    def test_markdown(self):
        md = export(convs(), "md")
        self.assertIn("# 파이썬 리스트 정렬 질문", md)
        self.assertIn("### User", md)
        self.assertIn("### Claude", md)
        self.assertNotIn("### Claude", export(convs(), "md", only="user"))

    def test_text(self):
        txt = export(convs(), "txt")
        self.assertIn("[Turn 1] User:", txt)
        self.assertIn("[Turn 2] Claude:", txt)

    def test_chat(self):
        lines = export(convs(), "chat", system="너는 친절한 조수야").strip().split("\n")
        self.assertEqual(len(lines), 2)
        obj = json.loads(lines[0])
        self.assertEqual([m["role"] for m in obj["messages"]], ["system", "user", "assistant", "user", "assistant"])
        self.assertEqual(obj["metadata"]["title"], "파이썬 리스트 정렬 질문")

    def test_json_single_vs_many(self):
        one = json.loads(export(convs()[:1], "json"))
        self.assertIsInstance(one, dict)
        self.assertIn("messages", one)
        many = json.loads(export(convs(), "json"))
        self.assertEqual(len(many), 2)

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            export(convs(), "xml")


if __name__ == "__main__":
    unittest.main()
