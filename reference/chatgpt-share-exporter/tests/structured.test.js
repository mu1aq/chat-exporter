import test from 'node:test';
import assert from 'node:assert/strict';
import { findStructuredConversation, parseJsonScripts } from '../src/structured.js';

function node(id, parent, role, text) {
  return {
    id,
    parent,
    children: [],
    message: role ? { id: `m-${id}`, author: { role }, content: { content_type: 'text', parts: [text] } } : null
  };
}

test('reconstructs only the selected current_node branch', () => {
  const root = node('root', null, null, '');
  const user = node('u1', 'root', 'user', 'hello');
  const abandoned = node('a-old', 'u1', 'assistant', 'old answer');
  const selected = node('a-new', 'u1', 'assistant', 'new **answer**');
  root.children = ['u1'];
  user.children = ['a-old', 'a-new'];

  const payload = { data: { title: 'Branched chat', current_node: 'a-new', mapping: { root, u1: user, 'a-old': abandoned, 'a-new': selected } } };
  const result = findStructuredConversation(payload);
  assert.equal(result.title, 'Branched chat');
  assert.deepEqual(result.messages.map((message) => [message.role, message.markdown]), [
    ['user', 'hello'],
    ['assistant', 'new **answer**']
  ]);
});

test('parses JSON script blocks without evaluating JavaScript', () => {
  assert.equal(parseJsonScripts(['{"title":"x"}', 'window.bad = alert(1)']).length, 1);
});
