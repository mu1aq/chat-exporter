import copy
import unittest

from helpers import fixture

from shared_chat_exporter.extract import Options, extract


class BranchTest(unittest.TestCase):
    def setUp(self):
        self.conv = extract(fixture("rich.json"), Options(tools=True, thinking=True))

    def test_active_path_unchanged(self):
        # the active path stays as-is in turns/messages
        self.assertEqual(len(self.conv["turns"]), 2)
        self.assertEqual(self.conv["stats"]["messages"], 4)

    def test_all_branches_preserved(self):
        br = self.conv["branches"]
        self.assertTrue(br["linked"])
        self.assertEqual(br["active_leaf_uuid"], "a2")
        # all 5 messages of the full snapshot are preserved as nodes
        self.assertEqual(len(br["nodes"]), 5)
        self.assertEqual({n["uuid"] for n in br["nodes"]},
                         {"u1", "a1-old", "a1", "u2", "a2"})
        # two branches: active(a2), alternate(a1-old)
        leaves = {p["leaf_uuid"]: p for p in br["paths"]}
        self.assertEqual(set(leaves), {"a2", "a1-old"})
        self.assertTrue(leaves["a2"]["is_active"])
        self.assertFalse(leaves["a1-old"]["is_active"])
        self.assertEqual(leaves["a1-old"]["message_uuids"], ["u1", "a1-old"])
        self.assertEqual(self.conv["stats"]["branches"], 2)
        self.assertEqual(self.conv["stats"]["alternate_branches"], 1)

    def test_alternate_branch_content_kept(self):
        node = next(n for n in self.conv["branches"]["nodes"] if n["uuid"] == "a1-old")
        self.assertFalse(node["is_active"])
        self.assertEqual(node["parent_uuid"], "u1")
        self.assertEqual(node["message"]["text"], "(다시 생성하기 전 답변)")

    def test_linear_conversation_single_active_path(self):
        conv = extract(fixture("basic.json"))
        paths = conv["branches"]["paths"]
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0]["is_active"])
        self.assertEqual(conv["stats"]["alternate_branches"], 0)


class RawMetadataTest(unittest.TestCase):
    def test_attachment_and_file_metadata(self):
        conv = extract(fixture("rich.json"))
        msg0 = conv["messages"][0]
        att = msg0["attachments"][0]
        self.assertEqual(att["name"], "Pasted text")
        self.assertEqual(att["meta"]["file_type"], "txt")
        self.assertEqual(msg0["files"], ["chart.png"])          # name list kept as-is (backward compatible)
        self.assertEqual(msg0["files_meta"][0]["meta"]["file_kind"], "image")
        self.assertEqual(msg0["parent_uuid"], "00000000-0000-4000-8000-000000000000")

    def test_text_block_citations_not_dropped(self):
        snap = {"uuid": "c1", "snapshot_name": "t", "chat_messages": [
            {"uuid": "u", "index": 0, "sender": "human",
             "content": [{"type": "text", "text": "q"}]},
            {"uuid": "a", "index": 1, "sender": "assistant",
             "content": [{"type": "text", "text": "answer",
                          "citations": [{"url": "https://e.com", "title": "src"}]}]},
        ]}
        conv = extract(snap)
        block = conv["messages"][1]["blocks"][0]
        self.assertEqual(block["type"], "text")
        self.assertEqual(block["citations"][0]["url"], "https://e.com")

    def test_unknown_block_not_silently_dropped(self):
        snap = {"uuid": "c2", "snapshot_name": "t", "chat_messages": [
            {"uuid": "u", "index": 0, "sender": "human", "content": [{"type": "text", "text": "q"}]},
            {"uuid": "a", "index": 1, "sender": "assistant", "content": [
                {"type": "image", "source": {"kind": "url", "url": "https://e.com/x.png"}},
                {"type": "text", "text": "done"},
            ]},
        ]}
        conv = extract(snap)
        blocks = conv["messages"][1]["blocks"]
        unknown = [b for b in blocks if b["type"] == "unknown"]
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]["subtype"], "image")
        self.assertEqual(unknown[0]["raw"]["source"]["url"], "https://e.com/x.png")


class ArtifactHistoryTest(unittest.TestCase):
    def test_version_history(self):
        conv = extract(fixture("rich.json"), Options(tools=True))
        art = conv["artifacts"][0]
        self.assertEqual(art["versions"], 2)
        self.assertEqual([h["action"] for h in art["history"]], ["create", "update"])
        self.assertIn("12%", art["history"][0]["content"])
        self.assertIn("15%", art["history"][1]["content"])
        self.assertNotIn("12%", art["history"][1]["content"])

    def test_change_events_record_apply_and_failure(self):
        events = extract(fixture("rich.json"))["artifact_events"]
        self.assertTrue(all(e["applied"] for e in events))
        self.assertEqual([e["action"] for e in events], ["create", "update"])

        snap = {"uuid": "c3", "snapshot_name": "t", "chat_messages": [
            {"uuid": "u", "index": 0, "sender": "human", "content": [{"type": "text", "text": "q"}]},
            {"uuid": "a", "index": 1, "sender": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "artifacts",
                 "input": {"command": "update", "id": "r", "old_str": "nope", "new_str": "x"}},
            ]},
        ]}
        conv = extract(snap)
        self.assertEqual(len(conv["artifacts"]), 0)
        self.assertFalse(conv["artifact_events"][0]["applied"])
        self.assertTrue(conv["artifact_events"][0]["reason"])
        self.assertTrue(any("could not be applied" in w for w in conv["warnings"]))


class NoMutationTest(unittest.TestCase):
    def test_snapshot_not_mutated(self):
        snap = fixture("rich.json")
        before = copy.deepcopy(snap)
        extract(snap, Options(tools=True, thinking=True))
        self.assertEqual(snap, before)


if __name__ == "__main__":
    unittest.main()
