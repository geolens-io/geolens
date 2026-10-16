import i18next from 'i18next';
import en from './locales/en/import.json';

describe('import bulk.importingFiles plural', () => {
  it('reads singular for one file and plural otherwise', async () => {
    const i18n = i18next.createInstance();
    await i18n.init({ lng: 'en', resources: { en: { import: en } }, ns: ['import'], defaultNS: 'import' });

    expect(i18n.t('bulk.importingFiles', { count: 1 })).toBe('Importing 1 file');
    expect(i18n.t('bulk.importingFiles', { count: 3 })).toBe('Importing 3 files');
  });
});
