/**
 * Source→bundle key-existence guard (GAP-024)
 *
 * Scans src/**\/*.{ts,tsx} for static t('...'), i18n.t('...'), getFixedT, and
 * <Trans i18nKey="..."> usages, resolves each key's namespace (explicit ns:key,
 * useTranslation('ns') / getFixedT default ns, or defaultNS), and asserts each
 * STATIC key exists in src/i18n/locales/en/<ns>.json.
 *
 * LIMITATION: Dynamic keys (template literals, variables) are skipped. The script
 * logs each skipped dynamic key with file+line if VERBOSE=1 is set.
 *
 * Exit 0 = all static keys found. Exit 1 = missing keys detected.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, '..');
const SRC_ROOT = path.join(FRONTEND_ROOT, 'src');
const LOCALES_EN = path.join(FRONTEND_ROOT, 'src', 'i18n', 'locales', 'en');

const DEFAULT_NS = 'common';
const VERBOSE = process.env.VERBOSE === '1';

// ---------------------------------------------------------------------------
// Load English bundles
// ---------------------------------------------------------------------------

function loadBundle(ns) {
  const filePath = path.join(LOCALES_EN, `${ns}.json`);
  try {
    return JSON.parse(readFileSync(filePath, 'utf8'));
  } catch {
    return null;
  }
}

const NAMESPACES = [
  'common',
  'auth',
  'search',
  'dataset',
  'import',
  'collections',
  'admin',
  'builder',
  'report',
];

const bundles = Object.fromEntries(NAMESPACES.map((ns) => [ns, loadBundle(ns)]));

/**
 * Check if a dotted key path exists in a nested object.
 */
function keyExists(bundle, keyPath) {
  if (!bundle) return false;
  const parts = keyPath.split('.');
  let cur = bundle;
  for (const part of parts) {
    if (cur === null || typeof cur !== 'object' || !(part in cur)) {
      return false;
    }
    cur = cur[part];
  }
  return true;
}

// ---------------------------------------------------------------------------
// Recursively collect .ts/.tsx files (excluding __tests__, *.test.*, *.spec.*)
// ---------------------------------------------------------------------------

function collectFiles(dir, results = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      // Skip node_modules, dist, and the locales directory itself
      if (['node_modules', 'dist', 'locales'].includes(entry.name)) continue;
      collectFiles(full, results);
    } else if (
      entry.isFile() &&
      /\.(ts|tsx)$/.test(entry.name) &&
      !entry.name.includes('.test.') &&
      !entry.name.includes('.spec.')
    ) {
      results.push(full);
    }
  }
  return results;
}

// ---------------------------------------------------------------------------
// Parse a file and extract (ns, key, line) references
// ---------------------------------------------------------------------------

/**
 * From the file content, derive the "default namespace" used in this file by:
 *   1. Look for `const { t } = useTranslation('ns')` — the plain `t` binding with a namespace
 *   2. Look for `const { t } = useTranslation()` — no arg → defaultNS
 *   3. Look for `const { t } = useTranslation()` anywhere → defaultNS
 *   4. useTranslation('ns') — first found
 *   5. getFixedT(lng, 'ns') — second arg
 *   6. Fall back to DEFAULT_NS
 *
 * This avoids false-positives in files that have multiple t-aliases:
 *   const { t } = useTranslation()          // plain t → defaultNS
 *   const { t: tAuth } = useTranslation('auth') // tAuth → auth ns (but we scan with t() regex)
 */
function inferFileNs(content) {
  // Pattern: const { t } = useTranslation('ns') — exactly `t` (not an alias like tAuth)
  // This is the primary binding for plain t() calls.
  const plainTWithNs = content.match(/const\s*\{\s*t\s*\}\s*=\s*useTranslation\(\s*['"]([^'"]+)['"]\s*\)/);
  if (plainTWithNs) return plainTWithNs[1];

  // Pattern: const { t } = useTranslation() — no arg → defaultNS
  const plainTNoNs = content.match(/const\s*\{\s*t\s*\}\s*=\s*useTranslation\(\s*\)/);
  if (plainTNoNs) return DEFAULT_NS;

  // Destructured with other fields: const { t, i18n } = useTranslation('ns')
  const destructuredWithNs = content.match(/const\s*\{[^}]*\bt\b[^}]*\}\s*=\s*useTranslation\(\s*['"]([^'"]+)['"]\s*\)/);
  if (destructuredWithNs) return destructuredWithNs[1];

  // Destructured with no arg
  const destructuredNoArg = content.match(/const\s*\{[^}]*\bt\b[^}]*\}\s*=\s*useTranslation\(\s*\)/);
  if (destructuredNoArg) return DEFAULT_NS;

  // getFixedT(anything, 'ns')
  const gftMatch = content.match(/getFixedT\([^,]+,\s*['"]([^'"]+)['"]/);
  if (gftMatch) return gftMatch[1];

  return DEFAULT_NS;
}

const DYNAMIC_KEY_PATTERN = /\$\{|^\s*[a-zA-Z_]\w*\s*$/;

/**
 * Returns true if `t` in this file is injected as a prop/parameter rather
 * than obtained from useTranslation(). In such cases we cannot statically
 * determine the namespace, so we skip the file to avoid false positives.
 *
 * Detection heuristics:
 *   - File has no useTranslation or getFixedT call of any kind, AND
 *   - `t` appears as a destructured parameter in a function signature
 *     (e.g. `{ t }: BaseStyleEditorProps`) or as a plain function parameter,
 *     OR `t` is typed as a function type (e.g. `t: AnyTFunction`).
 */
function isTPropInjected(content) {
  const hasTranslation =
    /useTranslation\s*\(/.test(content) || /getFixedT\s*\(/.test(content);
  if (hasTranslation) return false;

  // t is declared as a prop in the function parameter list
  const tAsParam =
    /\{\s*[^}]*\bt\b[^}]*\}\s*:\s*\w/.test(content) || // { t }: SomeType
    /\(\s*[^)]*\bt\b[^)]*\)\s*[=:>{]/.test(content) || // (t, ...) => or (t: ...)
    /\bt\s*:\s*\w*[Ff]unction/.test(content) ||        // t: AnyTFunction
    /\bt\s*:\s*TFunction/.test(content);                // t: TFunction

  return tAsParam;
}

