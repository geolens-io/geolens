/**
 * API-error i18n boundary guard.
 *
 * Backend `detail` is deliberately English diagnostic text. The frontend must
 * classify it into a stable common:errors key, never pass unknown prose through
 * to a toast or screen. This script verifies that contract and inventories the
 * backend surface so growth remains visible in CI.
 */

import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(SCRIPT_DIR, '..');
const REPO_ROOT = path.resolve(FRONTEND_ROOT, '..');
const ERROR_MAP_PATH = path.join(FRONTEND_ROOT, 'src/lib/error-map.ts');
const BACKEND_ROOT = path.join(REPO_ROOT, 'backend/app');
const LANGUAGES = ['en', 'es', 'fr', 'de'];

function collectFiles(root, extension, files = []) {
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const full = path.join(root, entry.name);
    if (entry.isDirectory()) collectFiles(full, extension, files);
    else if (entry.isFile() && entry.name.endsWith(extension)) files.push(full);
  }
  return files;
}

function fail(messages) {
  console.error('API error localization boundary failed:');
  for (const message of messages) console.error(`  - ${message}`);
  process.exit(1);
}

const failures = [];
const errorMap = readFileSync(ERROR_MAP_PATH, 'utf8');

// These were the two historical leak paths: unknown detail and dynamic quotas
// were returned verbatim. Keep the check textual and obvious so a future
// refactor cannot accidentally restore either behavior.
if (/return\s+backendMessage\s*;/.test(errorMap)) {
  failures.push('error-map.ts returns unknown backendMessage verbatim');
}
if (/startsWith\(['"](?:Storage|Dataset) quota exceeded/.test(errorMap)) {
  failures.push('quota detail is passed through instead of interpolated into a locale key');
}
if (!/return\s+fallbackDescriptor\(status\)\s*;/.test(errorMap)) {
  failures.push('unmapped details are not routed through the status fallback classifier');
}

const productionTs = collectFiles(path.join(FRONTEND_ROOT, 'src'), '.ts')
  .concat(collectFiles(path.join(FRONTEND_ROOT, 'src'), '.tsx'))
  .filter((file) => !file.includes(`${path.sep}__tests__${path.sep}`))
  .filter((file) => !/\.(?:test|spec)\.[^.]+$/.test(file))
  .filter((file) => file !== ERROR_MAP_PATH);

for (const file of productionTs) {
  const source = readFileSync(file, 'utf8');
  if (/summarizeErrorDetail\s*\(/.test(source)) {
    failures.push(
      `${path.relative(FRONTEND_ROOT, file)} reduces API detail to raw display prose`,
    );
  }
  if (file.includes(`${path.sep}src${path.sep}api${path.sep}`)) {
    if (/\bstatusText\b/.test(source)) {
      failures.push(
        `${path.relative(FRONTEND_ROOT, file)} displays browser HTTP status prose`,
      );
    }
    if (/throw\s+new\s+(?:Api)?Error\(\s*(?:detail|body(?:\.detail)?)\b/.test(source)) {
      failures.push(
        `${path.relative(FRONTEND_ROOT, file)} throws raw API detail`,
      );
    }
    if (/throw\s+new\s+Error\(\s*`[^`]*\$\{(?:response|res)\.status\}/.test(source)) {
      failures.push(
        `${path.relative(FRONTEND_ROOT, file)} formats an HTTP status in English prose`,
      );
    }
  }
}

const referencedKeys = new Set(
  [...errorMap.matchAll(/['"]errors\.([A-Za-z0-9]+)['"]/g)].map((match) => match[1]),
);
if (referencedKeys.size === 0) {
  failures.push('no stable API error keys were found');
}

for (const language of LANGUAGES) {
  const bundlePath = path.join(
    FRONTEND_ROOT,
    'src/i18n/locales',
    language,
    'common.json',
  );
  const bundle = JSON.parse(readFileSync(bundlePath, 'utf8'));
  for (const key of referencedKeys) {
    if (typeof bundle.errors?.[key] !== 'string' || bundle.errors[key].length === 0) {
      failures.push(`${language}/common.json is missing errors.${key}`);
    }
  }
}

const exactSection = errorMap.slice(
  errorMap.indexOf('const EXACT_ERROR_KEYS'),
  errorMap.indexOf('const STATUS_FALLBACK_KEYS'),
);
const exactMessages = new Set();
for (const match of exactSection.matchAll(
  /^\s*(?:'([^'\n]+)'|"([^"\n]+)"):\s*(?:\n\s*)?'errors\.[A-Za-z0-9]+'/gm,
)) {
  exactMessages.add(match[1] ?? match[2]);
}
if (exactMessages.size === 0) {
  failures.push('no backend details retain domain-specific copy');
}

const backendFiles = collectFiles(BACKEND_ROOT, '.py');
let detailAssignments = 0;
const staticDetails = new Set();
for (const file of backendFiles) {
  const source = readFileSync(file, 'utf8');
  detailAssignments += [...source.matchAll(/\bdetail\s*=/g)].length;
  for (const match of source.matchAll(
    /\bdetail\s*=\s*(?:f)?(["'])([^\n"']{2,})\1/g,
  )) {
    staticDetails.add(match[2]);
  }
}
if (detailAssignments === 0) {
  failures.push(
    'backend detail inventory found no assignments (check the configured path)',
  );
}

if (failures.length > 0) fail(failures);

const exactStaticDetails = [...staticDetails].filter((detail) =>
  exactMessages.has(detail),
).length;
console.log(
  `API error boundary OK: ${referencedKeys.size} stable locale keys and ` +
    `${exactMessages.size} exact compatibility mappings; ${detailAssignments} backend ` +
    `detail assignments (${staticDetails.size} directly static strings, ` +
    `${exactStaticDetails} exact matches) fall back safely by HTTP status.`,
);
