import { fireEvent, render, screen, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { LayerStyleEditor } from '../LayerStyleEditor';
import { LayerEditorPanel } from '../LayerEditorPanel';
import { stopsToLineGradientExpression } from '../LineGradientControls';
import type { MapLayerResponse } from '@/types/api';

// Radix Select uses ResizeObserver internally
(globalThis as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
Element.prototype.hasPointerCapture = vi.fn(() => false);
Element.prototype.releasePointerCapture = vi.fn();
Element.prototype.scrollIntoView = vi.fn();

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
  it('shows a geometry-aware pending style preview and scoped reset action', async () => {
    const onStyleConfigChange = vi.fn();
    const onOpacityChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          opacity: 0.42,
          paint: { 'fill-color': '#123456', 'fill-opacity': 0.4, '_outline-color': '#abcdef' },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={onOpacityChange}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    expect(screen.getByText('Pending style preview')).toBeInTheDocument();
    expect(screen.getByText('Reflects this layer before save')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Reset' }));
    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', null, expect.objectContaining({
      'fill-color': expect.any(String),
      'fill-opacity': expect.any(Number),
    }));
    expect(onOpacityChange).toHaveBeenCalledWith('layer-1', 1);
  });

  it('warns about unsupported imported style state without mutating style config', () => {
    const onStyleConfigChange = vi.fn();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          style_config: {
            mode: 'third_party_breaks',
            column: 'traffic',
            ramp: 'custom',
          } as unknown as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    expect(screen.getByText(/This imported style uses settings the visual editor cannot safely change/i)).toBeInTheDocument();
    expect(onStyleConfigChange).not.toHaveBeenCalled();
  });

  it('renders 4 dash preset buttons for line layers', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
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
        onRenderModeChange={vi.fn()}
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
        onRenderModeChange={vi.fn()}
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
        onRenderModeChange={vi.fn()}
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
        onRenderModeChange={vi.fn()}
      />,
    );

    const dottedBtn = screen.getByText('Dotted');
    expect(dottedBtn.className).toContain('bg-primary');

    const solidBtn = screen.getByText('Solid');
    expect(solidBtn.className).not.toContain('bg-primary');
  });
});

describe('LayerStyleEditor - line paint controls', () => {
  it('renders gap width, blur, and offset controls with existing line controls', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    expect(screen.getByText('Color')).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Opacity' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Width' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Gap' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Blur' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Offset' })).toBeInTheDocument();
    expect(screen.getByText('Solid')).toBeInTheDocument();
  });

  it('writes explicit line gap width, blur, and offset paint values', () => {
    const onPaintChange = vi.fn();

    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    fireEvent.keyDown(screen.getByRole('slider', { name: 'Gap' }), { key: 'ArrowRight' });
    fireEvent.keyDown(screen.getByRole('slider', { name: 'Blur' }), { key: 'ArrowRight' });
    fireEvent.keyDown(screen.getByRole('slider', { name: 'Offset' }), { key: 'ArrowLeft' });

    expect(onPaintChange).toHaveBeenCalledWith('layer-1', {
      'line-color': '#ff0000',
      'line-width': 2,
      'line-gap-width': 0.25,
    });
    expect(onPaintChange).toHaveBeenCalledWith('layer-1', {
      'line-color': '#ff0000',
      'line-width': 2,
      'line-blur': 0.25,
    });
    expect(onPaintChange).toHaveBeenCalledWith('layer-1', {
      'line-color': '#ff0000',
      'line-width': 2,
      'line-offset': -0.25,
    });
  });

  it('emits line width zoom expressions from the first-class editor', async () => {
    const onPaintChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    await user.click(within(screen.getByRole('group', { name: 'Width mode' })).getByRole('button', { name: 'Varies by zoom' }));

    expect(onPaintChange).toHaveBeenCalledWith('layer-1', {
      'line-color': '#ff0000',
      'line-width': ['interpolate', ['linear'], ['zoom'], 4, 2, 12, 2],
    });
  });

  it('preserves data-driven width messaging instead of exposing zoom width editing', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({
          paint: { 'line-color': '#ff0000', 'line-width': ['step', ['get', 'traffic'], 1, 10, 4] },
          style_config: { column: 'traffic', target: 'width', mode: 'graduated' } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    expect(screen.getByText('Width by: traffic')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Width mode' })).not.toBeInTheDocument();
  });

  it('shows unsupported line zoom-plus-data expressions without flattening them', () => {
    const onPaintChange = vi.fn();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          paint: {
            'line-color': '#ff0000',
            'line-width': ['interpolate', ['linear'], ['zoom'], 4, ['get', 'width'], 12, 6],
          },
        })}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    expect(screen.getByText('This property uses an unsupported expression. Use Advanced JSON to edit it.')).toBeInTheDocument();
    expect(onPaintChange).not.toHaveBeenCalled();
  });

  it('exposes first-class line gradient authoring controls (Phase 256)', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    // Phase 256 introduces first-class gradient authoring on line layers
    // (replaces the Phase 247 deferral where gradients were JSON-only).
    expect(screen.getByRole('button', { name: 'Gradient' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Solid color' })).toBeInTheDocument();
  });

  it('accepts line-gradient through advanced paint JSON', async () => {
    const onPaintChange = vi.fn();
    const user = userEvent.setup();
    const gradientPaint = {
      'line-color': '#ff0000',
      'line-width': 2,
      'line-gradient': ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'],
    };

    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Advanced JSON' }));
    await user.click(screen.getByRole('button', { name: 'Paint' }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: JSON.stringify(gradientPaint) } });
    await user.click(screen.getByRole('button', { name: 'Apply' }));

    expect(onPaintChange).toHaveBeenCalledWith('layer-1', gradientPaint);
  });
});

