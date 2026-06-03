import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { HeatmapStyleControls } from '../HeatmapStyleControls';
import type { MapLayerResponse } from '@/types/api';

// Radix Slider uses ResizeObserver which jsdom doesn't provide
class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver;

vi.mock('../ColorRampPicker', () => ({
  ColorRampPicker: ({ rampName, onChange }: { rampName: string; onChange: (name: string) => void }) => (
    <button data-testid="color-ramp-picker" onClick={() => onChange('Viridis')}>
      {rampName}
    </button>
  ),
}));

vi.mock('../layer-adapters/heatmap-adapter', () => ({
  buildHeatmapColorExpression: vi.fn(() => ['interpolate', ['linear'], ['heatmap-density'], 0, 'transparent', 1, 'red']),
}));

const baseLayer: MapLayerResponse = {
  id: 'layer-1',
  dataset_id: 'ds-1',
  dataset_title: 'Test',
  geometry_type: 'Point',
  layer_type: 'heatmap',
  paint: {
    'heatmap-radius': 30,
    'heatmap-intensity': 1,
  },
  layout: {},
  visible: true,
  order_index: 0,
  dataset_column_info: [
    { name: 'population', type: 'integer' },
    { name: 'area', type: 'double precision' },
    { name: 'name', type: 'varchar' },
  ],
} as unknown as MapLayerResponse;

describe('HeatmapStyleControls', () => {
  it('renders color ramp picker and slider controls', () => {
    render(<HeatmapStyleControls layer={baseLayer} onPaintChange={vi.fn()} />);

    expect(screen.getByTestId('color-ramp-picker')).toBeInTheDocument();
    // Radius and intensity values should be displayed
    expect(screen.getByText('30px')).toBeInTheDocument();
    expect(screen.getByText('1.0')).toBeInTheDocument();
  });

  it('calls onPaintChange when color ramp is changed', async () => {
    const user = userEvent.setup();
    const onPaintChange = vi.fn();
    render(<HeatmapStyleControls layer={baseLayer} onPaintChange={onPaintChange} />);

    await user.click(screen.getByTestId('color-ramp-picker'));

    expect(onPaintChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      '_heatmap-ramp': 'Viridis',
      'heatmap-color': expect.any(Array),
    }));
  });

  it('displays current color ramp name', () => {
    const layerWithRamp = {
      ...baseLayer,
      paint: { ...baseLayer.paint, '_heatmap-ramp': 'Blues' },
    } as unknown as MapLayerResponse;

    render(<HeatmapStyleControls layer={layerWithRamp} onPaintChange={vi.fn()} />);

    expect(screen.getByTestId('color-ramp-picker')).toHaveTextContent('Blues');
  });
});
