import i18next from 'i18next';
import { fallbackLng, normalizeLanguage } from './i18n';

// fix(#2029): the zh bundle is Simplified Chinese only. Match by CLDR
// script via Intl.Locale (zh-MY maximizes to Hans, zh-TW to Hant), not by
// discarding everything after the first hyphen.
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

// fix(#2029 P1): an English-initial session kept silently rendering English
// after switching locale. vi.doMock substitutes a standalone
// i18next.createInstance() since resetModules() can't evict the shared one.
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