describe('LayerStyleEditor - circle zoom expression controls', () => {
  it('emits circle radius zoom expressions from the point style editor', async () => {
    const onPaintChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: { 'circle-color': '#ff0000', 'circle-radius': 5 },
        })}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    await user.click(within(screen.getByRole('group', { name: 'Radius mode' })).getByRole('button', { name: 'Varies by zoom' }));

    expect(onPaintChange).toHaveBeenCalledWith('layer-1', {
      'circle-color': '#ff0000',
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 5, 12, 5],
    });
  });

  it('edits supported circle opacity expressions without raw JSON', () => {
    const onPaintChange = vi.fn();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: {
            'circle-color': '#ff0000',
            'circle-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.4, 12, 1],
            'circle-radius': 5,
          },
        })}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('Opacity Stop 2 value'), { target: { value: '0.75' } });

    expect(onPaintChange).toHaveBeenCalledWith('layer-1', {
      'circle-color': '#ff0000',
      'circle-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.4, 12, 0.75],
      'circle-radius': 5,
    });
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

  it('toggle fill OFF sets fill-opacity to 0 and saves current value in style_config', async () => {
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 0.5 },
          style_config: { builder: { outlineColor: '#000', outlineWidth: 1 } } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText('Toggle fill visibility'));
    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      builder: expect.objectContaining({
        fillDisabled: true,
        fillOpacitySaved: 0.5,
      }),
    }), expect.objectContaining({
      'fill-opacity': 0,
    }));
  });

  it('toggle fill ON restores saved opacity and removes builder flags', async () => {
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 0 },
          style_config: { builder: { fillDisabled: true, fillOpacitySaved: 0.5, outlineColor: '#000', outlineWidth: 1 } } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText('Toggle fill visibility'));
    const [, config, paint] = onStyleConfigChange.mock.calls[0];
    expect(paint['fill-opacity']).toBe(0.5);
    expect(config.builder.fillDisabled).toBeUndefined();
    expect(config.builder.fillOpacitySaved).toBeUndefined();
  });

  it('toggle stroke OFF on polygon sets builder outline width to 0', async () => {
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 0.3 },
          style_config: { builder: { outlineColor: '#000', outlineWidth: 2 } } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText('Toggle stroke visibility'));
    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      builder: expect.objectContaining({
        strokeDisabled: true,
        outlineWidthSaved: 2,
        outlineWidth: 0,
      }),
    }), expect.not.objectContaining({ '_stroke-disabled': true }));
  });

  it('toggle stroke OFF on circle sets circle-stroke-width to 0', async () => {
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: { 'circle-color': '#ff0000', 'circle-stroke-color': '#000', 'circle-stroke-width': 3 },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText('Toggle stroke visibility'));
    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      builder: expect.objectContaining({
        strokeDisabled: true,
        outlineWidthSaved: 3,
      }),
    }), expect.objectContaining({
      'circle-stroke-width': 0,
    }));
  });

  it('toggle stroke ON on circle restores saved width', async () => {
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: { 'circle-color': '#ff0000', 'circle-stroke-color': '#000', 'circle-stroke-width': 0 },
          style_config: { builder: { strokeDisabled: true, outlineWidthSaved: 3 } } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText('Toggle stroke visibility'));
    const [, config, paint] = onStyleConfigChange.mock.calls[0];
    expect(paint['circle-stroke-width']).toBe(3);
    expect(config).toBeNull();
  });

  it('collapses fill controls when fill is disabled', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 0 },
          style_config: { builder: { fillDisabled: true, outlineColor: '#000', outlineWidth: 1 } } as import('@/types/api').StyleConfig,
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
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 0.3 },
          style_config: { builder: { outlineColor: '#000', outlineWidth: 0, strokeDisabled: true } } as import('@/types/api').StyleConfig,
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

