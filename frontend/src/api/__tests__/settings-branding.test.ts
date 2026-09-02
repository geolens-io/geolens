/**
 * fix(#1778): updateBranding accepts Partial<BrandingConfig> -- so
 * `updateBranding({ privacy_url: '...' })` typechecks -- but only ever
 * forwarded `show_badge` into the PUT payload, silently dropping
 * privacy_url (and any future BrandingConfig field). A privacy_url-only
 * call issued `PUT /settings/` with an empty settings object and still
 * resolved as a success.
 *
 * These pin the request body updateBranding builds for privacy_url alone
 * and for both fields together, so a future field added to BrandingConfig
 * that is not also forwarded here fails this test instead of shipping
 * silently broken. settings.contract.test.ts already covers the
 * show_badge-only and empty-payload cases (including the dotted
 * `branding.show_badge` registry key), so this file does not repeat those.
 */
import { apiFetch } from '@/api/client';
import { updateBranding } from '@/api/settings';

vi.mock('@/api/client', () => ({
  apiFetch: vi.fn(() => Promise.resolve({ env_only: false, tabs: {} })),
}));

const mockApiFetch = vi.mocked(apiFetch);

function calledBody() {
  const init = mockApiFetch.mock.calls[0]?.[1];
  return JSON.parse((init?.body as string) ?? '{}');
}

describe('updateBranding forwards privacy_url', () => {
  beforeEach(() => vi.clearAllMocks());

  it('forwards a privacy_url-only update instead of silently dropping it', async () => {
    await updateBranding({ privacy_url: 'https://example.com/privacy' });

    expect(mockApiFetch).toHaveBeenCalledWith('/settings/', expect.objectContaining({ method: 'PUT' }));
    expect(calledBody()).toEqual({ settings: { privacy_url: 'https://example.com/privacy' } });
  });

  it('forwards both fields together when both are given', async () => {
    await updateBranding({ show_badge: false, privacy_url: 'https://example.com/privacy' });

    expect(calledBody()).toEqual({
      settings: { 'branding.show_badge': false, privacy_url: 'https://example.com/privacy' },
    });
  });

  it('forwards an explicit null privacy_url (clearing the value)', async () => {
    await updateBranding({ privacy_url: null });

    expect(calledBody()).toEqual({ settings: { privacy_url: null } });
  });
});
