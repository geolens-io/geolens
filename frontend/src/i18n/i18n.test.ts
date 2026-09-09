import { fallbackLng, normalizeLanguage } from './i18n';

// fix(#2029 review): the `zh` bundle is Simplified Chinese only. A tag
// resolver that discards everything after the first hyphen would also route
// zh-TW/zh-Hant (Traditional) browsers into it — assert Simplified tags
// match and Traditional ones fall back instead.
describe('normalizeLanguage', () => {
  it.each(['zh', 'zh-CN', 'zh-Hans', 'zh-Hans-CN', 'zh-SG'])(
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
