import test from 'node:test';
import assert from 'node:assert/strict';
import { validateShareUrl, shareIdFromUrl } from '../src/url.js';

test('accepts and normalizes a public ChatGPT share URL', () => {
  const input = 'https://chatgpt.com/share/6ac8fcff-9b64-83e8-bd25-d8d85bf215d2/?utm_source=x#fragment';
  assert.equal(validateShareUrl(input), 'https://chatgpt.com/share/6ac8fcff-9b64-83e8-bd25-d8d85bf215d2');
  assert.equal(shareIdFromUrl(input), '6ac8fcff-9b64-83e8-bd25-d8d85bf215d2');
});

for (const value of [
  'http://chatgpt.com/share/abcdefghi',
  'https://example.com/share/abcdefghi',
  'https://chatgpt.com.evil.example/share/abcdefghi',
  'https://user:pass@chatgpt.com/share/abcdefghi',
  'https://chatgpt.com:444/share/abcdefghi',
  'https://chatgpt.com/c/abcdefghi',
  'https://chatgpt.com/share/short'
]) {
  test(`rejects unsafe or unsupported URL: ${value}`, () => {
    assert.throws(() => validateShareUrl(value));
  });
}