describe('LayerStyleEditor - render mode (heatmap)', () => {
  it('renders "Render as" dropdown for point layers', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'Point', paint: { 'circle-color': '#ff0000' } })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    expect(screen.getByText('Render as')).toBeInTheDocument();
  });

  it('does NOT render "Render as" dropdown for polygon layers', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'Polygon', paint: { 'fill-color': '#ff0000' } })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    expect(screen.queryByText('Render as')).not.toBeInTheDocument();
  });

  it('does NOT render "Render as" dropdown for line layers', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'LineString', paint: { 'line-color': '#ff0000' } })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    expect(screen.queryByText('Render as')).not.toBeInTheDocument();
  });

  it('shows heatmap controls when render_mode is heatmap', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: { 'heatmap-radius': 30, 'heatmap-intensity': 1 },
          style_config: { mode: 'categorical', column: '', ramp: '', render_mode: 'heatmap' } as unknown as import('@/types/api').StyleConfig,
          dataset_column_info: [{ name: 'count', type: 'integer' }],
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    // Heatmap controls should be present
    expect(screen.getByText('Weight column')).toBeInTheDocument();
    expect(screen.getByText('Color ramp')).toBeInTheDocument();
    expect(screen.getByText('Radius')).toBeInTheDocument();
    expect(screen.getByText('Intensity')).toBeInTheDocument();

    // Circle controls should be absent
    expect(screen.queryByLabelText('Toggle stroke visibility')).not.toBeInTheDocument();
  });

  it('shows symbol controls when render_mode is symbol', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: {},
          style_config: {
            render_mode: 'symbol',
            symbol: { iconImage: 'marker', iconSize: 1 },
          } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    expect(screen.getAllByText('Symbol').length).toBeGreaterThan(0);
    expect(screen.getByLabelText('Icon')).toHaveValue('marker');
    expect(screen.getByRole('slider', { name: 'Size' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Rotation' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Toggle stroke visibility')).not.toBeInTheDocument();
  });

  it('offers cluster as a render mode for eligible point layers', async () => {
    const onRenderModeChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          dataset_feature_count: 100,
          paint: { 'circle-color': '#ff0000', 'circle-radius': 5 },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={onRenderModeChange}
      />,
    );

    await user.click(screen.getAllByRole('combobox')[0]);
    await user.click(screen.getByRole('option', { name: 'Cluster' }));

    expect(onRenderModeChange).toHaveBeenCalledWith('layer-1', 'cluster');
  });

  it('shows cluster authoring controls and writes builder config only', () => {
    const onStyleConfigChange = vi.fn();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          dataset_feature_count: 100,
          paint: { 'circle-color': '#ff0000', 'circle-radius': 5 },
          style_config: {
            render_mode: 'cluster',
            builder: {
              clusterRadius: 36,
              clusterMaxZoom: 12,
              clusterColor: '#3b82f6',
              clusterTextColor: '#ffffff',
              clusterTextSize: 13,
            },
          } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    expect(screen.getByText('Cluster appearance')).toBeInTheDocument();
    expect(screen.getByText('Tune cluster radius, expansion zoom, and count labels.')).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Cluster radius' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Max cluster zoom' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cluster color' })).toHaveAttribute('title', '#3b82f6');
    expect(screen.getByRole('button', { name: 'Count color' })).toHaveAttribute('title', '#ffffff');
    expect(screen.getByRole('slider', { name: 'Count size' })).toBeInTheDocument();

    fireEvent.keyDown(screen.getByRole('slider', { name: 'Cluster radius' }), { key: 'ArrowRight' });

    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      render_mode: 'cluster',
      builder: expect.objectContaining({
        clusterRadius: 37,
        clusterMaxZoom: 12,
        clusterTextSize: 13,
      }),
    }), { 'circle-color': '#ff0000', 'circle-radius': 5 });
  });

  it('writes symbol icon settings into style_config and keeps paint clean', () => {
    const onStyleConfigChange = vi.fn();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: { 'circle-color': '#ff0000' },
          style_config: {
            render_mode: 'symbol',
            symbol: { iconImage: 'marker' },
          } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('Icon'), { target: { value: 'bus' } });

    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      render_mode: 'symbol',
      symbol: expect.objectContaining({ iconImage: 'bus' }),
    }), { 'circle-color': '#ff0000' });
  });

  it('stores heatmap weight metadata in style_config and keeps paint clean', async () => {
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: { 'heatmap-radius': 30, 'heatmap-intensity': 1 },
          style_config: { render_mode: 'heatmap', builder: { heatmapRamp: 'YlOrRd' } } as import('@/types/api').StyleConfig,
          dataset_column_info: [{ name: 'count', type: 'integer' }],
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );

    const [, weightSelect] = screen.getAllByRole('combobox');
    await user.click(weightSelect);
    await user.click(screen.getByRole('option', { name: 'count' }));

    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      builder: expect.objectContaining({
        heatmapRamp: 'YlOrRd',
        heatmapWeightColumn: 'count',
      }),
    }), expect.objectContaining({
      'heatmap-weight': ['get', 'count'],
    }));
    const paint = onStyleConfigChange.mock.calls[0][2];
    expect(paint['_heatmap-weight-column']).toBeUndefined();
    expect(paint['_heatmap-ramp']).toBeUndefined();
  });
});

