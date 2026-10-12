import hashlib
import json
import unittest

from helpers import TempDir

from claude_share_extract import audit


class HashTest(unittest.TestCase):
    def test_sha256_helpers_agree(self):
        data = "안녕 hello".encode("utf-8")
        self.assertEqual(audit.sha256_bytes(data), hashlib.sha256(data).hexdigest())
        self.assertEqual(audit.sha256_text("안녕 hello"), hashlib.sha256(data).hexdigest())

    def test_sha256_file(self):
        with TempDir() as d:
            p = d / "x.bin"
            p.write_bytes(b"\x00\x01\x02binary\n")
            self.assertEqual(audit.sha256_file(p), hashlib.sha256(b"\x00\x01\x02binary\n").hexdigest())


class BuildTest(unittest.TestCase):
    def test_build_audit_sorted_and_hashed(self):
        files = {"b/c.json": b"{}", "a.txt": b"hello"}
        rep = audit.build_audit(files, provider="claude", source={"share_id": "x"})
        self.assertEqual(rep["schemaVersion"], audit.SCHEMA_VERSION)
        self.assertEqual([e["path"] for e in rep["files"]], ["a.txt", "b/c.json"])
        self.assertEqual(rep["files"][0]["sha256"], hashlib.sha256(b"hello").hexdigest())
        self.assertEqual(rep["files"][0]["bytes"], 5)
        self.assertEqual(rep["fileCount"], 2)
        self.assertEqual(rep["provider"], "claude")

    def test_validate_schema(self):
        good = audit.build_audit({"a.txt": b"hi"})
        self.assertEqual(audit.validate_schema(good), [])
        self.assertTrue(audit.validate_schema({"files": []}))          # schemaVersion/tool 누락
        self.assertTrue(audit.validate_schema("nope"))
        bad = {"schemaVersion": 1, "tool": {}, "files": [{"path": "a", "sha256": "short", "bytes": 1}]}
        self.assertTrue(any("sha256" in e for e in audit.validate_schema(bad)))


class VerifyTest(unittest.TestCase):
    def _bundle(self, d):
        (d / "a.txt").write_bytes(b"hello")
        (d / "sub").mkdir()
        (d / "sub" / "c.json").write_bytes(b"{}")
        files = {"a.txt": b"hello", "sub/c.json": b"{}"}
        rep = audit.build_audit(files)
        (d / "audit.json").write_text(json.dumps(rep), encoding="utf-8")
        return rep

    def test_verify_ok(self):
        with TempDir() as d:
            self._bundle(d)
            res = audit.verify(d / "audit.json")
            self.assertTrue(res["ok"], res)
            self.assertEqual(sorted(res["checked"]), ["a.txt", "sub/c.json"])

    def test_verify_detects_tamper(self):
        with TempDir() as d:
            self._bundle(d)
            (d / "a.txt").write_bytes(b"HELLO")  # 바이트 변조
            res = audit.verify(d / "audit.json")
            self.assertFalse(res["ok"])
            self.assertEqual(res["mismatches"][0]["path"], "a.txt")

    def test_verify_detects_missing(self):
        with TempDir() as d:
            self._bundle(d)
            (d / "sub" / "c.json").unlink()
            res = audit.verify(d / "audit.json")
            self.assertFalse(res["ok"])
            self.assertEqual(res["missing"], ["sub/c.json"])

    def test_verify_dict_with_base_dir(self):
        with TempDir() as d:
            rep = self._bundle(d)
            res = audit.verify(rep, d)
            self.assertTrue(res["ok"], res)


if __name__ == "__main__":
    unittest.main()
