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
  ColorRampPicker: ({
    rampName,
    onChange,
    reversed,
    onReversedChange,
  }: {
    rampName: string;
    onChange: (name: string) => void;
    reversed?: boolean;
    onReversedChange?: (v: boolean) => void;
  }) => (
    <div>
      <button data-testid="color-ramp-picker" onClick={() => onChange('Viridis')}>
        {rampName}
      </button>
      <button
        data-testid="ramp-reverse-toggle"
        data-reversed={String(reversed ?? false)}
        onClick={() => onReversedChange?.(!reversed)}
      >
        reverse
      </button>
    </div>
  ),
}));

vi.mock('../layer-adapters/heatmap-adapter', () => ({
  buildHeatmapColorExpression: vi.fn(() => ['interpolate', ['linear'], ['heatmap-density'], 0, 'transparent', 1, 'red']),
}));

import { buildHeatmapColorExpression } from '../layer-adapters/heatmap-adapter';

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

  // test(#828): the reverse toggle regressed once in the 1.6.0 cycle (an inert
  // default-false checkbox with no callback wired). Pin the write side: toggling
  // must persist _heatmap-reversed AND rebuild heatmap-color with the flag.
  describe('ramp reversal write side (#828)', () => {
    beforeEach(() => {
      vi.mocked(buildHeatmapColorExpression).mockClear();
    });

    it('toggling reverse on writes _heatmap-reversed=true and rebuilds heatmap-color', async () => {
      const user = userEvent.setup();
      const onPaintChange = vi.fn();
      render(<HeatmapStyleControls layer={baseLayer} onPaintChange={onPaintChange} />);

      await user.click(screen.getByTestId('ramp-reverse-toggle'));

      expect(onPaintChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
        '_heatmap-reversed': true,
        'heatmap-color': expect.any(Array),
      }));
      // The rebuilt expression must be flagged reversed for the default ramp.
      expect(buildHeatmapColorExpression).toHaveBeenLastCalledWith('YlOrRd', true);
    });

    it('toggling reverse off on a reversed layer writes _heatmap-reversed=false', async () => {
      const user = userEvent.setup();
      const onPaintChange = vi.fn();
      const reversedLayer = {
        ...baseLayer,
        paint: { ...baseLayer.paint, '_heatmap-ramp': 'Blues', '_heatmap-reversed': true },
      } as unknown as MapLayerResponse;
      render(<HeatmapStyleControls layer={reversedLayer} onPaintChange={onPaintChange} />);

      await user.click(screen.getByTestId('ramp-reverse-toggle'));

      expect(onPaintChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
        '_heatmap-reversed': false,
      }));
      expect(buildHeatmapColorExpression).toHaveBeenLastCalledWith('Blues', false);
    });

    it('defaults the reverse toggle to false when paint has no _heatmap-reversed', () => {
      render(<HeatmapStyleControls layer={baseLayer} onPaintChange={vi.fn()} />);
      expect(screen.getByTestId('ramp-reverse-toggle')).toHaveAttribute('data-reversed', 'false');
    });

    it('reflects _heatmap-reversed=true from paint in the reverse toggle', () => {
      const reversedLayer = {
        ...baseLayer,
        paint: { ...baseLayer.paint, '_heatmap-reversed': true },
      } as unknown as MapLayerResponse;
      render(<HeatmapStyleControls layer={reversedLayer} onPaintChange={vi.fn()} />);
      expect(screen.getByTestId('ramp-reverse-toggle')).toHaveAttribute('data-reversed', 'true');
    });

    it('changing the ramp preserves the reversed flag in the rebuilt expression', async () => {
      const user = userEvent.setup();
      const onPaintChange = vi.fn();
      const reversedLayer = {
        ...baseLayer,
        paint: { ...baseLayer.paint, '_heatmap-reversed': true },
      } as unknown as MapLayerResponse;
      render(<HeatmapStyleControls layer={reversedLayer} onPaintChange={onPaintChange} />);

      await user.click(screen.getByTestId('color-ramp-picker'));

      expect(onPaintChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
        '_heatmap-ramp': 'Viridis',
        '_heatmap-reversed': true,
      }));
      expect(buildHeatmapColorExpression).toHaveBeenLastCalledWith('Viridis', true);
    });
  });

  // fix(#788 item 3): SliderRow omitted aria-valuetext, so AT read the raw
  // number ("0.8") while the screen showed the formatted value ("80%").
  it('exposes the formatted value to AT via aria-valuetext on each slider', () => {
    render(<HeatmapStyleControls layer={baseLayer} onPaintChange={vi.fn()} />);

    // Radius, intensity, opacity — in render order. The attribute must sit on
    // the role="slider" element (the thumb), not a wrapper span.
    const valuetexts = screen
      .getAllByRole('slider')
      .map((thumb) => thumb.getAttribute('aria-valuetext'));
    expect(valuetexts).toEqual(['30px', '1.0', '80%']);
  });
});
