// `instructions` is the lead-in fragment only, because the component appends
// the verb separately ("browse"/"Examinar"/"Parcourir"/"Durchsuchen"/"浏览");
// a full sentence would duplicate it ("...to browse browse to upload"). These
// tests render the real
// component against the real bundles so a regression shows up as a
// literal duplicate substring.
import i18n from 'i18next';
import { render, screen } from '@/test/test-utils';
import { changeTestLanguage } from '@/test/i18n';
import { FileDropzone } from '../FileDropzone';
import type { SupportedLng } from '@/i18n/config';

// The real, non-English browse word per locale, proving
// changeTestLanguage loaded the bundle instead of falling back to English.
const NON_ENGLISH_LOCALES: Exclude<SupportedLng, 'en'>[] = ['es', 'fr', 'de', 'zh'];
const NON_ENGLISH_BROWSE_WORD: Record<Exclude<SupportedLng, 'en'>, string> = {
  es: 'Examinar',
  fr: 'Parcourir',
  de: 'Durchsuchen',
  zh: '浏览',
};

function composedInstructions(): string {
  // The heading text is split across a plain text node and a bolded <span>
  // ("browse"), so read the whole heading's textContent rather than
  // matching a single text node.
  return screen.getByRole('heading', { level: 3 }).textContent ?? '';
}

describe('FileDropzone instructions text (#1853)', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('does not repeat the browse verb in English', () => {
    render(<FileDropzone onFilesAccepted={() => {}} />);

    const text = composedInstructions();
    expect(text).toBe('Drag and drop files here, or browse to upload');
    // The bug produced "...to browse browse to upload" — assert the verb
    // appears exactly once.
    expect(text.match(/browse/gi)).toHaveLength(1);
  });

  it.each(NON_ENGLISH_LOCALES)('does not repeat the browse verb in %s', async (lng) => {
    await changeTestLanguage(lng);
    render(<FileDropzone onFilesAccepted={() => {}} />);

    const text = composedInstructions();
    const browseWord = i18n.t('import:dropzone.browse');
    expect(browseWord).toBe(NON_ENGLISH_BROWSE_WORD[lng]);
    // The pre-fix bug duplicated the locale's own browse word (once from
    // `instructions`, once bolded).
    const occurrences = text.split(browseWord).length - 1;
    expect(occurrences).toBe(1);
  });
});
