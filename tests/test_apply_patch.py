import unittest

from shared_chat_exporter.apply_patch import extract_patches, reconstruct

ADD = r'const p = "*** Begin Patch\n*** Add File: a.py\n+x = 1\n+y = 2\n*** End Patch";'
UPDATE = ("*** Begin Patch\n*** Update File: a.py\n@@\n x = 1\n-y = 2\n+y = 3\n*** End Patch")
BADUPDATE = ("*** Begin Patch\n*** Update File: a.py\n@@\n nope\n-missing\n+added\n*** End Patch")


class ExtractTest(unittest.TestCase):
    def test_unescapes_js_block(self):
        blocks = extract_patches(ADD)
        self.assertEqual(len(blocks), 1)
        self.assertIn("*** Add File: a.py", blocks[0])
        self.assertIn("\n+x = 1\n", blocks[0])

    def test_no_patch(self):
        self.assertEqual(extract_patches("plain text"), [])


class ReconstructTest(unittest.TestCase):
    def test_add_then_update(self):
        arts, fails = reconstruct(extract_patches(ADD) + [UPDATE])
        self.assertEqual(fails, 0)
        self.assertEqual(len(arts), 1)
        a = arts[0]
        self.assertEqual(a["key"], "a.py")
        self.assertEqual(a["ext"], "py")
        self.assertEqual(a["versions"], 2)
        self.assertEqual(a["content"], "x = 1\ny = 3\n")
        self.assertEqual([h["action"] for h in a["history"]], ["create", "update"])

    def test_unmatched_hunk_is_reported_not_fabricated(self):
        arts, fails = reconstruct(extract_patches(ADD) + [BADUPDATE])
        self.assertEqual(fails, 1)
        self.assertEqual(arts[0]["content"], "x = 1\ny = 2\n")  # unchanged


if __name__ == "__main__":
    unittest.main()
