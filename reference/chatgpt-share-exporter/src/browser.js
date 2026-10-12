import { collectRenderedConversation } from './dom.js';
import { validateShareUrl } from './url.js';

function recordKey(record) {
  return record.sourceId ?? `${record.role}\u0000${record.turnIndex ?? ''}\u0000${record.plainText}\u0000${record.html}`;
}

function sortCollectedRecords(records) {
  const indexes = records.map((record) => record.turnIndex);
  if (indexes.every(Number.isFinite) && new Set(indexes).size === indexes.length) {
    return records.sort((a, b) => a.turnIndex - b.turnIndex);
  }
  return records;
}

async function scrollState(page, target) {
  return page.evaluate((requestedTarget) => {
    const roleNode = document.querySelector('[data-message-author-role="user"], [data-message-author-role="assistant"]');
    let scroller = roleNode?.parentElement ?? null;
    while (scroller) {
      const style = getComputedStyle(scroller);
      if (scroller.scrollHeight > scroller.clientHeight + 20 && /auto|scroll/.test(style.overflowY)) break;
      scroller = scroller.parentElement;
    }
    scroller ??= document.scrollingElement;
    if (!scroller) return { top: 0, height: 0, client: 0 };
    if (requestedTarget === 'top') scroller.scrollTop = 0;
    else if (requestedTarget === 'bottom') scroller.scrollTop = scroller.scrollHeight;
    else if (typeof requestedTarget === 'number') scroller.scrollTop = requestedTarget;
    return { top: scroller.scrollTop, height: scroller.scrollHeight, client: scroller.clientHeight };
  }, target);
}

async function collectAllRenderedMessages(page, timeoutMs) {
  const deadline = Date.now() + Math.min(timeoutMs, 35_000);
  const collected = new Map();
  const observations = [];
  const uniqueCounts = [];

  async function sample() {
    const snapshot = await page.evaluate(collectRenderedConversation, { messagesOnly: true });
    observations.push(snapshot.records.length);
    for (const record of snapshot.records) collected.set(recordKey(record), record);
    uniqueCounts.push(collected.size);
  }

  await sample();
  const tocIndices = await page.evaluate(() => [...document.querySelectorAll('[data-toc-item-index]')]
    .map((element) => Number(element.getAttribute('data-toc-item-index')))
    .filter(Number.isFinite)
    .sort((a, b) => a - b));

  // Current long ChatGPT shares virtualize old turns, but expose one TOC marker
  // per user prompt. Visiting each marker materializes that region without
  // depending on private payload formats.
  for (const index of tocIndices) {
    if (Date.now() >= deadline) break;
    await page.evaluate((itemIndex) => {
      document.querySelector(`[data-toc-item-index="${itemIndex}"]`)?.click();
    }, index);
    await page.waitForTimeout(100);
    await sample();
  }

  // Fallback for layouts without TOC markers, and a second safety net if a
  // marker did not materialize its turn. Sweep the actual overflow container.
  if (!tocIndices.length || collected.size < tocIndices.length * 2) {
    let state = await scrollState(page, 'top');
    await page.waitForTimeout(200);
    let unchanged = 0;
    for (let step = 0; step < 500 && Date.now() < deadline; step += 1) {
      const before = collected.size;
      await sample();
      unchanged = before === collected.size ? unchanged + 1 : 0;
      state = await scrollState(page, undefined);
      const atBottom = state.top + state.client >= state.height - 2;
      if (atBottom && unchanged >= 2) break;
      const increment = Math.max(300, state.client * 0.8);
      await scrollState(page, Math.min(state.height, state.top + increment));
      await page.waitForTimeout(100);
    }
  }

  const dom = await page.evaluate(collectRenderedConversation);
  dom.records = sortCollectedRecords([...collected.values()]);
  return {
    dom,
    observations,
    traversal: {
      tocPromptCount: tocIndices.length,
      tocPromptsVisited: Math.min(tocIndices.length, observations.length - 1),
      uniqueMessageCounts: uniqueCounts,
      deadlineReached: Date.now() >= deadline
    }
  };
}

export async function captureSharePage(url, options = {}) {
  const {
    headless = true,
    timeoutMs = 45_000,
    browserChannel,
    userAgent
  } = options;

  let playwright;
  try {
    playwright = await import('playwright');
  } catch (error) {
    throw new Error(`Playwright is not installed. Run npm install first. (${error.message})`);
  }

  const launchOptions = { headless };
  if (browserChannel) launchOptions.channel = browserChannel;

  let browser;
  try {
    browser = await playwright.chromium.launch(launchOptions);
  } catch (error) {
    if (/executable|browser.*not found|install/i.test(error.message)) {
      throw new Error(`Chromium for Playwright is missing. Run: npx playwright install chromium\n${error.message}`);
    }
    throw error;
  }

  const networkJson = [];
  const responseTasks = new Set();
  try {
    const context = await browser.newContext({
      locale: 'en-US',
      javaScriptEnabled: true,
      serviceWorkers: 'block',
      ...(userAgent ? { userAgent } : {})
    });
    const page = await context.newPage();
    page.setDefaultTimeout(timeoutMs);

    page.on('response', (response) => {
      const task = (async () => {
        try {
          const responseUrl = new URL(response.url());
          if (responseUrl.hostname !== 'chatgpt.com') return;
          const contentType = (await response.allHeaders())['content-type'] ?? '';
          if (!/application\/json/i.test(contentType)) return;
          const body = await response.json();
          networkJson.push({ url: response.url(), status: response.status(), body });
        } catch {
          // A response may be gone by the time its body is requested; DOM remains the fallback.
        }
      })();
      responseTasks.add(task);
      task.finally(() => responseTasks.delete(task));
    });

    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: timeoutMs });
    if (!response) throw new Error('Navigation produced no HTTP response.');
    const status = response.status();
    if (status >= 400) throw new Error(`The shared page returned HTTP ${status}.`);
    try {
      validateShareUrl(page.url());
    } catch {
      throw new Error(`The share link redirected outside a public ChatGPT share page (${page.url()}). It may be deleted, restricted, or require sign-in.`);
    }

    await page.waitForLoadState('networkidle', { timeout: Math.min(12_000, timeoutMs) }).catch(() => {});
    const collected = await collectAllRenderedMessages(page, timeoutMs);
    await Promise.allSettled([...responseTasks]);
    const html = await page.content();
    const screenshot = options.screenshotPath
      ? await page.screenshot({ path: options.screenshotPath, fullPage: true }).then(() => options.screenshotPath)
      : null;

    return {
      status,
      finalUrl: page.url(),
      dom: collected.dom,
      html,
      screenshot,
      observations: collected.observations,
      traversal: collected.traversal,
      networkJson
    };
  } finally {
    await browser.close();
  }
}

