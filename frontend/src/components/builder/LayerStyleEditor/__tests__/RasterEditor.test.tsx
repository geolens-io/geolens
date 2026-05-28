import { fireEvent, render, screen, within } from '@/test/test-utils';
import { RasterEditor } from '../RasterEditor';
import type { BaseStyleEditorProps } from '../types';
import type { MapLayerResponse } from '@/types/api';

// Mock coalesceFrame to invoke synchronously so fireEvent.change tests work
// without needing to advance rAF timers (same pattern as raf-coalesce.test.ts).
vi.mock('@/lib/builder/raf-coalesce', () => ({
  coalesceFrame: (_key: string, fn: () => void) => fn(),
  __getPendingForTest: () => new Map(),
  __flushForTest: () => {},
  __resetForTest: () => {},
}));

// Mock shadcn Select to a simple native <select> so fireEvent.change works
// without needing a portal/Radix runtime in jsdom.
vi.mock('@/components/ui/select', async () => {
  const { createElement, Fragment } = await import('react');
  const Select = ({ value, onValueChange, children }: {
    value: string;
    onValueChange: (v: string) => void;
    children: React.ReactNode;
  }) =>
    createElement(
      'select',
      { 'data-slot': 'select', value, onChange: (e: React.ChangeEvent<HTMLSelectElement>) => onValueChange(e.target.value) },
      children,
    );
  const SelectTrigger = ({ children }: { children: React.ReactNode }) => createElement(Fragment, null, children);
  const SelectValue = () => null;
  const SelectContent = ({ children }: { children: React.ReactNode }) => createElement(Fragment, null, children);
  const SelectItem = ({ value, children, disabled }: {
    value: string;
    children: React.ReactNode;
    disabled?: boolean;
  }) => createElement('option', { value, disabled }, children);
  return { Select, SelectTrigger, SelectValue, SelectContent, SelectItem };
});

// Mock the Slider to a native input so fireEvent.change and aria-valuetext work
vi.mock('@/components/ui/slider', () => ({
  Slider: ({
    value,
    min,
    max,
    step,
    onValueChange,
    'aria-label': ariaLabel,
    'aria-valuetext': ariaValuetext,
  }: {
    value: number[];
    min: number;
    max: number;
    step: number;
    onValueChange: (value: number[]) => void;
    'aria-label': string;
    'aria-valuetext': string;
  }) => (
    <input
      type="range"
      aria-label={ariaLabel}
      aria-valuetext={ariaValuetext}
      value={value[0]}
      min={min}
      max={max}
      step={step}
      onChange={(e) => onValueChange([Number(e.currentTarget.value)])}
    />
  ),
}));

function makeRasterLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-raster-1',
    dataset_id: 'ds-raster-1',
    dataset_name: 'raster-dataset',
    dataset_geometry_type: null,
    dataset_table_name: 'raster_table',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: 'Raster Layer',
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
    strokeEnabled: false,
    fillEnabled: false,
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
        'style.raster.title': 'Raster',
        'style.raster.brightnessMin': 'Brightness min',
        'style.raster.contrast': 'Contrast',
        'style.raster.saturation': 'Saturation',
        'style.raster.hueRotate': 'Hue',
        'style.raster.reset': 'Reset',
        'style.raster.resetTitle': 'Reset raster style',
        'style.raster.sectionColormap': 'COLORMAP',
        'style.raster.colormapLabel': 'Colormap',
        'style.raster.stretchLabel': 'Stretch',
        'style.raster.stretchMinmax': 'Min/Max',
        'style.raster.stretchPercentile': 'Percentile (2–98%)',
        'style.raster.stretchStddev': 'Std Deviation',
        'style.raster.colormapGray': 'Grayscale',
        'style.raster.colormapViridis': 'Viridis',
        'style.raster.colormapInferno': 'Inferno',
        'style.raster.colormapPlasma': 'Plasma',
        'style.raster.colormapMagma': 'Magma',
        'style.raster.colormapYlorrd': 'Yellow-Red',
        'style.raster.colormapBugn': 'Blue-Green',
        'style.raster.colormapTerrain': 'Terrain',
      };
      return labels[key] ?? key;
    },
    ...overrides,
  };
}

