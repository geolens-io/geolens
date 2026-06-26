/**
 * GLUX-014 / GLUX-002 (Phase 1248): regression gate for the SettingsPage
 * control semantics.
 *
 * Asserts:
 * - The selected theme toggle button conveys state via aria-pressed, not color
 *   alone. Reverting the aria-pressed attribute fails this test.
 * - The language select is queryable by its accessible name via the shared
 *   FieldLabel primitive. Removing the FieldLabel + id binding fails this test.
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

// ── mock useTheme — theme set to 'dark' for assertions ───────────────────────
const mockSetTheme = vi.fn();
vi.mock('@/components/theme-provider', () => ({
  useTheme: () => ({ theme: 'dark', setTheme: mockSetTheme, resolvedTheme: 'dark' }),
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

describe('GLUX-014 / GLUX-002: SettingsPage control semantics', () => {
  it('selected theme button has aria-pressed=true; unselected buttons have aria-pressed=false', () => {
    render(<SettingsPage />);

    // useTheme is mocked to return theme='dark'; the dark button is selected
    const darkButton = screen.getByRole('button', { name: 'theme.dark' });
    expect(darkButton).toHaveAttribute('aria-pressed', 'true');

    const lightButton = screen.getByRole('button', { name: 'theme.light' });
    expect(lightButton).toHaveAttribute('aria-pressed', 'false');

    const systemButton = screen.getByRole('button', { name: 'theme.system' });
    expect(systemButton).toHaveAttribute('aria-pressed', 'false');
  });

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
