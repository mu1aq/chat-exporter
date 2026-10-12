import base64
import copy
import json
import unittest

from helpers import TempDir, fixture, fixture_text

from shared_chat_exporter import audit
from shared_chat_exporter.bundle import write_bundle
from shared_chat_exporter.exporters import export
from shared_chat_exporter.extract import Options, extract


def _rich_bundle(d, **kw):
    raw = fixture_text("rich.json")
    conv = extract(fixture("rich.json"), Options(tools=True, thinking=True))
    transcript = export([conv], "md")
    assets = [
        {"id": "f1", "name": "chart.png", "mime": "image/png"},                 # no bytes
        {"id": "f2", "name": "logo.png", "mime": "image/png", "data": b"\x89PNG\r\n"},  # has bytes
    ]
    manifest = write_bundle(d, conv, raw_source=raw, transcript=transcript, assets=assets, **kw)
    return conv, manifest


class BundleLayoutTest(unittest.TestCase):
    def test_core_files_written(self):
        with TempDir() as d:
            _rich_bundle(d)
            for rel in ("raw.json", "conversation.json", "transcript.md",
                        "manifest.json", "audit.json", "checksums.sha256"):
                self.assertTrue((d / rel).is_file(), rel)

    def test_raw_source_is_verbatim(self):
        with TempDir() as d:
            _rich_bundle(d)
            self.assertEqual((d / "raw.json").read_bytes(), fixture_text("rich.json").encode("utf-8"))

    def test_conversation_json_has_branches_and_artifacts(self):
        with TempDir() as d:
            _rich_bundle(d)
            conv = json.loads((d / "conversation.json").read_text(encoding="utf-8"))
            self.assertEqual(conv["provider"], "claude")
            self.assertEqual(len(conv["branches"]["paths"]), 2)
            self.assertEqual(conv["artifacts"][0]["versions"], 2)

    def test_all_artifact_versions_written(self):
        with TempDir() as d:
            _, manifest = _rich_bundle(d)
            art_dir = manifest["artifacts"][0]["dir"]
            self.assertTrue((d / art_dir / "v01.md").is_file())
            self.assertTrue((d / art_dir / "v02.md").is_file())
            self.assertTrue((d / art_dir / "latest.md").is_file())
            self.assertTrue((d / art_dir / "meta.json").is_file())
            self.assertIn("12%", (d / art_dir / "v01.md").read_text(encoding="utf-8"))
            self.assertIn("15%", (d / art_dir / "v02.md").read_text(encoding="utf-8"))

    def test_assets_fetched_and_dropped(self):
        with TempDir() as d:
            _, manifest = _rich_bundle(d)
            by_name = {a["name"]: a for a in manifest["assets"]}
            self.assertFalse(by_name["chart.png"]["fetched"])
            self.assertIsNone(by_name["chart.png"]["saved_path"])
            self.assertTrue(by_name["logo.png"]["fetched"])
            self.assertTrue((d / by_name["logo.png"]["saved_path"]).is_file())
            # an asset that could not be fetched goes into dropped with a reason
            self.assertTrue(any("chart.png" in x["item"] and x["reason"] for x in manifest["dropped"]))


class BundleAuditTest(unittest.TestCase):
    def test_audit_verifies(self):
        with TempDir() as d:
            _rich_bundle(d)
            res = audit.verify(d / "audit.json")
            self.assertTrue(res["ok"], res)
            self.assertIn("conversation.json", res["checked"])
            self.assertIn("manifest.json", res["checked"])

    def test_audit_detects_tamper(self):
        with TempDir() as d:
            _rich_bundle(d)
            (d / "conversation.json").write_bytes(b"{} tampered")
            res = audit.verify(d / "audit.json")
            self.assertFalse(res["ok"])
            self.assertTrue(any(m["path"] == "conversation.json" for m in res["mismatches"]))

    def test_checksums_cover_every_content_file(self):
        with TempDir() as d:
            _, manifest = _rich_bundle(d)
            lines = [ln for ln in (d / "checksums.sha256").read_text(encoding="utf-8").splitlines() if ln]
            paths = {ln.split("  ", 1)[1] for ln in lines}
            self.assertEqual(paths, set(manifest["contents"]))


