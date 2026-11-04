import { screen } from '@testing-library/react';
import { render } from '@/test/test-utils';
import type { DashboardConfig } from '@/types/api';
import type { ReaderTheme } from '@/lib/reader-theme';
import { DashboardPanel } from '../DashboardPanel';
import { ViewerWithDashboard } from '../ViewerWithDashboard';

vi.mock('@/api/aggregate', () => ({ fetchAggregate: vi.fn(() => new Promise(() => {})) }));

const layerId = '0b7d2f4e-3c1a-4e8b-9f6d-5a2c7e1b9d34';

function config(panel?: 'right' | 'bottom'): DashboardConfig {
  return {
    version: 1,
    ...(panel ? { panel } : {}),
    widgets: [
      {
        id: '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11',
        type: 'indicator',
        v: 1,
        layer_id: layerId,
        scope: 'layer',
        config: { stat: 'count', column: null },
      },
    ],
  } as DashboardConfig;
}

function renderLayout(panel?: 'right' | 'bottom', readerTheme?: ReaderTheme) {
  render(
    <ViewerWithDashboard
      config={config(panel)}
      readerTheme={readerTheme}
      layers={[{ id: layerId, dataset_id: 'ds-1', dataset_name: 'Parcels' } as never]}
    >
      {() => <div data-testid="viewport" />}
    </ViewerWithDashboard>,
  );
  return screen.getByTestId('viewport').parentElement!;
}

describe('ViewerWithDashboard', () => {
  it('puts the panel beside the map on wide screens by default', () => {
    expect(renderLayout().className).toContain('md:flex-row');
  });

  it('keeps the panel below the map when the author chose the bottom', () => {
    const layout = renderLayout('bottom');
    expect(layout.className).not.toContain('md:flex-row');
    expect(screen.getByRole('region', { name: 'Dashboard' })).toBeInTheDocument();
  });
});

describe('reader theme', () => {
  const theme = { accent: '#0a7f4f', logo_url: 'https://cdn.example.com/logo.svg', font_family: null };

  it('scopes the accent to the viewer and shows the logo in the dashboard header', () => {
    const layout = renderLayout('right', theme);
    expect(layout.style.getPropertyValue('--primary')).toBe('#0a7f4f');
    expect(document.documentElement.style.getPropertyValue('--primary')).toBe('');
    const panel = screen.getByRole('region', { name: 'Dashboard' });
    expect(panel.querySelector('img')).toHaveAttribute('src', theme.logo_url);
  });

  it('renders with the standard tokens and no logo without a theme', () => {
    const layout = renderLayout('right');
    expect(layout.getAttribute('style')).toBeNull();
    expect(screen.getByRole('region', { name: 'Dashboard' }).querySelector('img')).toBeNull();
  });

  it('leaves the panel the Builder renders unthemed', () => {
    render(<DashboardPanel config={config('right')} layers={[{ id: layerId } as never]} map={null} />);
    const panel = screen.getByRole('region', { name: 'Dashboard' });
    expect(panel.querySelector('img')).toBeNull();
    expect(panel.closest('[style]')).toBeNull();
  });
});
