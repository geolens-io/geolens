/**
 * fix(#1778): the Appearance/branding toggle sent `branding_show_badge`;
 * the registry key is `branding.show_badge`, so every save 400s.
 *
 * Pins the exact PUT body key `updateBranding` sends, so a future rename
 * back to the underscore spelling fails here instead of shipping a dead
 * Appearance toggle.
 */
import { updateBranding } from '@/api/settings';
import { apiFetch } from '@/api/client';

vi.mock('@/api/client', () => ({
  apiFetch: vi.fn(() => Promise.resolve({ env_only: false, tabs: {} })),
}));

const mockApiFetch = vi.mocked(apiFetch);

beforeEach(() => {
  mockApiFetch.mockClear();
});

function calledUrl() {
  return mockApiFetch.mock.calls[0]?.[0];
}
function calledInit() {
  return mockApiFetch.mock.calls[0]?.[1];
}

describe('updateBranding request contract', () => {
  it('PUTs the dotted registry key branding.show_badge, not branding_show_badge', async () => {
    await updateBranding({ show_badge: true });
    expect(calledUrl()).toBe('/settings/');
    expect(calledInit()?.method).toBe('PUT');
    expect(JSON.parse(calledInit()?.body as string)).toEqual({
      settings: { 'branding.show_badge': true },
    });
  });

  it('omits the key entirely when show_badge is undefined', async () => {
    await updateBranding({});
    expect(JSON.parse(calledInit()?.body as string)).toEqual({ settings: {} });
  });
});
