#!/usr/bin/env node
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(scriptDir, '..');
const sourceDir = path.join(rootDir, 'src');
const strict = process.argv.includes('--strict') || process.env.HARDCODED_TOAST_STRICT === '1';
const selfTest = process.argv.includes('--self-test');
const toastMethods = ['error', 'success', 'info', 'warning', 'message'];
const hardcodedToastPattern = /\btoast\.(error|success|info|warning|message)\(\s*(['"`])(?:\\.|(?!\2)[\s\S])*?\2/g;
const extensions = new Set(['.ts', '.tsx']);
const ignoredSegments = new Set(['node_modules', 'dist', 'coverage', 'test-results']);
const findings = [];

function hardcodedToastCalls(source) {
  hardcodedToastPattern.lastIndex = 0;
  return [...source.matchAll(hardcodedToastPattern)];
}

if (selfTest) {
  const failures = [];
  for (const method of toastMethods) {
    const samples = [
      `toast.${method}('Translated? No.');`,
      `toast.${method}("lowercase text");`,
      `toast.${method}(\`Template literal\`);`,
      `toast.${method}(\`A multiline\nmessage\`);`,
    ];
    for (const sample of samples) {
      if (hardcodedToastCalls(sample).length !== 1) failures.push(`missed: ${sample}`);
    }
    const dynamic = `toast.${method}(t('notifications.saved'));`;
    if (hardcodedToastCalls(dynamic).length !== 0) failures.push(`false positive: ${dynamic}`);
  }

  if (failures.length > 0) {
    console.error('Hardcoded toast scanner self-test failed:');
    for (const failure of failures) console.error(`  ${failure}`);
    process.exit(1);
  }

  console.log(`Hardcoded toast scanner self-test passed for: ${toastMethods.join(', ')}.`);
  process.exit(0);
}

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
  const source = readFileSync(file, 'utf8');

  for (const match of hardcodedToastCalls(source)) {
    const line = source.slice(0, match.index).split(/\r?\n/).length;
    const excerpt = match[0].replace(/\s+/g, ' ').trim();
    findings.push(`${relativePath}:${line}: toast.${match[1]}(): ${excerpt}`);
  }
}

if (findings.length === 0) {
  console.log(`No hardcoded toast string literals found for: ${toastMethods.join(', ')}.`);
  process.exit(0);
}

console.warn(`Found ${findings.length} hardcoded toast string literal(s):`);
for (const finding of findings) {
  console.warn(`  ${finding}`);
}

if (strict) {
  process.exit(1);
}

console.warn('Non-strict mode: reporting only. Re-run with --strict or HARDCODED_TOAST_STRICT=1 to fail.');
