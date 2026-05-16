import { render, screen } from '@/test/test-utils';
import { RenderModeSwitch } from '../RenderModeSwitch';
import type { BaseStyleEditorProps } from '../types';
import type { MapLayerResponse } from '@/types/api';

// Mock all sub-editors so we test dispatch, not sub-component internals
vi.mock('../FillEditor', () => ({ FillEditor: () => <div>FillEditor</div>, default: () => <div>FillEditor</div> }));
vi.mock('../LineEditor', () => ({ LineEditor: () => <div>LineEditor</div>, default: () => <div>LineEditor</div> }));
vi.mock('../CircleEditor', () => ({ CircleEditor: () => <div>CircleEditor</div>, default: () => <div>CircleEditor</div> }));
vi.mock('../SymbolEditor', () => ({ SymbolEditor: () => <div>SymbolEditor</div>, default: () => <div>SymbolEditor</div> }));
vi.mock('../HeatmapEditor', () => ({ HeatmapEditor: () => <div>HeatmapEditor</div>, default: () => <div>HeatmapEditor</div> }));
vi.mock('../ClusterEditor', () => ({ ClusterEditor: () => <div>ClusterEditor</div>, default: () => <div>ClusterEditor</div> }));
vi.mock('../RasterEditor', () => ({ RasterEditor: () => <div>RasterEditor</div>, default: () => <div>RasterEditor</div> }));

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'ds-1',
    dataset_name: 'test',
    dataset_geometry_type: 'Polygon',
    dataset_table_name: 'test_table',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: 'Layer',
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    style_config: null,
    ...overrides,
  };
}

const baseProps: Omit<BaseStyleEditorProps, 'dispatchKey'> = {
  layer: makeLayer(),
  paint: {},
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
  t: (key: string) => key,
};

describe('RenderModeSwitch', () => {
  it('renders FillEditor when dispatchKey is "fill"', () => {
    render(<RenderModeSwitch {...baseProps} dispatchKey="fill" />);
    expect(screen.getByText('FillEditor')).toBeInTheDocument();
  });

  it('renders LineEditor when dispatchKey is "line"', () => {
    render(<RenderModeSwitch {...baseProps} dispatchKey="line" />);
    expect(screen.getByText('LineEditor')).toBeInTheDocument();
  });

  it('renders CircleEditor when dispatchKey is "circle"', () => {
    render(<RenderModeSwitch {...baseProps} dispatchKey="circle" />);
    expect(screen.getByText('CircleEditor')).toBeInTheDocument();
  });

  it('renders SymbolEditor when dispatchKey is "symbol"', () => {
    render(<RenderModeSwitch {...baseProps} dispatchKey="symbol" />);
    expect(screen.getByText('SymbolEditor')).toBeInTheDocument();
  });

  it('renders HeatmapEditor when dispatchKey is "heatmap"', () => {
    render(<RenderModeSwitch {...baseProps} dispatchKey="heatmap" />);
    expect(screen.getByText('HeatmapEditor')).toBeInTheDocument();
  });

  it('renders ClusterEditor when dispatchKey is "cluster"', () => {
    render(<RenderModeSwitch {...baseProps} dispatchKey="cluster" />);
    expect(screen.getByText('ClusterEditor')).toBeInTheDocument();
  });

  it('renders RasterEditor when dispatchKey is "raster"', () => {
    render(<RenderModeSwitch {...baseProps} dispatchKey="raster" />);
    expect(screen.getByText('RasterEditor')).toBeInTheDocument();
  });

  it('returns null and emits console.warn for an unsupported dispatchKey', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    // vitest runs with NODE_ENV !== 'production', so the DEV warn path is active
    const { container } = render(<RenderModeSwitch {...baseProps} dispatchKey="unsupported-xyz" />);

    expect(container.firstChild).toBeNull();
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('unsupported-xyz'));

    warnSpy.mockRestore();
  });
});
