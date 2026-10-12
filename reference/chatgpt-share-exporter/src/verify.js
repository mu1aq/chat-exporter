import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { sha256 } from './hash.js';

export async function verifyExport(outputPath, auditPath = `${outputPath}.audit.json`) {
  const resolvedOutput = path.resolve(outputPath);
  const resolvedAudit = path.resolve(auditPath);
  const [output, auditText] = await Promise.all([
    readFile(resolvedOutput, 'utf8'),
    readFile(resolvedAudit, 'utf8')
  ]);
  const audit = JSON.parse(auditText);
  const actual = sha256(output);
  return {
    ok: actual === audit.outputSha256,
    expectedSha256: audit.outputSha256,
    actualSha256: actual,
    outputPath: resolvedOutput,
    auditPath: resolvedAudit,
    messageCount: audit.selectedMessageCount,
    validation: audit.validation
  };
}