describe('RasterEditor', () => {
  it('Test 1: renders all 4 sliders with correct aria-labels', () => {
    render(<RasterEditor {...makeProps(makeRasterLayer())} />);

    expect(screen.getByRole('slider', { name: 'Brightness min' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Contrast' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Saturation' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Hue' })).toBeInTheDocument();
  });

  it('Test 2: Brightness slider change calls onPaintProp with raster-brightness-min', () => {
    const onPaintProp = vi.fn();
    render(<RasterEditor {...makeProps(makeRasterLayer(), { onPaintProp })} />);

    const slider = screen.getByRole('slider', { name: 'Brightness min' });
    fireEvent.change(slider, { target: { value: '0.6' } });

    expect(onPaintProp).toHaveBeenCalledWith('raster-brightness-min', 0.6);
  });

  it('Test 3: Contrast slider change calls onPaintProp with raster-contrast', () => {
    const onPaintProp = vi.fn();
    render(<RasterEditor {...makeProps(makeRasterLayer(), { onPaintProp })} />);

    const slider = screen.getByRole('slider', { name: 'Contrast' });
    fireEvent.change(slider, { target: { value: '0.3' } });

    expect(onPaintProp).toHaveBeenCalledWith('raster-contrast', 0.3);
  });

  it('Test 4: Saturation slider change calls onPaintProp with raster-saturation', () => {
    const onPaintProp = vi.fn();
    render(<RasterEditor {...makeProps(makeRasterLayer(), { onPaintProp })} />);

    const slider = screen.getByRole('slider', { name: 'Saturation' });
    fireEvent.change(slider, { target: { value: '-0.4' } });

    expect(onPaintProp).toHaveBeenCalledWith('raster-saturation', -0.4);
  });

  it('Test 5: Hue slider change calls onPaintProp with raster-hue-rotate', () => {
    const onPaintProp = vi.fn();
    render(<RasterEditor {...makeProps(makeRasterLayer(), { onPaintProp })} />);

    const slider = screen.getByRole('slider', { name: 'Hue' });
    fireEvent.change(slider, { target: { value: '45' } });

    expect(onPaintProp).toHaveBeenCalledWith('raster-hue-rotate', 45);
  });

  it('Test 6: Reset button calls onPaintProp 4 times with RASTER_PAINT_DEFAULTS values', () => {
    const onPaintProp = vi.fn();
    const { container } = render(<RasterEditor {...makeProps(makeRasterLayer(), { onPaintProp })} />);

    // Open the Reset collapsible by clicking the trigger button (only one button at this point)
    const buttons = screen.getAllByRole('button');
    const triggerBtn = buttons[0]; // The trigger is the first (and only) button initially
    fireEvent.click(triggerBtn);

    // After opening, find the Reset action button inside CollapsibleContent
    // It is the Button with type="button" that is a direct child of the collapsible content div
    const allButtons = container.querySelectorAll('button[type="button"]');
    // The second button is the reset action button (first is the trigger)
    const actionBtn = allButtons[1];
    if (actionBtn) {
      fireEvent.click(actionBtn);
    }

    expect(onPaintProp).toHaveBeenCalledWith('raster-brightness-min', 0);
    expect(onPaintProp).toHaveBeenCalledWith('raster-contrast', 0);
    expect(onPaintProp).toHaveBeenCalledWith('raster-saturation', 0);
    expect(onPaintProp).toHaveBeenCalledWith('raster-hue-rotate', 0);
  });

  it('Test 7: save→reload symmetry — paint values flow into slider aria-valuetext', () => {
    const layer = makeRasterLayer({
      paint: {
        'raster-brightness-min': 0.7,
        'raster-contrast': 0.2,
        'raster-saturation': -0.1,
        'raster-hue-rotate': 120,
      },
    });
    render(
      <RasterEditor
        {...makeProps(layer, { paint: layer.paint as Record<string, unknown> })}
      />,
    );

    expect(screen.getByRole('slider', { name: 'Brightness min' })).toHaveAttribute(
      'aria-valuetext',
      '0.70',
    );
    expect(screen.getByRole('slider', { name: 'Contrast' })).toHaveAttribute(
      'aria-valuetext',
      '0.20',
    );
    expect(screen.getByRole('slider', { name: 'Saturation' })).toHaveAttribute(
      'aria-valuetext',
      '-0.10',
    );
    expect(screen.getByRole('slider', { name: 'Hue' })).toHaveAttribute(
      'aria-valuetext',
      '120°',
    );
  });

  it('Test 8: default export equals named export', async () => {
    const mod = await import('../RasterEditor');
    expect(mod.default).toBe(mod.RasterEditor);
  });

  // ─── COLORMAP section tests ───────────────────────────────────────────────

  it('Test 9: COLORMAP section renders when band_count === 1', () => {
    render(
      <RasterEditor
        {...makeProps(makeRasterLayer({ band_count: 1 }))}
      />,
    );
    expect(screen.getByText('COLORMAP')).toBeInTheDocument();
  });

  it('Test 10: COLORMAP section is absent when band_count === 3 (multi-band)', () => {
    render(
      <RasterEditor
        {...makeProps(makeRasterLayer({ band_count: 3 }))}
      />,
    );
    expect(screen.queryByText('COLORMAP')).not.toBeInTheDocument();
  });

  it('Test 11: COLORMAP section is absent when band_count is null', () => {
    render(
      <RasterEditor
        {...makeProps(makeRasterLayer({ band_count: null }))}
      />,
    );
    expect(screen.queryByText('COLORMAP')).not.toBeInTheDocument();
  });

  it('Test 12: COLORMAP section is absent when band_count is undefined', () => {
    render(
      <RasterEditor
        {...makeProps(makeRasterLayer({ band_count: undefined }))}
      />,
    );
    expect(screen.queryByText('COLORMAP')).not.toBeInTheDocument();
  });

  it('Test 13: changing the colormap Select fires onPaintProp("_colormap", value)', () => {
    const onPaintProp = vi.fn();
    render(
      <RasterEditor
        {...makeProps(makeRasterLayer({ band_count: 1 }), { onPaintProp })}
      />,
    );

    // The colormap select has value "gray" by default.
    // Find the native select by its current value and change it.
    const selects = screen.getAllByRole('combobox');
    // First select is colormap, second is stretch
    const colormapSelect = selects[0]!;
    fireEvent.change(colormapSelect, { target: { value: 'viridis' } });

    expect(onPaintProp).toHaveBeenCalledWith('_colormap', 'viridis');
  });

  it('Test 14: selecting minmax stretch fires onPaintProp("_stretch", "minmax")', () => {
    const onPaintProp = vi.fn();
    render(
      <RasterEditor
        {...makeProps(makeRasterLayer({ band_count: 1 }), { onPaintProp })}
      />,
    );

    const selects = screen.getAllByRole('combobox');
    const stretchSelect = selects[1]!;
    // Re-select minmax to fire the handler
    fireEvent.change(stretchSelect, { target: { value: 'minmax' } });

    expect(onPaintProp).toHaveBeenCalledWith('_stretch', 'minmax');
  });

  it('Test 15: the 8 colormap options are present in the colormap Select', () => {
    render(
      <RasterEditor
        {...makeProps(makeRasterLayer({ band_count: 1 }))}
      />,
    );
    const selects = screen.getAllByRole('combobox');
    const colormapSelect = selects[0]!;
    // Check accessible names (i18n labels) for all 8 colormaps
    const expectedLabels = ['Grayscale', 'Viridis', 'Inferno', 'Plasma', 'Magma', 'Yellow-Red', 'Blue-Green', 'Terrain'];
    for (const label of expectedLabels) {
      expect(within(colormapSelect).getByRole('option', { name: label })).toBeInTheDocument();
    }
    // Also verify the Titiler value attributes
    const expectedValues = ['gray', 'viridis', 'inferno', 'plasma', 'magma', 'ylorrd', 'bugn', 'terrain'];
    const options = within(colormapSelect).getAllByRole('option');
    const actualValues = options.map((o) => (o as HTMLOptionElement).value);
    for (const v of expectedValues) {
      expect(actualValues).toContain(v);
    }
  });

  it('Test 16: the 3 stretch options are present and all enabled (v1032)', () => {
    render(
      <RasterEditor
        {...makeProps(makeRasterLayer({ band_count: 1 }))}
      />,
    );
    const selects = screen.getAllByRole('combobox');
    const stretchSelect = selects[1]!;

    const minmaxOpt = within(stretchSelect).getByRole('option', { name: /min\/max/i });
    expect(minmaxOpt).not.toBeDisabled();

    const percentileOpt = within(stretchSelect).getByRole('option', { name: /percentile/i });
    expect(percentileOpt).not.toBeDisabled();

    const stddevOpt = within(stretchSelect).getByRole('option', { name: /std/i });
    expect(stddevOpt).not.toBeDisabled();
  });

  it('Test 17: selecting percentile fires onPaintProp("_stretch", "percentile")', () => {
    const onPaintProp = vi.fn();
    render(
      <RasterEditor
        {...makeProps(makeRasterLayer({ band_count: 1 }), { onPaintProp })}
      />,
    );

    const selects = screen.getAllByRole('combobox');
    const stretchSelect = selects[1]!;
    fireEvent.change(stretchSelect, { target: { value: 'percentile' } });

    expect(onPaintProp).toHaveBeenCalledWith('_stretch', 'percentile');
  });

  it('Test 18: selecting stddev fires onPaintProp("_stretch", "stddev"); no "coming soon" suffix', () => {
    const onPaintProp = vi.fn();
    render(
      <RasterEditor
        {...makeProps(makeRasterLayer({ band_count: 1 }), { onPaintProp })}
      />,
    );
    const selects = screen.getAllByRole('combobox');
    const stretchSelect = selects[1]!;
    fireEvent.change(stretchSelect, { target: { value: 'stddev' } });
    expect(onPaintProp).toHaveBeenCalledWith('_stretch', 'stddev');
    // The strategies are implemented in v1032 — the "coming soon" suffix is gone.
    expect(screen.queryByText(/coming soon/i)).not.toBeInTheDocument();
  });
});
