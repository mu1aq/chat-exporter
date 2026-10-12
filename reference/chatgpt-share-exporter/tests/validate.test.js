import test from 'node:test';
import assert from 'node:assert/strict';
import { validateCapture } from '../src/validate.js';

test('reports missing messages and a restricted-page hint', () => {
  const result = validateCapture({
    messages: [],
    domMessages: [],
    structuredMessages: [],
    capture: { dom: { bodyText: 'You do not have access to this workspace conversation.' }, observations: [] }
  });
  assert.equal(result.errors.length, 1);
  assert.match(result.errors[0], /restricted|unavailable/i);
});

test('warns when cross-check counts disagree', () => {
  const message = { role: 'user', markdown: 'hello' };
  const result = validateCapture({
    messages: [message],
    domMessages: [message],
    structuredMessages: [message, { role: 'assistant', markdown: 'hi' }],
    capture: { finalUrl: 'x', dom: { bodyText: '', pageUrl: 'x' }, observations: [1, 1] }
  });
  assert.match(result.warnings.join('\n'), /mismatch/i);
});

test('warns when virtualized prompt markers outnumber collected user messages', () => {
  const message = { role: 'user', markdown: 'hello' };
  const result = validateCapture({
    messages: [message],
    domMessages: [message],
    structuredMessages: [],
    capture: {
      finalUrl: 'x',
      dom: { bodyText: '', pageUrl: 'x' },
      observations: [1, 1],
      traversal: { tocPromptCount: 3, deadlineReached: false }
    }
  });
  assert.match(result.warnings.join('\n'), /Possible omission/);
});