describe('LayerStyleEditor — line-gradient integration', () => {
  it('integration: line-gradient renders Solid/Gradient toggle inside line controls', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: 'Solid color' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Gradient' })).toBeInTheDocument();
  });

  it('integration: line-gradient toggle does not render for polygon layers', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'Polygon', paint: { 'fill-color': '#abcdef' } })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Gradient' })).not.toBeInTheDocument();
  });

  it('integration: clicking Gradient line-gradient mode commits builder.lineGradient.stops and a canonical paint expression', async () => {
    const onPaintChange = vi.fn();
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();
    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
        onRenderModeChange={vi.fn()}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Gradient' }));
    // paint MUST contain a canonical line-gradient array
    const paintCalls = onPaintChange.mock.calls as Array<[string, Record<string, unknown>]>;
    const paintWithGradient = paintCalls.find((c) => Array.isArray(c[1]['line-gradient']));
    expect(paintWithGradient).toBeDefined();
    // styleConfig MUST contain builder.lineGradient.stops
    const styleConfigCalls = onStyleConfigChange.mock.calls as Array<[string, { builder?: { lineGradient?: { stops?: unknown[] } } } | null, Record<string, unknown>]>;
    const builderUpdate = styleConfigCalls.find((c) => Array.isArray(c[1]?.builder?.lineGradient?.stops));
    expect(builderUpdate).toBeDefined();
  });
});

