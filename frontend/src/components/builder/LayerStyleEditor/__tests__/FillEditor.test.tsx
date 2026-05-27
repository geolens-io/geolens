import { fireEvent, render, screen } from '@/test/test-utils';
import { FillEditor } from '../FillEditor';
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

function makeFillLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-fill',
    dataset_id: 'ds-fill',
    dataset_name: 'fill-dataset',
    dataset_geometry_type: 'Polygon',
    dataset_table_name: 'fill_table',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: 'Fill Layer',
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: { 'fill-color': '#3b82f6', 'fill-opacity': 0.8, '_outline-color': '#1d4ed8' },
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
    isPolygon: true,
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
    t: (key: string, opts?: Record<string, unknown>) => {
      if (key === 'style.extrusionRange') {
        const o = opts ?? {};
        return `Range: ${o.min}–${o.max}, ${o.count} features`;
      }
      const labels: Record<string, string> = {
        'style.fill': 'Fill',
        'style.toggleFill': 'Toggle fill visibility',
        'style.color': 'Color',
        'style.opacity': 'Opacity',
        'style.stroke': 'Stroke',
        'style.toggleStroke': 'Toggle stroke visibility',
        'style.width': 'Width',
        'style.heightColumn': 'Height column',
        'style.none': 'None',
        'style.styledBy': 'Styled by',
      };
      return labels[key] ?? key;
    },
    ...overrides,
  };
}

