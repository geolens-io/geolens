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
        'style.raster.stretchColormapHint': 'Stretch sets the input range for the colormap.',
        'style.raster.pminLabel': 'Low %',
        'style.raster.pmaxLabel': 'High %',
        'style.raster.sigmaLabel': 'Sigma (σ)',
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

  // ─── GATE-SPLIT tests ─────────────────────────────────────────────────────

  it('Test 19: multi-band (band_count=3): stretch Select present, colormap Select absent', () => {
    render(
      <RasterEditor
        {...makeProps(makeRasterLayer({ band_count: 3 }))}
      />,
    );
    // Stretch select exists (has Min/Max option)
    const selects = screen.getAllByRole('combobox');
    expect(selects.length).toBeGreaterThanOrEqual(1);
    const stretchSelect = selects[0]!;
    expect(within(stretchSelect).getByRole('option', { name: /min\/max/i })).toBeInTheDocument();
    // Colormap option absent — viridis should not be in any select
    const allOptions = screen.queryAllByRole('option', { name: /viridis/i });
    expect(allOptions.length).toBe(0);
  });

  it('Test 20: single-band (band_count=1): both colormap and stretch selects present', () => {
    render(
      <RasterEditor
        {...makeProps(makeRasterLayer({ band_count: 1 }))}
      />,
    );
    const selects = screen.getAllByRole('combobox');
    expect(selects.length).toBeGreaterThanOrEqual(2);
    // First select is colormap (has Viridis option)
    expect(within(selects[0]!).getByRole('option', { name: /viridis/i })).toBeInTheDocument();
    // Second select is stretch (has Min/Max option)
    expect(within(selects[1]!).getByRole('option', { name: /min\/max/i })).toBeInTheDocument();
  });

  it('Test 21: band_count=null: neither colormap nor stretch selects render', () => {
    render(
      <RasterEditor
        {...makeProps(makeRasterLayer({ band_count: null }))}
      />,
    );
    expect(screen.queryAllByRole('combobox').length).toBe(0);
  });

  it('Test 22: band_count=undefined: neither colormap nor stretch selects render', () => {
    render(
      <RasterEditor
        {...makeProps(makeRasterLayer({ band_count: undefined }))}
      />,
    );
    expect(screen.queryAllByRole('combobox').length).toBe(0);
  });

  // ─── PERCENTILE INPUTS tests ──────────────────────────────────────────────

  it('Test 23: percentile stretch: Low% / High% number inputs appear', () => {
    const layer = makeRasterLayer({ band_count: 1, paint: { _stretch: 'percentile' } });
    render(
      <RasterEditor
        {...makeProps(layer, { paint: layer.paint as Record<string, unknown> })}
      />,
    );
    const spinbuttons = screen.getAllByRole('spinbutton');
    expect(spinbuttons.length).toBeGreaterThanOrEqual(2);
  });

  it('Test 24: percentile out-of-range guard: pmin >= pmax does not call onPaintProp("_pmin", invalid)', () => {
    const onPaintProp = vi.fn();
    // pmax default is 98; enter pmin=99 which is > pmax=98 — invalid
    const layer = makeRasterLayer({ band_count: 1, paint: { _stretch: 'percentile' } });
    render(
      <RasterEditor
        {...makeProps(layer, { paint: layer.paint as Record<string, unknown>, onPaintProp })}
      />,
    );
    const spinbuttons = screen.getAllByRole('spinbutton');
    const pminInput = spinbuttons[0]!;
    fireEvent.change(pminInput, { target: { value: '99' } });
    // Should not call onPaintProp with the invalid value 99 (>= pmax 98)
    const calls = onPaintProp.mock.calls.filter(
      ([k, v]) => k === '_pmin' && v === 99,
    );
    expect(calls.length).toBe(0);
  });

  it('Test 25: percentile out-of-range guard: pmin < 0 does not call onPaintProp("_pmin", invalid)', () => {
    const onPaintProp = vi.fn();
    const layer = makeRasterLayer({ band_count: 1, paint: { _stretch: 'percentile' } });
    render(
      <RasterEditor
        {...makeProps(layer, { paint: layer.paint as Record<string, unknown>, onPaintProp })}
      />,
    );
    const spinbuttons = screen.getAllByRole('spinbutton');
    const pminInput = spinbuttons[0]!;
    fireEvent.change(pminInput, { target: { value: '-5' } });
    const calls = onPaintProp.mock.calls.filter(
      ([k, v]) => k === '_pmin' && v === -5,
    );
    expect(calls.length).toBe(0);
  });

  it('Test 26: percentile valid entry: pmin=10 calls onPaintProp("_pmin", 10)', () => {
    const onPaintProp = vi.fn();
    const layer = makeRasterLayer({ band_count: 1, paint: { _stretch: 'percentile' } });
    render(
      <RasterEditor
        {...makeProps(layer, { paint: layer.paint as Record<string, unknown>, onPaintProp })}
      />,
    );
    const spinbuttons = screen.getAllByRole('spinbutton');
    const pminInput = spinbuttons[0]!;
    fireEvent.change(pminInput, { target: { value: '10' } });
    expect(onPaintProp).toHaveBeenCalledWith('_pmin', 10);
  });

  // ─── SIGMA SEGMENTED tests ────────────────────────────────────────────────

  it('Test 27: stddev stretch: sigma buttons 1/2/3 render with aria-pressed on default 2', () => {
    const layer = makeRasterLayer({ band_count: 1, paint: { _stretch: 'stddev' } });
    render(
      <RasterEditor
        {...makeProps(layer, { paint: layer.paint as Record<string, unknown> })}
      />,
    );
    const btn1 = screen.getByRole('button', { name: '1' });
    const btn2 = screen.getByRole('button', { name: '2' });
    const btn3 = screen.getByRole('button', { name: '3' });
    expect(btn1).toBeInTheDocument();
    expect(btn2).toBeInTheDocument();
    expect(btn3).toBeInTheDocument();
    // Default sigma is 2 → aria-pressed=true on btn2
    expect(btn2).toHaveAttribute('aria-pressed', 'true');
    expect(btn1).toHaveAttribute('aria-pressed', 'false');
    expect(btn3).toHaveAttribute('aria-pressed', 'false');
  });

  it('Test 28: sigma button click fires onPaintProp("_sigma", 3)', () => {
    const onPaintProp = vi.fn();
    const layer = makeRasterLayer({ band_count: 1, paint: { _stretch: 'stddev' } });
    render(
      <RasterEditor
        {...makeProps(layer, { paint: layer.paint as Record<string, unknown>, onPaintProp })}
      />,
    );
    const btn3 = screen.getByRole('button', { name: '3' });
    fireEvent.click(btn3);
    expect(onPaintProp).toHaveBeenCalledWith('_sigma', 3);
  });

  it('Test 29: minmax stretch: no pmin/pmax/sigma controls', () => {
    const layer = makeRasterLayer({ band_count: 1, paint: { _stretch: 'minmax' } });
    render(
      <RasterEditor
        {...makeProps(layer, { paint: layer.paint as Record<string, unknown> })}
      />,
    );
    expect(screen.queryAllByRole('spinbutton').length).toBe(0);
    // sigma buttons: no button named '1', '2', or '3'
    expect(screen.queryByRole('button', { name: '1' })).toBeNull();
    expect(screen.queryByRole('button', { name: '2' })).toBeNull();
    expect(screen.queryByRole('button', { name: '3' })).toBeNull();
  });

  // ─── HINT tests ───────────────────────────────────────────────────────────

  it('Test 30: hint present when band_count=1 && stretch=percentile && colormap=viridis', () => {
    const layer = makeRasterLayer({
      band_count: 1,
      paint: { _stretch: 'percentile', _colormap: 'viridis' },
    });
    render(
      <RasterEditor
        {...makeProps(layer, { paint: layer.paint as Record<string, unknown> })}
      />,
    );
    const note = screen.getByRole('note');
    expect(note).toHaveTextContent('Stretch sets the input range for the colormap.');
  });

  it('Test 31: hint absent for stretch=minmax (even with non-gray colormap)', () => {
    const layer = makeRasterLayer({
      band_count: 1,
      paint: { _stretch: 'minmax', _colormap: 'viridis' },
    });
    render(
      <RasterEditor
        {...makeProps(layer, { paint: layer.paint as Record<string, unknown> })}
      />,
    );
    expect(screen.queryByRole('note')).toBeNull();
  });

  it('Test 32: hint absent for colormap=gray (even with non-minmax stretch)', () => {
    const layer = makeRasterLayer({
      band_count: 1,
      paint: { _stretch: 'percentile', _colormap: 'gray' },
    });
    render(
      <RasterEditor
        {...makeProps(layer, { paint: layer.paint as Record<string, unknown> })}
      />,
    );
    expect(screen.queryByRole('note')).toBeNull();
  });

  it('Test 33: hint absent for band_count=3', () => {
    const layer = makeRasterLayer({
      band_count: 3,
      paint: { _stretch: 'percentile', _colormap: 'viridis' },
    });
    render(
      <RasterEditor
        {...makeProps(layer, { paint: layer.paint as Record<string, unknown> })}
      />,
    );
    expect(screen.queryByRole('note')).toBeNull();
  });
});
