import { fireEvent, render, screen } from '@/test/test-utils';
import { DEMEditorScene } from '../DEMEditorScene';
import type { MapLayerResponse } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) => {
      if (options?.defaultValue !== undefined) {
        let result = options.defaultValue as string;
        const params = options as Record<string, unknown>;
        Object.keys(params).forEach((k) => {
          if (k !== 'defaultValue') {
            result = result.replace(`{{${k}}}`, String(params[k]));
          }
        });
        return result;
      }
      return key;
    },
  }),
}));

vi.mock('../StyleColorPicker', () => ({
  StyleColorPicker: ({
    label,
    color,
    onChange,
  }: {
    label: string;
    color: string;
    onChange: (value: string) => void;
  }) => (
    <button type="button" aria-label={label} data-testid={`color-picker-${label.toLowerCase()}`} onClick={() => onChange('#ABCDEF')}>
      {label}:{color}
    </button>
  ),
}));

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

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});

function makeDEMLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: overrides.id ?? 'dem-layer-1',
    dataset_id: overrides.dataset_id ?? 'dem-dataset-1',
    dataset_name: overrides.dataset_name ?? 'Grand Canyon DEM',
    dataset_geometry_type: null,
    dataset_table_name: overrides.dataset_table_name ?? 'dem_table',
    dataset_extent_bbox: overrides.dataset_extent_bbox ?? [0, 0, 1, 1],
    dataset_column_info: overrides.dataset_column_info ?? null,
    dataset_feature_count: overrides.dataset_feature_count ?? null,
    dataset_sample_values: overrides.dataset_sample_values ?? null,
    display_name: overrides.display_name ?? 'Grand Canyon DEM',
    sort_order: overrides.sort_order ?? 0,
    visible: overrides.visible ?? true,
    opacity: overrides.opacity ?? 1,
    paint: overrides.paint ?? {},
    layout: overrides.layout ?? {},
    filter: overrides.filter ?? null,
    label_config: overrides.label_config ?? null,
    popup_config: overrides.popup_config ?? null,
    style_config: overrides.style_config ?? null,
    layer_type: overrides.layer_type ?? null,
    dataset_record_type: overrides.dataset_record_type ?? 'raster_dataset',
    show_in_legend: overrides.show_in_legend ?? true,
    is_dem: overrides.is_dem ?? true,
    dem_vertical_units: overrides.dem_vertical_units ?? null,
    ...overrides,
  };
}

function defaultProps(overrides: Partial<React.ComponentProps<typeof DEMEditorScene>> = {}) {
  return {
    layer: makeDEMLayer(),
    onPaintChange: vi.fn(),
    onStyleConfigChange: vi.fn(),
    onOpacityChange: vi.fn(),
    onZoomChange: vi.fn(),
    onTerrainBind: vi.fn(),
    ...overrides,
  };
}

