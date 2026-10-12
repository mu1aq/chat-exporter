import { normalizeForComparison } from './hash.js';

const ROLES = new Set(['user', 'assistant']);

function contentToMarkdown(content) {
  if (!content) return '';
  if (typeof content === 'string') return content;

  const parts = Array.isArray(content.parts) ? content.parts : [];
  const rendered = [];
  for (const part of parts) {
    if (typeof part === 'string') {
      rendered.push(part);
      continue;
    }
    if (!part || typeof part !== 'object') continue;

    // Multimodal share payloads vary. Preserve any textual representation and
    // leave an explicit marker for media that cannot be losslessly embedded.
    if (typeof part.text === 'string') rendered.push(part.text);
    else if (typeof part.content === 'string') rendered.push(part.content);
    else if (part.asset_pointer || part.image_url || part.url) {
      const target = part.image_url?.url ?? part.image_url ?? part.url ?? part.asset_pointer;
      rendered.push(`![shared media](${target})`);
    }
  }

  if (rendered.length) return rendered.join('\n');
  if (typeof content.text === 'string') return content.text;
  return '';
}

function messageFromNode(node) {
  const message = node?.message ?? node;
  const role = message?.author?.role ?? message?.role;
  if (!ROLES.has(role)) return null;
  const markdown = contentToMarkdown(message.content ?? message);
  return {
    role,
    markdown,
    plainText: markdown,
    sourceId: message.id ?? node?.id ?? null,
    createTime: message.create_time ?? message.createTime ?? null,
    source: 'structured'
  };
}

function mappingPath(candidate) {
  const mapping = candidate.mapping;
  const ids = Object.keys(mapping);
  if (!ids.length) return [];

  // Prefer the explicitly selected branch. Shared conversations can retain
  // abandoned branches in mapping; walking parents prevents duplicate replies.
  let leafId = candidate.current_node ?? candidate.currentNode ?? null;
  if (!leafId || !mapping[leafId]) {
    const leaves = ids.filter((id) => !ids.some((other) => mapping[other]?.parent === id));
    leafId = leaves.at(-1) ?? ids.at(-1);
  }

  const reversed = [];
  const seen = new Set();
  while (leafId && mapping[leafId] && !seen.has(leafId)) {
    seen.add(leafId);
    reversed.push(mapping[leafId]);
    leafId = mapping[leafId].parent;
  }
  return reversed.reverse();
}

function extractCandidate(value) {
  if (!value || typeof value !== 'object') return null;

  if (value.mapping && typeof value.mapping === 'object' && !Array.isArray(value.mapping)) {
    const messages = mappingPath(value).map(messageFromNode).filter(Boolean);
    if (messages.length) return { title: value.title ?? null, messages };
  }

  for (const key of ['messages', 'conversation', 'data']) {
    const nested = value[key];
    if (Array.isArray(nested)) {
      const messages = nested.map(messageFromNode).filter(Boolean);
      if (messages.length) return { title: value.title ?? null, messages };
    }
  }
  return null;
}

/** Search nested JSON for the strongest conversation-shaped object. */
export function findStructuredConversation(root) {
  const queue = [root];
  const seen = new Set();
  let best = null;

  while (queue.length) {
    const value = queue.shift();
    if (!value || typeof value !== 'object' || seen.has(value)) continue;
    seen.add(value);

    const candidate = extractCandidate(value);
    if (candidate && (!best || candidate.messages.length > best.messages.length)) best = candidate;

    if (seen.size > 50_000) break;
    for (const child of Array.isArray(value) ? value : Object.values(value)) {
      if (child && typeof child === 'object') queue.push(child);
    }
  }
  return best;
}

export function parseJsonScripts(scripts) {
  const values = [];
  for (const script of scripts) {
    const trimmed = script.trim();
    if (!trimmed) continue;
    try {
      values.push(JSON.parse(trimmed));
      continue;
    } catch {
      // Some frameworks assign a JSON object to a global variable.
    }
    const first = trimmed.indexOf('{');
    const last = trimmed.lastIndexOf('}');
    if (first >= 0 && last > first) {
      try {
        values.push(JSON.parse(trimmed.slice(first, last + 1)));
      } catch {
        // RSC/JavaScript payloads are intentionally not evaluated.
      }
    }
  }
  return values;
}

export function roleSequence(messages) {
  return messages.map((message) => message.role).join(',');
}

export function textSequence(messages) {
  return messages.map((message) => normalizeForComparison(message.plainText ?? message.markdown));
}

