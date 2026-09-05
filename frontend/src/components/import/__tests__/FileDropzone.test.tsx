// fix(#1853): `instructions` shipped as a full sentence ending in the same
// verb the component appends separately ("browse"/"Examinar"/"Parcourir"/
// "Durchsuchen"), so the headline read "Drag and drop files here, or click
// to browse browse to upload" — the trailing verb duplicated. `instructions`
// is now trimmed to the lead-in fragment in all four locales; these tests
// render the real component (no react-i18next mock) against the real
// bundles so a locale regression shows up as a literal duplicate substring.
import i18n from 'i18next';
import { render, screen } from '@/test/test-utils';
import { FileDropzone } from '../FileDropzone';

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

  it.each(['es', 'fr', 'de'])('does not repeat the browse verb in %s', async (lng) => {
    await i18n.changeLanguage(lng);
    render(<FileDropzone onFilesAccepted={() => {}} />);

    const text = composedInstructions();
    const browseWord = i18n.t('import:dropzone.browse');
    // Count occurrences of the locale's own browse word — the pre-fix bug
    // was a literal duplicate of it (once from `instructions`, once bolded).
    const occurrences = text.split(browseWord).length - 1;
    expect(occurrences).toBe(1);
  });
});
