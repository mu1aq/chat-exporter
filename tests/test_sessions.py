import json
import unittest
from pathlib import Path

from shared_chat_exporter.extract import Options, extract
from shared_chat_exporter.sessions import detect_session, finalize_session, session_to_snapshot

from helpers import FIXTURES, TempDir, run_cli

SESSION = FIXTURES / "sessions" / "claude_code_session.jsonl"
CODEX = FIXTURES / "sessions" / "codex_session.jsonl"


def load(path=SESSION):
    snap = session_to_snapshot(path)
    return finalize_session(extract(snap, Options(tools=True, thinking=True)), path, snap)


class DetectTest(unittest.TestCase):
    def test_detects_claude_code_log(self):
        self.assertEqual(detect_session(SESSION), "claude-code")

    def test_claude_snapshot_is_not_a_session(self):
        self.assertIsNone(detect_session(FIXTURES / "basic.json"))

    def test_detects_codex_rollout(self):
        self.assertEqual(detect_session(CODEX), "codex")


class ConversionTest(unittest.TestCase):
    def setUp(self):
        self.conv = load()

    def test_source_fields(self):
        src = self.conv["source"]
        self.assertEqual(self.conv["provider"], "claude-code")
        self.assertEqual(src["provider"], "claude-code")
        self.assertIsNone(src["share_url"])
        self.assertTrue(src["session_file"].endswith("claude_code_session.jsonl"))
        self.assertEqual(src["title"], "Sort a list")
        self.assertEqual(src.get("model"), "claude-opus-5")

    def test_two_turns_merged(self):
        turns = self.conv["turns"]
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]["user_input"], "Sort a list of dicts by age?")
        # both assistant lines of the first turn are merged
        self.assertIn("Use sorted().", turns[0]["agent_output"])
        self.assertIn("sorted(xs, key=lambda d: d['age'])", turns[0]["agent_output"])
        self.assertEqual(turns[1]["user_input"], "Descending?")
        self.assertIn("Add reverse=True.", turns[1]["agent_output"])

    def test_thinking_and_tool_pairing(self):
        t0 = self.conv["turns"][0]
        self.assertEqual(t0["thinking"], "Use sorted with a key.")
        calls = t0["tool_calls"]
        self.assertEqual([c["name"] for c in calls], ["Bash"])
        self.assertEqual(calls[0]["input"], {"command": "echo hi"})
        self.assertEqual(calls[0]["result"], "hi")

    def test_sidechain_excluded_but_warned(self):
        self.assertNotIn("SIDECHAIN_SECRET", json.dumps(self.conv, ensure_ascii=False))
        self.assertTrue(any("sidechain" in w for w in self.conv["warnings"]))

    def test_crlf_normalized(self):
        out = self.conv["turns"][1]["agent_output"]
        self.assertEqual(out, "Add reverse=True.\nDone.")
        self.assertNotIn("\r", json.dumps(self.conv, ensure_ascii=False))


class CodexTest(unittest.TestCase):
    def setUp(self):
        self.conv = load(CODEX)

    def test_source_fields(self):
        src = self.conv["source"]
        self.assertEqual(self.conv["provider"], "codex")
        self.assertIsNone(src["share_url"])
        self.assertEqual(src["title"], "List files then sort.")
        self.assertEqual(src.get("model"), "gpt-daybreak-blue")

    def test_turns_skip_developer_and_context(self):
        turns = self.conv["turns"]
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]["user_input"], "List files then sort.")
        self.assertNotIn("environment_context", json.dumps(self.conv, ensure_ascii=False))
        self.assertIn("Found two files.", turns[0]["agent_output"])
        self.assertEqual(turns[1]["user_input"], "Sort descending.")
        self.assertIn("Use reverse=True.", turns[1]["agent_output"])

    def test_reasoning_and_tools(self):
        t0, t1 = self.conv["turns"]
        self.assertEqual(t0["thinking"], "Plan: run ls.")
        self.assertEqual([c["name"] for c in t0["tool_calls"]], ["exec"])
        self.assertEqual(t0["tool_calls"][0]["input"], {"input": "ls -la"})
        self.assertEqual(t0["tool_calls"][0]["result"], "file1\nfile2")
        self.assertEqual(t1["tool_calls"][0]["name"], "wait")
        self.assertEqual(t1["tool_calls"][0]["input"], {"ms": 10})
        self.assertEqual(t1["tool_calls"][0]["result"], "done")

    def test_encrypted_reasoning_marked_uncertain(self):
        reasons = [u["reason"] for u in self.conv["preservation"]["uncertain"]]
        self.assertTrue(any("encrypted" in r for r in reasons))

    def test_cli_bundle_roundtrip(self):
        with TempDir() as d:
            r = run_cli(str(CODEX), "--bundle", str(d))
            self.assertEqual(r.code, 0, r.err)
            self.assertTrue((d / "raw.jsonl").is_file())
            manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["provider"], "codex")
            self.assertEqual(run_cli("verify", str(d)).code, 0)


