import TurndownService from 'turndown';
import { gfm } from 'turndown-plugin-gfm';

function longestBacktickRun(text) {
  return Math.max(0, ...Array.from(text.matchAll(/`+/g), (match) => match[0].length));
}

export function createTurndownService() {
  const service = new TurndownService({
    headingStyle: 'atx',
    bulletListMarker: '-',
    codeBlockStyle: 'fenced',
    fence: '```',
    emDelimiter: '*',
    strongDelimiter: '**',
    linkStyle: 'inlined',
    preformattedCode: true
  });
  service.use(gfm);

  service.addRule('chatgptMath', {
    filter(node) {
      if (node.nodeName !== 'SPAN' && node.nodeName !== 'DIV') return false;
      const classes = node.getAttribute?.('class') ?? '';
      return classes.split(/\s+/).includes('katex');
    },
    replacement(_content, node) {
      const tex = node.querySelector?.('annotation[encoding="application/x-tex"]')?.textContent;
      if (!tex) return node.textContent ?? '';
      const display = (node.getAttribute?.('class') ?? '').includes('katex-display') || node.parentElement?.classList?.contains('katex-display');
      return display ? `\n\n$$\n${tex}\n$$\n\n` : `$${tex}$`;
    }
  });

  service.addRule('languageAwareCodeBlock', {
    filter: 'pre',
    replacement(_content, node) {
      const code = node.querySelector?.('code');
      const raw = (code?.textContent ?? node.textContent ?? '').replace(/\n$/, '');
      const classes = `${code?.getAttribute?.('class') ?? ''} ${node.getAttribute?.('class') ?? ''}`;
      const language = classes.match(/(?:lang(?:uage)?-)([\w.+#-]+)/i)?.[1] ?? '';
      const fence = '`'.repeat(Math.max(3, longestBacktickRun(raw) + 1));
      return `\n\n${fence}${language}\n${raw}\n${fence}\n\n`;
    }
  });

  // ChatGPT user messages often use CSS white-space: pre-wrap instead of <p>.
  // Text-node newlines must survive the HTML-to-Markdown conversion.
  service.addRule('preWrap', {
    filter(node) {
      return node.nodeName === 'DIV' && /(?:^|\s)whitespace-pre-wrap(?:\s|$)/.test(node.getAttribute?.('class') ?? '');
    },
    replacement(content) {
      return `\n\n${content}\n\n`;
    }
  });

  return service;
}

export function htmlToMarkdown(html) {
  return createTurndownService()
    .turndown(html)
    .replace(/\r\n?/g, '\n')
    // Do not trim spaces before a newline: two trailing spaces are Markdown's
    // explicit hard-break syntax and are produced from <br>.
    .replace(/\n[ \t]+\n/g, '\n\n')
    .replace(/^\n+|\n+$/g, '');
}

