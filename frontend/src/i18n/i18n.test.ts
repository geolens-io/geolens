import i18next from 'i18next';
import { fallbackLng, normalizeLanguage } from './i18n';

// fix(#2029 review): the `zh` bundle is Simplified Chinese only. A tag
// resolver that discards everything after the first hyphen would also route
// zh-TW/zh-Hant (Traditional) browsers into it — assert Simplified tags
// match (including zh-MY, which CLDR maximizes to zh-Hans-MY, not a
// zh-CN/SG region code) and Traditional ones fall back instead.
describe('normalizeLanguage', () => {
  it.each(['zh', 'zh-CN', 'zh-Hans', 'zh-Hans-CN', 'zh-SG', 'zh-MY'])(
    'resolves the Simplified Chinese tag %s to zh',
    (tag) => {
      expect(normalizeLanguage(tag)).toBe('zh');
    },
  );

  it.each(['zh-TW', 'zh-HK', 'zh-MO', 'zh-Hant', 'zh-Hant-TW'])(
    'falls back for the Traditional Chinese tag %s',
    (tag) => {
      expect(normalizeLanguage(tag)).toBe(fallbackLng);
    },
  );

  it('still resolves other locales by their base language', () => {
    expect(normalizeLanguage('fr-CA')).toBe('fr');
    expect(normalizeLanguage('de-AT')).toBe('de');
    expect(normalizeLanguage('es-MX')).toBe('es');
  });

  it('falls back for an unsupported or missing tag', () => {
    expect(normalizeLanguage('ja-JP')).toBe(fallbackLng);
    expect(normalizeLanguage(undefined)).toBe(fallbackLng);
  });
});

// fix(#2029 review round 3, P1): a session that starts in English (the
// jsdom/browser default with no stored preference) hands i18next the
// Object.freeze'd `resources` singleton by reference. Switching language
// from there used to silently keep rendering English — hasLoadedNamespace
// falsely reported the target namespace "loaded" via the fallback chain, so
// the load was skipped, and even fixing that check alone would have made
// i18n.addResourceBundle() throw against the frozen, non-extensible store.
//
// This drives the real initializeI18n()/changeAppLanguage() against a
// standalone i18next instance (vi.resetModules() alone can't evict the
// package's Vite-optimized singleton that src/test/setup.ts already
// initialized, so a plain re-import still returns that shared, already-
// initialized instance) — vi.doMock substitutes an independent instance
// from i18next.createInstance() so this exercises real, unmodified app
// code, not a reimplementation of it.
describe('changeAppLanguage (English-initial session)', () => {
  afterEach(() => {
    vi.doUnmock('i18next');
    window.localStorage.removeItem('i18nextLng');
  });

  it('loads and applies a locale switched to for the first time', async () => {
    window.localStorage.removeItem('i18nextLng');
    const standalone = i18next.createInstance();
    vi.doMock('i18next', () => ({ default: standalone }));
    vi.resetModules();

    const fresh = await import('./i18n');
    await fresh.initializeI18n();
    expect(fresh.default.language).toBe('en');
    expect(fresh.default.t('common:save')).toBe('Save');

    await expect(fresh.changeAppLanguage('zh')).resolves.toBeUndefined();

    expect(fresh.default.language).toBe('zh');
    expect(fresh.default.t('common:save')).toBe('保存');
  });
});
