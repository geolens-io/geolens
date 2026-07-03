import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { useColumnValues, useColumnStats } from '@/hooks/use-maps';
import { getRampColors, nextRotatingRamp } from '@/lib/color-ramps';
import { equalIntervalBreaks } from '@/lib/classification';
import { DataDrivenStyleEditor } from '../DataDrivenStyleEditor';
import type { MapLayerResponse, StyleConfig } from '@/types/api';

// --- Polyfills ---

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

// --- Mocks ---

vi.mock('@/hooks/use-maps', () => ({
  useColumnValues: vi.fn(),
  useColumnStats: vi.fn(),
}));

const mockUseColumnValues = vi.mocked(useColumnValues);
const mockUseColumnStats = vi.mocked(useColumnStats);

// Render HexColorPicker as a simple button that fires onChange with a known color
vi.mock('react-colorful', () => ({
  HexColorPicker: ({ onChange }: { color?: string; onChange: (hex: string) => void }) => (
    <button data-testid="hex-color-picker" onClick={() => onChange('#ff0000')}>
      pick
    </button>
  ),
  HexColorInput: () => null,
}));

// Render popover content inline (jsdom has no portal/positioning support)
vi.mock('@/components/ui/popover', () => ({
  Popover: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  PopoverTrigger: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  PopoverContent: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}));

// Mock map-sync to avoid maplibre-gl setup in jsdom
vi.mock('@/components/builder/map-sync', () => ({
  getLayerType: (geomType: string | null) => {
    const gt = (geomType ?? '').toUpperCase();
    if (gt.includes('POINT')) return 'circle';
    if (gt.includes('LINE')) return 'line';
    return 'fill';
  },
}));

// Mock ColorRampPicker to avoid chroma.scale errors in jsdom and allow ramp selection
vi.mock('../ColorRampPicker', () => ({
  ColorRampPicker: ({ rampName, onChange }: { rampName: string; onChange: (name: string) => void; mode: string }) => (
    <div data-testid="color-ramp-picker">
      <span>{rampName}</span>
      <button onClick={() => onChange('Paired')}>Paired</button>
      <button onClick={() => onChange('Set3')}>Set 3</button>
    </div>
  ),
}));

// --- Helpers ---

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'ds-1',
    dataset_name: 'Test Dataset',
    dataset_geometry_type: 'Polygon',
    dataset_table_name: 'test_table',
    dataset_extent_bbox: null,
    dataset_column_info: [
      { name: 'typeA', type: 'varchar' },
      { name: 'population', type: 'integer' },
    ],
    dataset_feature_count: 100,
    dataset_sample_values: null,
    display_name: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: { 'fill-color': '#3b82f6' },
    layout: {},
    filter: null,
    ...overrides,
  } as MapLayerResponse;
}

/** Minimal query-result shape — the component only destructures `data`. */
function hookData<T>(data: T) {
  return { data } as unknown as ReturnType<typeof useColumnValues>;
}

function noData() {
  return { data: undefined } as unknown as ReturnType<typeof useColumnValues>;
}

// --- Tests ---

