import i18next from 'i18next';
import en from './locales/en/import.json';
import es from './locales/es/import.json';
import fr from './locales/fr/import.json';

// Spanish and French pick the CLDR "many" form for a million, and i18next
// does not fall back from _many to _other.
describe('import warnings.zmDropped.features plural', () => {
  it.each([
    ['es', es, '1000000 de entidades perdieron sus valores Z o M'],
    ['fr', fr, "1000000 d'entités ont perdu leurs valeurs Z ou M"],
  ] as const)('has a %s form for a million features', async (lng, resources, text) => {
    const i18n = i18next.createInstance();
    await i18n.init({
      lng,
      fallbackLng: 'en',
      resources: { [lng]: { import: resources }, en: { import: en } },
      ns: ['import'],
      defaultNS: 'import',
    });

    expect(i18n.t('warnings.zmDropped.features', { count: 1000000 })).toBe(text);
    expect(i18n.t('warnings.zmDropped.features', { count: 1 })).not.toBe(text);
  });
});
