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
    t: (key: string) => {
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
});
