import unittest

from shared_chat_exporter.router import detect_provider, main, route_url, routes_from_args


CHATGPT = "https://chatgpt.com/share/6749af1c-0e14-8012-8830-ce0554744fc3"
CLAUDE = "https://claude.ai/share/3b8f2c1e-5a6d-4e7f-9a0b-1c2d3e4f5a6b"


class DispatchTest(unittest.TestCase):
    def test_detects_exact_provider_host(self):
        self.assertEqual(detect_provider(CHATGPT), "chatgpt")
        self.assertEqual(detect_provider(CLAUDE), "claude")
        self.assertEqual(detect_provider("chatgpt.com/share/6749af1c-0e14-8012-8830-ce0554744fc3"), "chatgpt")
        self.assertIsNone(detect_provider("http://chatgpt.com/share/6749af1c-0e14-8012-8830-ce0554744fc3"))
        self.assertIsNone(detect_provider("https://chatgpt.com.evil.test/share/12345678"))
        self.assertIsNone(detect_provider("https://example.test/?next=chatgpt.com/share/12345678"))

    def test_routes_to_provider_dependency(self):
        gpt = route_url(CHATGPT)
        claude = route_url(CLAUDE)
        self.assertEqual((gpt.provider, gpt.module), ("chatgpt", "shared_chat_exporter.chatgpt"))
        self.assertEqual((claude.provider, claude.module), ("claude", "shared_chat_exporter.snapshot"))
        self.assertEqual(gpt.canonical_url, CHATGPT)
        self.assertEqual(claude.canonical_url, CLAUDE)

    def test_finds_multiple_provider_links_in_cli_args(self):
        routes = routes_from_args([CHATGPT, CLAUDE, "--bundle", "out/archive"])
        self.assertEqual([route.provider for route in routes], ["chatgpt", "claude"])

    def test_detect_command(self):
        self.assertEqual(main(["--detect", CHATGPT]), 0)
        self.assertEqual(main(["--detect", CLAUDE]), 0)


if __name__ == "__main__":
    unittest.main()
