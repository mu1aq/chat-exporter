import test from 'node:test';
import assert from 'node:assert/strict';
import { parseArgs } from '../src/cli.js';

test('parses shorthand extraction and explicit options', () => {
  const parsed = parseArgs([
    'https://chatgpt.com/share/12345678',
    '--output', 'chat.txt', '--format', 'txt', '--strict', '--save-html'
  ]);
  assert.equal(parsed.command, 'extract');
  assert.equal(parsed.positional[0], 'https://chatgpt.com/share/12345678');
  assert.equal(parsed.output, 'chat.txt');
  assert.equal(parsed.format, 'txt');
  assert.equal(parsed.strict, true);
  assert.equal(parsed.saveHtml, true);
});

test('rejects an option with a missing value', () => {
  assert.throws(() => parseArgs(['extract', 'https://chatgpt.com/share/12345678', '--output']), /Missing value/);
});
