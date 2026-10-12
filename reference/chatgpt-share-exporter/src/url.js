const SHARE_ID = /^[A-Za-z0-9_-]{8,200}$/;

/**
 * Strictly validate a public ChatGPT conversation share URL. This deliberately
 * rejects arbitrary hosts, ports and credentials so the browser cannot be used
 * as a general-purpose URL fetcher (SSRF/open-redirect footgun).
 */
export function validateShareUrl(input) {
  let url;
  try {
    url = new URL(input);
  } catch {
    throw new Error('Invalid URL. Expected https://chatgpt.com/share/<conversation-id>');
  }

  if (url.protocol !== 'https:') {
    throw new Error('Only HTTPS ChatGPT share links are accepted.');
  }
  if (url.hostname.toLowerCase() !== 'chatgpt.com') {
    throw new Error('Only the chatgpt.com host is accepted.');
  }
  if (url.port || url.username || url.password) {
    throw new Error('Ports and URL credentials are not accepted.');
  }

  const match = url.pathname.match(/^\/share\/([^/]+)\/?$/);
  if (!match || !SHARE_ID.test(match[1])) {
    throw new Error('Expected a conversation URL shaped like https://chatgpt.com/share/<conversation-id>');
  }

  url.pathname = `/share/${match[1]}`;
  url.search = '';
  url.hash = '';
  return url.toString();
}

export function shareIdFromUrl(url) {
  return new URL(validateShareUrl(url)).pathname.split('/').at(-1);
}

