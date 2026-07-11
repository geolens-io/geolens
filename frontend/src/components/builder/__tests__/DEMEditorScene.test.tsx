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

vi.mock('../ColorRampPicker', () => ({
  ColorRampPicker: ({
    rampName,
    onChange,
  }: {
    rampName: string;
    onChange: (name: string) => void;
    mode: string;
  }) => (
    <button
      type="button"
      data-testid="color-ramp-picker"
      data-ramp={rampName}
      onClick={() => onChange('Inferno')}
    >
      ColorRampPicker:{rampName}
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

// style_config widened: tests express partial DEM render-mode shapes that
// don't satisfy StyleConfig's required mode/column/ramp fields. The runtime
// indexed signature accepts these — only the strict static check rejects.
function makeDEMLayer(
  overrides: Omit<Partial<MapLayerResponse>, 'style_config'> & {
    style_config?: unknown;
  } = {},
): MapLayerResponse {
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
    style_config: (overrides.style_config ?? null) as unknown as MapLayerResponse['style_config'],
    layer_type: overrides.layer_type ?? null,
    dataset_record_type: overrides.dataset_record_type ?? 'raster_dataset',
    show_in_legend: overrides.show_in_legend ?? true,
    is_dem: overrides.is_dem ?? true,
    dem_vertical_units: overrides.dem_vertical_units ?? null,
    ...overrides,
  } as MapLayerResponse;
}

function defaultProps(
  overrides: Partial<React.ComponentProps<typeof DEMEditorScene>> = {},
): React.ComponentProps<typeof DEMEditorScene> {
  return {
    layer: makeDEMLayer(),
    onPaintChange: vi.fn(),
    onStyleConfigChange: vi.fn(),
    onOpacityChange: vi.fn(),
    onZoomChange: vi.fn(),
    onTerrainBind: vi.fn(),
    onTerrainUnbind: vi.fn(),
    terrainExaggeration: 1,
    onTerrainExaggerationChange: vi.fn(),
    onRemove: vi.fn(),
    ...overrides,
  };
}

describe('DEMEditorScene', () => {
  // fix(HT-01): hillshade overlay and 3D terrain are independent switches, not
  // an exclusive radio. Both can be active on one DEM at once.
  it('renders independent Hillshade shading and Use as 3D terrain switches', () => {
    render(<DEMEditorScene {...defaultProps()} />);

    expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Hillshade shading' })).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Use as 3D terrain' })).toBeInTheDocument();
  });

  // fix(HT-01): the overlay switch reflects render_mode; the terrain switch
  // reflects isTerrainBound — independently.
  it('overlay switch reflects render_mode and terrain switch reflects isTerrainBound', () => {
    // No render_mode → overlay on; not bound → terrain off
    const { rerender } = render(
      <DEMEditorScene {...defaultProps({ layer: makeDEMLayer({ style_config: null }) })} />,
    );
    expect(screen.getByRole('switch', { name: 'Hillshade shading' })).toBeChecked();
    expect(screen.getByRole('switch', { name: 'Use as 3D terrain' })).not.toBeChecked();

    // render_mode:terrain → overlay off
    rerender(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ style_config: { render_mode: 'terrain' } }),
        })}
      />,
    );
    expect(screen.getByRole('switch', { name: 'Hillshade shading' })).not.toBeChecked();

    // The hybrid state: overlay on AND terrain bound simultaneously
    rerender(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ style_config: { render_mode: 'hillshade' } }),
          isTerrainBound: true,
        })}
      />,
    );
    expect(screen.getByRole('switch', { name: 'Hillshade shading' })).toBeChecked();
    expect(screen.getByRole('switch', { name: 'Use as 3D terrain' })).toBeChecked();
  });

  // fix(HT-02): toggling the overlay writes ONLY render_mode — it never
  // binds/unbinds terrain, so an overlay round trip can't drop the mesh.
  it('toggling the hillshade overlay off writes render_mode=terrain without touching terrain binding', () => {
    const onStyleConfigChange = vi.fn();
    const onTerrainUnbind = vi.fn();
    render(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ id: 'dem-1', style_config: { render_mode: 'hillshade' } }),
          onStyleConfigChange,
          onTerrainUnbind,
          isTerrainBound: true,
        })}
      />,
    );

    fireEvent.click(screen.getByRole('switch', { name: 'Hillshade shading' }));

    expect(onStyleConfigChange).toHaveBeenCalledOnce();
    const [config] = onStyleConfigChange.mock.calls[0] as [{ render_mode: string } | null, Record<string, unknown>];
    expect(config?.render_mode).toBe('terrain');
    expect(onTerrainUnbind).not.toHaveBeenCalled();
  });

  // fix(HT-02): the terrain switch binds/unbinds ONLY terrain — it never
  // rewrites render_mode, so the overlay survives a terrain round trip.
  it('the terrain switch binds and unbinds terrain without touching render_mode', () => {
    const onTerrainBind = vi.fn();
    const onTerrainUnbind = vi.fn();
    const onStyleConfigChange = vi.fn();

    const { rerender } = render(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ id: 'dem-1', style_config: { render_mode: 'hillshade' } }),
          onTerrainBind, onTerrainUnbind, onStyleConfigChange,
          isTerrainBound: false,
        })}
      />,
    );

    fireEvent.click(screen.getByRole('switch', { name: 'Use as 3D terrain' }));
    expect(onTerrainBind).toHaveBeenCalledWith('dem-1');
    expect(onStyleConfigChange).not.toHaveBeenCalled();

    rerender(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ id: 'dem-1', style_config: { render_mode: 'hillshade' } }),
          onTerrainBind, onTerrainUnbind, onStyleConfigChange,
          isTerrainBound: true,
        })}
      />,
    );
    fireEvent.click(screen.getByRole('switch', { name: 'Use as 3D terrain' }));
    expect(onTerrainUnbind).toHaveBeenCalledWith('dem-1');
    expect(onStyleConfigChange).not.toHaveBeenCalled();
  });

  // Test 5: Missing/legacy Image mode falls back to Hillshade controls
  it('in missing/legacy Image mode, Appearance section shows Hillshade controls', () => {
    render(
      <DEMEditorScene
        {...defaultProps({ layer: makeDEMLayer({ style_config: { render_mode: 'image' } as unknown as MapLayerResponse['style_config'] }) })}
      />,
    );

    expect(screen.queryByText('No additional appearance controls for image mode')).not.toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Sun azimuth/i })).toBeInTheDocument();
  });

  // Test 6: Overlay-on shows Sun Position and Shading Colors
  it('with the hillshade overlay on, Relief Shading section shows Sun Position and Shading Colors', () => {
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
    expect(screen.queryByText('No additional appearance controls for image mode')).not.toBeInTheDocument();
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

  // Test 8: Slider attributes for supported Hillshade controls
  it('Azimuth and Exaggeration sliders use supported MapLibre hillshade paint ranges', () => {
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

    expect(screen.queryByRole('slider', { name: 'Altitude' })).not.toBeInTheDocument();

    const exaggeration = screen.getByRole('slider', { name: 'Exaggeration' });
    expect(exaggeration).toHaveAttribute('min', '0');
    expect(exaggeration).toHaveAttribute('max', '1');
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

  it('clamps hillshade exaggeration before sending paint updates', () => {
    const onPaintChange = vi.fn();
    render(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ style_config: { render_mode: 'hillshade' } }),
          onPaintChange,
        })}
      />,
    );

    fireEvent.change(screen.getByRole('slider', { name: 'Exaggeration' }), { target: { value: '2.1' } });

    expect(onPaintChange).toHaveBeenCalledWith(expect.objectContaining({
      'hillshade-exaggeration': 1,
    }));
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

  // builder-audit #338 CONSIST-01: the accent swatch default must match the adapter's
  // HILLSHADE_PAINT_DEFAULTS (black #000000) — the value buildHillshadePaint renders —
  // not the prior divergent brown literal that lied about the rendered default.
  it('shows the adapter hillshade defaults (black accent) on an untouched DEM', () => {
    render(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ style_config: { render_mode: 'hillshade' }, paint: {} }),
        })}
      />,
    );

    // The mock StyleColorPicker renders `{label}:{color}`.
    expect(screen.getByTestId('color-picker-accent')).toHaveTextContent('#000000');
    expect(screen.getByTestId('color-picker-highlight')).toHaveTextContent('#ffffff');
    expect(screen.getByTestId('color-picker-shadow')).toHaveTextContent('#000000');
  });

  // Test 11: the exaggeration slider appears under the terrain switch when bound
  it('shows the terrain exaggeration control only when the DEM is bound as terrain', () => {
    const { rerender } = render(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ style_config: { render_mode: 'hillshade' } }),
          isTerrainBound: false,
          terrainExaggeration: 1.6,
        })}
      />,
    );
    // Unbound: no exaggeration control, but the terrain hint is always present.
    expect(screen.queryByRole('slider', { name: 'Terrain exaggeration' })).not.toBeInTheDocument();
    expect(
      screen.getByText(/Terrain uses elevation data to extrude the map surface/),
    ).toBeInTheDocument();

    rerender(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ style_config: { render_mode: 'hillshade' } }),
          isTerrainBound: true,
          terrainExaggeration: 1.6,
        })}
      />,
    );
    const terrainExaggeration = screen.getByRole('slider', { name: 'Terrain exaggeration' });
    expect(terrainExaggeration).toHaveAttribute('min', '0');
    expect(terrainExaggeration).toHaveAttribute('max', '3');
    expect((terrainExaggeration as HTMLInputElement).value).toBe('1.6');
    expect(screen.getByRole('spinbutton', { name: 'Terrain exaggeration value' })).toHaveValue(1.6);
  });

  it('terrain exaggeration slider writes through the DEM layer callback', () => {
    const onTerrainExaggerationChange = vi.fn();
    render(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ id: 'dem-terrain-test', style_config: { render_mode: 'hillshade' } }),
          isTerrainBound: true,
          onTerrainExaggerationChange,
        })}
      />,
    );

    fireEvent.change(screen.getByRole('slider', { name: 'Terrain exaggeration' }), { target: { value: '2.4' } });

    expect(onTerrainExaggerationChange).toHaveBeenCalledWith('dem-terrain-test', 2.4);
  });

  it('terrain exaggeration number field writes through the DEM layer callback', () => {
    const onTerrainExaggerationChange = vi.fn();
    render(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ id: 'dem-terrain-test', style_config: { render_mode: 'hillshade' } }),
          isTerrainBound: true,
          onTerrainExaggerationChange,
        })}
      />,
    );

    fireEvent.change(screen.getByRole('spinbutton', { name: 'Terrain exaggeration value' }), {
      target: { value: '2.45' },
    });

    expect(onTerrainExaggerationChange).toHaveBeenCalledWith('dem-terrain-test', 2.5);
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

  // --- CONTOUR LINES section: REMOVED in v1032 (CONTOUR-02 cut) ---
  // maplibre-contour@0.1.0 is incompatible with maplibre-gl 5.x: its dem1-contour://
  // custom-protocol tile URLs are not routed by the v5 source loader → resolved as
  // relative HTTP → malformed Request → 28 errors/enable (see
  // .planning/audits/CONTOUR-WORKER-v1032.md). The control, contour-sync.ts, and the dep
  // were removed. The assertions below are the permanent regression pins that the contour
  // section never renders in any DEM render mode.

  describe('CONTOUR LINES section (removed — stays gone)', () => {
    it('section is absent in legacy image mode after hillshade fallback', () => {
      render(
        <DEMEditorScene
          {...defaultProps({ layer: makeDEMLayer({ style_config: { render_mode: 'image' } as unknown as MapLayerResponse['style_config'] }) })}
        />,
      );
      expect(screen.queryByText('CONTOUR LINES')).not.toBeInTheDocument();
    });

    it('section is absent in hillshade mode (EDITOR-DEM-04 cut in v1032)', () => {
      render(
        <DEMEditorScene
          {...defaultProps({
            layer: makeDEMLayer({ style_config: { render_mode: 'hillshade' } }),
          })}
        />,
      );
      // Contour cut in v1032: section must NOT appear in the DOM
      expect(screen.queryByText('CONTOUR LINES')).not.toBeInTheDocument();
    });

    it('section is absent in terrain mode (EDITOR-DEM-04 cut in v1032)', () => {
      render(
        <DEMEditorScene
          {...defaultProps({
            layer: makeDEMLayer({ style_config: { render_mode: 'terrain' } as unknown as MapLayerResponse['style_config'] }),
          })}
        />,
      );
      // Contour cut in v1032: section must NOT appear in the DOM
      expect(screen.queryByText('CONTOUR LINES')).not.toBeInTheDocument();
    });

  });

  // --- HYPSOMETRIC TINT section tests (EDITOR-DEM-05) ---

  describe('HYPSOMETRIC TINT section', () => {
    it('section is present in legacy image mode after hillshade fallback', () => {
      render(
        <DEMEditorScene
          {...defaultProps({ layer: makeDEMLayer({ style_config: { render_mode: 'image' } as unknown as MapLayerResponse['style_config'] }) })}
        />,
      );
      expect(screen.getByText('HYPSOMETRIC TINT')).toBeInTheDocument();
      expect(screen.getByRole('switch', { name: 'Elevation tint' })).toBeInTheDocument();
    });

    it('section is present in hillshade mode with toggle + no picker when disabled', () => {
      render(
        <DEMEditorScene
          {...defaultProps({
            layer: makeDEMLayer({ style_config: { render_mode: 'hillshade' } }),
          })}
        />,
      );
      expect(screen.getByText('HYPSOMETRIC TINT')).toBeInTheDocument();
      expect(screen.getByRole('switch', { name: 'Elevation tint' })).toBeInTheDocument();
      // Picker absent when disabled
      expect(screen.queryByTestId('color-ramp-picker')).not.toBeInTheDocument();
    });

    it('shows ColorRampPicker when _hypso-enabled is true in hillshade mode', () => {
      render(
        <DEMEditorScene
          {...defaultProps({
            layer: makeDEMLayer({
              style_config: { render_mode: 'hillshade' },
              paint: { '_hypso-enabled': true },
            }),
          })}
        />,
      );
      expect(screen.getByTestId('color-ramp-picker')).toBeInTheDocument();
    });

    it('section shows only the requires-hillshade hint when the overlay is off', () => {
      render(
        <DEMEditorScene
          {...defaultProps({
            layer: makeDEMLayer({
              style_config: { render_mode: 'terrain' },
            }),
          })}
        />,
      );
      expect(screen.getByText('HYPSOMETRIC TINT')).toBeInTheDocument();
      expect(
        screen.getByText('Elevation tint requires hillshade shading'),
      ).toBeInTheDocument();
      // No toggle or picker while the overlay is off
      expect(screen.queryByRole('switch', { name: 'Elevation tint' })).not.toBeInTheDocument();
      expect(screen.queryByTestId('color-ramp-picker')).not.toBeInTheDocument();
    });

    it('toggling the Switch fires onPaintChange with _hypso-enabled=true', () => {
      const onPaintChange = vi.fn();
      render(
        <DEMEditorScene
          {...defaultProps({
            layer: makeDEMLayer({ style_config: { render_mode: 'hillshade' } }),
            onPaintChange,
          })}
        />,
      );

      const switchEl = screen.getByRole('switch', { name: 'Elevation tint' });
      fireEvent.click(switchEl);

      expect(onPaintChange).toHaveBeenCalledOnce();
      const [paint] = onPaintChange.mock.calls[0] as [Record<string, unknown>];
      expect(paint['_hypso-enabled']).toBe(true);
    });

    it('selecting a ramp fires onPaintChange with _hypso-ramp', () => {
      const onPaintChange = vi.fn();
      render(
        <DEMEditorScene
          {...defaultProps({
            layer: makeDEMLayer({
              style_config: { render_mode: 'hillshade' },
              paint: { '_hypso-enabled': true, '_hypso-ramp': 'Viridis' },
            }),
            onPaintChange,
          })}
        />,
      );

      const picker = screen.getByTestId('color-ramp-picker');
      fireEvent.click(picker);

      expect(onPaintChange).toHaveBeenCalledOnce();
      const [paint] = onPaintChange.mock.calls[0] as [Record<string, unknown>];
      expect(paint['_hypso-ramp']).toBe('Inferno');
    });

    it('ColorRampPicker receives default Viridis ramp when _hypso-ramp not set', () => {
      render(
        <DEMEditorScene
          {...defaultProps({
            layer: makeDEMLayer({
              style_config: { render_mode: 'hillshade' },
              paint: { '_hypso-enabled': true },
            }),
          })}
        />,
      );

      const picker = screen.getByTestId('color-ramp-picker');
      expect(picker).toHaveAttribute('data-ramp', 'Viridis');
    });

    // builder-audit #338 MAINT-01: the 0–4000 m, meters-only limitation is surfaced in-product
    // alongside the ramp picker (only when the tint is enabled).
    it('surfaces the 0–4000 m meters-only limitation note when the tint is enabled', () => {
      const { rerender } = render(
        <DEMEditorScene
          {...defaultProps({
            layer: makeDEMLayer({ style_config: { render_mode: 'hillshade' }, paint: {} }),
          })}
        />,
      );
      // Absent until enabled.
      expect(screen.queryByText(/spans 0–4000 m and assumes meters/i)).not.toBeInTheDocument();

      rerender(
        <DEMEditorScene
          {...defaultProps({
            layer: makeDEMLayer({
              style_config: { render_mode: 'hillshade' },
              paint: { '_hypso-enabled': true },
            }),
          })}
        />,
      );
      expect(screen.getByText(/spans 0–4000 m and assumes meters/i)).toBeInTheDocument();
    });
  });

  // fix(HT-01/02): the Matterhorn hybrid state — hillshade overlay ON and 3D
  // terrain bound on the SAME DEM — is representable truthfully, and a terrain
  // off→on round trip neither touches the overlay nor loses information.
  describe('hybrid hillshade + terrain state (Matterhorn regression)', () => {
    it('shows both switches on simultaneously for the hybrid state', () => {
      render(
        <DEMEditorScene
          {...defaultProps({
            layer: makeDEMLayer({
              style_config: { render_mode: 'hillshade', builder: { hypso_enabled: true, hypso_ramp: 'Viridis' } },
            }),
            isTerrainBound: true,
          })}
        />,
      );
      expect(screen.getByRole('switch', { name: 'Hillshade shading' })).toBeChecked();
      expect(screen.getByRole('switch', { name: 'Use as 3D terrain' })).toBeChecked();
      // Overlay controls remain available while terrain is also bound.
      expect(screen.getByText('SUN POSITION')).toBeInTheDocument();
    });

    it('terrain off→on round trip never rewrites render_mode (overlay preserved)', () => {
      const onStyleConfigChange = vi.fn();
      const onTerrainBind = vi.fn();
      const onTerrainUnbind = vi.fn();
      const layer = makeDEMLayer({ id: 'dem-1', style_config: { render_mode: 'hillshade' } });

      const { rerender } = render(
        <DEMEditorScene
          {...defaultProps({ layer, onStyleConfigChange, onTerrainBind, onTerrainUnbind, isTerrainBound: true })}
        />,
      );

      // Turn terrain off, then back on.
      fireEvent.click(screen.getByRole('switch', { name: 'Use as 3D terrain' }));
      rerender(
        <DEMEditorScene
          {...defaultProps({ layer, onStyleConfigChange, onTerrainBind, onTerrainUnbind, isTerrainBound: false })}
        />,
      );
      fireEvent.click(screen.getByRole('switch', { name: 'Use as 3D terrain' }));

      expect(onTerrainUnbind).toHaveBeenCalledWith('dem-1');
      expect(onTerrainBind).toHaveBeenCalledWith('dem-1');
      // The overlay authority was never written during the terrain round trip.
      expect(onStyleConfigChange).not.toHaveBeenCalled();
    });
  });

  // fix(HT-05): the old "source conflict" advisory note is gone — the hillshade
  // overlay and 3D mesh coexist on one DEM, so there is nothing to warn about.
  it('never renders a terrain-bound source-conflict advisory note', () => {
    render(
      <DEMEditorScene
        {...defaultProps({
          layer: makeDEMLayer({ style_config: { render_mode: 'hillshade' } }),
          isTerrainBound: true,
        })}
      />,
    );
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
    expect(screen.queryByText(/also powers the map's 3D terrain/i)).not.toBeInTheDocument();
  });

  // fix(HT-02): toggling the overlay off preserves unrelated style_config keys.
  it('toggling the overlay off preserves other style_config keys', () => {
    const onStyleConfigChange = vi.fn();
    const layer = makeDEMLayer({
      style_config: { render_mode: 'hillshade', some_other_key: 'preserved' },
    });

    render(
      <DEMEditorScene
        {...defaultProps({ layer, onStyleConfigChange })}
      />,
    );

    fireEvent.click(screen.getByRole('switch', { name: 'Hillshade shading' }));

    expect(onStyleConfigChange).toHaveBeenCalledOnce();
    const [config] = onStyleConfigChange.mock.calls[0] as [Record<string, unknown> | null, Record<string, unknown>];
    expect(config?.render_mode).toBe('terrain');
    expect(config?.some_other_key).toBe('preserved');
  });
});
