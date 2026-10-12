/**
 * This function is stringified and executed inside the Playwright page. Keep it
 * self-contained: it may not close over Node variables.
 */
export function collectRenderedConversation(options = {}) {
  const roleSelector = '[data-message-author-role="user"], [data-message-author-role="assistant"]';
  const directRoleNodes = [...document.querySelectorAll(roleSelector)].filter((node) => {
    const parent = node.parentElement?.closest(roleSelector);
    return !parent;
  });

  function cleanClone(node) {
    const clone = node.cloneNode(true);
    const removeSelectors = [
      'script', 'style', 'noscript', 'template', 'button', 'svg',
      '[aria-hidden="true"]', '[data-testid*="copy"]', '[data-testid*="feedback"]',
      '[data-testid*="action"]', '.sr-only'
    ];
    for (const element of clone.querySelectorAll(removeSelectors.join(','))) element.remove();
    for (const element of clone.querySelectorAll('*')) {
      for (const attribute of [...element.attributes]) {
        if (/^on/i.test(attribute.name)) element.removeAttribute(attribute.name);
      }
    }
    return clone;
  }

  function fromRoleNode(node) {
    const role = node.getAttribute('data-message-author-role');
    const clone = cleanClone(node);
    const turn = node.closest('[data-testid^="conversation-turn-"]');
    const turnIndexMatch = turn?.getAttribute('data-testid')?.match(/conversation-turn-(\d+)/);
    return {
      role,
      html: clone.innerHTML,
      plainText: node.innerText ?? node.textContent ?? '',
      sourceId: node.closest('[data-message-id]')?.getAttribute('data-message-id') ??
        node.getAttribute('data-message-id') ?? null,
      turnIndex: turnIndexMatch ? Number(turnIndexMatch[1]) : null,
      source: 'dom-role-attribute'
    };
  }

  let records = directRoleNodes.map(fromRoleNode);
  let selector = 'data-message-author-role';

  if (!records.length) {
    selector = 'conversation-turn-article';
    const turns = [...document.querySelectorAll('[data-testid^="conversation-turn-"]')];
    records = turns.map((article) => {
      const explicit = article.querySelector(roleSelector);
      let role = explicit?.getAttribute('data-message-author-role') ?? null;
      if (!role) {
        const label = `${article.getAttribute('aria-label') ?? ''} ${article.innerText.slice(0, 100)}`.toLowerCase();
        if (/\byou said\b|\buser\b/.test(label)) role = 'user';
        else if (/\bchatgpt said\b|\bassistant\b/.test(label)) role = 'assistant';
      }
      if (!role) return null;
      const content = explicit ?? article;
      const clone = cleanClone(content);
      return {
        role,
        html: clone.innerHTML,
        plainText: content.innerText ?? content.textContent ?? '',
        sourceId: article.getAttribute('data-message-id') ?? article.getAttribute('data-testid'),
        turnIndex: Number(article.getAttribute('data-testid')?.match(/conversation-turn-(\d+)/)?.[1] ?? NaN),
        source: 'dom-turn-article'
      };
    }).filter(Boolean);
  }

  const scripts = options.messagesOnly ? [] : [...document.scripts]
    .filter((script) => script.type === 'application/json' || script.id === '__NEXT_DATA__')
    .map((script) => script.textContent ?? '')
    .filter(Boolean);

  const documentTitle = document.title.replace(/\s*[|–-]\s*ChatGPT\s*$/i, '').trim();
  const openGraphTitle = document.querySelector('meta[property="og:title"]')?.content?.trim();
  const openGraphDescription = document.querySelector('meta[property="og:description"]')?.content?.trim();
  const genericTitles = new Set(['ChatGPT', 'Check out this chat', 'Shared Chat']);
  const title = (!genericTitles.has(documentTitle) && documentTitle) ||
    document.querySelector('main h1')?.textContent?.trim() ||
    (!genericTitles.has(openGraphTitle) && openGraphTitle) ||
    openGraphDescription || documentTitle || openGraphTitle || null;
  const bodyText = options.messagesOnly ? '' : (document.body?.innerText ?? '');

  return {
    records,
    selector,
    scripts,
    title,
    bodyText: bodyText.slice(0, 50_000),
    pageUrl: location.href,
    documentLanguage: document.documentElement.lang || null
  };
}