describe('DEMEditorScene', () => {
  // Test 1: Renders RENDER AS pill strip with 3 pills
  it('renders RENDER AS pill strip with 3 pills (▦ Image, ⛰ Hillshade, ◬ Terrain) with radiogroup role', () => {
    render(<DEMEditorScene {...defaultProps()} />);

    const group = screen.getByRole('radiogroup');
    expect(group).toBeInTheDocument();

    // All three pills should be present
    expect(screen.getByText(/Image/)).toBeInTheDocument();
    expect(screen.getByText(/Hillshade/)).toBeInTheDocument();
    expect(screen.getByText(/Terrain/)).toBeInTheDocument();
  });

  // Test 2: Active pill matches layer's render mode
  it('active pill matches layer render_mode: null/undefined → Image, hillshade → Hillshade, terrain → Terrain', () => {
    // No render_mode → Image active
    const { rerender } = render(
      <DEMEditorScene {...defaultProps({ layer: makeDEMLayer({ style_config: null }) })} />,
    );
    let imagePill = screen.getByRole('radio', { name: /Image/i });
    expect(imagePill).toHaveAttribute('aria-checked', 'true');

    // Hillshade
    rerender(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ style_config: { render_mode: 'hillshade' } }),
        })}
      />,
    );
    const hillshadePill = screen.getByRole('radio', { name: /Hillshade/i });
    expect(hillshadePill).toHaveAttribute('aria-checked', 'true');
    imagePill = screen.getByRole('radio', { name: /Image/i });
    expect(imagePill).toHaveAttribute('aria-checked', 'false');

    // Terrain
    rerender(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ style_config: { render_mode: 'terrain' } as Parameters<typeof makeDEMLayer>[0]['style_config'] }),
        })}
      />,
    );
    const terrainPill = screen.getByRole('radio', { name: /Terrain/i });
    expect(terrainPill).toHaveAttribute('aria-checked', 'true');
  });

  // Test 3: Clicking Hillshade pill calls onStyleConfigChange with render_mode='hillshade'
  it('clicking Hillshade pill calls onStyleConfigChange with render_mode=hillshade and shows Hillshade appearance', () => {
    const onStyleConfigChange = vi.fn();
    render(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ style_config: null }),
          onStyleConfigChange,
        })}
      />,
    );

    const hillshadePill = screen.getByRole('radio', { name: /Hillshade/i });
    fireEvent.click(hillshadePill);

    expect(onStyleConfigChange).toHaveBeenCalledOnce();
    const [config] = onStyleConfigChange.mock.calls[0] as [{ render_mode: string } | null, Record<string, unknown>];
    expect(config?.render_mode).toBe('hillshade');
  });

  // Test 4: Clicking Terrain pill calls onTerrainBind AND onStyleConfigChange
  it('clicking Terrain pill calls onTerrainBind(layerId) AND onStyleConfigChange with render_mode=terrain', () => {
    const onTerrainBind = vi.fn();
    const onStyleConfigChange = vi.fn();
    const layer = makeDEMLayer({ id: 'dem-terrain-test', style_config: null });

    render(
      <DEMEditorScene
        {...defaultProps({ layer, onTerrainBind, onStyleConfigChange })}
      />,
    );

    const terrainPill = screen.getByRole('radio', { name: /Terrain/i });
    fireEvent.click(terrainPill);

    expect(onTerrainBind).toHaveBeenCalledOnce();
    expect(onTerrainBind).toHaveBeenCalledWith('dem-terrain-test');
    expect(onStyleConfigChange).toHaveBeenCalledOnce();
    const [config] = onStyleConfigChange.mock.calls[0] as [{ render_mode: string } | null, Record<string, unknown>];
    expect(config?.render_mode).toBe('terrain');
  });

  // Test 5: Image mode shows image hint only
  it('in Image mode, Appearance section shows image hint and no compass/colors', () => {
    render(
      <DEMEditorScene
        {...defaultProps({ layer: makeDEMLayer({ style_config: null }) })}
      />,
    );

    expect(screen.getByText('No additional appearance controls for image mode')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /Sun azimuth/i })).not.toBeInTheDocument();
  });

  // Test 6: Hillshade mode shows Sun Position and Shading Colors
  it('in Hillshade mode, Appearance section shows Sun Position and Shading Colors sub-sections', () => {
    render(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ style_config: { render_mode: 'hillshade' } }),
        })}
      />,
    );

    // Sun position heading
    expect(screen.getByText('SUN POSITION')).toBeInTheDocument();
    // Shading colors heading
    expect(screen.getByText('SHADING COLORS')).toBeInTheDocument();
    // Should not show image hint or terrain hint
    expect(screen.queryByText('No additional appearance controls for image mode')).not.toBeInTheDocument();
    expect(screen.queryByText(/Terrain uses elevation data/)).not.toBeInTheDocument();
  });

  // Test 7: Compass widget renders correctly
  it('in Hillshade mode, compass widget has role=img and aria-label with azimuth, needle has rotate transform', () => {
    const layer = makeDEMLayer({
      style_config: { render_mode: 'hillshade' },
      paint: { 'hillshade-illumination-direction': 135 },
    });

    render(<DEMEditorScene {...defaultProps({ layer })} />);

    const compass = screen.getByRole('img', { name: /Sun azimuth: 135°/ });
    expect(compass).toBeInTheDocument();

    // Find needle element inside compass
    const needle = compass.querySelector('[aria-hidden="true"]');
    expect(needle).toBeTruthy();
    expect((needle as HTMLElement).style.transform).toContain('rotate(135deg)');
  });

  // Test 8: Slider attributes for Azimuth, Altitude, Exaggeration
  it('Azimuth slider has correct aria attributes and range (0-360, step 1); Altitude 0-90; Exaggeration 0-5 step 0.1', () => {
    render(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ style_config: { render_mode: 'hillshade' } }),
        })}
      />,
    );

    const azimuth = screen.getByRole('slider', { name: 'Azimuth' });
    expect(azimuth).toHaveAttribute('min', '0');
    expect(azimuth).toHaveAttribute('max', '360');
    expect(azimuth).toHaveAttribute('step', '1');

    const altitude = screen.getByRole('slider', { name: 'Altitude' });
    expect(altitude).toHaveAttribute('min', '0');
    expect(altitude).toHaveAttribute('max', '90');

    const exaggeration = screen.getByRole('slider', { name: 'Exaggeration' });
    expect(exaggeration).toHaveAttribute('min', '0');
    expect(exaggeration).toHaveAttribute('max', '5');
    expect(exaggeration).toHaveAttribute('step', '0.1');
  });

  // Test 9: Changing Azimuth slider calls onPaintChange with correct key
  it('changing Azimuth slider calls onPaintChange with hillshade-illumination-direction', () => {
    const onPaintChange = vi.fn();
    render(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ style_config: { render_mode: 'hillshade' } }),
          onPaintChange,
        })}
      />,
    );

    const azimuthSlider = screen.getByRole('slider', { name: 'Azimuth' });
    fireEvent.change(azimuthSlider, { target: { value: '200' } });

    expect(onPaintChange).toHaveBeenCalledOnce();
    const [paint] = onPaintChange.mock.calls[0] as [Record<string, unknown>];
    expect(paint['hillshade-illumination-direction']).toBe(200);
  });

  // Test 10: Color pickers call onPaintChange with correct hillshade keys
  it('Highlight/Shadow/Accent color pickers call onPaintChange with correct hillshade color keys', () => {
    const onPaintChange = vi.fn();
    render(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ style_config: { render_mode: 'hillshade' } }),
          onPaintChange,
        })}
      />,
    );

    // Highlight
    const highlightPicker = screen.getByTestId('color-picker-highlight');
    fireEvent.click(highlightPicker);
    expect(onPaintChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ 'hillshade-highlight-color': '#ABCDEF' }),
    );

    onPaintChange.mockClear();

    // Shadow
    const shadowPicker = screen.getByTestId('color-picker-shadow');
    fireEvent.click(shadowPicker);
    expect(onPaintChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ 'hillshade-shadow-color': '#ABCDEF' }),
    );

    onPaintChange.mockClear();

    // Accent
    const accentPicker = screen.getByTestId('color-picker-accent');
    fireEvent.click(accentPicker);
    expect(onPaintChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ 'hillshade-accent-color': '#ABCDEF' }),
    );
  });

  // Test 11: Terrain mode shows terrain hint only
  it('in Terrain mode, Appearance section shows terrain hint only (no compass, no colors, no image hint)', () => {
    render(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ style_config: { render_mode: 'terrain' } as Parameters<typeof makeDEMLayer>[0]['style_config'] }),
        })}
      />,
    );

    expect(
      screen.getByText(/Terrain uses elevation data to extrude the map surface/),
    ).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /Sun azimuth/i })).not.toBeInTheDocument();
    expect(screen.queryByText('No additional appearance controls for image mode')).not.toBeInTheDocument();
    expect(screen.queryByText('SUN POSITION')).not.toBeInTheDocument();
  });

  // Test 12: Visibility section renders opacity and zoom inputs
  it('Visibility section renders opacity slider and min/max zoom inputs', () => {
    render(<DEMEditorScene {...defaultProps()} />);

    const opacitySlider = screen.getByRole('slider', { name: /Opacity/i });
    expect(opacitySlider).toBeInTheDocument();

    const minZoom = screen.getByLabelText(/Minimum zoom/i);
    const maxZoom = screen.getByLabelText(/Maximum zoom/i);
    expect(minZoom).toBeInTheDocument();
    expect(maxZoom).toBeInTheDocument();
  });

  // Test 13: Footer renders "Delete layer" button
  it('footer renders a Delete layer button', () => {
    render(<DEMEditorScene {...defaultProps()} />);
    // The DEMEditorScene renders a footer with a delete layer button
    const deleteBtn = screen.getByRole('button', { name: /Delete layer/i });
    expect(deleteBtn).toBeInTheDocument();
  });

  // Test 14: Switching render mode preserves style_config keys not under current mode
  it('switching image→hillshade→image preserves other style_config keys', () => {
    const onStyleConfigChange = vi.fn();
    const layer = makeDEMLayer({
      style_config: { render_mode: 'hillshade', some_other_key: 'preserved' } as Parameters<typeof makeDEMLayer>[0]['style_config'],
    });

    render(
      <DEMEditorScene
        {...defaultProps({ layer, onStyleConfigChange })}
      />,
    );

    // Switch to Image (removes render_mode, but other keys stay)
    const imagePill = screen.getByRole('radio', { name: /Image/i });
    fireEvent.click(imagePill);

    expect(onStyleConfigChange).toHaveBeenCalledOnce();
    const [config] = onStyleConfigChange.mock.calls[0] as [Record<string, unknown> | null, Record<string, unknown>];
    // render_mode should be absent; other keys should remain
    expect(config?.render_mode).toBeUndefined();
    expect(config?.some_other_key).toBe('preserved');
  });
});
