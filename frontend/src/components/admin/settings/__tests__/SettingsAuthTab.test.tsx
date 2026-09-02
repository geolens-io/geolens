import { QueryClient } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { SettingsAuthTab } from '../SettingsAuthTab';
import { buildOAuthEndpointFields } from '../oauth-endpoint-fields';
import { queryKeys } from '@/lib/query-keys';
import {
  listOAuthProviders,
  createOAuthProvider,
  updateOAuthProvider,
  deleteOAuthProvider,
  type OAuthProviderConfig,
  type SettingItem,
} from '@/api/settings';

// Mock listOAuthProviders so the embedded OAuthProvidersSection does not hit
// the network via useQuery — return an empty provider list.
vi.mock('@/api/settings', async () => {
  const actual = await vi.importActual<typeof import('@/api/settings')>('@/api/settings');
  return {
    ...actual,
    listOAuthProviders: vi.fn().mockResolvedValue([]),
    createOAuthProvider: vi.fn(),
    updateOAuthProvider: vi.fn(),
    deleteOAuthProvider: vi.fn(),
  };
});

const OIDC_PROVIDER: OAuthProviderConfig = {
  id: 'provider-1',
  slug: 'legacy-oidc',
  display_name: 'Legacy OIDC',
  provider_type: 'oidc',
  client_id: 'client-id',
  discovery_url: null,
  authorize_url: 'https://idp.example.com/authorize',
  token_url: 'https://idp.example.com/token',
  userinfo_url: 'https://idp.example.com/userinfo',
  scopes: 'openid profile email',
  default_role: 'viewer',
  group_claim: null,
  group_role_mapping: null,
  enabled: true,
  created_at: '2026-07-10T00:00:00Z',
  updated_at: '2026-07-10T00:00:00Z',
};

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
    onSave,
    onReset,
    onDirtyChange,
  }: {
    onSave?: (changes: Record<string, unknown>) => void;
    onReset?: (key: string) => void;
    onDirtyChange?: (dirty: boolean) => void;
  } = {},
) {
  const _onSave = onSave ?? vi.fn();
  const _onReset = onReset ?? vi.fn();
  const _onDirtyChange = onDirtyChange ?? vi.fn();
  const settings = defaultSettings(settingsOverrides);
  render(
    <SettingsAuthTab
      settings={settings}
      envOnly={false}
      onSave={_onSave}
      onReset={_onReset}
      isSaving={false}
      onDirtyChange={_onDirtyChange}
    />,
  );
  return { onSave: _onSave, onReset: _onReset, onDirtyChange: _onDirtyChange };
}

