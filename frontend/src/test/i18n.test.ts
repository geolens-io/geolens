import i18n from 'i18next';
import { afterEach, describe, expect, it } from 'vitest';

import { changeTestLanguage } from './i18n';

describe('#1866: changeTestLanguage loads real locale bundles', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('switches to a real, translated string rather than the English fallback', async () => {
    await changeTestLanguage('fr');
    expect(i18n.language).toBe('fr');
    expect(i18n.t('import:dropzone.browse')).toBe('Parcourir');
  });

  it('switches between two non-English, non-fallback locales', async () => {
    // fix(#1866): a second locale exercises the plain addResourceBundle
    // path (data[lng] already exists), not just the placeholder branch.
    await changeTestLanguage('de');
    expect(i18n.t('import:dropzone.browse')).toBe('Durchsuchen');

    await changeTestLanguage('fr');
    expect(i18n.t('import:dropzone.browse')).toBe('Parcourir');
  });

  it('does not leak a registered locale into English', async () => {
    await changeTestLanguage('fr');
    await i18n.changeLanguage('en');
    expect(i18n.t('import:dropzone.browse')).toBe('browse');
  });
});