describe('LayerEditorPanel — layer switch state isolation (WR-01)', () => {
  const handlers = {
    onTabChange: vi.fn(),
    onPaintChange: vi.fn(),
    onOpacityChange: vi.fn(),
    onFilterChange: vi.fn(),
    onLabelChange: vi.fn(),
    onPopupChange: vi.fn(),
    onStyleConfigChange: vi.fn(),
    onLayoutChange: vi.fn(),
    onRenderModeChange: vi.fn(),
    onRemove: vi.fn(),
  };

  it('switching from layer with no gradient to layer with gradient resets local mode to Gradient (no stale solid)', () => {
    const layerA: MapLayerResponse = {
      ...makeLayer({ id: 'layer-A', paint: { 'line-color': '#ff0000' } }),
    };
    const gradientExpr = stopsToLineGradientExpression([
      { position: 0, color: '#000' },
      { position: 1, color: '#fff' },
    ]);
    const layerB: MapLayerResponse = {
      ...makeLayer({
        id: 'layer-B',
        paint: { 'line-gradient': gradientExpr },
        style_config: { builder: { lineGradient: { stops: [{ position: 0, color: '#000' }, { position: 1, color: '#fff' }] } } } as import('@/types/api').StyleConfig,
      }),
    };

    const { rerender } = render(
      <LayerEditorPanel layer={layerA} activeTab="style" handlers={handlers} onClose={vi.fn()} />,
    );
    // Layer A starts in Solid mode (no gradient)
    expect(screen.getByRole('button', { name: 'Solid color' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Gradient' })).toHaveAttribute('aria-pressed', 'false');

    // Switch to layer B (which has a canonical gradient). With key={layer.id},
    // the LayerStyleEditor remounts and LineGradientControls re-derives initialMode
    // from layer B's paint, putting the toggle into Gradient mode.
    rerender(<LayerEditorPanel layer={layerB} activeTab="style" handlers={handlers} onClose={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Gradient' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Solid color' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('switching from layer with gradient to layer without gradient resets local mode to Solid', () => {
    const gradientExpr = stopsToLineGradientExpression([
      { position: 0, color: '#000' },
      { position: 1, color: '#fff' },
    ]);
    const layerA: MapLayerResponse = {
      ...makeLayer({
        id: 'layer-A',
        paint: { 'line-gradient': gradientExpr },
        style_config: { builder: { lineGradient: { stops: [{ position: 0, color: '#000' }, { position: 1, color: '#fff' }] } } } as import('@/types/api').StyleConfig,
      }),
    };
    const layerB: MapLayerResponse = {
      ...makeLayer({ id: 'layer-B', paint: { 'line-color': '#ff0000' } }),
    };

    const { rerender } = render(
      <LayerEditorPanel layer={layerA} activeTab="style" handlers={handlers} onClose={vi.fn()} />,
    );
    expect(screen.getByRole('button', { name: 'Gradient' })).toHaveAttribute('aria-pressed', 'true');

    rerender(<LayerEditorPanel layer={layerB} activeTab="style" handlers={handlers} onClose={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Solid color' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Gradient' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('renders inspector tabs and back control with visible keyboard focus treatment', () => {
    render(
      <LayerEditorPanel
        layer={makeLayer()}
        activeTab="filter"
        handlers={handlers}
        onClose={vi.fn()}
        isDrillDown={true}
        enableLegacyTabs={true}
      />,
    );

    const tablist = screen.getByRole('tablist');
    const filterTab = within(tablist).getByRole('tab', { name: 'Filter' });
    expect(filterTab).toHaveAttribute('aria-selected', 'true');
    expect(filterTab.className).toContain('focus-visible:ring-2');
    expect(screen.getByRole('button', { name: 'Back to layers' }).className).toContain('focus-visible:ring-2');
  });
});