describe('DataDrivenStyleEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseColumnValues.mockReturnValue(noData());
    mockUseColumnStats.mockReturnValue(
      noData() as unknown as ReturnType<typeof useColumnStats>,
    );
  });

  describe('useEffect guard — categorical', () => {
    const VALUES = ['cat1', 'cat2', 'cat3'];
    const RAMP = 'Set2';
    const COLORS = getRampColors(RAMP, VALUES.length);

    function matchingCategoricalConfig(): StyleConfig {
      return {
        mode: 'categorical',
        column: 'typeA',
        ramp: RAMP,
        categories: VALUES.map((v, i) => ({ value: v, color: COLORS[i] })),
      };
    }

    it('preserves colors on re-mount when style_config matches hook data', async () => {
      const config = matchingCategoricalConfig();
      mockUseColumnValues.mockReturnValue(
        hookData({ values: VALUES, count: VALUES.length }),
      );

      const onStyleConfigChange = vi.fn();
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({ style_config: config })}
          onStyleConfigChange={onStyleConfigChange}
        />,
      );

      // Give the useEffect a chance to run; the guard should pass and skip the callback
      await waitFor(() => {
        expect(onStyleConfigChange).not.toHaveBeenCalled();
      });
    });

    it('regenerates colors when categories do not match hook data', async () => {
      const staleConfig: StyleConfig = {
        mode: 'categorical',
        column: 'typeA',
        ramp: RAMP,
        categories: [
          { value: 'old1', color: '#aaaaaa' },
          { value: 'old2', color: '#bbbbbb' },
        ],
      };
      mockUseColumnValues.mockReturnValue(
        hookData({ values: VALUES, count: VALUES.length }),
      );

      const onStyleConfigChange = vi.fn();
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({ style_config: staleConfig })}
          onStyleConfigChange={onStyleConfigChange}
        />,
      );

      await waitFor(() => {
        expect(onStyleConfigChange).toHaveBeenCalledTimes(1);
      });

      const [layerId, newConfig] = onStyleConfigChange.mock.calls[0];
      expect(layerId).toBe('layer-1');
      expect((newConfig as StyleConfig).mode).toBe('categorical');
      expect((newConfig as StyleConfig).column).toBe('typeA');
      expect((newConfig as StyleConfig).ramp).toBe(RAMP);
      expect((newConfig as StyleConfig).categories).toHaveLength(VALUES.length);
    });

    it('regenerates colors when ramp changes via ColorRampPicker', async () => {
      const config = matchingCategoricalConfig();
      mockUseColumnValues.mockReturnValue(
        hookData({ values: VALUES, count: VALUES.length }),
      );

      const onStyleConfigChange = vi.fn();
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({ style_config: config })}
          onStyleConfigChange={onStyleConfigChange}
        />,
      );

      await waitFor(() => {
        expect(onStyleConfigChange).not.toHaveBeenCalled();
      });

      const user = userEvent.setup();
      const pairedButton = screen.getByRole('button', { name: /Paired/i });
      await user.click(pairedButton);

      await waitFor(() => {
        expect(onStyleConfigChange).toHaveBeenCalledTimes(1);
      });

      const [, newConfig] = onStyleConfigChange.mock.calls[0];
      expect((newConfig as StyleConfig).ramp).toBe('Paired');
    });

    it('resolves custom ramp to Set2 when regenerating categorical colors', async () => {
      const customConfig: StyleConfig = {
        mode: 'categorical',
        column: 'typeA',
        ramp: 'custom',
        categories: [{ value: 'stale', color: '#000000' }],
      };
      mockUseColumnValues.mockReturnValue(
        hookData({ values: VALUES, count: VALUES.length }),
      );

      const onStyleConfigChange = vi.fn();
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({ style_config: customConfig })}
          onStyleConfigChange={onStyleConfigChange}
        />,
      );

      // setRamp('Set2') inside the effect triggers a second render cycle,
      // so we wait for the callback and check the first call's config
      await waitFor(() => {
        expect(onStyleConfigChange).toHaveBeenCalled();
      });

      const [, newConfig] = onStyleConfigChange.mock.calls[0];
      expect((newConfig as StyleConfig).ramp).toBe('Set2');

      const expectedColors = getRampColors('Set2', VALUES.length);
      const categories = (newConfig as StyleConfig).categories!;
      categories.forEach((cat, i) => {
        expect(cat.color).toBe(expectedColors[i]);
      });
    });
  });

  describe('recoverable validation copy', () => {
    it('explains how to recover when categorical mode has no text columns', () => {
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({ dataset_column_info: [{ name: 'population', type: 'integer' }] })}
          onStyleConfigChange={vi.fn()}
        />,
      );

      expect(screen.getByText(/Categorical styles need a text column/i)).toBeInTheDocument();
    });

    it('explains missing imported style columns without changing style config', () => {
      const onStyleConfigChange = vi.fn();
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({
            style_config: {
              mode: 'graduated',
              column: 'old_population',
              ramp: 'YlOrRd',
              classCount: 5,
              method: 'equal_interval',
            },
          })}
          onStyleConfigChange={onStyleConfigChange}
        />,
      );

      expect(screen.getByText(/Column "old_population" is no longer available/i)).toBeInTheDocument();
      expect(onStyleConfigChange).not.toHaveBeenCalled();
    });
  });

  describe('useEffect guard — graduated', () => {
    it('resolves custom ramp to YlOrRd when regenerating graduated colors', async () => {
      const customConfig: StyleConfig = {
        mode: 'graduated',
        column: 'population',
        ramp: 'custom',
        method: 'equal_interval',
        classCount: 5,
      };
      mockUseColumnStats.mockReturnValue(
        hookData({
          min: 0,
          max: 100,
          count: 100,
          mean: 50,
          quantiles: [],
        }) as unknown as ReturnType<typeof useColumnStats>,
      );

      const onStyleConfigChange = vi.fn();
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({ style_config: customConfig })}
          onStyleConfigChange={onStyleConfigChange}
        />,
      );

      await waitFor(() => {
        expect(onStyleConfigChange).toHaveBeenCalled();
      });

      const [, newConfig] = onStyleConfigChange.mock.calls[0];
      expect((newConfig as StyleConfig).ramp).toBe('YlOrRd');

      const expectedBreaks = equalIntervalBreaks(0, 100, 5);
      const expectedColors = getRampColors('YlOrRd', 5);
      expect((newConfig as StyleConfig).breaks).toEqual(expectedBreaks);
      expect((newConfig as StyleConfig).colors).toEqual(expectedColors);
    });
  });

  describe('per-category and per-class color editing', () => {
    it('handleCategoryColorChange sets ramp to custom', async () => {
      const VALUES = ['cat1', 'cat2'];
      const RAMP = 'Set2';
      const COLORS = getRampColors(RAMP, VALUES.length);
      const config: StyleConfig = {
        mode: 'categorical',
        column: 'typeA',
        ramp: RAMP,
        categories: VALUES.map((v, i) => ({ value: v, color: COLORS[i] })),
      };
      mockUseColumnValues.mockReturnValue(
        hookData({ values: VALUES, count: VALUES.length }),
      );

      const onStyleConfigChange = vi.fn();
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({ style_config: config })}
          onStyleConfigChange={onStyleConfigChange}
        />,
      );

      await waitFor(() => {
        expect(onStyleConfigChange).not.toHaveBeenCalled();
      });

      const user = userEvent.setup();
      const pickers = screen.getAllByTestId('hex-color-picker');
      await user.click(pickers[0]);

      // handleCategoryColorChange fires onStyleConfigChange after 200ms debounce;
      // setRamp('custom') may trigger a second useEffect run
      await waitFor(() => {
        expect(onStyleConfigChange).toHaveBeenCalled();
      }, { timeout: 1000 });
      // The first call is from handleCategoryColorChange
      const [layerId, newConfig] = onStyleConfigChange.mock.calls[0];
      expect(layerId).toBe('layer-1');
      expect((newConfig as StyleConfig).ramp).toBe('custom');
      expect((newConfig as StyleConfig).categories![0].color).toBe('#ff0000');
      expect((newConfig as StyleConfig).categories![1].color).toBe(COLORS[1]);
    });

    it('handleGraduatedColorChange sets ramp to custom', async () => {
      const breaks = equalIntervalBreaks(0, 100, 3);
      const colors = getRampColors('YlOrRd', 3);
      const config: StyleConfig = {
        mode: 'graduated',
        column: 'population',
        ramp: 'YlOrRd',
        method: 'equal_interval',
        classCount: 3,
        breaks,
        colors,
      };
      mockUseColumnStats.mockReturnValue(
        hookData({
          min: 0,
          max: 100,
          count: 100,
          mean: 50,
          quantiles: [],
        }) as unknown as ReturnType<typeof useColumnStats>,
      );

      const onStyleConfigChange = vi.fn();
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({ style_config: config })}
          onStyleConfigChange={onStyleConfigChange}
        />,
      );

      await waitFor(() => {
        expect(onStyleConfigChange).not.toHaveBeenCalled();
      });

      const user = userEvent.setup();
      const pickers = screen.getAllByTestId('hex-color-picker');
      await user.click(pickers[0]);

      // After 200ms debounce, onStyleConfigChange should have been called
      await waitFor(() => {
        expect(onStyleConfigChange).toHaveBeenCalled();
      }, { timeout: 1000 });
      const [layerId, newConfig] = onStyleConfigChange.mock.calls[0];
      expect(layerId).toBe('layer-1');
      expect((newConfig as StyleConfig).ramp).toBe('custom');
      expect((newConfig as StyleConfig).colors![0]).toBe('#ff0000');
      expect((newConfig as StyleConfig).colors!.slice(1)).toEqual(colors.slice(1));
    });
  });

  describe('target selector', () => {
    it('shows a target selector with Color and Radius options for a point layer in graduated mode', async () => {
      const config: StyleConfig = {
        mode: 'graduated',
        column: 'population',
        ramp: 'YlOrRd',
        method: 'equal_interval',
        classCount: 5,
      };
      mockUseColumnStats.mockReturnValue(
        hookData({
          min: 0,
          max: 100,
          count: 100,
          mean: 50,
          quantiles: [],
        }) as unknown as ReturnType<typeof useColumnStats>,
      );

      render(
        <DataDrivenStyleEditor
          layer={makeLayer({
            dataset_geometry_type: 'Point',
            paint: { 'circle-color': '#3b82f6' },
            style_config: config,
          })}
          onStyleConfigChange={vi.fn()}
        />,
      );

      // Target selector should be visible (i18n renders "Target" label)
      expect(screen.getByText('Target')).toBeDefined();
    });

    it('does NOT show a target selector for a polygon layer in graduated mode', async () => {
      const config: StyleConfig = {
        mode: 'graduated',
        column: 'population',
        ramp: 'YlOrRd',
        method: 'equal_interval',
        classCount: 5,
      };
      mockUseColumnStats.mockReturnValue(
        hookData({
          min: 0,
          max: 100,
          count: 100,
          mean: 50,
          quantiles: [],
        }) as unknown as ReturnType<typeof useColumnStats>,
      );

      render(
        <DataDrivenStyleEditor
          layer={makeLayer({
            dataset_geometry_type: 'Polygon',
            paint: { 'fill-color': '#3b82f6' },
            style_config: config,
          })}
          onStyleConfigChange={vi.fn()}
        />,
      );

      // Target selector should NOT be visible for polygon
      expect(screen.queryByText('Target')).toBeNull();
    });

    it('does NOT show a target selector in categorical mode for a point layer', async () => {
      mockUseColumnValues.mockReturnValue(
        hookData({ values: ['a', 'b'], count: 2 }),
      );

      render(
        <DataDrivenStyleEditor
          layer={makeLayer({
            dataset_geometry_type: 'Point',
            paint: { 'circle-color': '#3b82f6' },
          })}
          onStyleConfigChange={vi.fn()}
        />,
      );

      // Categorical mode — target selector should NOT be shown
      expect(screen.queryByText('Target')).toBeNull();
    });

    it('clears stale size style_config when switching a graduated radius style to categorical', async () => {
      const onStyleConfigChange = vi.fn();
      const user = userEvent.setup();

      render(
        <DataDrivenStyleEditor
          layer={makeLayer({
            dataset_geometry_type: 'Point',
            paint: {
              'circle-color': ['step', ['get', 'population'], '#fee8c8', 20, '#fdbb84'],
              'circle-radius': ['step', ['get', 'population'], 2, 20, 8],
            },
            style_config: {
              mode: 'graduated',
              column: 'population',
              ramp: 'YlOrRd',
              method: 'equal_interval',
              classCount: 5,
              target: 'radius',
              sizes: [2, 4, 6, 8, 10],
              sizeRange: [2, 10],
              breaks: [20, 40, 60, 80],
            },
          })}
          onStyleConfigChange={onStyleConfigChange}
        />,
      );

      await user.click(screen.getAllByRole('combobox')[0]);
      await user.click(await screen.findByRole('option', { name: 'Categorical' }));

      expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', null, expect.objectContaining({
        'circle-color': '#3b82f6',
        'circle-radius': 5,
      }));
      expect(onStyleConfigChange).not.toHaveBeenCalledWith(
        'layer-1',
        expect.objectContaining({ target: 'radius' }),
        expect.anything(),
      );
    });

  });

  describe('B-003 / UX-L1: no phantom dirty on open', () => {
    it('does not emit onStyleConfigChange opening on a seeded graduated-size config missing classCount/sizeRange', async () => {
      // Restless Earth showcase quake layer shape (scripts/seed-showcase.py) —
      // no classCount, no sizeRange; both are fully implied by sizes/breaks.
      const seededConfig: StyleConfig = {
        mode: 'graduated',
        column: 'mag',
        ramp: 'YlOrRd',
        target: 'radius',
        method: 'manual',
        breaks: [5, 6, 7],
        sizes: [3, 5, 8, 12],
        colors: ['#ffffb2', '#fecc5c', '#fd8d3c', '#e31a1c'],
      };

      mockUseColumnStats.mockReturnValue(
        hookData({
          min: 1.2,
          max: 8,
          count: 500,
          mean: 4,
          quantiles: [],
        }) as unknown as ReturnType<typeof useColumnStats>,
      );

      const onStyleConfigChange = vi.fn();
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({
            dataset_geometry_type: 'Point',
            dataset_column_info: [{ name: 'mag', type: 'double precision' }],
            paint: { 'circle-color': '#3b82f6' },
            style_config: seededConfig,
          })}
          onStyleConfigChange={onStyleConfigChange}
        />,
      );

      await waitFor(() => {
        expect(onStyleConfigChange).not.toHaveBeenCalled();
      });
    });

    it('does not emit onStyleConfigChange opening on a seeded graduated-color config missing classCount', async () => {
      // 3D-buildings showcase layer shape (scripts/seed-showcase.py) — colors
      // (7) + breaks (6) but no classCount; classCount is implied by colors.length.
      const seededConfig: StyleConfig = {
        mode: 'graduated',
        column: 'height_roof',
        ramp: 'Plasma',
        target: 'color',
        method: 'quantile',
        breaks: [60, 120, 250, 450, 750, 1200],
        colors: [
          '#0d0887',
          '#5601a4',
          '#900da3',
          '#cb4679',
          '#ed7953',
          '#fdb42f',
          '#f0f921',
        ],
      };

      mockUseColumnStats.mockReturnValue(
        hookData({
          min: 0,
          max: 1500,
          count: 1000,
          mean: 300,
          quantiles: [60, 120, 250, 450, 750, 1200],
        }) as unknown as ReturnType<typeof useColumnStats>,
      );

      const onStyleConfigChange = vi.fn();
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({
            dataset_geometry_type: 'Polygon',
            dataset_column_info: [{ name: 'height_roof', type: 'double precision' }],
            paint: { 'fill-color': '#3b82f6' },
            style_config: seededConfig,
          })}
          onStyleConfigChange={onStyleConfigChange}
        />,
      );

      await waitFor(() => {
        expect(onStyleConfigChange).not.toHaveBeenCalled();
      });
    });
  });

  describe('classification methods (ENH-04)', () => {
    function graduatedConfig(method: StyleConfig['method'] = 'equal_interval'): StyleConfig {
      return {
        mode: 'graduated',
        column: 'population',
        ramp: 'YlOrRd',
        classCount: 5,
        method,
      };
    }

    function statsWith(extra: Record<string, unknown> = {}) {
      return hookData({
        min: 0,
        max: 100,
        count: 100,
        mean: 50,
        quantiles: [20, 40, 60, 80],
        ...extra,
      }) as unknown as ReturnType<typeof useColumnStats>;
    }

    it('jenks method produces strictly ascending breaks in the persisted config', async () => {
      mockUseColumnStats.mockReturnValue(statsWith());
      const onStyleConfigChange = vi.fn();
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({ style_config: graduatedConfig('jenks') })}
          onStyleConfigChange={onStyleConfigChange}
        />,
      );

      await waitFor(() => {
        expect(onStyleConfigChange).toHaveBeenCalled();
      });
      const [, newConfig] = onStyleConfigChange.mock.calls[0];
      const breaks = (newConfig as StyleConfig).breaks!;
      expect(breaks.length).toBeGreaterThan(0);
      for (let i = 1; i < breaks.length; i++) {
        expect(breaks[i]).toBeGreaterThan(breaks[i - 1]);
      }
      expect((newConfig as StyleConfig).method).toBe('jenks');
    });

    it('shows the manual-breaks editor and persists entered ascending breaks', async () => {
      mockUseColumnStats.mockReturnValue(statsWith());
      const onStyleConfigChange = vi.fn();
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({
            style_config: { ...graduatedConfig('manual'), breaks: [10, 20] },
          })}
          onStyleConfigChange={onStyleConfigChange}
        />,
      );

      // The manual editor renders numeric inputs seeded from the persisted breaks.
      const rows = await screen.findAllByLabelText(/Break value/i);
      expect(rows.length).toBeGreaterThanOrEqual(2);

      const user = userEvent.setup();
      await user.clear(rows[0]);
      await user.type(rows[0], '15');
      await user.clear(rows[1]);
      await user.type(rows[1], '30');

      await waitFor(() => {
        // The latest manual write should carry the freshly-typed ascending breaks.
        const manualCalls = onStyleConfigChange.mock.calls.filter(
          ([, cfg]) => (cfg as StyleConfig)?.method === 'manual',
        );
        expect(manualCalls.length).toBeGreaterThan(0);
        const last = manualCalls[manualCalls.length - 1];
        expect((last[1] as StyleConfig).breaks).toEqual([15, 30]);
      });
    });

    it('warns and does not write a config for non-ascending manual breaks', async () => {
      mockUseColumnStats.mockReturnValue(statsWith());
      const onStyleConfigChange = vi.fn();
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({
            style_config: { ...graduatedConfig('manual'), breaks: [10, 20] },
          })}
          onStyleConfigChange={onStyleConfigChange}
        />,
      );

      const rows = await screen.findAllByLabelText(/Break value/i);
      const user = userEvent.setup();
      // Make them descending: 50 then 5 → invalid.
      await user.clear(rows[0]);
      await user.type(rows[0], '50');
      await user.clear(rows[1]);
      await user.type(rows[1], '5');

      // Inline warning is shown.
      expect(
        await screen.findByText(/strictly ascending order/i),
      ).toBeInTheDocument();

      // No graduated manual config written for the invalid input.
      const manualWrite = onStyleConfigChange.mock.calls.find(
        ([, cfg]) =>
          (cfg as StyleConfig)?.method === 'manual' &&
          JSON.stringify((cfg as StyleConfig)?.breaks) === JSON.stringify([50, 5]),
      );
      expect(manualWrite).toBeUndefined();
    });

    it('disables the std-dev option when stddev is unavailable', async () => {
      // No stddev on the stats response → option gated.
      mockUseColumnStats.mockReturnValue(statsWith());
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({ style_config: graduatedConfig() })}
          onStyleConfigChange={vi.fn()}
        />,
      );

      const user = userEvent.setup();
      // Open the method select (the graduated method combobox).
      const comboboxes = screen.getAllByRole('combobox');
      await user.click(comboboxes[comboboxes.length - 1]);
      const stdDevOption = await screen.findByRole('option', { name: /Standard Deviation/i });
      expect(stdDevOption).toHaveAttribute('aria-disabled', 'true');
    });

    it('resets target to color when handleClear is called', async () => {
      const config: StyleConfig = {
        mode: 'graduated',
        column: 'population',
        ramp: 'YlOrRd',
        method: 'equal_interval',
        classCount: 5,
        target: 'radius',
        sizes: [2, 6, 10, 14, 18],
        sizeRange: [2, 18],
        breaks: [20, 40, 60, 80],
      };

      const onStyleConfigChange = vi.fn();
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({
            dataset_geometry_type: 'Point',
            paint: { 'circle-color': '#3b82f6', 'circle-radius': ['step', ['get', 'population'], 2, 20, 6, 40, 10, 60, 14, 80, 18] },
            style_config: config,
          })}
          onStyleConfigChange={onStyleConfigChange}
        />,
      );

      const user = userEvent.setup();
      const clearBtn = screen.getByRole('button', { name: /clear/i });
      await user.click(clearBtn);

      expect(onStyleConfigChange).toHaveBeenCalled();
      const [layerId, clearedConfig] = onStyleConfigChange.mock.calls[0];
      expect(layerId).toBe('layer-1');
      // config should be null after clear
      expect(clearedConfig).toBeNull();
    });
  });

  describe('ENH-08: ramp rotation + data-character suggestion', () => {
    const VALUES = ['cat1', 'cat2', 'cat3'];
    const STATS = {
      min: 0,
      max: 100,
      count: 100,
      mean: 50,
      quantiles: [25, 50, 75],
    };

    it('two fresh graduated layers at different rotation indices get different default ramps', async () => {
      // Fresh graduated layers: style_config has column + mode but NO ramp saved.
      // Effect 2 fires because column is set + stats available → persists the rotated ramp.
      mockUseColumnStats.mockReturnValue(
        hookData(STATS) as unknown as ReturnType<typeof useColumnStats>,
      );

      const ramp0 = nextRotatingRamp('graduated', 0); // 'YlOrRd'
      const ramp2 = nextRotatingRamp('graduated', 2); // 'Greens'
      expect(ramp0).not.toBe(ramp2);

      const onChange0 = vi.fn();
      const onChange2 = vi.fn();

      // Cast as StyleConfig: deliberately omitting ramp to represent a fresh
      // layer state (as-if the saved config had no ramp field set).
      const gradConfigNoRamp = {
        mode: 'graduated' as const,
        column: 'population',
        method: 'equal_interval' as const,
        classCount: 5,
      } as StyleConfig;

      const { unmount: unmount0 } = render(
        <DataDrivenStyleEditor
          layer={makeLayer({ id: 'g0', style_config: { ...gradConfigNoRamp } })}
          onStyleConfigChange={onChange0}
          rampRotationIndex={0}
        />,
      );

      await waitFor(() => {
        expect(onChange0).toHaveBeenCalled();
      });
      unmount0();

      render(
        <DataDrivenStyleEditor
          layer={makeLayer({ id: 'g2', style_config: { ...gradConfigNoRamp } })}
          onStyleConfigChange={onChange2}
          rampRotationIndex={2}
        />,
      );

      await waitFor(() => {
        expect(onChange2).toHaveBeenCalled();
      });

      const c0 = onChange0.mock.calls[0][1] as StyleConfig;
      const c2 = onChange2.mock.calls[0][1] as StyleConfig;
      expect(c0.ramp).toBe(ramp0);
      expect(c2.ramp).toBe(ramp2);
      // Key assertion: N adds → N distinct ramps (different rotation indices → different ramps)
      expect(c0.ramp).not.toBe(c2.ramp);
    });

    it('fresh layer ColorRampPicker displays the rotated default — two adds show distinct ramps', () => {
      // Without selecting a column, the ramp state is visible via the ColorRampPicker
      // only after a column is selected. Here we verify the INITIAL ramp state by
      // checking rampName shown in the picker when the component first enters mode with column.
      const ramp0 = nextRotatingRamp('categorical', 0); // 'Set2'
      const ramp1 = nextRotatingRamp('categorical', 1); // 'Paired'
      expect(ramp0).not.toBe(ramp1);

      // Mount a categorical layer that already has a column selected so the picker renders.
      // No ramp saved → fresh layer uses rotated default.
      mockUseColumnValues.mockReturnValue(
        hookData({ values: VALUES, count: VALUES.length }),
      );

      // Cast as StyleConfig: deliberately omitting ramp to represent a fresh
      // layer (as-if no ramp was ever saved). The column is already set so the
      // ColorRampPicker renders immediately — we can inspect the displayed ramp.
      const freshNoRamp0 = {
        mode: 'categorical' as const,
        column: 'typeA',
      } as StyleConfig;

      const { unmount: u0 } = render(
        <DataDrivenStyleEditor
          layer={makeLayer({ id: 'fresh-0', style_config: freshNoRamp0 })}
          onStyleConfigChange={vi.fn()}
          rampRotationIndex={0}
        />,
      );
      // ColorRampPicker receives rampName from ramp state; verify it shows index-0 ramp
      const picker0 = screen.getByTestId('color-ramp-picker');
      expect(picker0.textContent).toContain(ramp0);
      u0();

      const freshNoRamp1 = {
        mode: 'categorical' as const,
        column: 'typeA',
      } as StyleConfig;

      render(
        <DataDrivenStyleEditor
          layer={makeLayer({ id: 'fresh-1', style_config: freshNoRamp1 })}
          onStyleConfigChange={vi.fn()}
          rampRotationIndex={1}
        />,
      );
      const picker1 = screen.getByTestId('color-ramp-picker');
      expect(picker1.textContent).toContain(ramp1);
      expect(ramp0).not.toBe(ramp1);
    });

    it('a layer with a saved ramp keeps that ramp regardless of rotation index', async () => {
      const SAVED_RAMP = 'Inferno';
      const savedConfig: StyleConfig = {
        mode: 'categorical',
        column: 'typeA',
        ramp: SAVED_RAMP,
        categories: VALUES.map((v, i) => ({ value: v, color: getRampColors(SAVED_RAMP, VALUES.length)[i] })),
      };
      mockUseColumnValues.mockReturnValue(
        hookData({ values: VALUES, count: VALUES.length }),
      );

      const onStyleConfigChange = vi.fn();
      // rampRotationIndex=5 would select a non-Inferno ramp, but saved ramp wins
      render(
        <DataDrivenStyleEditor
          layer={makeLayer({ style_config: savedConfig })}
          onStyleConfigChange={onStyleConfigChange}
          rampRotationIndex={5}
        />,
      );

      // Guard recognizes config matches → no callback → saved ramp preserved
      await waitFor(() => {
        expect(onStyleConfigChange).not.toHaveBeenCalled();
      });

      // The ColorRampPicker shows the saved ramp name
      const picker = screen.getByTestId('color-ramp-picker');
      expect(picker.textContent).toContain(SAVED_RAMP);
    });
  });
});
