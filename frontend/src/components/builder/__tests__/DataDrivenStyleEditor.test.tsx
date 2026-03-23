import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { useColumnValues, useColumnStats } from '@/hooks/use-maps';
import { getRampColors } from '@/lib/color-ramps';
import { equalIntervalBreaks } from '@/lib/classification';
import { DataDrivenStyleEditor } from '../DataDrivenStyleEditor';
import type { MapLayerResponse, StyleConfig } from '@/types/api';

// --- Polyfills ---

// Radix Select uses ResizeObserver internally
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

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
  return { data } as ReturnType<typeof useColumnValues>;
}

function noData() {
  return { data: undefined } as ReturnType<typeof useColumnValues>;
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

      // handleCategoryColorChange fires onStyleConfigChange directly;
      // setRamp('custom') may trigger a second useEffect run
      expect(onStyleConfigChange).toHaveBeenCalled();
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

      expect(onStyleConfigChange).toHaveBeenCalled();
      const [layerId, newConfig] = onStyleConfigChange.mock.calls[0];
      expect(layerId).toBe('layer-1');
      expect((newConfig as StyleConfig).ramp).toBe('custom');
      expect((newConfig as StyleConfig).colors![0]).toBe('#ff0000');
      expect((newConfig as StyleConfig).colors!.slice(1)).toEqual(colors.slice(1));
    });
  });
});