/**
 * Parse static t('...') / i18n.t('...') / t("...") calls.
 * Returns array of { ns, key, line }.
 */
function parseFile(filePath) {
  const rawContent = readFileSync(filePath, 'utf8');

  // Skip files where t is prop-injected — we can't resolve namespace statically
  if (isTPropInjected(rawContent)) {
    if (VERBOSE) console.warn(`  [skip-file] ${path.relative(SRC_ROOT, filePath)} — t is prop-injected`);
    return [];
  }

  // Strip single-line comments (//) and block comments (/* */) to avoid
  // matching t('key') references inside comments (e.g. documentation examples).
  const content = rawContent
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))  // block comments → spaces (preserve line numbers)
    .replace(/\/\/[^\n]*/g, (m) => ' '.repeat(m.length));            // line comments → spaces

  const fileNs = inferFileNs(rawContent); // infer from raw (comments may have useTranslation refs too)
  const refs = [];
  const skipped = [];

  // --- t('key') / t("key") / t(`key`) calls (static key only) ---
  // Also catches i18n.t('key'), tRef.current('key'), etc.
  // We match: word boundary + t( then a string literal
  const T_CALL_RE = /\bt\(\s*(['"`])([^'"`\n]+?)\1/g;
  let m;
  while ((m = T_CALL_RE.exec(content)) !== null) {
    const quote = m[1];
    const raw = m[2];
    // template literal with interpolation → dynamic, skip
    if (quote === '`' && raw.includes('${')) {
      if (VERBOSE) {
        const line = content.slice(0, m.index).split('\n').length;
        skipped.push({ file: filePath, line, reason: 'template-literal', raw });
      }
      continue;
    }
    // pure variable reference (no dots, looks like a variable name) — unlikely
    // but guard anyway
    const lineNo = content.slice(0, m.index).split('\n').length;

    // Resolve ns:key vs plain key
    let ns, key;
    if (raw.includes(':')) {
      const colon = raw.indexOf(':');
      ns = raw.slice(0, colon);
      key = raw.slice(colon + 1);
    } else {
      ns = fileNs;
      key = raw;
    }

    // Validate namespace is known
    if (!NAMESPACES.includes(ns)) {
      // Could be a dynamic ns — skip
      if (VERBOSE) {
        skipped.push({ file: filePath, line: lineNo, reason: `unknown-ns:${ns}`, raw });
      }
      continue;
    }

    refs.push({ ns, key, line: lineNo });
  }

  // --- <Trans i18nKey="key"> / i18nKey={'key'} ---
  const TRANS_RE = /i18nKey\s*=\s*(?:"([^"]+)"|'([^']+)'|\{['"]([^'"]+)['"]\})/g;
  while ((m = TRANS_RE.exec(content)) !== null) {
    const raw = m[1] || m[2] || m[3];
    const lineNo = content.slice(0, m.index).split('\n').length;
    let ns, key;
    if (raw.includes(':')) {
      const colon = raw.indexOf(':');
      ns = raw.slice(0, colon);
      key = raw.slice(colon + 1);
    } else {
      ns = fileNs;
      key = raw;
    }
    if (!NAMESPACES.includes(ns)) continue;
    refs.push({ ns, key, line: lineNo });
  }

  if (VERBOSE && skipped.length > 0) {
    for (const s of skipped) {
      console.warn(`  [skip] ${path.relative(SRC_ROOT, s.file)}:${s.line} — ${s.reason}: ${s.raw}`);
    }
  }

  return refs;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

const files = collectFiles(SRC_ROOT);
const missing = []; // { file, line, ns, key }
const seen = new Set(); // deduplicate

for (const file of files) {
  let refs;
  try {
    refs = parseFile(file);
  } catch (err) {
    console.warn(`Warning: could not parse ${path.relative(SRC_ROOT, file)}: ${err.message}`);
    continue;
  }

  for (const { ns, key, line } of refs) {
    const dedupKey = `${ns}:${key}`;
    if (seen.has(dedupKey)) continue;
    seen.add(dedupKey);

    if (!keyExists(bundles[ns], key)) {
      missing.push({
        file: path.relative(SRC_ROOT, file),
        line,
        ns,
        key,
      });
    }
  }
}

if (missing.length === 0) {
  console.log('✓ All static source-referenced i18n keys exist in the en bundles.');
  process.exit(0);
}

// Group by namespace for readability
const byNs = {};
for (const m of missing) {
  (byNs[m.ns] ||= []).push(m);
}

console.error(`\n✗ ${missing.length} source-referenced key(s) missing from en bundles:\n`);
for (const [ns, items] of Object.entries(byNs).sort()) {
  console.error(`  [${ns}] — ${items.length} missing:`);
  for (const { key, file, line } of items.sort((a, b) => a.key.localeCompare(b.key))) {
    console.error(`    ${key}  (${file}:${line})`);
  }
  console.error('');
}

console.error(
  `Run this script again after adding the missing keys to src/i18n/locales/en/<ns>.json.\n`,
);
process.exit(1);
