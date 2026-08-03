import { QueryClient } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { SamlProvidersSection } from '../SamlProvidersSection';
import { queryKeys } from '@/lib/query-keys';
import {
  listSamlProviders,
  createSamlProvider,
  updateSamlProvider,
  deleteSamlProvider,
  type SamlProviderConfig,
} from '@/api/saml';

vi.mock('@/api/saml', () => ({
  listSamlProviders: vi.fn().mockResolvedValue([]),
  createSamlProvider: vi.fn(),
  updateSamlProvider: vi.fn(),
  deleteSamlProvider: vi.fn(),
  fetchSamlMetadata: vi.fn(),
}));

// The section pre-fills sp_entity_id from the authoritative public_api_url; stub it
// so the component never reaches the network for tile-config.
vi.mock('@/api/settings', async () => {
  const actual = await vi.importActual<typeof import('@/api/settings')>('@/api/settings');
  return {
    ...actual,
    getTileConfig: vi.fn().mockResolvedValue({
      cdn_base_url: null,
      public_app_url: 'https://geo.example.com',
      public_api_url: 'https://geo.example.com/api',
      public_base_url: 'https://geo.example.com',
      mvt_source_layer_prefix: null,
    }),
  };
});

const SAML_PROVIDER: SamlProviderConfig = {
  id: 'saml-1',
  slug: 'okta',
  display_name: 'Okta',
  provider_type: 'saml',
  client_id: '',
  discovery_url: null,
  authorize_url: null,
  token_url: null,
  userinfo_url: null,
  scopes: '',
  default_role: 'viewer',
  group_claim: null,
  group_role_mapping: null,
  enabled: true,
  created_at: '2026-07-10T00:00:00Z',
  updated_at: '2026-07-10T00:00:00Z',
  idp_entity_id: 'https://okta.example.com/saml/metadata',
  idp_sso_url: 'https://okta.example.com/saml/sso',
  sp_entity_id: 'https://geo.example.com/api/auth/saml/okta',
};

// fix(#1117): SAML rows live in the same catalog.oauth_providers table as OAuth and
// are returned unfiltered by the login page's /auth/oauth/providers/, so a SAML
// mutation changes the login buttons too. This section invalidated its own list and
// the admin OAuth list but never authConfig.oauthProviders.
describe('SamlProvidersSection provider mutations', () => {
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
    vi.mocked(createSamlProvider).mockResolvedValueOnce(SAML_PROVIDER);
    const invalidateQueries = spyOnInvalidate();
    const user = userEvent.setup();

    render(<SamlProvidersSection />);

    await user.click(screen.getByRole('button', { name: /add saml provider/i }));
    await user.type(await screen.findByLabelText('Display Name'), 'Okta');
    await user.type(
      screen.getByLabelText('IdP Entity ID'),
      'https://okta.example.com/saml/metadata',
    );
    await user.type(
      screen.getByLabelText('IdP SSO URL'),
      'https://okta.example.com/saml/sso',
    );
    await user.type(screen.getByLabelText('IdP Signing Certificate (PEM)'), 'cert-pem');
    await user.click(screen.getByRole('button', { name: 'Create Provider' }));

    await waitFor(() => expect(createSamlProvider).toHaveBeenCalledOnce());
    expectBothProviderCaches(invalidateQueries);
  });

  it('invalidates both provider caches after an update', async () => {
    vi.mocked(listSamlProviders).mockResolvedValueOnce([SAML_PROVIDER]);
    vi.mocked(updateSamlProvider).mockResolvedValueOnce(SAML_PROVIDER);
    const invalidateQueries = spyOnInvalidate();
    const user = userEvent.setup();

    render(<SamlProvidersSection />);

    const providerRow = (await screen.findByText('Okta')).closest('tr');
    await user.click(within(providerRow!).getByRole('button', { name: 'Edit provider' }));
    const displayName = await screen.findByLabelText('Display Name');
    await user.clear(displayName);
    await user.type(displayName, 'Okta Prod');
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(updateSamlProvider).toHaveBeenCalledOnce());
    expectBothProviderCaches(invalidateQueries);
  });

  it('invalidates both provider caches after a delete', async () => {
    vi.mocked(listSamlProviders).mockResolvedValueOnce([SAML_PROVIDER]);
    vi.mocked(deleteSamlProvider).mockResolvedValueOnce(undefined);
    const invalidateQueries = spyOnInvalidate();
    const user = userEvent.setup();

    render(<SamlProvidersSection />);

    const providerRow = (await screen.findByText('Okta')).closest('tr');
    await user.click(within(providerRow!).getByRole('button', { name: 'Delete provider' }));
    await user.click(await screen.findByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(deleteSamlProvider).toHaveBeenCalledWith(SAML_PROVIDER.id));
    expectBothProviderCaches(invalidateQueries);
  });
});
