import unittest

from helpers import fixture

from shared_chat_exporter.extract import Options, extract, fence
from shared_chat_exporter.select import SelectError, parse_turn_spec, select_turns


class BasicTest(unittest.TestCase):
    def test_pairs(self):
        conv = extract(fixture("basic.json"))
        self.assertEqual(len(conv["turns"]), 2)
        t1, t2 = conv["turns"]
        self.assertEqual(t1["user_input"], "파이썬에서 딕셔너리 리스트를 나이순으로 정렬하려면?")
        self.assertIn("sorted", t1["agent_output"])
        self.assertEqual(t2["user_input"], "내림차순은요?")
        self.assertIn("reverse=True", t2["agent_output"])
        self.assertEqual(conv["warnings"], [])
        self.assertEqual(conv["source"]["share_url"], "https://claude.ai/share/3b8f2c1e-5a6d-4e7f-9a0b-1c2d3e4f5a6b")
        self.assertNotIn("created_by", str(conv["source"]))

    def test_default_options_hide_tools_and_thinking(self):
        t = extract(fixture("rich.json"))["turns"][0]
        self.assertNotIn("tool_calls", t)
        self.assertNotIn("thinking", t)
        self.assertEqual(t["tool_call_count"], 2)


class RichTest(unittest.TestCase):
    def setUp(self):
        self.conv = extract(fixture("rich.json"), Options(tools=True, thinking=True))

    def test_branch_keeps_shared_path(self):
        self.assertEqual(self.conv["stats"]["messages"], 4)
        self.assertEqual(self.conv["stats"]["messages_in_snapshot"], 5)
        self.assertTrue(any("branches" in w for w in self.conv["warnings"]))
        self.assertNotIn("다시 생성하기 전", self.conv["turns"][0]["agent_output"])

    def test_attachments_in_input(self):
        u = self.conv["turns"][0]["user_input"]
        self.assertIn("[attachment: Pasted text]\n- 매출 12% 증가", u)
        self.assertIn("[file: chart.png]", u)
        self.assertEqual(self.conv["turns"][0]["attachments"], ["Pasted text", "chart.png"])
        no = extract(fixture("rich.json"), attachments=False)["turns"][0]["user_input"]
        self.assertNotIn("attachment", no)

    def test_tool_results_paired(self):
        calls = self.conv["turns"][0]["tool_calls"]
        self.assertEqual([c["name"] for c in calls], ["web_search", "artifacts"])
        self.assertEqual(calls[0]["result"], "보고서 양식 예시\n요약-성과-계획 순서")

    def test_thinking(self):
        self.assertEqual(self.conv["turns"][0]["thinking"], "메모를 정리해서 보고서 형태로 만든다.")

    def test_artifact_create_and_update(self):
        out1, out2 = self.conv["turns"][0]["agent_output"], self.conv["turns"][1]["agent_output"]
        self.assertIn("[Artifact: 주간 보고서]\n````markdown\n# 주간 보고서", out1)
        self.assertIn("[Artifact update: 주간 보고서]", out2)
        self.assertIn("매출 15% 증가", out2)
        arts = self.conv["artifacts"]
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0]["ext"], "md")
        self.assertEqual(arts[0]["versions"], 2)
        self.assertIn("매출 15% 증가", arts[0]["content"])
        self.assertNotIn("12%", arts[0]["content"])
        hidden = extract(fixture("rich.json"), artifacts=False)
        self.assertNotIn("Artifact", hidden["turns"][0]["agent_output"])
        self.assertEqual(len(hidden["artifacts"]), 1)

    def test_current_leaf_preferred(self):
        snap = fixture("rich.json")
        snap["chat_messages"] = snap["chat_messages"][:3]
        snap["current_leaf_message_uuid"] = "a1-old"
        conv = extract(snap)
        self.assertEqual(conv["turns"][0]["agent_output"], "(다시 생성하기 전 답변)")


class ApiStyleTest(unittest.TestCase):
    def setUp(self):
        self.conv = extract(fixture("api_style.json"), tools=True)

    def test_tool_only_human_is_not_a_turn(self):
        self.assertEqual(len(self.conv["turns"]), 2)
        self.assertEqual(self.conv["turns"][0]["user_input"], "중복 행을 지우는 스크립트 만들어줘")
        self.assertEqual(self.conv["turns"][1]["user_input"], "고마워")
        self.assertEqual(self.conv["turns"][1]["agent_output"], "")

    def test_tool_result_from_human_message_pairs(self):
        calls = self.conv["turns"][0]["tool_calls"]
        self.assertEqual(calls[0]["result"], "File created")
        self.assertTrue(calls[2]["is_error"])

    def test_file_tools_tracked(self):
        arts = self.conv["artifacts"]
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0]["ext"], "py")
        self.assertEqual(arts[0]["language"], "python")
        self.assertIn("print('v2')", arts[0]["content"])
        self.assertIn("```python\nimport csv", self.conv["turns"][0]["agent_output"])


class SelectTest(unittest.TestCase):
    def test_turn_spec(self):
        self.assertEqual(parse_turn_spec("1-3,5,8-", 10), {1, 2, 3, 5, 8, 9, 10})
        self.assertEqual(parse_turn_spec("-2", 10), {1, 2})
        for bad in ["a", "3-1", "-"]:
            with self.subTest(bad=bad), self.assertRaises(SelectError):
                parse_turn_spec(bad, 5)

    def test_filters(self):
        conv = extract(fixture("basic.json"))
        self.assertEqual([t["turn"] for t in select_turns(conv, turns="2")["turns"]], [2])
        self.assertEqual([t["turn"] for t in select_turns(conv, last=1)["turns"]], [2])
        self.assertEqual([t["turn"] for t in select_turns(conv, grep="REVERSE")["turns"]], [2])
        self.assertEqual(len(conv["turns"]), 2)  # 원본은 그대로
        with self.assertRaises(SelectError):
            select_turns(conv, grep="(")


class FenceTest(unittest.TestCase):
    def test_fence_longer_than_content(self):
        self.assertEqual(fence("plain"), "```")
        self.assertEqual(fence("a ```` b"), "`````")


if __name__ == "__main__":
    unittest.main()
