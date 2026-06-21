import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { SettingsAuthTab } from '../SettingsAuthTab';
import type { SettingItem } from '@/api/settings';

// Mock listOAuthProviders so the embedded OAuthProvidersSection does not hit
// the network via useQuery — return an empty provider list.
vi.mock('@/api/settings', async () => {
  const actual = await vi.importActual<typeof import('@/api/settings')>('@/api/settings');
  return {
    ...actual,
    listOAuthProviders: vi.fn().mockResolvedValue([]),
  };
});

function makeSetting(key: string, value: unknown): SettingItem {
  return { key, value, source: 'overridden', label: key };
}

function defaultSettings(overrides: SettingItem[] = []): SettingItem[] {
  const base: SettingItem[] = [
    makeSetting('registration_enabled', false),
    makeSetting('landing_first', false),
    makeSetting('password_login_enabled', true),
    makeSetting('allowed_email_domains', []),
    makeSetting('access_token_expire_minutes', 15),
    makeSetting('refresh_token_expire_days', 7),
    makeSetting('login_rate_limit', 5),
  ];
  // Merge overrides by key
  const overrideKeys = new Set(overrides.map((s) => s.key));
  return [...base.filter((s) => !overrideKeys.has(s.key)), ...overrides];
}

function renderTab(
  settingsOverrides: SettingItem[] = [],
  {
    onSave = vi.fn(),
    onReset = vi.fn(),
    onDirtyChange = vi.fn(),
  }: {
    onSave?: ReturnType<typeof vi.fn>;
    onReset?: ReturnType<typeof vi.fn>;
    onDirtyChange?: ReturnType<typeof vi.fn>;
  } = {},
) {
  const settings = defaultSettings(settingsOverrides);
  render(
    <SettingsAuthTab
      settings={settings}
      envOnly={false}
      onSave={onSave}
      onReset={onReset}
      isSaving={false}
      onDirtyChange={onDirtyChange}
    />,
  );
  return { onSave, onReset, onDirtyChange };
}

describe('SettingsAuthTab', () => {
  describe('Test 1: control rendering', () => {
    it('renders the Allow Password Login Switch and the domain allowlist widget', () => {
      renderTab();

      // Password-login Switch
      expect(screen.getByRole('switch', { name: /allow password login/i })).toBeInTheDocument();

      // Domain allowlist section — label and add button
      expect(screen.getByText(/allowed email domains/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /^add$/i })).toBeInTheDocument();
    });
  });

  describe('Test 2: empty vs populated domain list', () => {
    it('shows the unrestricted hint when the domain list is empty', () => {
      renderTab([makeSetting('allowed_email_domains', [])]);

      expect(screen.getByText(/no restrictions.*all email domains are allowed/i)).toBeInTheDocument();
    });

    it('shows removable entries for each domain when the list is populated', () => {
      renderTab([makeSetting('allowed_email_domains', ['acme.com', 'example.org'])]);

      expect(screen.getByText('acme.com')).toBeInTheDocument();
      expect(screen.getByText('example.org')).toBeInTheDocument();

      // A remove button per entry
      expect(screen.getByRole('button', { name: /remove domain acme\.com/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /remove domain example\.org/i })).toBeInTheDocument();

      // No unrestricted hint
      expect(screen.queryByText(/no restrictions/i)).not.toBeInTheDocument();
    });
  });

  describe('Test 3: add and remove interactions mark the form dirty', () => {
    it('adding a domain marks the form dirty (save button becomes enabled)', async () => {
      const user = userEvent.setup();
      renderTab([makeSetting('allowed_email_domains', [])]);

      const input = screen.getByPlaceholderText(/example\.com/i);
      const addButton = screen.getByRole('button', { name: /^add$/i });

      // Save button starts disabled (no dirty fields)
      expect(screen.getByRole('button', { name: /save/i })).toBeDisabled();

      await user.type(input, 'newdomain.com');
      await user.click(addButton);

      // After adding, save button should be enabled
      expect(screen.getByRole('button', { name: /save/i })).toBeEnabled();
      // The new domain should appear in the list
      expect(screen.getByText('newdomain.com')).toBeInTheDocument();
    });

    it('removing a domain marks the form dirty', async () => {
      const user = userEvent.setup();
      renderTab([makeSetting('allowed_email_domains', ['acme.com'])]);

      // Initially clean — save disabled
      expect(screen.getByRole('button', { name: /save/i })).toBeDisabled();

      const removeButton = screen.getByRole('button', { name: /remove domain acme\.com/i });
      await user.click(removeButton);

      // After removing, save button should be enabled (dirty)
      expect(screen.getByRole('button', { name: /save/i })).toBeEnabled();
    });
  });

  describe('Test 4: Save calls onSave with allowed_email_domains as an array', () => {
    it('clicking Save invokes onSave with allowed_email_domains as a plain array', async () => {
      const user = userEvent.setup();
      const onSave = vi.fn();
      renderTab(
        [makeSetting('allowed_email_domains', [])],
        { onSave },
      );

      // Add a domain to dirty the form
      const input = screen.getByPlaceholderText(/example\.com/i);
      await user.type(input, 'corp.io');
      await user.click(screen.getByRole('button', { name: /^add$/i }));

      // Click Save
      await user.click(screen.getByRole('button', { name: /save/i }));

      expect(onSave).toHaveBeenCalledOnce();
      expect(onSave).toHaveBeenCalledWith(
        expect.objectContaining({
          allowed_email_domains: expect.any(Array),
        }),
      );

      // Confirm the value is an array containing the added domain
      const payload = onSave.mock.calls[0][0] as Record<string, unknown>;
      expect(Array.isArray(payload.allowed_email_domains)).toBe(true);
      expect(payload.allowed_email_domains).toContain('corp.io');
    });
  });
});
