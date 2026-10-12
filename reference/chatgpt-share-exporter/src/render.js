import { sha256 } from './hash.js';

function cleanTitle(title) {
  return String(title || 'ChatGPT shared conversation').replace(/[\r\n]+/g, ' ').trim();
}

export function renderMarkdown(conversation, metadata) {
  const lines = [
    `# ${cleanTitle(conversation.title)}`,
    '',
    `> Source: ${metadata.sourceUrl}`,
    `> Exported: ${metadata.exportedAt}`,
    `> Messages: ${conversation.messages.length}`,
    `> Extraction path: ${metadata.extractionPath}`,
    '',
    '---',
    ''
  ];

  conversation.messages.forEach((message, index) => {
    const label = message.role === 'user' ? 'User' : 'Assistant';
    lines.push(`## ${index + 1}. ${label}`, '', message.markdown, '', '---', '');
  });
  return `${lines.join('\n').replace(/\n+$/g, '')}\n`;
}

export function renderText(conversation, metadata) {
  const lines = [
    cleanTitle(conversation.title),
    `Source: ${metadata.sourceUrl}`,
    `Exported: ${metadata.exportedAt}`,
    `Messages: ${conversation.messages.length}`,
    ''
  ];
  conversation.messages.forEach((message, index) => {
    lines.push(
      `===== MESSAGE ${index + 1} / ${message.role.toUpperCase()} =====`,
      message.markdown,
      `===== END MESSAGE ${index + 1} =====`,
      ''
    );
  });
  return `${lines.join('\n').replace(/\n+$/g, '')}\n`;
}

export function createAudit({ conversation, metadata, validation, outputText, outputPath, capture }) {
  return {
    schemaVersion: 1,
    tool: { name: 'chatgpt-share-exporter', version: '1.0.0' },
    sourceUrl: metadata.sourceUrl,
    finalUrl: capture.finalUrl,
    exportedAt: metadata.exportedAt,
    title: conversation.title,
    outputPath,
    outputSha256: sha256(outputText),
    extractionPath: metadata.extractionPath,
    selectedMessageCount: conversation.messages.length,
    domMessageCount: metadata.domMessageCount,
    structuredMessageCount: metadata.structuredMessageCount,
    roleSequence: conversation.messages.map((message) => message.role),
    messages: conversation.messages.map((message, index) => ({
      index: index + 1,
      role: message.role,
      sourceId: message.sourceId ?? null,
      turnIndex: message.turnIndex ?? null,
      source: message.source,
      characters: message.markdown.length,
      sha256: sha256(message.markdown)
    })),
    capture: {
      httpStatus: capture.status,
      selector: capture.dom.selector,
      countObservations: capture.observations,
      tocPromptCount: capture.traversal?.tocPromptCount ?? 0,
      tocPromptsVisited: capture.traversal?.tocPromptsVisited ?? 0,
      uniqueMessageCounts: capture.traversal?.uniqueMessageCounts ?? [],
      traversalDeadlineReached: capture.traversal?.deadlineReached ?? false,
      documentLanguage: capture.dom.documentLanguage,
      networkJsonResponses: capture.networkJson.map((entry) => ({ url: entry.url, status: entry.status }))
    },
    validation,
    limitations: [
      'This report proves the saved bytes have not changed since export; it cannot prove the shared page itself exposed every original token.',
      'Rendered HTML may normalize equivalent Markdown syntax and may omit unsupported interactive/media content.',
      'ChatGPT share-page markup and private payload schemas are not a stable public export API.'
    ]
  };
}

