/**
 * SiteBanner rendering matrix.
 *
 * Scenarios:
 *  A) banner_text set            → banner renders (no auth required)
 *  B) banner_text empty/blank    → no banner
 *  C) banner_color applied       → matching token class; unknown falls back to warning
 */
import { render, screen } from '@testing-library/react';
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
  it('A) banner_text set → banner renders without auth', () => {
    renderBanner({ banner_text: 'Maintenance window Saturday 02:00 UTC' });

    expect(screen.getByRole('status').textContent).toBe('Maintenance window Saturday 02:00 UTC');
  });

  it('B) banner_text empty or blank → no banner', () => {
    renderBanner({ banner_text: '' });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();

    renderBanner({ banner_text: '   ' });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('C) banner_color maps to token class; unknown falls back to warning', () => {
    renderBanner({ banner_text: 'Heads up', banner_color: 'info' });
    expect(screen.getByRole('status').className).toContain('text-info');

    renderBanner({ banner_text: 'Heads up', banner_color: 'bogus' });
    const banners = screen.getAllByRole('status');
    expect(banners[banners.length - 1].className).toContain('text-warning');
  });
});
