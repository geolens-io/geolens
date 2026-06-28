/**
 * GLUX-002 (Phase 1248): regression gate for the SettingsPage control semantics.
 *
 * Asserts:
 * - The language select is queryable by its accessible name via the shared
 *   FieldLabel primitive. Removing the FieldLabel + id binding fails this test.
 *
 * #347 (UX-01) (v1049): the theme toggle was removed from Settings (it now lives only
 * in the navbar user dropdown), so the former aria-pressed assertion is gone.
 */
import { render, screen } from '@/test/test-utils';
import { vi } from 'vitest';
import { SettingsPage } from '@/pages/SettingsPage';

// ── mock react-i18next ──────────────────────────────────────────────────────
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: 'en' },
  }),
}));

// ── mock i18n helpers ────────────────────────────────────────────────────────
vi.mock('@/i18n', () => ({ changeAppLanguage: vi.fn() }));
vi.mock('@/i18n/config', () => ({
  fallbackLng: 'en',
  languageOptions: [{ value: 'en', label: 'English' }],
}));

// ── mock auth ────────────────────────────────────────────────────────────────
vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({
    user: { username: 'testuser', roles: ['user'] },
    token: 'tok',
    isAdmin: false,
    isEditor: false,
  }),
}));

// ── mock quota ───────────────────────────────────────────────────────────────
vi.mock('@/hooks/use-quota', () => ({
  useMyUsage: () => ({ data: null }),
}));

// ── misc mocks ───────────────────────────────────────────────────────────────
vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

vi.mock('@/components/settings/MyApiKeySection', () => ({
  MyApiKeySection: () => null,
}));

describe('GLUX-002: SettingsPage control semantics', () => {
  it('language select is queryable by its accessible name via FieldLabel (GLUX-002)', () => {
    render(<SettingsPage />);

    // FieldLabel renders <label htmlFor="settings-language-select"> which
    // associates the label with the SelectTrigger that has id="settings-language-select".
    // getByLabelText traverses the for/id relationship to find the control.
    // Removing the FieldLabel + id binding makes this assertion fail.
    const languageControl = screen.getByLabelText('settings.language.title');
    expect(languageControl).toBeInTheDocument();
  });
});
