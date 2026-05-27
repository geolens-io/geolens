import { fireEvent, render, screen } from '@/test/test-utils';
import { LineEditor } from '../LineEditor';
import type { BaseStyleEditorProps } from '../types';
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

function makeLineLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-line',
    dataset_id: 'ds-line',
    dataset_name: 'line-dataset',
    dataset_geometry_type: 'LineString',
    dataset_table_name: 'line_table',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: 'Line Layer',
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: { 'line-color': '#ff0000', 'line-width': 2 },
    layout: {},
    filter: null,
    label_config: null,
    style_config: null,
    ...overrides,
  };
}

function makeProps(layer: MapLayerResponse, overrides: Partial<BaseStyleEditorProps> = {}): BaseStyleEditorProps {
  return {
    layer,
    paint: layer.paint as Record<string, unknown>,
    isDataDriven: false,
    builderConfig: {},
    styleConfig: null,
    symbolConfig: { iconImage: 'marker', iconSize: 1, iconRotation: 0, iconAnchor: 'center' },
    renderMode: 'points',
    isPolygon: false,
    numericColumns: [],
    currentHeightCol: '',
    strokeEnabled: true,
    fillEnabled: true,
    clusterAvailable: false,
    onPaintChange: vi.fn(),
    onLayoutChange: vi.fn(),
    onStyleConfigChange: vi.fn(),
    onRenderModeChange: vi.fn(),
    onPaintProp: vi.fn(),
    onToggleFill: vi.fn(),
    onToggleStroke: vi.fn(),
    onHeatmapPaintChange: vi.fn(),
    onSymbolConfigChange: vi.fn(),
    onBuilderChange: vi.fn(),
    t: (key: string) => {
      const labels: Record<string, string> = {
        'style.line': 'Line',
        'style.color': 'Color',
        'style.opacity': 'Opacity',
        'style.width': 'Width',
        'style.gapWidth': 'Gap',
        'style.blur': 'Blur',
        'style.offset': 'Offset',
        'style.pattern': 'Pattern',
        'style.dash.solid': 'Solid',
        'style.dash.dashed': 'Dashed',
        'style.dash.dotted': 'Dotted',
        'style.dash.dashDot': 'Dash-dot',
        'style.styledBy': 'Styled by',
        'style.widthByColumn': 'Width by',
        // LineGradientControls i18n keys
        'style.lineGradient.solid': 'Solid color',
        'style.lineGradient.gradient': 'Gradient',
        'style.lineGradient.advanced': 'Advanced',
      };
      return labels[key] ?? key;
    },
    ...overrides,
  };
}

