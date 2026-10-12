import { normalizeForComparison } from './hash.js';
import { roleSequence } from './structured.js';

const BLOCKED_PATTERNS = [
  /conversation (?:is )?(?:unavailable|not found)/i,
  /shared link (?:has been )?(?:deleted|disabled|expired)/i,
  /you (?:do not|don't) have access/i,
  /workspace.*(?:access|member|permission)/i,
  /sign in to (?:view|continue)/i,
  /unable to load (?:conversation|shared)/i,
  /something went wrong/i,
  /what(?:’|'|)s on your mind today/i
];

export function validateCapture({ messages, domMessages, structuredMessages, capture }) {
  const errors = [];
  const warnings = [];

  if (!messages.length) {
    const hint = BLOCKED_PATTERNS.find((pattern) => pattern.test(capture.dom.bodyText));
    errors.push(hint
      ? 'No messages were found; the page displays a known unavailable, restricted, sign-in, or new-chat state.'
      : 'No user/assistant messages were found. The page layout may have changed or the link is unavailable.');
  }

  messages.forEach((message, index) => {
    if (!['user', 'assistant'].includes(message.role)) errors.push(`Message ${index + 1} has an unsupported role.`);
    if (!normalizeForComparison(message.markdown)) warnings.push(`Message ${index + 1} (${message.role}) is empty after conversion.`);
  });

  if (domMessages.length && structuredMessages.length) {
    if (domMessages.length !== structuredMessages.length) {
      warnings.push(`Cross-check mismatch: DOM found ${domMessages.length} messages, structured data found ${structuredMessages.length}.`);
    } else if (roleSequence(domMessages) !== roleSequence(structuredMessages)) {
      warnings.push('Cross-check mismatch: DOM and structured data have different role order.');
    }
  }

  const observed = capture.observations ?? [];
  if (observed.length >= 2 && observed.at(-1) !== observed.at(-2)) {
    warnings.push('Message count had not stabilized before capture; lazy-loaded content may be missing.');
  }
  if (/…\s*$|\.\.\.\s*$/.test(messages.at(-1)?.markdown ?? '')) {
    warnings.push('The final message ends in an ellipsis. This may be intentional, but review it for truncation.');
  }
  const tocPromptCount = capture.traversal?.tocPromptCount ?? 0;
  const userCount = messages.filter((message) => message.role === 'user').length;
  if (tocPromptCount && userCount !== tocPromptCount) {
    warnings.push(`Possible omission: the page exposes ${tocPromptCount} prompt markers, but ${userCount} user messages were collected.`);
  }
  if (capture.traversal?.deadlineReached) {
    warnings.push('The virtualized-message traversal reached its time limit; review the prompt/message counts for omissions.');
  }
  if (capture.finalUrl !== capture.dom.pageUrl) warnings.push('Final browser URL and DOM URL disagree.');

  return { errors, warnings };
}

