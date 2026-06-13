/**
 * GUARD-04: TypeIcon useMemo keyed on paint/layout/dataset_geometry_type/opacity/style_config.
 *
 * Strategy: spy on the real `extractStyleHints` so we can count calls and
 * compare outputs, without relying on the full StackRow render tree.
 * The existing StackRow.test.tsx mocks the whole layer-icons module, so this
 * test lives in its own file to avoid that mock leaking in.
 */
import { describe, expect, it, vi } from 'vitest';
import * as layerIcons from '@/components/map/layer-icons';
import { render } from '@/test/test-utils';
import { StackRow } from '../StackRow';
import type { MapLayerResponse } from '@/types/api';
import type { DraggableAttributes } from '@dnd-kit/core';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
}));

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-memo',
    dataset_id: 'ds-1',
    dataset_name: 'Demo',
    dataset_geometry_type: 'POLYGON',
    dataset_table_name: 'demo',
    dataset_extent_bbox: [0, 0, 1, 1],
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: { 'fill-color': '#3b82f6', 'fill-opacity': 0.5 },
    layout: {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: null,
    layer_type: 'vector_geolens',
    dataset_record_type: 'vector_dataset',
    show_in_legend: true,
    is_dem: false,
    dem_vertical_units: null,
    ...overrides,
  };
}

function makeDragHandleProps() {
  const attributes: DraggableAttributes = {
    role: 'button',
    tabIndex: 0,
    'aria-pressed': false,
    'aria-roledescription': 'sortable',
    'aria-describedby': 'dnd-desc',
    'aria-disabled': false,
  };
  return {
    attributes,
    listeners: {},
    setActivatorNodeRef: vi.fn(),
  };
}

function defaultProps(layer: MapLayerResponse, overrides = {}) {
  return {
    layer,
    selected: false,
    dragHandleProps: makeDragHandleProps(),
    onSelectLayer: vi.fn(),
    onToggleVisibility: vi.fn(),
    onRemove: vi.fn(),
    onRename: vi.fn(),
    onDuplicate: vi.fn(),
    ...overrides,
  };
}

describe('GUARD-04 TypeIcon useMemo — extractStyleHints', () => {
  it('(a) hint output matches a direct extractStyleHints call with the same inputs', () => {
    // Verify the memoized result equals what extractStyleHints returns directly.
    const layer = makeLayer();
    const expected = layerIcons.extractStyleHints(
      layer.paint ?? {},
      layer.layout ?? {},
      layer.dataset_geometry_type,
      layer.opacity,
      layer.style_config,
    );

    // Spy AFTER we've captured the expected value so the spy doesn't interfere.
    const spy = vi.spyOn(layerIcons, 'extractStyleHints');
    render(<StackRow {...defaultProps(layer)} />);

    // Spy was called at least once; all calls return the same shape.
    expect(spy).toHaveBeenCalled();
    spy.mock.results.forEach((result) => {
      expect(result.value).toEqual(expected);
    });

    spy.mockRestore();
  });

  it('(b) does NOT recompute when only an unrelated prop (visible/display_name) changes', () => {
    const layer = makeLayer();
    const spy = vi.spyOn(layerIcons, 'extractStyleHints');

    const { rerender } = render(<StackRow {...defaultProps(layer)} />);
    const callsAfterMount = spy.mock.calls.length;
    expect(callsAfterMount).toBeGreaterThan(0);

    // Change a prop that is NOT a memo key — visibility and display_name are
    // irrelevant to extractStyleHints (paint/layout/geomType/opacity/style_config unchanged).
    rerender(
      <StackRow
        {...defaultProps({ ...layer, visible: false, display_name: 'Renamed' })}
      />,
    );

    // extractStyleHints must NOT be called again after the rerender.
    expect(spy.mock.calls.length).toBe(callsAfterMount);

    spy.mockRestore();
  });

  it('(b) DOES recompute when a keyed field changes (paint)', () => {
    const layer = makeLayer();
    const spy = vi.spyOn(layerIcons, 'extractStyleHints');

    const { rerender } = render(<StackRow {...defaultProps(layer)} />);
    const callsAfterMount = spy.mock.calls.length;
    expect(callsAfterMount).toBeGreaterThan(0);

    // Change paint — this IS a memo key.
    rerender(
      <StackRow
        {...defaultProps({ ...layer, paint: { 'fill-color': '#ff0000', 'fill-opacity': 0.9 } })}
      />,
    );

    expect(spy.mock.calls.length).toBeGreaterThan(callsAfterMount);

    spy.mockRestore();
  });

  it('(b) DOES recompute when a keyed field changes (style_config)', () => {
    const layer = makeLayer({ style_config: null });
    const spy = vi.spyOn(layerIcons, 'extractStyleHints');

    const { rerender } = render(<StackRow {...defaultProps(layer)} />);
    const callsAfterMount = spy.mock.calls.length;

    rerender(
      <StackRow
        {...defaultProps({ ...layer, style_config: { render_mode: 'heatmap' } as MapLayerResponse['style_config'] })}
      />,
    );

    expect(spy.mock.calls.length).toBeGreaterThan(callsAfterMount);

    spy.mockRestore();
  });

  it('(b) DOES recompute when a keyed field changes (opacity)', () => {
    const layer = makeLayer({ opacity: 1 });
    const spy = vi.spyOn(layerIcons, 'extractStyleHints');

    const { rerender } = render(<StackRow {...defaultProps(layer)} />);
    const callsAfterMount = spy.mock.calls.length;

    rerender(
      <StackRow {...defaultProps({ ...layer, opacity: 0.4 })} />,
    );

    expect(spy.mock.calls.length).toBeGreaterThan(callsAfterMount);

    spy.mockRestore();
  });
});
