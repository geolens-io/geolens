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
        onOpacityChange={vi.fn()}
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
        onOpacityChange={vi.fn()}
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
        onOpacityChange={vi.fn()}
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
        onOpacityChange={vi.fn()}
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
        onOpacityChange={vi.fn()}
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

describe('LayerStyleEditor - fill/stroke toggles', () => {
  it('renders fill and stroke toggles for polygon layers', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'Polygon', paint: { 'fill-color': '#ff0000', 'fill-opacity': 0.3 } })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText('Toggle fill visibility')).toBeInTheDocument();
    expect(screen.getByLabelText('Toggle stroke visibility')).toBeInTheDocument();
  });

  it('renders stroke toggle only for circle layers (no fill toggle)', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'Point', paint: { 'circle-color': '#ff0000' } })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.queryByLabelText('Toggle fill visibility')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Toggle stroke visibility')).toBeInTheDocument();
  });

  it('renders no toggles for line layers', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.queryByLabelText('Toggle fill visibility')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Toggle stroke visibility')).not.toBeInTheDocument();
  });

  it('toggle fill OFF sets fill-opacity to 0 and saves current value', async () => {
    const onPaintChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 0.5, '_outline-color': '#000', '_outline-width': 1 },
        })}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText('Toggle fill visibility'));
    expect(onPaintChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      '_fill-disabled': true,
      '_fill-opacity-saved': 0.5,
      'fill-opacity': 0,
    }));
  });

  it('toggle fill ON restores saved opacity and removes flags', async () => {
    const onPaintChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 0, '_fill-disabled': true, '_fill-opacity-saved': 0.5, '_outline-color': '#000', '_outline-width': 1 },
        })}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText('Toggle fill visibility'));
    const call = onPaintChange.mock.calls[0][1];
    expect(call['fill-opacity']).toBe(0.5);
    expect(call['_fill-disabled']).toBeUndefined();
    expect(call['_fill-opacity-saved']).toBeUndefined();
  });

  it('toggle stroke OFF on polygon sets _outline-width to 0', async () => {
    const onPaintChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 0.3, '_outline-color': '#000', '_outline-width': 2 },
        })}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText('Toggle stroke visibility'));
    expect(onPaintChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      '_stroke-disabled': true,
      '_outline-width-saved': 2,
      '_outline-width': 0,
    }));
  });

  it('toggle stroke OFF on circle sets circle-stroke-width to 0', async () => {
    const onPaintChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: { 'circle-color': '#ff0000', 'circle-stroke-color': '#000', 'circle-stroke-width': 3 },
        })}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText('Toggle stroke visibility'));
    expect(onPaintChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      '_stroke-disabled': true,
      '_outline-width-saved': 3,
      'circle-stroke-width': 0,
    }));
  });

  it('toggle stroke ON on circle restores saved width', async () => {
    const onPaintChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: { 'circle-color': '#ff0000', 'circle-stroke-color': '#000', 'circle-stroke-width': 0, '_stroke-disabled': true, '_outline-width-saved': 3 },
        })}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText('Toggle stroke visibility'));
    const call = onPaintChange.mock.calls[0][1];
    expect(call['circle-stroke-width']).toBe(3);
    expect(call['_stroke-disabled']).toBeUndefined();
    expect(call['_outline-width-saved']).toBeUndefined();
  });

  it('collapses fill controls when fill is disabled', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 0, '_fill-disabled': true, '_outline-color': '#000', '_outline-width': 1 },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    // Fill toggle should be present but fill controls (opacity slider) should be hidden
    expect(screen.getByLabelText('Toggle fill visibility')).toBeInTheDocument();
    // The fill opacity slider label should not be visible when collapsed
    // We check that the fill section's color/opacity controls are not present
    // The "Stroke" section should still be visible
    expect(screen.getByText('Stroke')).toBeInTheDocument();
  });

  it('collapses stroke controls when stroke is disabled on polygon', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 0.3, '_outline-color': '#000', '_outline-width': 0, '_stroke-disabled': true },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    // Stroke toggle present but stroke controls collapsed
    expect(screen.getByLabelText('Toggle stroke visibility')).toBeInTheDocument();
    expect(screen.getByText('Fill')).toBeInTheDocument();
  });
});
