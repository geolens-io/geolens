// GAP-024: the existing resources.test.ts only checks bundle-internal
// invariants (every namespace ships for every locale; locales keep key parity
// with EN). It never reads component SOURCE, so a `t('some.key')` referencing a
// key that exists in NO bundle — and has no defaultValue — ships green through
// every i18n gate and renders the raw key string to the user.
//
// This guard scans source `t('literal')` / `i18n.t('literal')` / <Trans
// i18nKey="..."> usages and fails when a referenced key exists in NEITHER the
// EN bundles NOR provides a defaultValue. Scope (per the review): static string
// keys only — dynamic keys (template literals / variables) are skipped, and a
// key seeded in ANY EN namespace bundle passes (per-file namespace attribution
// is intentionally not enforced to avoid false positives). Plural suffixes
// (_one/_other/_zero/_two/_few/_many) resolve to their base.
import { loadAllResources } from '@/i18n/resources';

// Load every source module as a raw string (Vite-native; no node:fs, matching
// the project convention). Eager so the scan is synchronous.
const sourceModules = import.meta.glob('/src/**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

function flattenKeys(value: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(value).flatMap(([key, nested]) => {
    const next = prefix ? `${prefix}.${key}` : key;
    if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
      return flattenKeys(nested as Record<string, unknown>, next);
    }
    return [next];
  });
}

const PLURAL_SUFFIX = /_(one|other|zero|two|few|many)$/;

// Matches t('key') / t("key") / i18n.t('key') / <Trans i18nKey="key">. Captures
// the quote and the key. Only literal keys (start with a letter) are matched;
// template literals and variables produce no match and are skipped.
const T_CALL = /\bt\(\s*(['"])([A-Za-z][A-Za-z0-9_.:-]*)\1/g;
const I18N_KEY_ATTR = /\bi18nKey=(['"])([A-Za-z][A-Za-z0-9_.:-]*)\1/g;

interface Reference {
  key: string;
  file: string;
}

function hasDefaultValue(src: string, callStart: number): boolean {
  // Look at the argument list of this call: from the opening paren to its match.
  // A shallow `defaultValue:` anywhere in the next ~200 chars before the call's
  // closing paren counts. Good enough — false "has default" only suppresses a
  // would-be failure, and the dry run found zero such cases.
  const window = src.slice(callStart, callStart + 240);
  const close = window.indexOf(')');
  const scope = close >= 0 ? window.slice(0, close + 1) : window;
  return scope.includes('defaultValue');
}

function collectReferences(): Reference[] {
  const refs: Reference[] = [];
  for (const [file, src] of Object.entries(sourceModules)) {
    // Skip tests, the i18n machinery itself, and type decls.
    if (
      /\.(test|spec)\.tsx?$/.test(file) ||
      file.includes('/__tests__/') ||
      file.includes('/src/test/') ||
      file.includes('/src/i18n/') ||
      file.endsWith('.d.ts')
    ) {
      continue;
    }

    for (const m of src.matchAll(T_CALL)) {
      if (hasDefaultValue(src, m.index ?? 0)) continue;
      refs.push({ key: m[2], file });
    }
    for (const m of src.matchAll(I18N_KEY_ATTR)) {
      refs.push({ key: m[2], file });
    }
  }
  return refs;
}

describe('GAP-024: source-referenced i18n keys exist in the bundles', () => {
  it('every static t() / i18nKey key is seeded in an EN bundle or has a defaultValue', async () => {
    const resources = await loadAllResources();

    // Build the universe of EN keys across all namespaces, plus plural bases.
    const known = new Set<string>();
    for (const bundle of Object.values(resources.en)) {
      for (const k of flattenKeys(bundle)) {
        known.add(k);
        const base = k.replace(PLURAL_SUFFIX, '');
        if (base !== k) known.add(base);
      }
    }

    const missing: Reference[] = [];
    for (const ref of collectReferences()) {
      // Strip an explicit `ns:` prefix — we match against the global key set.
      const bare = ref.key.includes(':') ? ref.key.split(':', 2)[1] : ref.key;
      if (known.has(bare)) continue;
      if (known.has(bare.replace(PLURAL_SUFFIX, ''))) continue;
      missing.push({ key: ref.key, file: ref.file });
    }

    expect(
      missing,
      `Source references i18n keys absent from every EN bundle (and with no defaultValue). ` +
        `Add them to the matching src/i18n/locales/*/<ns>.json or pass a defaultValue:\n` +
        missing.map((r) => `  ${r.key}  (${r.file})`).join('\n'),
    ).toEqual([]);
  });
});
