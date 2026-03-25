import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { LayerStyleEditor } from '../LayerStyleEditor';
import type { MapLayerResponse } from '@/types/api';

// Radix Select uses ResizeObserver internally
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

const makeLayer = (overrides: Partial<MapLayerResponse> = {}): MapLayerResponse => ({
  id: 'layer-1',
  dataset_id: 'ds-1',
  dataset_name: 'test-dataset',
  dataset_geometry_type: 'LineString',
  dataset_table_name: 'test_table',
  dataset_extent_bbox: null,
  dataset_column_info: null,
  dataset_feature_count: null,
  dataset_sample_values: null,
  display_name: 'Test Layer',
  sort_order: 0,
  visible: true,
  opacity: 1,
  paint: { 'line-color': '#ff0000', 'line-width': 2 },
  layout: {},
  filter: null,
  label_config: null,
  style_config: null,
  ...overrides,
});

describe('LayerStyleEditor - dash presets', () => {
  it('renders 4 dash preset buttons for line layers', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.getByText('Solid')).toBeInTheDocument();
    expect(screen.getByText('Dashed')).toBeInTheDocument();
    expect(screen.getByText('Dotted')).toBeInTheDocument();
    expect(screen.getByText('Dash-dot')).toBeInTheDocument();
  });

  it('does not render dash presets for polygon layers', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'Polygon', paint: { 'fill-color': '#ff0000' } })}
        onPaintChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.queryByText('Solid')).not.toBeInTheDocument();
    expect(screen.queryByText('Dashed')).not.toBeInTheDocument();
  });

  it('calls onLayoutChange with dash value when preset clicked', async () => {
    const onLayoutChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={onLayoutChange}
      />,
    );

    await user.click(screen.getByText('Dashed'));
    expect(onLayoutChange).toHaveBeenCalledWith('layer-1', { 'line-dasharray': [4, 2] });
  });

  it('calls onLayoutChange without dasharray when Solid clicked', async () => {
    const onLayoutChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({ layout: { 'line-dasharray': [4, 2] } })}
        onPaintChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={onLayoutChange}
      />,
    );

    await user.click(screen.getByText('Solid'));
    // Solid removes line-dasharray from layout
    expect(onLayoutChange).toHaveBeenCalledWith('layer-1', {});
  });

  it('highlights the active preset based on current layout', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ layout: { 'line-dasharray': [1, 2] } })}
        onPaintChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    const dottedBtn = screen.getByText('Dotted');
    expect(dottedBtn.className).toContain('bg-primary');

    const solidBtn = screen.getByText('Solid');
    expect(solidBtn.className).not.toContain('bg-primary');
  });
});
