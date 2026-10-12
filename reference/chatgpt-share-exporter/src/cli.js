#!/usr/bin/env node
import process from 'node:process';
import { pathToFileURL } from 'node:url';
import { extractConversation, saveExtraction, saveHtmlSnapshot } from './extract.js';
import { verifyExport } from './verify.js';

const HELP = `chatgpt-share-export - export public ChatGPT shared conversations

Usage:
  chatgpt-share-export <share-url> [options]
  chatgpt-share-export extract <share-url> [options]
  chatgpt-share-export verify <export.md|export.txt> [--audit <report.json>]

Extract options:
  -o, --output <path>       Output file (default: conversation.md)
  -f, --format <md|txt>     Output format (default: inferred from extension)
      --audit <path>        Audit report path (default: <output>.audit.json)
      --save-html           Save rendered source HTML for manual inspection
      --html <path>         Save HTML at a specific path (implies --save-html)
      --screenshot <path>   Save a full-page screenshot
      --headed              Show Chromium while extracting
      --channel <name>      Use an installed browser channel (chrome or msedge)
      --timeout <ms>        Navigation/extraction timeout (default: 45000)
      --strict              Exit non-zero if validation has warnings
  -h, --help                Show help

Only public https://chatgpt.com/share/... URLs are accepted. The tool never logs
in, imports cookies, solves access challenges, or bypasses workspace controls.`;

function parseArgs(argv) {
  const args = [...argv];
  const command = ['extract', 'verify'].includes(args[0]) ? args.shift() : 'extract';
  const result = { command, positional: [], output: 'conversation.md', timeoutMs: 45_000 };
  const takeValue = (flag) => {
    const value = args.shift();
    if (value === undefined || value.startsWith('-')) throw new Error(`Missing value for ${flag}.`);
    return value;
  };

  while (args.length) {
    const arg = args.shift();
    if (arg === '-h' || arg === '--help') result.help = true;
    else if (arg === '-o' || arg === '--output') result.output = takeValue(arg);
    else if (arg === '-f' || arg === '--format') result.format = takeValue(arg);
    else if (arg === '--audit') result.auditPath = takeValue(arg);
    else if (arg === '--save-html') result.saveHtml = true;
    else if (arg === '--html') { result.htmlPath = takeValue(arg); result.saveHtml = true; }
    else if (arg === '--screenshot') result.screenshotPath = takeValue(arg);
    else if (arg === '--headed') result.headless = false;
    else if (arg === '--channel') result.browserChannel = takeValue(arg);
    else if (arg === '--timeout') result.timeoutMs = Number(takeValue(arg));
    else if (arg === '--strict') result.strict = true;
    else if (arg.startsWith('-')) throw new Error(`Unknown option: ${arg}`);
    else result.positional.push(arg);
  }
  return result;
}

function validateOptions(options) {
  if (options.help) return;
  if (!options.positional[0]) throw new Error(options.command === 'verify' ? 'Missing export file.' : 'Missing ChatGPT share URL.');
  if (!Number.isFinite(options.timeoutMs) || options.timeoutMs < 1_000) throw new Error('--timeout must be at least 1000 ms.');
  if (options.format && !['md', 'markdown', 'txt', 'text'].includes(options.format)) throw new Error('--format must be md or txt.');
  if (options.browserChannel && !['chrome', 'msedge', 'chromium'].includes(options.browserChannel)) {
    throw new Error('--channel must be chrome, msedge, or chromium.');
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  validateOptions(options);
  if (options.help) {
    console.log(HELP);
    return;
  }

  if (options.command === 'verify') {
    const result = await verifyExport(options.positional[0], options.auditPath);
    console.log(`${result.ok ? 'OK' : 'FAILED'}: ${result.outputPath}`);
    console.log(`SHA-256 expected: ${result.expectedSha256}`);
    console.log(`SHA-256 actual:   ${result.actualSha256}`);
    console.log(`Messages recorded: ${result.messageCount}`);
    if (!result.ok) process.exitCode = 2;
    return;
  }

  const format = ['txt', 'text'].includes(options.format) ? 'text' :
    ['md', 'markdown'].includes(options.format) ? 'markdown' : undefined;
  const result = await extractConversation(options.positional[0], options);
  if (result.validation.errors.length) {
    for (const error of result.validation.errors) console.error(`ERROR: ${error}`);
    if (options.saveHtml) {
      const htmlPath = await saveHtmlSnapshot(result, options);
      console.error(`Rendered HTML snapshot: ${htmlPath}`);
    }
    process.exitCode = 1;
    return;
  }
  const saved = await saveExtraction(result, { ...options, format });
  console.log(`Saved ${result.conversation.messages.length} messages to ${saved.outputPath}`);
  console.log(`Audit report: ${saved.auditPath}`);
  if (saved.htmlPath) console.log(`Rendered HTML snapshot: ${saved.htmlPath}`);
  for (const warning of result.validation.warnings) console.warn(`WARNING: ${warning}`);
  if (options.strict && result.validation.warnings.length) process.exitCode = 2;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(`ERROR: ${error.message}`);
    process.exitCode = 1;
  });
}

export { parseArgs };
