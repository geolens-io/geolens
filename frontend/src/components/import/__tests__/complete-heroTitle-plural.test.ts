// fix(#1853): the import success screen's `complete.heroTitle` had no
// `_one`/`_other` split, so i18next always served the (plural) bare key —
// "1 datasets added to the catalog" — regardless of count.
//
// fix(#1863 P1, codex round 2): French and Spanish CLDR plural rules select
// a distinct "many" category for an exact non-zero multiple of a million
// (Intl.PluralRules('fr').select(1000000) === 'many'), and i18next does NOT
// fall back from an unresolved heroTitle_many to heroTitle_other — a
// missing _many rendered the raw key or the English fallback string
// instead. Added heroTitle_many to all four locale bundles (AGENTS.md:
// plural-suffix keys are all-four-or-none).
//
// These tests read the locale JSON bundles directly rather than driving
// them through a live i18next instance and i18n.changeLanguage(). This test
// harness's i18next is initialized with a FROZEN `resources` object holding
// only the eagerly-bundled fallback (en) locale (src/i18n/resources.ts) —
// other locales are lazy-loaded via `changeAppLanguage`, which itself
// short-circuits here because `i18n.hasLoadedNamespace(ns, { lng })`
// reports a namespace "loaded" via the en fallback chain even when the
// target locale was never actually registered, and the ResourceStore
// refuses to mutate a frozen object regardless. So neither a bare
// `i18n.changeLanguage('fr')` nor `changeAppLanguage('fr')` can make a real
// French string reach `t()` in this suite — both silently render the
// English fallback text under the reported language. Reading the bundles
// directly and interpolating {{count}} by hand tests exactly what changed
// (the resource files) without depending on plumbing this harness cannot
// exercise; the English-only assertions below still go through the real
// `i18n.t()`, since English is loaded for real.
import i18n from 'i18next';
import enImport from '@/i18n/locales/en/import.json';
import esImport from '@/i18n/locales/es/import.json';
import frImport from '@/i18n/locales/fr/import.json';
import deImport from '@/i18n/locales/de/import.json';

const BUNDLES: Record<string, typeof enImport> = {
  en: enImport,
  es: esImport,
  fr: frImport,
  de: deImport,
};

function interpolateCount(template: string, count: number): string {
  return template.replace(/\{\{count\}\}/g, String(count));
}

describe('import:complete.heroTitle pluralization (#1853)', () => {
  it('uses the singular form for count=1 in English', () => {
    expect(i18n.t('import:complete.heroTitle', { count: 1 })).toBe(
      '1 dataset added to the catalog',
    );
  });

  it('uses the plural form for count>1 in English', () => {
    expect(i18n.t('import:complete.heroTitle', { count: 3 })).toBe(
      '3 datasets added to the catalog',
    );
  });

  it.each(['es', 'fr', 'de'])('has a singular wording distinct from _other in %s', (lng) => {
    const { complete } = BUNDLES[lng];
    // Compare the raw templates (before interpolation) — the singular and
    // plural/other forms must use different wording (noun/participle
    // agreement), not merely differ by the digit that gets substituted in.
    expect(complete.heroTitle_one).not.toBe(complete.heroTitle_other);
  });

  it.each(['fr', 'es'])(
    'ships a heroTitle_many form for the exact-million CLDR category in %s',
    (lng) => {
      expect(new Intl.PluralRules(lng).select(1_000_000)).toBe('many');

      const { complete } = BUNDLES[lng];
      expect(complete.heroTitle_many).toBeDefined();
      expect(complete.heroTitle_many).toContain('{{count}}');

      const many = interpolateCount(complete.heroTitle_many, 1_000_000);
      const other = interpolateCount(complete.heroTitle_other, 1_000_000);
      // Strip digits/punctuation/whitespace before comparing — both would
      // trivially contain "1000000" regardless of pluralization. What must
      // differ is the surrounding wording (the "de"/partitive construction
      // French and Spanish use for exact millions).
      expect(many.replace(/[\d.,\s]/g, '')).not.toBe(other.replace(/[\d.,\s]/g, ''));
    },
  );

  it.each(['en', 'de'])(
    'ships heroTitle_many for key parity even though %s has no distinct CLDR "many" category',
    (lng) => {
      // English/German never select this category, so the key is never
      // reachable at runtime — it exists only so all four locale bundles
      // carry the same key set (AGENTS.md's all-four-or-none rule).
      expect(new Intl.PluralRules(lng).select(1_000_000)).toBe('other');

      const { complete } = BUNDLES[lng];
      expect(complete.heroTitle_many).toBeDefined();
      expect(complete.heroTitle_many).toContain('{{count}}');
    },
  );

  it('every locale bundle carries exactly the same heroTitle_* key set (AGENTS.md all-four-or-none)', () => {
    const suffixSets = Object.fromEntries(
      Object.entries(BUNDLES).map(([lng, bundle]) => [
        lng,
        Object.keys(bundle.complete)
          .filter((k) => k.startsWith('heroTitle'))
          .sort(),
      ]),
    );
    const [first, ...rest] = Object.values(suffixSets);
    for (const keys of rest) {
      expect(keys).toEqual(first);
    }
  });
});
