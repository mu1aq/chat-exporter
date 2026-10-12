import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createAudit, renderMarkdown, renderText } from '../src/render.js';
import { verifyExport } from '../src/verify.js';

const conversation = {
  title: 'Example',
  messages: [
    { role: 'user', markdown: 'line 1\nline 2', source: 'test', sourceId: 'u1' },
    { role: 'assistant', markdown: '| A |\n|---|\n| B |', source: 'test', sourceId: 'a1' }
  ]
};
const metadata = {
  sourceUrl: 'https://chatgpt.com/share/12345678',
  exportedAt: '2026-10-10T00:00:00.000Z',
  extractionPath: 'test',
  domMessageCount: 2,
  structuredMessageCount: 2
};
const capture = {
  finalUrl: metadata.sourceUrl,
  status: 200,
  dom: { selector: 'test', documentLanguage: 'en' },
  observations: [2, 2, 2],
  networkJson: []
};

test('renders messages in order in Markdown and text', () => {
  const markdown = renderMarkdown(conversation, metadata);
  const text = renderText(conversation, metadata);
  assert.ok(markdown.indexOf('## 1. User') < markdown.indexOf('## 2. Assistant'));
  assert.ok(text.indexOf('MESSAGE 1 / USER') < text.indexOf('MESSAGE 2 / ASSISTANT'));
  assert.match(markdown, /line 1\nline 2/);
});

test('audit verification detects later modification', async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'share-export-'));
  const outputPath = path.join(directory, 'chat.md');
  const auditPath = `${outputPath}.audit.json`;
  const outputText = renderMarkdown(conversation, metadata);
  const audit = createAudit({
    conversation,
    metadata,
    validation: { errors: [], warnings: [] },
    outputText,
    outputPath,
    capture
  });
  await writeFile(outputPath, outputText, 'utf8');
  await writeFile(auditPath, JSON.stringify(audit), 'utf8');
  assert.equal((await verifyExport(outputPath)).ok, true);

  const original = await readFile(outputPath, 'utf8');
  await writeFile(outputPath, `${original}tampered`, 'utf8');
  assert.equal((await verifyExport(outputPath)).ok, false);
});