describe('SettingsAuthTab', () => {
  describe('OAuth endpoint modes', () => {
    it('clears explicit GitHub endpoints when discovery mode is selected', () => {
      expect(
        buildOAuthEndpointFields({
          provider_type: 'google',
          discovery_url: 'https://accounts.google.com/.well-known/openid-configuration',
          authorize_url: 'https://ghe.example.com/authorize',
          token_url: 'https://ghe.example.com/token',
          userinfo_url: 'https://ghe.example.com/user',
        }),
      ).toEqual({
        discovery_url: 'https://accounts.google.com/.well-known/openid-configuration',
        authorize_url: null,
        token_url: null,
        userinfo_url: null,
      });
    });

    it('preserves explicit endpoints for an OIDC provider without discovery', () => {
      expect(
        buildOAuthEndpointFields({
          provider_type: 'oidc',
          discovery_url: '',
          authorize_url: 'https://idp.example.com/authorize',
          token_url: 'https://idp.example.com/token',
          userinfo_url: 'https://idp.example.com/userinfo',
        }),
      ).toEqual({
        discovery_url: null,
        authorize_url: 'https://idp.example.com/authorize',
        token_url: 'https://idp.example.com/token',
        userinfo_url: 'https://idp.example.com/userinfo',
      });
    });

    it.each(['google', 'microsoft'] as const)(
      'clears hidden explicit endpoints for %s without discovery',
      (provider_type) => {
        expect(
          buildOAuthEndpointFields({
            provider_type,
            discovery_url: '',
            authorize_url: 'https://hidden.example.com/authorize',
            token_url: 'https://hidden.example.com/token',
            userinfo_url: 'https://hidden.example.com/userinfo',
          }),
        ).toEqual({
          discovery_url: null,
          authorize_url: null,
          token_url: null,
          userinfo_url: null,
        });
      },
    );

    it('retains explicit OIDC endpoints when saving an unrelated edit', async () => {
      const provider = OIDC_PROVIDER;
      vi.mocked(listOAuthProviders).mockResolvedValueOnce([provider]);
      vi.mocked(updateOAuthProvider).mockResolvedValueOnce(provider);
      const user = userEvent.setup();

      renderTab();

      const providerRow = (await screen.findByText('Legacy OIDC')).closest('tr');
      expect(providerRow).not.toBeNull();
      await user.click(within(providerRow!).getAllByRole('button')[0]);
      const displayName = await screen.findByLabelText('Display Name');
      await user.clear(displayName);
      await user.type(displayName, 'Renamed OIDC');
      await user.click(screen.getByRole('button', { name: 'Save Changes' }));

      await waitFor(() => expect(updateOAuthProvider).toHaveBeenCalledOnce());
      expect(updateOAuthProvider).toHaveBeenCalledWith(
        provider.id,
        expect.objectContaining({
          display_name: 'Renamed OIDC',
          discovery_url: null,
          authorize_url: provider.authorize_url,
          token_url: provider.token_url,
          userinfo_url: provider.userinfo_url,
        }),
      );
      expect(vi.mocked(updateOAuthProvider).mock.calls[0][1]).not.toHaveProperty('client_secret');
    });

    it('clears discovery when explicit GitHub mode is selected', () => {
      expect(
        buildOAuthEndpointFields({
          provider_type: 'github',
          discovery_url: 'https://stale.example.com/.well-known/openid-configuration',
          authorize_url: '',
          token_url: '',
          userinfo_url: '',
        }),
      ).toEqual({
        discovery_url: null,
        authorize_url: null,
        token_url: null,
        userinfo_url: null,
      });
    });
  });

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
      const capturedCalls: Record<string, unknown>[] = [];
      const onSave = vi.fn((changes: Record<string, unknown>) => { capturedCalls.push(changes); });
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
      const payload = capturedCalls[0];
      expect(Array.isArray(payload.allowed_email_domains)).toBe(true);
      expect(payload.allowed_email_domains).toContain('corp.io');
    });
  });

  // fix(#1117): every OAuth mutation has to refresh BOTH the admin table
  // (settingsOAuth.providers, read here) and the login page's buttons
  // (authConfig.oauthProviders, read by components/auth/OAuthButtons.tsx). Only the
  // first was invalidated, so an admin who added or removed a provider and then
  // logged out kept the stale button set for the rest of the session.
  describe('OAuth provider mutations refresh the login page too', () => {
    beforeEach(() => {
      // Call history only — mockReset would drop listOAuthProviders' resolved value,
      // which the module factory sets once.
      vi.mocked(createOAuthProvider).mockClear();
      vi.mocked(updateOAuthProvider).mockClear();
      vi.mocked(deleteOAuthProvider).mockClear();
    });

    afterEach(() => {
      vi.restoreAllMocks();
    });

    function spyOnInvalidate() {
      return vi
        .spyOn(QueryClient.prototype, 'invalidateQueries')
        .mockResolvedValue(undefined);
    }

    function expectBothProviderCaches(
      invalidateQueries: ReturnType<typeof spyOnInvalidate>,
    ) {
      expect(invalidateQueries).toHaveBeenCalledWith({
        queryKey: queryKeys.settingsOAuth.providers,
      });
      expect(invalidateQueries).toHaveBeenCalledWith({
        queryKey: queryKeys.authConfig.oauthProviders,
      });
    }

    it('invalidates both provider caches after a create', async () => {
      vi.mocked(createOAuthProvider).mockResolvedValueOnce(OIDC_PROVIDER);
      const invalidateQueries = spyOnInvalidate();
      const user = userEvent.setup();

      renderTab();

      await user.click(screen.getByRole('button', { name: /add provider/i }));
      await user.type(await screen.findByLabelText('Client ID'), 'new-client-id');
      await user.type(screen.getByLabelText('Client Secret'), 'new-client-secret');
      await user.click(screen.getByRole('button', { name: 'Create Provider' }));

      await waitFor(() => expect(createOAuthProvider).toHaveBeenCalledOnce());
      expectBothProviderCaches(invalidateQueries);
    });

    it('invalidates both provider caches after an update', async () => {
      vi.mocked(listOAuthProviders).mockResolvedValueOnce([OIDC_PROVIDER]);
      vi.mocked(updateOAuthProvider).mockResolvedValueOnce(OIDC_PROVIDER);
      const invalidateQueries = spyOnInvalidate();
      const user = userEvent.setup();

      renderTab();

      const providerRow = (await screen.findByText('Legacy OIDC')).closest('tr');
      await user.click(within(providerRow!).getAllByRole('button')[0]);
      const displayName = await screen.findByLabelText('Display Name');
      await user.clear(displayName);
      await user.type(displayName, 'Renamed OIDC');
      await user.click(screen.getByRole('button', { name: 'Save Changes' }));

      await waitFor(() => expect(updateOAuthProvider).toHaveBeenCalledOnce());
      expectBothProviderCaches(invalidateQueries);
    });

    it('invalidates both provider caches after a delete', async () => {
      vi.mocked(listOAuthProviders).mockResolvedValueOnce([OIDC_PROVIDER]);
      vi.mocked(deleteOAuthProvider).mockResolvedValueOnce(undefined);
      const invalidateQueries = spyOnInvalidate();
      const user = userEvent.setup();

      renderTab();

      const providerRow = (await screen.findByText('Legacy OIDC')).closest('tr');
      await user.click(within(providerRow!).getAllByRole('button')[1]);
      await user.click(await screen.findByRole('button', { name: 'Delete' }));

      await waitFor(() => expect(deleteOAuthProvider).toHaveBeenCalledWith(OIDC_PROVIDER.id));
      expectBothProviderCaches(invalidateQueries);
    });
  });

  // fix(#1755): the OAuth client secret is an admin secret, not a login
  // credential -- it needs the same password-manager opt-out attributes the
  // service-token inputs gained in #1750.
  describe('Client Secret field opts out of password managers', () => {
    it('opts out the client secret field', async () => {
      const user = userEvent.setup();
      renderTab();

      await user.click(screen.getByRole('button', { name: /add provider/i }));
      const secretInput = await screen.findByLabelText('Client Secret');

      expect(secretInput).toHaveAttribute('type', 'password');
      expect(secretInput).toHaveAttribute('autocomplete', 'new-password');
      expect(secretInput).toHaveAttribute('data-1p-ignore');
      expect(secretInput).toHaveAttribute('data-lpignore', 'true');
      expect(secretInput).toHaveAttribute('data-bwignore');
    });
  });
});