class BundleSafetyTest(unittest.TestCase):
    def test_asset_name_collision(self):
        with TempDir() as d:
            conv = extract(fixture("basic.json"))
            assets = [{"name": "a.png", "data": b"1"}, {"name": "a.png", "data": b"2"}]
            manifest = write_bundle(d, conv, assets=assets)
            saved = sorted(a["saved_path"] for a in manifest["assets"])
            self.assertEqual(len(set(saved)), 2)
            for p in saved:
                self.assertTrue((d / p).is_file())

    def test_asset_path_traversal_contained(self):
        with TempDir() as d:
            conv = extract(fixture("basic.json"))
            manifest = write_bundle(d, conv, assets=[{"name": "../../evil.sh", "data": b"x"}])
            saved = manifest["assets"][0]["saved_path"]
            self.assertTrue(saved.startswith("assets/"))
            self.assertNotIn("..", saved)
            self.assertFalse((d.parent / "evil.sh").exists())

    def test_missing_raw_and_transcript_recorded_uncertain(self):
        with TempDir() as d:
            conv = extract(fixture("basic.json"))
            manifest = write_bundle(d, conv)  # no raw/transcript
            items = {x["item"] for x in manifest["uncertain"]}
            self.assertIn("raw source", items)
            self.assertIn("transcript", items)

    def test_conversation_dict_not_mutated(self):
        with TempDir() as d:
            conv = extract(fixture("rich.json"), Options(tools=True))
            before = copy.deepcopy(conv)
            write_bundle(d, conv, raw_source="x", transcript="y")
            self.assertEqual(conv, before)


class ProviderNeutralTest(unittest.TestCase):
    """The ChatGPT provider schema (branches=list, artifacts.versions=list, assets.content_base64) can also be bundled."""

    def _chatgpt_conv(self):
        return {
            "source": {"provider": "chatgpt", "share_id": "abc", "title": "t",
                       "share_url": "https://chatgpt.com/share/abc"},
            "turns": [{"turn": 1, "user_input": "hi", "agent_output": "yo"}],
            "messages": [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "yo"}],
            "branches": [
                {"id": "L", "leaf_id": "L", "is_active": True, "node_ids": ["n1"], "messages": [], "index": 0},
                {"id": "A", "leaf_id": "A", "is_active": False, "node_ids": ["n2"], "messages": [], "index": 1},
            ],
            "active_branch_id": "L",
            "artifacts": [{"key": "a1", "title": "Doc", "ext": "md", "content": "final", "language": "",
                           "versions": [{"version": 1, "content": "v1"}, {"version": 2, "content": "final"}]}],
            "assets": [
                {"id": "asset-1", "name": "img.png", "mime": "image/png", "fetched": True,
                 "content_base64": base64.b64encode(b"PNGDATA").decode("ascii")},
                {"id": "asset-2", "name": "big.bin", "fetched": False, "reason": "too big"},
            ],
            "stats": {"turns": 1, "messages": 2},
            "warnings": [],
        }

    def test_chatgpt_shape_bundles(self):
        with TempDir() as d:
            conv = self._chatgpt_conv()
            manifest = write_bundle(d, conv, assets=conv["assets"], provider="chatgpt")
            self.assertEqual(manifest["provider"], "chatgpt")
            self.assertEqual(manifest["branches"]["pathCount"], 2)
            self.assertEqual(manifest["branches"]["alternateCount"], 1)

            art_dir = manifest["artifacts"][0]["dir"]
            self.assertTrue((d / art_dir / "v01.md").is_file())
            self.assertEqual((d / art_dir / "v02.md").read_text(encoding="utf-8"), "final")

            by_name = {a["name"]: a for a in manifest["assets"]}
            self.assertTrue(by_name["img.png"]["fetched"])
            self.assertEqual((d / by_name["img.png"]["saved_path"]).read_bytes(), b"PNGDATA")
            self.assertTrue(any("big.bin" in x["item"] for x in manifest["dropped"]))

            res = audit.verify(d / "audit.json")
            self.assertTrue(res["ok"], res)


if __name__ == "__main__":
    unittest.main()
