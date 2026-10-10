import { QueryClient } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';
import { fetchEdition } from '@/api/edition';
import { SettingsAuthTab } from '../SettingsAuthTab';
import { buildOAuthEndpointFields } from '../oauth-endpoint-fields';
import { queryKeys } from '@/lib/query-keys';
import {
  listOAuthProviders,
  createOAuthProvider,
  updateOAuthProvider,
  deleteOAuthProvider,
  getNotificationStatus,
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
    getNotificationStatus: vi.fn().mockResolvedValue({
      notifications_enabled: true,
      smtp_configured: true,
      webhook_configured: false,
    }),
  };
});

vi.mock('@/api/edition', () => ({
  fetchEdition: vi.fn().mockResolvedValue({ edition: 'community', features: [] }),
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

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
    makeSetting('email_verification_required', true),
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

  // fix(#1778): email_verification_required registers on tab="auth" but no
  // tab component read the key, so the control an operator needs to decide
  // whether self-registered accounts activate without proving an address was
  // invisible in the admin UI.
  describe('Email Verification Required toggle (#1778)', () => {
    it('renders, reflects the current value, and reports a change', async () => {
      const user = userEvent.setup();
      const { onDirtyChange } = renderTab([
        makeSetting('registration_enabled', true),
        makeSetting('email_verification_required', true),
      ]);

      const toggle = screen.getByRole('switch', { name: /require email verification/i });
      expect(toggle).toHaveAttribute('aria-checked', 'true');

      await user.click(toggle);

      expect(toggle).toHaveAttribute('aria-checked', 'false');
      expect(onDirtyChange).toHaveBeenCalledWith(true);
    });
  });

  describe('sign-up safeguards', () => {
    const GOOGLE_PROVIDER: OAuthProviderConfig = {
      ...OIDC_PROVIDER,
      id: 'google-1',
      slug: 'google',
      display_name: 'Google',
      provider_type: 'google',
    };

    it('dims Require Email Verification while Self-Registration is off', () => {
      renderTab([makeSetting('registration_enabled', false)]);
      expect(screen.getByRole('switch', { name: /require email verification/i })).toBeDisabled();
      expect(screen.getByText(/applies when self-registration is on/i)).toBeInTheDocument();
    });

    it('notes a missing SMTP host next to Require Email Verification', async () => {
      vi.mocked(getNotificationStatus).mockResolvedValueOnce({
        notifications_enabled: false,
        smtp_configured: false,
        webhook_configured: false,
      });
      renderTab([makeSetting('registration_enabled', true)]);
      expect(await screen.findByText(/smtp is not configured/i)).toBeInTheDocument();
    });

    it('warns when registration is on, a public provider is enabled and no domains are listed', async () => {
      vi.mocked(listOAuthProviders).mockResolvedValue([GOOGLE_PROVIDER]);
      renderTab([makeSetting('registration_enabled', true)]);
      expect(await screen.findByText(/anyone with such an account/i)).toBeInTheDocument();
      vi.mocked(listOAuthProviders).mockResolvedValue([]);
    });

    it.each([
      ['a domain is listed', [makeSetting('registration_enabled', true), makeSetting('allowed_email_domains', ['acme.com'])], [GOOGLE_PROVIDER]],
      ['registration is off', [makeSetting('registration_enabled', false)], [GOOGLE_PROVIDER]],
      ['the provider is disabled', [makeSetting('registration_enabled', true)], [{ ...GOOGLE_PROVIDER, enabled: false }]],
      ['the provider is a single-tenant OIDC one', [makeSetting('registration_enabled', true)], [OIDC_PROVIDER]],
    ])('does not warn when %s', async (_name, settings, providers) => {
      vi.mocked(listOAuthProviders).mockResolvedValue(providers);
      renderTab(settings);
      await screen.findAllByText(providers[0].display_name);
      expect(screen.queryByText(/anyone with such an account/i)).not.toBeInTheDocument();
      vi.mocked(listOAuthProviders).mockResolvedValue([]);
    });

    it('warns for a multi-tenant Microsoft provider', async () => {
      vi.mocked(listOAuthProviders).mockResolvedValue([
        {
          ...GOOGLE_PROVIDER,
          provider_type: 'microsoft',
          discovery_url: 'https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration',
        },
      ]);
      renderTab([makeSetting('registration_enabled', true)]);
      expect(await screen.findByText(/anyone with such an account/i)).toBeInTheDocument();
      vi.mocked(listOAuthProviders).mockResolvedValue([]);
    });

    it.each([
      'https://login.microsoftonline.us/common/v2.0/.well-known/openid-configuration',
      'https://login.microsoftonline.com/Organizations/v2.0/.well-known/openid-configuration',
    ])('warns for the multi-tenant Microsoft authority %s', async (discovery_url) => {
      vi.mocked(listOAuthProviders).mockResolvedValue([
        { ...GOOGLE_PROVIDER, provider_type: 'microsoft', discovery_url },
      ]);
      renderTab([makeSetting('registration_enabled', true)]);
      expect(await screen.findByText(/anyone with such an account/i)).toBeInTheDocument();
      vi.mocked(listOAuthProviders).mockResolvedValue([]);
    });

    it('confirms before resetting Self-Registration', async () => {
      const user = userEvent.setup();
      const onReset = vi.fn();
      renderTab([makeSetting('registration_enabled', false)], { onReset });
      await user.click(screen.getAllByRole('button', { name: /reset/i })[0]);
      expect(onReset).not.toHaveBeenCalled();
      await user.click(await screen.findByRole('button', { name: /^reset$/i }));
      expect(onReset).toHaveBeenCalledWith('registration_enabled');
    });

    it('shows the default sign-up role control when the backend exposes the key', () => {
      renderTab([makeSetting('registration_default_role', 'editor')]);
      expect(screen.getByRole('combobox', { name: /default role for new sign-ups/i })).toHaveTextContent('Editor');
    });

    it('confirms before saving admin as the sign-up default role', async () => {
      // jsdom lacks scrollIntoView, which Radix Select calls when it opens.
      Element.prototype.scrollIntoView = vi.fn();
      const user = userEvent.setup();
      const { onSave } = renderTab([makeSetting('registration_default_role', 'viewer')]);
      screen.getByRole('combobox', { name: /default role for new sign-ups/i }).focus();
      await user.keyboard('{Enter}');
      await user.click(await screen.findByRole('option', { name: 'Admin' }));
      await user.click(screen.getByRole('button', { name: /^save$/i }));
      expect(onSave).not.toHaveBeenCalled();
      await user.click(await screen.findByRole('button', { name: /save with admin role/i }));
      expect(onSave).toHaveBeenCalledOnce();
    });

    it('confirms before turning on Self-Registration when the stored sign-up role is admin', async () => {
      const user = userEvent.setup();
      const { onSave } = renderTab([makeSetting('registration_default_role', 'admin')]);
      await user.click(screen.getByRole('switch', { name: /self-registration/i }));
      await user.click(screen.getByRole('button', { name: /^save$/i }));
      expect(onSave).not.toHaveBeenCalled();
      await user.click(await screen.findByRole('button', { name: /save with admin role/i }));
      expect(onSave).toHaveBeenCalledWith({ registration_enabled: true });
    });

    it('confirms before turning on Self-Registration when an enabled provider gives the admin role', async () => {
      vi.mocked(listOAuthProviders).mockResolvedValue([{ ...GOOGLE_PROVIDER, enabled: true, default_role: 'admin' }]);
      const user = userEvent.setup();
      const { onSave } = renderTab();
      await screen.findByRole('button', { name: 'Edit Google' });
      await user.click(screen.getByRole('switch', { name: /self-registration/i }));
      await user.click(screen.getByRole('button', { name: /^save$/i }));
      expect(onSave).not.toHaveBeenCalled();
      expect(await screen.findByText(/everyone who signs up becomes an administrator/i)).toBeInTheDocument();
      vi.mocked(listOAuthProviders).mockResolvedValue([]);
    });

    it('warns about admin sign-ups before resetting Self-Registration', async () => {
      const user = userEvent.setup();
      renderTab([makeSetting('registration_default_role', 'admin')]);
      await user.click(screen.getAllByRole('button', { name: /reset/i })[0]);
      expect(await screen.findByText(/everyone who signs up becomes an administrator/i)).toBeInTheDocument();
    });

    it('confirms before turning password login back on opens admin sign-ups', async () => {
      const user = userEvent.setup();
      const { onSave } = renderTab([
        makeSetting('registration_enabled', true),
        makeSetting('password_login_enabled', false),
        makeSetting('registration_default_role', 'admin'),
      ]);
      await user.click(screen.getByRole('switch', { name: /allow password login/i }));
      await user.click(screen.getByRole('button', { name: /^save$/i }));
      expect(onSave).not.toHaveBeenCalled();
      await user.click(await screen.findByRole('button', { name: /save with admin role/i }));
      expect(onSave).toHaveBeenCalledWith({ password_login_enabled: true });
    });

    it('confirms before email verification lets admin sign-ups activate themselves', async () => {
      const user = userEvent.setup();
      const { onSave } = renderTab([
        makeSetting('registration_enabled', true),
        makeSetting('email_verification_required', false),
        makeSetting('registration_default_role', 'admin'),
      ]);
      await user.click(screen.getByRole('switch', { name: /require email verification/i }));
      await user.click(screen.getByRole('button', { name: /^save$/i }));
      expect(onSave).not.toHaveBeenCalled();
      expect(await screen.findByText(/everyone who signs up becomes an administrator/i)).toBeInTheDocument();
    });

    it.each([
      ['is still loading', () => new Promise<never>(() => {})],
      ['failed to load', () => Promise.reject(new Error('down'))],
    ])('confirms turning on Self-Registration while the provider list %s', async (_state, load) => {
      vi.mocked(listOAuthProviders).mockImplementation(load);
      const user = userEvent.setup();
      const { onSave } = renderTab();
      await user.click(screen.getByRole('switch', { name: /self-registration/i }));
      await user.click(screen.getByRole('button', { name: /^save$/i }));
      expect(onSave).not.toHaveBeenCalled();
      expect(await screen.findByText(/everyone who signs up becomes an administrator/i)).toBeInTheDocument();
      vi.mocked(listOAuthProviders).mockReset();
      vi.mocked(listOAuthProviders).mockResolvedValue([]);
    });

    it('saves other settings without a prompt while the provider list is loading', async () => {
      vi.mocked(listOAuthProviders).mockImplementation(() => new Promise<never>(() => {}));
      const user = userEvent.setup();
      const { onSave } = renderTab();
      const input = screen.getByLabelText(/login rate limit/i);
      await user.clear(input);
      await user.type(input, '9');
      await user.click(screen.getByRole('button', { name: /^save$/i }));
      expect(onSave).toHaveBeenCalledWith({ login_rate_limit: 9 });
      vi.mocked(listOAuthProviders).mockReset();
      vi.mocked(listOAuthProviders).mockResolvedValue([]);
    });

    it('counts an enabled SAML provider with the admin role', async () => {
      vi.mocked(listOAuthProviders).mockResolvedValue([
        { ...GOOGLE_PROVIDER, id: 'saml-1', slug: 'okta', display_name: 'Okta', provider_type: 'saml' as OAuthProviderConfig['provider_type'], enabled: true, default_role: 'admin' },
      ]);
      const user = userEvent.setup();
      const { onSave } = renderTab();
      await waitFor(() => expect(listOAuthProviders).toHaveBeenCalled());
      await screen.findByText(/no oauth providers configured/i);
      await user.click(screen.getByRole('switch', { name: /self-registration/i }));
      await user.click(screen.getByRole('button', { name: /^save$/i }));
      expect(onSave).not.toHaveBeenCalled();
      expect(await screen.findByText(/everyone who signs up becomes an administrator/i)).toBeInTheDocument();
      vi.mocked(listOAuthProviders).mockResolvedValue([]);
    });

    it('hides the default sign-up role control when the key is absent', () => {
      renderTab();
      expect(screen.queryByText(/default role for new sign-ups/i)).not.toBeInTheDocument();
    });
  });

  describe('input checks', () => {
    it.each(['*', '@acme.com', 'com', '*.com', 'a b.com'])('refuses the domain chip %s', async (bad) => {
      const user = userEvent.setup();
      renderTab();
      await user.type(screen.getByPlaceholderText(/example\.com/i), bad);
      await user.click(screen.getByRole('button', { name: /^add$/i }));
      expect(screen.getByRole('alert')).toHaveTextContent(/not a valid domain/i);
      expect(screen.getByRole('button', { name: /save/i })).toBeDisabled();
    });

    it('accepts a wildcard subdomain chip', async () => {
      const user = userEvent.setup();
      renderTab();
      await user.type(screen.getByPlaceholderText(/example\.com/i), '*.Acme.com');
      await user.click(screen.getByRole('button', { name: /^add$/i }));
      expect(screen.getByText('*.acme.com')).toBeInTheDocument();
    });

    it('does not send 0 for an emptied number field', async () => {
      const user = userEvent.setup();
      const { onSave } = renderTab();
      const input = screen.getByLabelText(/login rate limit/i);
      await user.clear(input);
      expect(screen.getByRole('button', { name: /save/i })).toBeDisabled();
      await user.type(input, '9');
      await user.click(screen.getByRole('button', { name: /save/i }));
      expect(onSave).toHaveBeenCalledWith({ login_rate_limit: 9 });
    });

    it('confirms before resetting the domain allowlist', async () => {
      const user = userEvent.setup();
      const onReset = vi.fn();
      renderTab([makeSetting('allowed_email_domains', ['acme.com'])], { onReset });
      const resetButtons = screen.getAllByRole('button', { name: /reset/i });
      // the allowlist badge is the only overridden key whose reset sits inside its section
      const allowlistReset = resetButtons.find((b) =>
        b.closest('div.space-y-3')?.textContent?.includes('Allowed Email Domains'),
      );
      await user.click(allowlistReset!);
      expect(onReset).not.toHaveBeenCalled();
      await user.click(await screen.findByRole('button', { name: /^reset$/i }));
      expect(onReset).toHaveBeenCalledWith('allowed_email_domains');
    });
  });

  describe('provider dialog and table', () => {
    async function openEditByName(provider: OAuthProviderConfig) {
      vi.mocked(listOAuthProviders).mockResolvedValueOnce([provider]);
      const user = userEvent.setup();
      renderTab();
      expect(await screen.findByRole('button', { name: `Delete ${provider.display_name}` })).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: `Edit ${provider.display_name}` }));
      return user;
    }

    async function openEdit(provider: OAuthProviderConfig) {
      vi.mocked(listOAuthProviders).mockResolvedValueOnce([provider]);
      const user = userEvent.setup();
      renderTab();
      const row = (await screen.findByText(provider.display_name)).closest('tr');
      await user.click(within(row!).getAllByRole('button')[0]);
      return user;
    }

    it('names the row buttons and the dialog selects for assistive tech', async () => {
      const user = await openEditByName(OIDC_PROVIDER);
      expect(await screen.findByRole('combobox', { name: 'Provider Type' })).toBeInTheDocument();
      expect(screen.getByRole('combobox', { name: 'Default Role' })).toBeInTheDocument();
      expect(user).toBeDefined();
    });

    it('keeps the slug when the display name is edited on an existing provider', async () => {
      const user = await openEdit(OIDC_PROVIDER);
      const name = await screen.findByLabelText('Display Name');
      await user.clear(name);
      await user.type(name, 'Renamed');
      expect(screen.getByLabelText('Slug')).toHaveValue('legacy-oidc');
      expect(screen.queryByText(/changing the slug/i)).not.toBeInTheDocument();
    });

    it('warns when the slug of an existing provider is changed', async () => {
      const user = await openEdit(OIDC_PROVIDER);
      await user.type(await screen.findByLabelText('Slug'), 'x');
      expect(screen.getByText(/changing the slug changes the callback url/i)).toBeInTheDocument();
    });

    it('still derives the slug from the display name for a new provider', async () => {
      const user = userEvent.setup();
      renderTab();
      await user.click(screen.getByRole('button', { name: /add provider/i }));
      const name = await screen.findByLabelText('Display Name');
      await user.clear(name);
      await user.type(name, 'Acme SSO');
      expect(screen.getByLabelText('Slug')).toHaveValue('acme-sso');
    });

    it('shows the backend error detail when a save is refused', async () => {
      vi.mocked(updateOAuthProvider).mockRejectedValueOnce(new Error('Would remove the last sign-in method'));
      const user = await openEdit(OIDC_PROVIDER);
      await screen.findByLabelText('Display Name');
      await user.click(screen.getByRole('button', { name: 'Save Changes' }));
      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('Would remove the last sign-in method')),
      );
    });

    it('asks for confirmation before saving a provider whose default role is admin', async () => {
      vi.mocked(updateOAuthProvider).mockResolvedValueOnce(OIDC_PROVIDER);
      const user = await openEdit({ ...OIDC_PROVIDER, default_role: 'admin' });
      await screen.findByLabelText('Display Name');
      await user.click(screen.getByRole('button', { name: 'Save Changes' }));
      expect(updateOAuthProvider).not.toHaveBeenCalled();
      await user.click(await screen.findByRole('button', { name: /save with admin role/i }));
      await waitFor(() => expect(updateOAuthProvider).toHaveBeenCalledOnce());
    });

    it('hides group mapping fields outside the enterprise edition', async () => {
      await openEdit(OIDC_PROVIDER);
      await screen.findByLabelText('Display Name');
      expect(screen.queryByLabelText('Group Claim')).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/group role mapping/i)).not.toBeInTheDocument();
    });

    it('clears legacy group fields on save outside the enterprise edition', async () => {
      vi.mocked(updateOAuthProvider).mockResolvedValueOnce(OIDC_PROVIDER);
      const user = await openEdit({
        ...OIDC_PROVIDER,
        group_claim: 'groups',
        group_role_mapping: { Admins: 'admin' },
      });
      await screen.findByLabelText('Display Name');
      await waitFor(() => expect(fetchEdition).toHaveBeenCalled());
      await user.click(screen.getByRole('button', { name: 'Save Changes' }));
      await waitFor(() => expect(updateOAuthProvider).toHaveBeenCalledOnce());
      expect(updateOAuthProvider).toHaveBeenCalledWith(
        OIDC_PROVIDER.id,
        expect.objectContaining({ group_claim: null, group_role_mapping: null }),
      );
    });

    it('keeps a GitHub provider\'s group mapping on enterprise edits', async () => {
      vi.mocked(fetchEdition).mockResolvedValueOnce({ edition: 'enterprise', features: [] });
      vi.mocked(updateOAuthProvider).mockResolvedValueOnce(OIDC_PROVIDER);
      const mapping = { Admins: 'admin' };
      const user = await openEdit({
        ...OIDC_PROVIDER,
        provider_type: 'github',
        group_claim: 'groups',
        group_role_mapping: mapping,
      });
      await screen.findByLabelText('Display Name');
      await waitFor(() => expect(fetchEdition).toHaveBeenCalled());
      await user.click(screen.getByRole('button', { name: 'Save Changes' }));
      await waitFor(() => expect(updateOAuthProvider).toHaveBeenCalledOnce());
      expect(updateOAuthProvider).toHaveBeenCalledWith(
        OIDC_PROVIDER.id,
        expect.objectContaining({ group_claim: 'groups', group_role_mapping: mapping }),
      );
    });

    it('lists default roles, keeps unknown roles visible and drops SAML rows', async () => {
      vi.mocked(listOAuthProviders).mockResolvedValueOnce([
        { ...OIDC_PROVIDER, default_role: 'curator' },
        { ...OIDC_PROVIDER, id: 'saml-1', display_name: 'Corp SAML', provider_type: 'saml' as never },
      ]);
      renderTab();
      expect(await screen.findByText('curator')).toBeInTheDocument();
      expect(screen.queryByText('Corp SAML')).not.toBeInTheDocument();
    });
  });
});