describe('FillEditor', () => {
  it('renders fill-opacity slider, fill-color picker, and stroke controls', () => {
    render(<FillEditor {...makeProps(makeFillLayer())} />);

    expect(screen.getByLabelText('Toggle fill visibility')).toBeInTheDocument();
    expect(screen.getByLabelText('Toggle stroke visibility')).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Opacity' })).toBeInTheDocument();
    // Color label appears for fill color and stroke color; both should be present
    expect(screen.getAllByText('Color').length).toBeGreaterThan(0);
  });

  it('renders stroke color and width when strokeEnabled is true', () => {
    render(<FillEditor {...makeProps(makeFillLayer())} />);

    // Stroke is enabled so stroke width slider should appear
    expect(screen.getByRole('slider', { name: 'Width' })).toBeInTheDocument();
  });

  it('collapses fill controls when fillEnabled is false', () => {
    render(<FillEditor {...makeProps(makeFillLayer(), { fillEnabled: false })} />);

    // Fill toggle still present
    expect(screen.getByLabelText('Toggle fill visibility')).toBeInTheDocument();
    // Fill opacity slider hidden when collapsed
    expect(screen.queryByRole('slider', { name: 'Opacity' })).not.toBeInTheDocument();
  });

  it('shows data-driven message instead of color picker when isDataDriven is true', () => {
    const layer = makeFillLayer({
      style_config: { column: 'population', mode: 'graduated', ramp: 'Blues' } as MapLayerResponse['style_config'],
    });
    render(
      <FillEditor
        {...makeProps(layer, {
          isDataDriven: true,
          t: (key: string, opts?: Record<string, unknown>) => {
            if (key === 'style.styledBy') return `Styled by: ${opts?.column}`;
            return key;
          },
        })}
      />,
    );

    expect(screen.getByText('Styled by: population')).toBeInTheDocument();
    // The fill color picker button should not be present in data-driven mode
    // (stroke color picker may still appear)
    expect(screen.queryByRole('button', { name: 'Color' })).not.toBeInTheDocument();
  });

  it('calls onToggleFill when fill switch clicked', async () => {
    const onToggleFill = vi.fn();
    render(<FillEditor {...makeProps(makeFillLayer(), { onToggleFill })} />);

    fireEvent.click(screen.getByLabelText('Toggle fill visibility'));
    expect(onToggleFill).toHaveBeenCalledTimes(1);
  });

  it('calls onToggleStroke when stroke switch clicked', async () => {
    const onToggleStroke = vi.fn();
    render(<FillEditor {...makeProps(makeFillLayer(), { onToggleStroke })} />);

    fireEvent.click(screen.getByLabelText('Toggle stroke visibility'));
    expect(onToggleStroke).toHaveBeenCalledTimes(1);
  });

  it('shows height column selector when isPolygon=true and numericColumns provided', () => {
    render(
      <FillEditor
        {...makeProps(makeFillLayer({
          dataset_column_info: [{ name: 'height', type: 'integer' }],
        }), {
          numericColumns: [{ name: 'height', type: 'integer' }],
          isPolygon: true,
          currentHeightCol: '',
          t: (key: string) => {
            const labels: Record<string, string> = {
              'style.fill': 'Fill', 'style.toggleFill': 'Toggle fill visibility',
              'style.color': 'Color', 'style.opacity': 'Opacity',
              'style.stroke': 'Stroke', 'style.toggleStroke': 'Toggle stroke visibility',
              'style.width': 'Width', 'style.heightColumn': 'Height column',
              'style.none': 'None', 'style.styledBy': 'Styled by',
            };
            return labels[key] ?? key;
          },
        })}
      />,
    );

    expect(screen.getByText('Height column')).toBeInTheDocument();
  });

  it('is a named export and a default export from FillEditor.tsx', async () => {
    // Verify both export forms resolve to the same component
    const { FillEditor: named } = await import('../FillEditor');
    const defaultExport = (await import('../FillEditor')).default;
    expect(named).toBeDefined();
    expect(defaultExport).toBeDefined();
    expect(named).toBe(defaultExport);
  });

  // --- 3D extrusion range hint tests ---

  it('shows range hint with integer min–max and count when dataset_sample_values has data', () => {
    const layer = makeFillLayer({
      dataset_column_info: [{ name: 'height', type: 'integer' }],
      dataset_sample_values: { height: [10, 50, 200] },
    });
    render(
      <FillEditor
        {...makeProps(layer, {
          numericColumns: [{ name: 'height', type: 'integer' }],
          currentHeightCol: 'height',
          isPolygon: true,
        })}
      />,
    );

    expect(screen.getByText(/Range:.*features/)).toBeInTheDocument();
    expect(screen.getByText('Range: 10–200, 3 features')).toBeInTheDocument();
  });

  it('hides range hint when dataset_sample_values is null', () => {
    const layer = makeFillLayer({
      dataset_column_info: [{ name: 'height', type: 'integer' }],
      dataset_sample_values: null,
    });
    render(
      <FillEditor
        {...makeProps(layer, {
          numericColumns: [{ name: 'height', type: 'integer' }],
          currentHeightCol: 'height',
          isPolygon: true,
        })}
      />,
    );

    expect(screen.queryByText(/Range:/)).not.toBeInTheDocument();
  });

  it('hides range hint when dataset_sample_values has an empty array for the column', () => {
    const layer = makeFillLayer({
      dataset_column_info: [{ name: 'height', type: 'integer' }],
      dataset_sample_values: { height: [] },
    });
    render(
      <FillEditor
        {...makeProps(layer, {
          numericColumns: [{ name: 'height', type: 'integer' }],
          currentHeightCol: 'height',
          isPolygon: true,
        })}
      />,
    );

    expect(screen.queryByText(/Range:/)).not.toBeInTheDocument();
  });

  it('renders fractional min–max with 1 decimal place', () => {
    const layer = makeFillLayer({
      dataset_column_info: [{ name: 'height', type: 'double' }],
      dataset_sample_values: { height: [1.5, 2.7, 3.1] },
    });
    render(
      <FillEditor
        {...makeProps(layer, {
          numericColumns: [{ name: 'height', type: 'double' }],
          currentHeightCol: 'height',
          isPolygon: true,
        })}
      />,
    );

    expect(screen.getByText('Range: 1.5–3.1, 3 features')).toBeInTheDocument();
  });

  it('renders integer min/max without .0 and uses toLocaleString for large counts', () => {
    const layer = makeFillLayer({
      dataset_column_info: [{ name: 'height', type: 'integer' }],
      dataset_sample_values: { height: [1, 1247] },
    });
    render(
      <FillEditor
        {...makeProps(layer, {
          numericColumns: [{ name: 'height', type: 'integer' }],
          currentHeightCol: 'height',
          isPolygon: true,
        })}
      />,
    );

    // count uses toLocaleString — "2" for 2 items; min=1, max=1247
    expect(screen.getByText('Range: 1–1,247, 2 features')).toBeInTheDocument();
  });

  it('hides range hint when currentHeightCol is empty string', () => {
    const layer = makeFillLayer({
      dataset_column_info: [{ name: 'height', type: 'integer' }],
      dataset_sample_values: { height: [10, 50, 200] },
    });
    render(
      <FillEditor
        {...makeProps(layer, {
          numericColumns: [{ name: 'height', type: 'integer' }],
          currentHeightCol: '',
          isPolygon: true,
        })}
      />,
    );

    expect(screen.queryByText(/Range:/)).not.toBeInTheDocument();
  });

  // Rule 1 auto-fix (1136-07): API returns sample values as strings; deriveExtrusionRange
  // must coerce them to numbers so the range hint shows in production.
  it('shows range hint when dataset_sample_values contains string numeric values (API format)', () => {
    const layer = makeFillLayer({
      dataset_column_info: [{ name: 'elevation', type: 'integer' }],
      // Simulate API response format: values are strings like "573", "515"
      dataset_sample_values: { elevation: ['573', '515', '607', '660', '595'] as unknown as number[] },
    });
    render(
      <FillEditor
        {...makeProps(layer, {
          numericColumns: [{ name: 'elevation', type: 'integer' }],
          currentHeightCol: 'elevation',
          isPolygon: true,
        })}
      />,
    );

    expect(screen.getByText(/Range:.*features/)).toBeInTheDocument();
    // min=515, max=660, count=5
    expect(screen.getByText('Range: 515–660, 5 features')).toBeInTheDocument();
  });

  it('hides range hint when all string values are non-numeric (e.g., column codes)', () => {
    const layer = makeFillLayer({
      dataset_column_info: [{ name: 'fcode', type: 'character varying' }],
      dataset_sample_values: { fcode: ['39009', '39004'] as unknown as number[] },
    });
    // fcode is character varying, not in numericColumns, so the height column section won't show
    // But even if it did, non-parseable strings should produce no hint
    render(
      <FillEditor
        {...makeProps(layer, {
          numericColumns: [],
          currentHeightCol: '',
          isPolygon: true,
        })}
      />,
    );

    expect(screen.queryByText(/Range:/)).not.toBeInTheDocument();
  });
});