class DriftAndDirTest(unittest.TestCase):
    def test_claude_code_version_drift_warns(self):
        with TempDir() as d:
            p = d / "s.jsonl"
            p.write_text("\n".join(json.dumps(x) for x in [
                {"type": "user", "uuid": "u1", "parentUuid": None, "sessionId": "s", "version": "2.9.999",
                 "timestamp": "2026-01-01T00:00:00Z", "message": {"role": "user", "content": "hi"}},
                {"type": "assistant", "uuid": "a1", "parentUuid": "u1", "sessionId": "s", "version": "2.9.999",
                 "message": {"role": "assistant", "content": [{"type": "text", "text": "yo"}]}},
            ]), encoding="utf-8")
            conv = finalize_session(extract(session_to_snapshot(p), Options()), p, session_to_snapshot(p))
            self.assertTrue(any("outside the tested range" in w for w in conv["warnings"]))

    def test_codex_version_drift_warns(self):
        with TempDir() as d:
            p = d / "rollout-x.jsonl"
            p.write_text("\n".join(json.dumps(x) for x in [
                {"type": "session_meta", "payload": {"session_id": "cx", "cli_version": "0.200.0"}},
                {"type": "response_item", "payload": {"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": "hi"}]}},
            ]), encoding="utf-8")
            snap = session_to_snapshot(p)
            conv = finalize_session(extract(snap, Options()), p, snap)
            self.assertTrue(any("outside the tested 0.162.1 series" in w for w in conv["warnings"]))

    def test_directory_of_jsonl_sessions(self):
        with TempDir() as src, TempDir() as out:
            for f in (SESSION, CODEX):
                (src / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
            r = run_cli(str(src), "-f", "md", "-o", str(out) + "/")
            self.assertEqual(r.code, 0, r.err)
            self.assertEqual(len(list(out.glob("*.md"))), 2)


class CliTest(unittest.TestCase):
    def test_markdown_export(self):
        r = run_cli(str(SESSION), "-f", "md", "--tools", "--thinking")
        self.assertEqual(r.code, 0, r.err)
        self.assertIn("# Sort a list", r.out)
        self.assertIn("## Turn 1", r.out)
        self.assertIn("Use sorted().", r.out)
        self.assertIn("Add reverse=True.", r.out)
        self.assertNotIn("SIDECHAIN_SECRET", r.out)

    def test_info_table(self):
        r = run_cli("info", str(SESSION))
        self.assertEqual(r.code, 0, r.err)
        self.assertIn("Turns / messages", r.out)
        self.assertIn("2 / ", r.out)

    def test_bundle_roundtrip(self):
        with TempDir() as d:
            r = run_cli(str(SESSION), "--bundle", str(d))
            self.assertEqual(r.code, 0, r.err)
            self.assertTrue((d / "raw.jsonl").is_file())
            manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["provider"], "claude-code")
            v = run_cli("verify", str(d))
            self.assertEqual(v.code, 0, v.err)


if __name__ == "__main__":
    unittest.main()
