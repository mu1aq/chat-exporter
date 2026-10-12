import csv
import io
import json
import unittest

from helpers import API_ID, BASIC_ID, FIXTURES, RICH_ID, TempDir, fixture_text, run_cli

BASIC = str(FIXTURES / "basic.json")
RICH = str(FIXTURES / "rich.json")
API = str(FIXTURES / "api_style.json")


class GetTest(unittest.TestCase):
    def test_default_is_get_and_jsonl_to_stdout(self):
        r = run_cli(BASIC)
        self.assertEqual(r.code, 0, r.err)
        rows = [json.loads(x) for x in r.out.strip().split("\n")]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["share_id"], BASIC_ID)

    def test_format_inferred_from_output(self):
        with TempDir() as d:
            out = d / "pairs.csv"
            r = run_cli("get", BASIC, RICH, "-o", str(out))
            self.assertEqual(r.code, 0, r.err)
            rows = list(csv.DictReader(io.StringIO(out.read_text(encoding="utf-8-sig"))))
            self.assertEqual(len(rows), 4)
            self.assertIn("대화 2개", r.err)

    def test_overwrite_guard(self):
        with TempDir() as d:
            out = d / "a.md"
            out.write_text("keep", encoding="utf-8")
            r = run_cli(BASIC, "-o", str(out))
            self.assertEqual(r.code, 1)
            self.assertIn("--force", r.err)
            self.assertEqual(out.read_text(encoding="utf-8"), "keep")
            r = run_cli(BASIC, "-o", str(out), "--force")
            self.assertEqual(r.code, 0)
            self.assertIn("# 파이썬 리스트 정렬 질문", out.read_text(encoding="utf-8"))

    def test_directory_output_one_file_per_conversation(self):
        with TempDir() as d:
            r = run_cli(str(FIXTURES), "-f", "md", "-o", str(d) + "/")
            self.assertEqual(r.code, 0, r.err)
            names = sorted(p.name for p in d.iterdir())
            self.assertEqual(names, ["CSV_정리_스크립트_9d0e1f2a.md", "주간_보고서_초안_만들기_5f2c1a9e.md",
                                     "파이썬_리스트_정렬_질문_3b8f2c1e.md"])
            r = run_cli(str(FIXTURES), "-f", "md", "-o", str(d) + "/")
            self.assertEqual(r.code, 1)

    def test_save_artifacts_and_raw(self):
        with TempDir() as d:
            r = run_cli(RICH, API, "-o", str(d / "out.jsonl"), "--save-artifacts", str(d / "arts"),
                        "--save-raw", str(d / "raw"))
            self.assertEqual(r.code, 0, r.err)
            report = d / "arts" / "주간_보고서_초안_만들기_5f2c1a9e" / "주간_보고서.md"
            self.assertIn("매출 15% 증가", report.read_text(encoding="utf-8"))
            script = d / "arts" / "CSV_정리_스크립트_9d0e1f2a" / "dedupe.py"
            self.assertIn("print('v2')", script.read_text(encoding="utf-8"))
            self.assertTrue((d / "raw" / f"{RICH_ID}.json").is_file())
            self.assertTrue((d / "raw" / f"{API_ID}.json").is_file())

    def test_selection_and_only(self):
        r = run_cli(RICH, "--turns", "2", "--only", "user")
        rows = [json.loads(x) for x in r.out.strip().split("\n")]
        self.assertEqual([(x["turn"], "agent_output" in x) for x in rows], [(2, False)])
        r = run_cli(RICH, "--turns", "x")
        self.assertEqual(r.code, 2)

    def test_chat_with_system(self):
        r = run_cli(BASIC, "-f", "chat", "--system", "간결하게 답하라")
        obj = json.loads(r.out)
        self.assertEqual(obj["messages"][0], {"role": "system", "content": "간결하게 답하라"})

    def test_stdin_and_list_file(self):
        r = run_cli("-", stdin_text=fixture_text("basic.json"))
        self.assertEqual(r.code, 0, r.err)
        self.assertEqual(len(r.out.strip().split("\n")), 2)
        with TempDir() as d:
            lst = d / "list.txt"
            lst.write_text(f"# 내 목록\n{BASIC}\n{RICH}  # 두 번째\n\n", encoding="utf-8")
            r = run_cli("get", "-i", str(lst))
            self.assertEqual(r.code, 0, r.err)
            self.assertEqual(len(r.out.strip().split("\n")), 4)

    def test_bad_inputs(self):
        r = run_cli("get", "nothing/here.json")
        self.assertEqual(r.code, 1)
        self.assertIn("파일이 없습니다", r.err)
        r = run_cli("https://claude.ai/chat/abc")
        self.assertIn("비공개 대화", r.err)
        with TempDir() as d:
            bad = d / "bad.json"
            bad.write_text('{"x": 1}', encoding="utf-8")
            r = run_cli(BASIC, str(bad))
            self.assertEqual(r.code, 1)
            self.assertEqual(len(r.out.strip().split("\n")), 2)  # 성공한 것은 출력

    def test_share_link_uses_cache(self):
        with TempDir() as d:
            (d / "snapshots").mkdir()
            (d / "snapshots" / f"{BASIC_ID}.json").write_text(fixture_text("basic.json"), encoding="utf-8")
            r = run_cli(f"https://claude.ai/share/{BASIC_ID}", "--cache-dir", str(d), "-f", "txt")
            self.assertEqual(r.code, 0, r.err)
            self.assertIn("캐시", r.err)
            self.assertIn("[턴 2] Claude:", r.out)


