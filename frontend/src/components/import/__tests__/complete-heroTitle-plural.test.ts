// fix(#1853): the import success screen's `complete.heroTitle` had no
// `_one`/`_other` split, so i18next always served the (plural) bare key —
// "1 datasets added to the catalog" — regardless of count. Uses the real
// i18next instance (initialized in src/test/setup.ts), not a mock, so a
// missing plural suffix in a locale bundle actually shows up here.
import i18n from 'i18next';

describe('import:complete.heroTitle pluralization (#1853)', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

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

  it.each(['es', 'fr', 'de'])('has a distinct singular form in %s', async (lng) => {
    await i18n.changeLanguage(lng);
    const singular = String(i18n.t('import:complete.heroTitle', { count: 1 }));
    const plural = String(i18n.t('import:complete.heroTitle', { count: 3 }));
    // Strip the interpolated digit before comparing — the two rendered
    // strings trivially differ by "1" vs "3" regardless of pluralization.
    // What must differ is the surrounding wording (singular noun/participle
    // vs plural); a missing _one/_other split serves the same bare-key
    // wording for every count, with only the digit changing.
    expect(singular.replace('1', '')).not.toBe(plural.replace('3', ''));
  });
});
