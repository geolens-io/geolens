import { render, screen } from '@/test/test-utils';
import { CircleEditor } from '../CircleEditor';
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

function makeCircleLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-circle',
    dataset_id: 'ds-circle',
    dataset_name: 'circle-dataset',
    dataset_geometry_type: 'Point',
    dataset_table_name: 'circle_table',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: 'Circle Layer',
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: { 'circle-color': '#ff0000', 'circle-radius': 5, 'circle-stroke-color': '#000', 'circle-stroke-width': 1 },
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
        'style.point': 'Point',
        'style.color': 'Color',
        'style.opacity': 'Opacity',
        'style.radius': 'Radius',
        'style.stroke': 'Stroke',
        'style.toggleStroke': 'Toggle stroke visibility',
        'style.width': 'Width',
        'style.styledBy': 'Styled by',
        'style.radiusByColumn': 'Radius by',
      };
      return labels[key] ?? key;
    },
    ...overrides,
  };
}

describe('CircleEditor', () => {
  it('renders circle-color picker, circle-opacity, circle-radius, and stroke controls', () => {
    render(<CircleEditor {...makeProps(makeCircleLayer())} />);

    // Color label may appear more than once (for the circle color + stroke color)
    expect(screen.getAllByText('Color').length).toBeGreaterThan(0);
    expect(screen.getByRole('slider', { name: 'Opacity' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Radius' })).toBeInTheDocument();
    expect(screen.getByLabelText('Toggle stroke visibility')).toBeInTheDocument();
  });

  it('renders stroke color and width sliders when strokeEnabled is true', () => {
    render(<CircleEditor {...makeProps(makeCircleLayer())} />);

    expect(screen.getByRole('slider', { name: 'Width' })).toBeInTheDocument();
  });

  it('collapses stroke controls when strokeEnabled is false', () => {
    render(<CircleEditor {...makeProps(makeCircleLayer(), { strokeEnabled: false })} />);

    expect(screen.getByLabelText('Toggle stroke visibility')).toBeInTheDocument();
    expect(screen.queryByRole('slider', { name: 'Width' })).not.toBeInTheDocument();
  });

  it('shows data-driven message instead of color picker when isDataDriven is true', () => {
    const layer = makeCircleLayer({
      style_config: { column: 'value', mode: 'graduated', ramp: 'Blues' } as MapLayerResponse['style_config'],
    });
    render(
      <CircleEditor
        {...makeProps(layer, {
          isDataDriven: true,
          t: (key: string, opts?: Record<string, unknown>) => {
            if (key === 'style.styledBy') return `Styled by: ${opts?.column}`;
            const labels: Record<string, string> = {
              'style.point': 'Point', 'style.opacity': 'Opacity', 'style.radius': 'Radius',
              'style.stroke': 'Stroke', 'style.toggleStroke': 'Toggle stroke visibility', 'style.width': 'Width',
            };
            return labels[key] ?? key;
          },
        })}
      />,
    );

    expect(screen.getByText('Styled by: value')).toBeInTheDocument();
    // Color picker button (popover trigger) should not be present in data-driven mode
    expect(screen.queryByRole('button', { name: 'Color' })).not.toBeInTheDocument();
  });

  it('hides radius slider when isDataDriven=true and target=radius', () => {
    const layer = makeCircleLayer({
      style_config: { column: 'pop', target: 'radius', mode: 'graduated', ramp: 'Blues' } as MapLayerResponse['style_config'],
    });
    render(
      <CircleEditor
        {...makeProps(layer, {
          isDataDriven: true,
          t: (key: string, opts?: Record<string, unknown>) => {
            if (key === 'style.radiusByColumn') return `Radius by: ${opts?.column}`;
            const labels: Record<string, string> = {
              'style.point': 'Point', 'style.opacity': 'Opacity', 'style.radius': 'Radius',
              'style.stroke': 'Stroke', 'style.toggleStroke': 'Toggle stroke visibility', 'style.width': 'Width',
            };
            return labels[key] ?? key;
          },
        })}
      />,
    );

    // Radius slider should be hidden when data-driven by radius
    expect(screen.queryByRole('slider', { name: 'Radius' })).not.toBeInTheDocument();
    expect(screen.getByText('Radius by: pop')).toBeInTheDocument();
  });

  it('is a named export and a default export from CircleEditor.tsx', async () => {
    const { CircleEditor: named } = await import('../CircleEditor');
    const defaultExport = (await import('../CircleEditor')).default;
    expect(named).toBeDefined();
    expect(defaultExport).toBeDefined();
    expect(named).toBe(defaultExport);
  });
});