describe('LineEditor', () => {
  it('renders line-color, line-width, line-opacity, gap width, blur, offset controls', () => {
    render(<LineEditor {...makeProps(makeLineLayer())} />);

    // Line color is accessible via the Solid/Gradient toggle (LineGradientControls)
    expect(screen.getByRole('button', { name: 'Solid color' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Opacity' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Width' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Gap' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Blur' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Offset' })).toBeInTheDocument();
  });

  it('renders 4 dash preset buttons (Solid, Dashed, Dotted, Dash-dot)', () => {
    render(<LineEditor {...makeProps(makeLineLayer())} />);

    expect(screen.getByText('Solid')).toBeInTheDocument();
    expect(screen.getByText('Dashed')).toBeInTheDocument();
    expect(screen.getByText('Dotted')).toBeInTheDocument();
    expect(screen.getByText('Dash-dot')).toBeInTheDocument();
  });

  it('calls onPaintChange with dash value when Dashed preset clicked', () => {
    const onPaintChange = vi.fn();
    render(<LineEditor {...makeProps(makeLineLayer(), { onPaintChange })} />);

    fireEvent.click(screen.getByText('Dashed'));
    expect(onPaintChange).toHaveBeenCalledWith('layer-line', {
      'line-color': '#ff0000',
      'line-width': 2,
      'line-dasharray': [4, 2],
    });
  });

  it('removes legacy layout dasharray when Solid preset clicked', () => {
    const onPaintChange = vi.fn();
    const onLayoutChange = vi.fn();
    render(
      <LineEditor {...makeProps(makeLineLayer({ paint: { 'line-color': '#ff0000', 'line-width': 2, 'line-dasharray': [4, 2] }, layout: { 'line-dasharray': [4, 2] } }), { onPaintChange, onLayoutChange })} />,
    );

    fireEvent.click(screen.getByText('Solid'));
    expect(onPaintChange).toHaveBeenCalledWith('layer-line', {
      'line-color': '#ff0000',
      'line-width': 2,
    });
    expect(onLayoutChange).toHaveBeenCalledWith('layer-line', {});
  });

  it('shows line-gradient toggle controls (Solid/Gradient mode toggle)', () => {
    render(<LineEditor {...makeProps(makeLineLayer())} />);

    expect(screen.getByRole('button', { name: 'Solid color' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Gradient' })).toBeInTheDocument();
  });

  it('shows data-driven width message instead of width slider when isDataDriven and target=width', () => {
    const layer = makeLineLayer({
      paint: { 'line-color': '#ff0000', 'line-width': ['step', ['get', 'traffic'], 1, 10, 4] },
      style_config: { column: 'traffic', target: 'width', mode: 'graduated' } as MapLayerResponse['style_config'],
    });
    render(
      <LineEditor
        {...makeProps(layer, {
          isDataDriven: true,
          styleConfig: layer.style_config ?? null,
          t: (key: string, opts?: Record<string, unknown>) => {
            if (key === 'style.widthByColumn') return `Width by: ${opts?.column}`;
            const labels: Record<string, string> = {
              'style.line': 'Line', 'style.opacity': 'Opacity', 'style.gapWidth': 'Gap',
              'style.blur': 'Blur', 'style.offset': 'Offset', 'style.pattern': 'Pattern',
              'style.dash.solid': 'Solid', 'style.dash.dashed': 'Dashed',
              'style.dash.dotted': 'Dotted', 'style.dash.dashDot': 'Dash-dot',
            };
            return labels[key] ?? key;
          },
        })}
      />,
    );

    expect(screen.getByText('Width by: traffic')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Width mode' })).not.toBeInTheDocument();
  });

  it('is a named export and a default export from LineEditor.tsx', async () => {
    const { LineEditor: named } = await import('../LineEditor');
    const defaultExport = (await import('../LineEditor')).default;
    expect(named).toBeDefined();
    expect(defaultExport).toBeDefined();
    expect(named).toBe(defaultExport);
  });

  // Phase 1136-02: line-cap / line-join Selects (EDITOR-LINE-01, EDITOR-LINE-02)
  it('renders a "Line ends" section heading after the dash pattern row', () => {
    render(<LineEditor {...makeProps(makeLineLayer(), {
      t: (key: string) => {
        const labels: Record<string, string> = {
          'style.line': 'Line', 'style.color': 'Color', 'style.opacity': 'Opacity',
          'style.width': 'Width', 'style.gapWidth': 'Gap', 'style.blur': 'Blur',
          'style.offset': 'Offset', 'style.pattern': 'Pattern',
          'style.dash.solid': 'Solid', 'style.dash.dashed': 'Dashed',
          'style.dash.dotted': 'Dotted', 'style.dash.dashDot': 'Dash-dot',
          'style.lineGradient.solid': 'Solid color', 'style.lineGradient.gradient': 'Gradient',
          'style.lineGradient.advanced': 'Advanced',
          'style.lineEnds': 'Line ends',
          'style.lineCap': 'Cap', 'style.lineCapButt': 'Butt', 'style.lineCapRound': 'Round', 'style.lineCapSquare': 'Square',
          'style.lineJoin': 'Join', 'style.lineJoinBevel': 'Bevel', 'style.lineJoinRound': 'Round', 'style.lineJoinMiter': 'Miter',
        };
        return labels[key] ?? key;
      },
    })} />);
    expect(screen.getByText('Line ends')).toBeInTheDocument();
  });

  it('renders a Cap Select with options Butt, Round, Square', () => {
    render(<LineEditor {...makeProps(makeLineLayer(), {
      t: (key: string) => {
        const labels: Record<string, string> = {
          'style.line': 'Line', 'style.color': 'Color', 'style.opacity': 'Opacity',
          'style.width': 'Width', 'style.gapWidth': 'Gap', 'style.blur': 'Blur',
          'style.offset': 'Offset', 'style.pattern': 'Pattern',
          'style.dash.solid': 'Solid', 'style.dash.dashed': 'Dashed',
          'style.dash.dotted': 'Dotted', 'style.dash.dashDot': 'Dash-dot',
          'style.lineGradient.solid': 'Solid color', 'style.lineGradient.gradient': 'Gradient',
          'style.lineGradient.advanced': 'Advanced',
          'style.lineEnds': 'Line ends',
          'style.lineCap': 'Cap', 'style.lineCapButt': 'Butt', 'style.lineCapRound': 'Round', 'style.lineCapSquare': 'Square',
          'style.lineJoin': 'Join', 'style.lineJoinBevel': 'Bevel', 'style.lineJoinRound': 'Round', 'style.lineJoinMiter': 'Miter',
        };
        return labels[key] ?? key;
      },
    })} />);
    const capTrigger = screen.getByRole('combobox', { name: 'Cap' });
    expect(capTrigger).toBeInTheDocument();
    fireEvent.click(capTrigger);
    expect(screen.getByRole('option', { name: 'Butt' })).toBeInTheDocument();
    expect(screen.getAllByRole('option', { name: 'Round' })[0]).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Square' })).toBeInTheDocument();
  });

  it('renders a Join Select with options Bevel, Round, Miter', () => {
    render(<LineEditor {...makeProps(makeLineLayer(), {
      t: (key: string) => {
        const labels: Record<string, string> = {
          'style.line': 'Line', 'style.color': 'Color', 'style.opacity': 'Opacity',
          'style.width': 'Width', 'style.gapWidth': 'Gap', 'style.blur': 'Blur',
          'style.offset': 'Offset', 'style.pattern': 'Pattern',
          'style.dash.solid': 'Solid', 'style.dash.dashed': 'Dashed',
          'style.dash.dotted': 'Dotted', 'style.dash.dashDot': 'Dash-dot',
          'style.lineGradient.solid': 'Solid color', 'style.lineGradient.gradient': 'Gradient',
          'style.lineGradient.advanced': 'Advanced',
          'style.lineEnds': 'Line ends',
          'style.lineCap': 'Cap', 'style.lineCapButt': 'Butt', 'style.lineCapRound': 'Round', 'style.lineCapSquare': 'Square',
          'style.lineJoin': 'Join', 'style.lineJoinBevel': 'Bevel', 'style.lineJoinRound': 'Round', 'style.lineJoinMiter': 'Miter',
        };
        return labels[key] ?? key;
      },
    })} />);
    const joinTrigger = screen.getByRole('combobox', { name: 'Join' });
    expect(joinTrigger).toBeInTheDocument();
    fireEvent.click(joinTrigger);
    expect(screen.getByRole('option', { name: 'Bevel' })).toBeInTheDocument();
    expect(screen.getAllByRole('option', { name: 'Round' })[0]).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Miter' })).toBeInTheDocument();
  });

  it('selecting Square from Cap Select calls onLayoutChange with line-cap: square', () => {
    const onLayoutChange = vi.fn();
    const t = (key: string) => {
      const labels: Record<string, string> = {
        'style.line': 'Line', 'style.color': 'Color', 'style.opacity': 'Opacity',
        'style.width': 'Width', 'style.gapWidth': 'Gap', 'style.blur': 'Blur',
        'style.offset': 'Offset', 'style.pattern': 'Pattern',
        'style.dash.solid': 'Solid', 'style.dash.dashed': 'Dashed',
        'style.dash.dotted': 'Dotted', 'style.dash.dashDot': 'Dash-dot',
        'style.lineGradient.solid': 'Solid color', 'style.lineGradient.gradient': 'Gradient',
        'style.lineGradient.advanced': 'Advanced',
        'style.lineEnds': 'Line ends',
        'style.lineCap': 'Cap', 'style.lineCapButt': 'Butt', 'style.lineCapRound': 'Round', 'style.lineCapSquare': 'Square',
        'style.lineJoin': 'Join', 'style.lineJoinBevel': 'Bevel', 'style.lineJoinRound': 'Round', 'style.lineJoinMiter': 'Miter',
      };
      return labels[key] ?? key;
    };
    render(<LineEditor {...makeProps(makeLineLayer(), { onLayoutChange, t })} />);
    fireEvent.click(screen.getByRole('combobox', { name: 'Cap' }));
    fireEvent.click(screen.getByRole('option', { name: 'Square' }));
    expect(onLayoutChange).toHaveBeenCalledWith('layer-line', expect.objectContaining({ 'line-cap': 'square' }));
  });

  it('selecting Bevel from Join Select calls onLayoutChange with line-join: bevel', () => {
    const onLayoutChange = vi.fn();
    const t = (key: string) => {
      const labels: Record<string, string> = {
        'style.line': 'Line', 'style.color': 'Color', 'style.opacity': 'Opacity',
        'style.width': 'Width', 'style.gapWidth': 'Gap', 'style.blur': 'Blur',
        'style.offset': 'Offset', 'style.pattern': 'Pattern',
        'style.dash.solid': 'Solid', 'style.dash.dashed': 'Dashed',
        'style.dash.dotted': 'Dotted', 'style.dash.dashDot': 'Dash-dot',
        'style.lineGradient.solid': 'Solid color', 'style.lineGradient.gradient': 'Gradient',
        'style.lineGradient.advanced': 'Advanced',
        'style.lineEnds': 'Line ends',
        'style.lineCap': 'Cap', 'style.lineCapButt': 'Butt', 'style.lineCapRound': 'Round', 'style.lineCapSquare': 'Square',
        'style.lineJoin': 'Join', 'style.lineJoinBevel': 'Bevel', 'style.lineJoinRound': 'Round', 'style.lineJoinMiter': 'Miter',
      };
      return labels[key] ?? key;
    };
    render(<LineEditor {...makeProps(makeLineLayer(), { onLayoutChange, t })} />);
    fireEvent.click(screen.getByRole('combobox', { name: 'Join' }));
    fireEvent.click(screen.getByRole('option', { name: 'Bevel' }));
    expect(onLayoutChange).toHaveBeenCalledWith('layer-line', expect.objectContaining({ 'line-join': 'bevel' }));
  });

  it('reads line-cap and line-join defaults from layer.layout and displays them', () => {
    const t = (key: string) => {
      const labels: Record<string, string> = {
        'style.line': 'Line', 'style.color': 'Color', 'style.opacity': 'Opacity',
        'style.width': 'Width', 'style.gapWidth': 'Gap', 'style.blur': 'Blur',
        'style.offset': 'Offset', 'style.pattern': 'Pattern',
        'style.dash.solid': 'Solid', 'style.dash.dashed': 'Dashed',
        'style.dash.dotted': 'Dotted', 'style.dash.dashDot': 'Dash-dot',
        'style.lineGradient.solid': 'Solid color', 'style.lineGradient.gradient': 'Gradient',
        'style.lineGradient.advanced': 'Advanced',
        'style.lineEnds': 'Line ends',
        'style.lineCap': 'Cap', 'style.lineCapButt': 'Butt', 'style.lineCapRound': 'Round', 'style.lineCapSquare': 'Square',
        'style.lineJoin': 'Join', 'style.lineJoinBevel': 'Bevel', 'style.lineJoinRound': 'Round', 'style.lineJoinMiter': 'Miter',
      };
      return labels[key] ?? key;
    };
    const layer = makeLineLayer({ layout: { 'line-cap': 'butt', 'line-join': 'miter' } });
    render(<LineEditor {...makeProps(layer, { t })} />);
    // Radix Select shows the selected value text inside the combobox trigger
    const capTrigger = screen.getByRole('combobox', { name: 'Cap' });
    const joinTrigger = screen.getByRole('combobox', { name: 'Join' });
    expect(capTrigger).toHaveTextContent('Butt');
    expect(joinTrigger).toHaveTextContent('Miter');
  });
});
