import test from 'node:test';
import assert from 'node:assert/strict';
import { htmlToMarkdown } from '../src/markdown.js';

test('preserves headings, fenced code language, table and line breaks', () => {
  const html = `
    <div class="markdown">
      <h2>Result</h2>
      <p>first<br>second</p>
      <pre><code class="language-js">const x = 1;\nconsole.log(x);\n</code></pre>
      <table><thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>
    </div>`;
  const markdown = htmlToMarkdown(html);
  assert.match(markdown, /## Result/);
  assert.match(markdown, /first\s{2}\nsecond/);
  assert.match(markdown, /```js\nconst x = 1;/);
  assert.match(markdown, /\| A \| B \|/);
});

test('uses a longer fence when code contains triple backticks', () => {
  const markdown = htmlToMarkdown('<pre><code>```\ninside\n```</code></pre>');
  assert.match(markdown, /````\n```\ninside/);
});
