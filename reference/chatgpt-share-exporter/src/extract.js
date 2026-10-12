import path from 'node:path';
import { mkdir, writeFile } from 'node:fs/promises';
import { captureSharePage } from './browser.js';
import { htmlToMarkdown } from './markdown.js';
import { findStructuredConversation, parseJsonScripts, roleSequence } from './structured.js';
import { validateCapture } from './validate.js';
import { createAudit, renderMarkdown, renderText } from './render.js';
import { validateShareUrl } from './url.js';

function domMessagesFromCapture(dom) {
  return dom.records.map((record) => ({
    role: record.role,
    markdown: htmlToMarkdown(record.html),
    plainText: record.plainText,
    sourceId: record.sourceId,
    turnIndex: record.turnIndex,
    source: record.source
  }));
}

function strongestStructured(capture) {
  const candidates = [];
  for (const entry of capture.networkJson) {
    const found = findStructuredConversation(entry.body);
    if (found) candidates.push(found);
  }
  for (const value of parseJsonScripts(capture.dom.scripts)) {
    const found = findStructuredConversation(value);
    if (found) candidates.push(found);
  }
  return candidates.sort((a, b) => b.messages.length - a.messages.length)[0] ?? null;
}

function chooseMessages(domMessages, structured) {
  const structuredMessages = structured?.messages ?? [];
  if (structuredMessages.length && domMessages.length === structuredMessages.length &&
      roleSequence(domMessages) === roleSequence(structuredMessages)) {
    return { messages: structuredMessages, extractionPath: 'structured-data (DOM cross-checked)' };
  }
  if (!domMessages.length && structuredMessages.length) {
    return { messages: structuredMessages, extractionPath: 'structured-data (DOM unavailable)' };
  }
  return { messages: domMessages, extractionPath: 'rendered-DOM' };
}

export async function extractConversation(url, options = {}) {
  const sourceUrl = validateShareUrl(url);
  const capture = await captureSharePage(sourceUrl, options);
  const domMessages = domMessagesFromCapture(capture.dom);
  const structured = strongestStructured(capture);
  const structuredMessages = structured?.messages ?? [];
  const selected = chooseMessages(domMessages, structured);
  const conversation = {
    title: structured?.title ?? capture.dom.title ?? 'ChatGPT shared conversation',
    messages: selected.messages
  };
  const validation = validateCapture({
    messages: selected.messages,
    domMessages,
    structuredMessages,
    capture
  });

  return {
    conversation,
    capture,
    validation,
    metadata: {
      sourceUrl,
      exportedAt: new Date().toISOString(),
      extractionPath: selected.extractionPath,
      domMessageCount: domMessages.length,
      structuredMessageCount: structuredMessages.length
    }
  };
}

export async function saveExtraction(result, options) {
  const format = options.format ?? (path.extname(options.output).toLowerCase() === '.txt' ? 'text' : 'markdown');
  const outputText = format === 'text'
    ? renderText(result.conversation, result.metadata)
    : renderMarkdown(result.conversation, result.metadata);
  const outputPath = path.resolve(options.output);
  const auditPath = options.auditPath
    ? path.resolve(options.auditPath)
    : `${outputPath}.audit.json`;

  await mkdir(path.dirname(outputPath), { recursive: true });
  await mkdir(path.dirname(auditPath), { recursive: true });
  await writeFile(outputPath, outputText, 'utf8');
  const audit = createAudit({
    ...result,
    outputText,
    outputPath,
    capture: result.capture
  });
  await writeFile(auditPath, `${JSON.stringify(audit, null, 2)}\n`, 'utf8');

  let htmlPath = null;
  if (options.saveHtml) {
    htmlPath = await saveHtmlSnapshot(result, options);
  }
  return { outputPath, auditPath, htmlPath, audit };
}

export async function saveHtmlSnapshot(result, options) {
  const outputPath = path.resolve(options.output);
  const htmlPath = options.htmlPath ? path.resolve(options.htmlPath) : `${outputPath}.source.html`;
  await mkdir(path.dirname(htmlPath), { recursive: true });
  await writeFile(htmlPath, result.capture.html, 'utf8');
  return htmlPath;
}