class OtherCommandsTest(unittest.TestCase):
    def test_show(self):
        r = run_cli("show", RICH, "--tools", "--thinking", "--no-pager")
        self.assertEqual(r.code, 0, r.err)
        for needle in ("주간 보고서 초안 만들기", "턴 1", "사용자", "Claude", "web_search", "메모를 정리", "분기"):
            self.assertIn(needle, r.out)
        self.assertNotIn("\x1b[", r.out)

    def test_info_json(self):
        r = run_cli("info", RICH, API, "--json")
        data = json.loads(r.out)
        self.assertEqual(data[0]["stats"]["tool_calls"], {"artifacts": 2, "web_search": 1})
        self.assertEqual(data[1]["artifacts"][0]["ext"], "py")

    def test_info_table(self):
        r = run_cli("info", BASIC)
        self.assertIn("턴 / 메시지", r.out)

    def test_url(self):
        r = run_cli("url", f"https://claude.ai/share/{BASIC_ID}")
        self.assertEqual(r.out.strip(), f"https://claude.ai/api/chat_snapshots/{BASIC_ID}?rendering_mode=messages&render_all_tools=true")
        r = run_cli("url", "--page", BASIC_ID)
        self.assertEqual(r.out.strip(), f"https://claude.ai/share/{BASIC_ID}")

    def test_cache_commands(self):
        with TempDir() as d:
            (d / "snapshots").mkdir()
            (d / "snapshots" / f"{BASIC_ID}.json").write_text(fixture_text("basic.json"), encoding="utf-8")
            r = run_cli("cache", "list", "--cache-dir", str(d))
            self.assertIn("파이썬 리스트 정렬 질문", r.out)
            r = run_cli("cache", "clear", "--cache-dir", str(d))
            self.assertEqual(r.code, 2)  # 표준 입력이 TTY가 아니면 --yes 필요
            r = run_cli("cache", "clear", "-y", "--cache-dir", str(d))
            self.assertEqual(r.code, 0)
            self.assertFalse(any((d / "snapshots").iterdir()))

    def test_version_and_help(self):
        r = run_cli("get", "--help")
        self.assertIn("--save-artifacts", r.out)


if __name__ == "__main__":
    unittest.main()
