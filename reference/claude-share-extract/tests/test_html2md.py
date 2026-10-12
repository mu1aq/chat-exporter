import unittest

from claude_share_extract.html2md import html_to_markdown, resource_refs


class HtmlToMarkdownTest(unittest.TestCase):
    def test_preserves_literal_pre_wrap_newlines(self):
        html = '<div class="whitespace-pre-wrap">line 1\n\nline 3\n- item</div>'
        self.assertEqual(html_to_markdown(html), "line 1\n\nline 3\n- item")

    def test_code_table_math_and_break(self):
        html = (
            '<h2>Result</h2><p>first<br>second</p>'
            '<pre><code class="language-js">const x = `a`;</code></pre>'
            '<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>'
            '<span class="katex"><annotation encoding="application/x-tex">x^2</annotation></span>'
        )
        md = html_to_markdown(html)
        self.assertIn("## Result", md)
        self.assertIn("first  \nsecond", md)
        self.assertIn("```js\nconst x = `a`;\n```", md)
        self.assertIn("| A | B |", md)
        self.assertIn("$x^2$", md)

    def test_lists_and_resources(self):
        md = html_to_markdown('<ol><li>one</li><li>two<ul><li>nested</li></ul></li></ol>')
        self.assertIn("1. one", md)
        self.assertIn("2. two", md)
        self.assertIn("- nested", md)
        refs = resource_refs('<img src="a.png" srcset="a-2x.png 2x, a-3x.png 3x" alt="A"><a download="x.csv" href="/x">x</a>')
        self.assertEqual([x["url"] for x in refs], ["a.png", "a-2x.png", "a-3x.png", "/x"])


if __name__ == "__main__":
    unittest.main()
