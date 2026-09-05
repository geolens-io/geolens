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

  it('switches back to English through the helper without throwing', async () => {
    // fix(#1866 codex r2): English's bundle is already loaded and frozen,
    // so registering it again (instead of just switching) used to throw.
    await changeTestLanguage('de');
    await expect(changeTestLanguage('en')).resolves.toBeUndefined();
    expect(i18n.language).toBe('en');
    expect(i18n.t('import:dropzone.browse')).toBe('browse');
  });

  it('leaves the fallback map frozen after a round trip', async () => {
    // The short-circuit fixes the throw by never touching the fallback
    // map at all, rather than by cloning or unfreezing it. Pins that the
    // freeze complete-heroTitle-plural.test.ts relies on is still real.
    await changeTestLanguage('de');
    await changeTestLanguage('en');
    const store = i18n.services.resourceStore;
    expect(Object.isFrozen(store.data.en)).toBe(true);
    expect(() => {
      store.data.en.common = {};
    }).toThrow(TypeError);
  });
});
