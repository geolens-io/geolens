// fix(#1866 codex r1): a real .spec.tsx file, proving the guard's glob
// reaches vitest's *.spec.{ts,tsx} convention, not only *.test.{ts,tsx}.
import { afterEach, describe, expect, it } from 'vitest';
import i18n from 'i18next';

import { changeTestLanguage } from '@/test/i18n';

describe('spec-glob-fixture', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('uses changeTestLanguage, so this file must never trip the guard', async () => {
    await changeTestLanguage('fr');
    expect(i18n.language).toBe('fr');
  });
});
