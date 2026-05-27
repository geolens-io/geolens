import { fireEvent, render, screen } from '@/test/test-utils';
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
      role="slider"
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
});
