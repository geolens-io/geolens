/**
 * SiteBanner rendering matrix.
 *
 * Scenarios:
 *  A) enabled + text set          → banner renders (no auth required)
 *  B) enabled but text empty/blank → no banner
 *  C) text set but not enabled     → no banner (disabled by default)
 *  D) banner_color applied         → matching token class; unknown falls back to warning
 *  E) dismiss                      → hides, persists in sessionStorage, reappears on text change
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SiteBanner } from '../SiteBanner';
import type { AuthConfigResponse } from '@/types/api';

vi.mock('@/api/auth', () => ({
  getAuthConfig: vi.fn(),
}));

function renderBanner(config: Partial<AuthConfigResponse> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const fullConfig: AuthConfigResponse = {
    registration_enabled: false,
    landing_first: false,
    demo_mode: false,
    auth_methods: [],
    banner_enabled: true,
    ...config,
  };
  queryClient.setQueryData(['auth', 'config'], fullConfig);

  return render(
    <QueryClientProvider client={queryClient}>
      <SiteBanner />
    </QueryClientProvider>,
  );
}

describe('SiteBanner', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('A) enabled + text set → banner renders without auth', () => {
    renderBanner({ banner_text: 'Maintenance window Saturday 02:00 UTC' });

    expect(screen.getByRole('status').textContent).toContain(
      'Maintenance window Saturday 02:00 UTC',
    );
  });

  it('B) enabled but text empty or blank → no banner', () => {
    renderBanner({ banner_text: '' });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();

    renderBanner({ banner_text: '   ' });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('C) text set but banner_enabled false/absent → no banner', () => {
    renderBanner({ banner_text: 'Staged announcement', banner_enabled: false });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();

    renderBanner({ banner_text: 'Staged announcement', banner_enabled: undefined });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('D) banner_color maps to token class; unknown falls back to warning', () => {
    renderBanner({ banner_text: 'Heads up', banner_color: 'info' });
    expect(screen.getByRole('status').className).toContain('text-info');

    renderBanner({ banner_text: 'Heads up', banner_color: 'bogus' });
    const banners = screen.getAllByRole('status');
    expect(banners[banners.length - 1].className).toContain('text-warning');
  });

  it('E) dismiss hides the banner, persists per session, resets on text change', () => {
    renderBanner({ banner_text: 'Dismiss me' });
    fireEvent.click(screen.getByRole('button'));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();

    // remount with the same text — stays dismissed via sessionStorage
    renderBanner({ banner_text: 'Dismiss me' });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();

    // admin changes the text — banner reappears
    renderBanner({ banner_text: 'New announcement' });
    expect(screen.getByRole('status')).toBeInTheDocument();
  });
});
