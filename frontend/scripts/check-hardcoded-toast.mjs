#!/usr/bin/env node
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(scriptDir, '..');
const sourceDir = path.join(rootDir, 'src');
const strict = process.argv.includes('--strict') || process.env.HARDCODED_TOAST_STRICT === '1';
const hardcodedToastErrorPattern = /\btoast\.error\(\s*(['"`])(?=[A-Z])(?:\\.|(?!\1).)*\1/g;
const extensions = new Set(['.ts', '.tsx']);
const ignoredSegments = new Set(['node_modules', 'dist', 'coverage', 'test-results']);
const findings = [];

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    if (ignoredSegments.has(entry)) continue;

    const fullPath = path.join(dir, entry);
    const stat = statSync(fullPath);
    if (stat.isDirectory()) {
      yield* walk(fullPath);
    } else if (extensions.has(path.extname(entry))) {
      yield fullPath;
    }
  }
}

for (const file of walk(sourceDir)) {
  const relativePath = path.relative(rootDir, file);
  const lines = readFileSync(file, 'utf8').split(/\r?\n/);

  lines.forEach((line, index) => {
    hardcodedToastErrorPattern.lastIndex = 0;
    if (hardcodedToastErrorPattern.test(line)) {
      findings.push(`${relativePath}:${index + 1}: ${line.trim()}`);
    }
  });
}

if (findings.length === 0) {
  console.log('No hardcoded toast.error() string literals found.');
  process.exit(0);
}

console.warn(`Found ${findings.length} hardcoded toast.error() string literal(s):`);
for (const finding of findings) {
  console.warn(`  ${finding}`);
}

if (strict) {
  process.exit(1);
}

console.warn('Non-strict mode: reporting only. Re-run with --strict or HARDCODED_TOAST_STRICT=1 to fail.');
