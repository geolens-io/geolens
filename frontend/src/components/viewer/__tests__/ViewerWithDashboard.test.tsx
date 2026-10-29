import { screen } from '@testing-library/react';
import { render } from '@/test/test-utils';
import type { DashboardConfig } from '@/types/api';
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

function renderLayout(panel?: 'right' | 'bottom') {
  render(
    <ViewerWithDashboard
      config={config(panel)}
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
