import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createElement, type ReactNode } from 'react';
import { MAP_COLORS } from '@/lib/map-colors';
import {
  EXPORT_CANVAS_MAX_AREA,
  EXPORT_CANVAS_MAX_DIMENSION,
  OG_ATTRIBUTION,
  THUMBNAIL_ATTRIBUTION,
} from '@/lib/map-image-attribution';
import { act } from '@testing-library/react';
import { renderHook as baseRenderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { TooltipProvider } from '@/components/ui/tooltip';
import { renderHook } from '@/test/test-utils';
import { buildLayerDiff, reconcileLayerDiffWithServer, useBuilderSave, __resetThumbnailDebounceForTests } from '@/components/builder/hooks/use-builder-save';
import { stampPersistedFolderGroupExpanded } from '@/components/builder/folder-groups';
import { usePluginStore } from '@/stores/map-plugin-store';
import type { MapLayerResponse } from '@/types/api';
import { queryKeys } from '@/lib/query-keys';
import { ApiError } from '@/api/client';

/* ── Mocks ─────────────────────────────────────────── */

const mockMutate = vi.fn();
const mockUpdateMapMutateAsync = vi.fn();
const mockPatchMapLayersMutateAsync = vi.fn();
const mockDuplicateMapMutateAsync = vi.fn();
const mockEnabledPlugins = vi.hoisted(() => ({
  value: null as string[] | null | undefined,
}));

vi.mock('@/hooks/use-maps', () => ({
  useUpdateMap: () => ({
    mutate: mockMutate,
    mutateAsync: mockUpdateMapMutateAsync,
    isPending: false,
  }),
  usePatchMapLayers: () => ({
    mutateAsync: mockPatchMapLayersMutateAsync,
    isPending: false,
  }),
  useDuplicateMap: () => ({
    mutateAsync: mockDuplicateMapMutateAsync,
    isPending: false,
  }),
}));

vi.mock('@/hooks/use-settings', () => ({
  useEnabledPlugins: () => ({ data: mockEnabledPlugins.value }),
}));

const mockUploadThumbnail = vi.fn((..._args: unknown[]) => Promise.resolve());
const mockUploadOgImage = vi.fn((..._args: unknown[]) => Promise.resolve());
// fix(#1778): the stale-diff recovery refetches the map to learn which layer
// ids the server still has.
const mockGetMap = vi.fn();
vi.mock('@/api/maps', () => ({
  getMap: (...args: unknown[]) => mockGetMap(...args),
  uploadThumbnail: (...args: unknown[]) => mockUploadThumbnail(...args),
  uploadOgImage: (...args: unknown[]) => mockUploadOgImage(...args),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockBlocker = { state: 'unblocked' as const, reset: vi.fn(), proceed: vi.fn() };
vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return {
    ...actual,
    useBlocker: () => mockBlocker,
  };
});

const mockEdition = vi.hoisted(() => ({
  isEnterprise: false,
}));

vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => ({
    edition: mockEdition.isEnterprise ? 'enterprise' : 'community',
    features: [],
    isEnterprise: mockEdition.isEnterprise,
    isLoading: false,
  }),
}));

/* ── Helpers ───────────────────────────────────────── */

function createMockCanvas() {
  // fix(#1479): the 2D context records its fills so the globe space backdrop
  // painted under a capture can be asserted, along with the order — a fill
  // after drawImage would erase the map instead of backing it.
  const fills: { style: string; rect: number[] }[] = [];
  const ctx = {
    drawImage: vi.fn(),
    fillStyle: '',
    font: '',
    textBaseline: '',
    fillText: vi.fn(),
    fillRect: vi.fn((...rect: number[]) => { fills.push({ style: ctx.fillStyle, rect }); }),
    strokeRect: vi.fn(),
    beginPath: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    createLinearGradient: vi.fn(() => ({ addColorStop: vi.fn() })),
    // feat(#1486): the attribution overlay measures before it draws.
    // fix(#1541 codex P1): length-proportional, not constant. A constant makes
    // every credit set "fit" on one line, so no test at this level could see a
    // wrap boundary — which is how the dropped credits went unnoticed here.
    // The fitter's own wrap arithmetic is exercised in
    // lib/__tests__/map-image-attribution.test.ts.
    measureText: vi.fn((text: string) => ({ width: text.length * 5 })),
  };
  return {
    width: 800,
    height: 600,
    toBlob: vi.fn((cb: (b: Blob | null) => void) => cb(new Blob(['png'], { type: 'image/png' }))),
    toDataURL: vi.fn(() => 'data:image/jpeg;base64,abc'),
    getContext: vi.fn(() => ctx),
    ctx,
    fills,
  };
}

/** feat(#1486): the credits a default mock map declares, as separate sources
 *  (which is how a real style carries them), and the single line they render
 *  as once joined. fix(#1541 codex P2): the reader takes the structured list
 *  and never re-splits the joined form, so the mock supplies the list. */
export const MOCK_CREDITS = ['© OpenFreeMap', '© OpenStreetMap contributors'];
export const MOCK_ATTRIBUTION = MOCK_CREDITS.join(' | ');

function createMockMap(
  overrides: { loaded?: boolean; globeSpace?: boolean; attribution?: string | null } = {},
) {
  // fix(#1479): capture paths ask the container whether the space backdrop is
  // on screen. Every mock map has one; only an opted-in map is marked.
  const container = document.createElement('div');
  if (overrides.globeSpace) container.setAttribute('data-globe-space', 'true');
  // feat(#1486): every real map declares credits on its sources and renders
  // them in the attribution control, so the default mock carries both. Pass
  // `attribution: null` for the no-credit-available case.
  const attribution =
    overrides.attribution === undefined ? MOCK_ATTRIBUTION : overrides.attribution;
  const credits = attribution === null ? [] : attribution.split(' | ');
  if (attribution !== null) {
    const inner = document.createElement('div');
    inner.className = 'maplibregl-ctrl-attrib-inner';
    // fix(#1541 codex P2 round 3): innerHTML, because MapLibre RENDERS the
    // credit HTML. Assigning it as text made an `<img alt="…">` credit read
    // back as its own markup, so a reader that could not see the alt still
    // found the provider name in the string — a mock artifact that made the
    // image-credit tests pass against the broken reader.
    inner.innerHTML = attribution;
    container.appendChild(inner);
  }
  return {
    getContainer: vi.fn(() => container),
    // The structured path the reader prefers: one source per credit, each
    // referenced by a visible layer. fix(#1541 codex P1): the reader sorts
    // shown sources ahead of hidden ones, and a style whose sources no layer
    // references reads as all-hidden — a state no real map is in.
    getStyle: vi.fn(() => ({
      sources: Object.fromEntries(
        credits.map((credit, i) => [`src-${i}`, { attribution: credit }]),
      ),
      layers: credits.map((_, i) => ({ id: `layer-${i}`, source: `src-${i}`, layout: {} })),
    })),
    getCenter: vi.fn(() => ({ lng: -73.9, lat: 40.7 })),
    getZoom: vi.fn(() => 10),
    getBearing: vi.fn(() => 0),
    getPitch: vi.fn(() => 0),
    getSource: vi.fn<(sourceId: string) => unknown>(() => undefined),
    triggerRepaint: vi.fn(),
    once: vi.fn(),
    off: vi.fn(),
    loaded: vi.fn(() => overrides.loaded ?? true),
    getCanvas: vi.fn(() => createMockCanvas()),
  };
}

/** PERF-08 (Phase 274): doCapture and handleExportPNG now register
 *  `map.once('render', ...)` and call `map.triggerRepaint()` instead of
 *  reading the canvas synchronously. Tests must locate the registered
 *  render callback and invoke it to simulate the next render frame. */
function fireRenderCallback(mockMap: ReturnType<typeof createMockMap>): void {
  const renderCall = mockMap.once.mock.calls.find(
    (c: unknown[]) => c[0] === 'render',
  );
  if (!renderCall) return;
  const cb = renderCall[1] as () => void;
  cb();
}

/** The real SaveState accepted by useBuilderSave. */
type SaveState = Parameters<typeof useBuilderSave>[0];

/**
 * Test factory that returns a fully-typed SaveState with sensible defaults.
 * Mock map instances are cast once here so call sites stay `as any`-free.
 */
function makeSaveState(overrides: Partial<SaveState> = {}): SaveState {
  return {
    mapId: 'map-1',
    localLayers: [],
    localBasemap: 'openfreemap-positron',
    showBasemapLabels: true,
    basemapConfig: null,
    terrainConfig: null,
    localName: 'Test Map',
    localDescription: 'A test',
    legendTitle: null,
    dockNotes: '',
    mapInstanceRef: { current: createMockMap() } as unknown as SaveState['mapInstanceRef'],
    setHasUnsavedChanges: vi.fn(),
    hasUnsavedChanges: false,
    hasThumbnail: true,
    // fix(#392): the real MapBuilderPage owns this ref; tests that don't
    // exercise the layer-create → save-baseline bridge get a plain no-op ref.
    saveBaselineSyncRef: { current: { add: () => {}, remove: () => {} } },
    ...overrides,
  };
}

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'dataset-1',
    dataset_name: 'Layer 1',
    dataset_geometry_type: 'MULTIPOLYGON',
    dataset_table_name: 'layer_1',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    layer_type: 'vector_geolens',
    dataset_record_type: 'vector_dataset',
    filter: null,
    label_config: null,
    style_config: null,
    show_in_legend: true,
    ...overrides,
  };
}

function renderHookWithQueryClient(state: SaveState, queryClient: QueryClient) {
  function Wrapper({ children }: { children: ReactNode }) {
    return createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(
        TooltipProvider,
        null,
        createElement(MemoryRouter, null, children),
      ),
    );
  }

  return baseRenderHook(() => useBuilderSave(state), { wrapper: Wrapper });
}

/* ── Tests ─────────────────────────────────────────── */

describe('reconcileLayerDiffWithServer (#1778)', () => {
  it('drops updated and removed ids the server no longer has', () => {
    const out = reconcileLayerDiffWithServer(
      {
        added: [{ dataset_id: 'ds-new', sort_order: 0 } as never],
        updated: [{ id: 'a', opacity: 0.5 }, { id: 'gone', opacity: 0.5 }],
        removed: ['b', 'alsoGone'],
      },
      new Set(['a', 'b']),
    );
    expect(out.added).toHaveLength(1);
    expect(out.updated).toEqual([{ id: 'a', opacity: 0.5 }]);
    expect(out.removed).toEqual(['b']);
  });

  it('drops order entries the server does not have or is about to remove', () => {
    const out = reconcileLayerDiffWithServer(
      { removed: ['b'], order: ['a', 'b', 'gone'] },
      new Set(['a', 'b']),
    );
    expect(out.order).toEqual(['a']);
  });

  it('omits order entirely when nothing survives, so the server does not renumber', () => {
    const out = reconcileLayerDiffWithServer({ order: ['gone'] }, new Set(['a']));
    expect(out.order).toBeUndefined();
  });

  it('never introduces a removal for a layer this session has not seen', () => {
    // The server has a layer another session added. Rebuilding the diff from a
    // refetched baseline would emit it as `removed`; reconciling cannot.
    const out = reconcileLayerDiffWithServer(
      { updated: [{ id: 'a', opacity: 0.5 }] },
      new Set(['a', 'addedByAnotherSession']),
    );
    expect(out.removed).toBeUndefined();
  });
});

describe('buildLayerDiff', () => {
  it('classifies added layers without baseline IDs', () => {
    const added = makeLayer({ id: 'new-layer', dataset_id: 'dataset-new', sort_order: 0 });

    const result = buildLayerDiff([], [added]);

    expect(result.unsupported).toBe(false);
    expect(result.diff.added).toEqual([
      expect.objectContaining({ dataset_id: 'dataset-new', sort_order: 0 }),
    ]);
    expect(result.diff.updated).toBeUndefined();
    expect(result.diff.removed).toBeUndefined();
  });

  it('classifies meaningful field updates by stable layer ID', () => {
    const baseline = makeLayer({ id: 'layer-1', paint: { 'fill-color': '#000000' } });
    const current = makeLayer({ id: 'layer-1', paint: { 'fill-color': '#ff0000' } });

    const result = buildLayerDiff([baseline], [current]);

    expect(result.diff.updated).toEqual([
      { id: 'layer-1', paint: { 'fill-color': '#ff0000' } },
    ]);
  });

  it('persists canonical paint after a stale property is cleared', () => {
    const gradient = ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'];
    const baseline = makeLayer({
      id: 'layer-1',
      dataset_geometry_type: 'LineString',
      paint: { 'line-color': '#111827', 'line-width': 4, 'line-gradient': gradient },
    });
    const current = makeLayer({
      id: 'layer-1',
      dataset_geometry_type: 'LineString',
      paint: { 'line-color': '#f97316', 'line-width': 4 },
    });

    const result = buildLayerDiff([baseline], [current]);

    expect(result.diff.updated).toEqual([
      { id: 'layer-1', paint: { 'line-color': '#f97316', 'line-width': 4 } },
    ]);
    expect(result.diff.updated?.[0].paint).not.toHaveProperty('line-gradient');
    expect(result.diff.updated?.[0].paint).not.toHaveProperty('clear_paint');
  });

  it('classifies removed layers by stable layer ID', () => {
    const baseline = makeLayer({ id: 'layer-1' });

    const result = buildLayerDiff([baseline], []);

    expect(result.diff.removed).toEqual(['layer-1']);
  });

  it('classifies reordered layers by stable layer ID order', () => {
    const layer1 = makeLayer({ id: 'layer-1', sort_order: 0 });
    const layer2 = makeLayer({ id: 'layer-2', sort_order: 1 });
    const current1 = makeLayer({ id: 'layer-1', sort_order: 1 });
    const current2 = makeLayer({ id: 'layer-2', sort_order: 0 });

    const result = buildLayerDiff([layer1, layer2], [current2, current1]);

    expect(result.diff.order).toEqual(['layer-2', 'layer-1']);
  });

  it('serializes virtual folder groups as child layer metadata, not added API layers', () => {
    const baseline = makeLayer({ id: 'layer-1' });
    const group = {
      ...makeLayer({ id: 'group-1', display_name: 'Field layers' }),
      layer_type: 'group:folder',
    } as unknown as MapLayerResponse;
    const groupedChild = {
      ...baseline,
      parent_group_id: 'group-1',
    } as MapLayerResponse & { parent_group_id: string };

    const result = buildLayerDiff(
      [baseline],
      [group, groupedChild],
      { 'group-1': { expanded: true } },
    );

    expect(result.diff.added).toBeUndefined();
    expect(result.diff.updated).toEqual([
      {
        id: 'layer-1',
        style_config: {
          builder: {
            folderGroupId: 'group-1',
            folderGroupName: 'Field layers',
            folderGroupExpanded: true,
          },
        },
      },
    ]);
  });

  // fix(#805): the baseline used to be prepared WITHOUT groupMeta, so baseline
  // children lacked the folderGroupExpanded marker while current children
  // carried it — every save of an unchanged grouped map emitted a spurious
  // per-child style_config PATCH.
  it('emits an empty diff for an unchanged grouped map (no spurious per-child style_config patch)', () => {
    const group = {
      ...makeLayer({ id: 'group-1', display_name: 'Field layers' }),
      layer_type: 'group:folder',
    } as unknown as MapLayerResponse;
    const child = {
      ...makeLayer({
        id: 'layer-1',
        sort_order: 1,
        style_config: {
          builder: {
            folderGroupId: 'group-1',
            folderGroupName: 'Field layers',
            folderGroupExpanded: true,
          },
        } as MapLayerResponse['style_config'],
      }),
      parent_group_id: 'group-1',
    } as MapLayerResponse;

    const result = buildLayerDiff(
      [group, child],
      [group, child],
      { 'group-1': { expanded: true } },
    );

    expect(result.diff).toEqual({});
  });

  // fix(#833): collapse state is persisted on children, so a collapse-only
  // change MUST reach the diff — it used to be stamped identically on both
  // sides (the #805 fix over-corrected) and only persisted when another
  // style_config edit rode along in the same save.
  it('a collapse-state-only change emits the per-child style_config patch', () => {
    const group = {
      ...makeLayer({ id: 'group-1', display_name: 'Field layers' }),
      layer_type: 'group:folder',
    } as unknown as MapLayerResponse;
    const child = {
      ...makeLayer({
        id: 'layer-1',
        sort_order: 1,
        style_config: {
          builder: {
            folderGroupId: 'group-1',
            folderGroupName: 'Field layers',
            folderGroupExpanded: true,
          },
        } as MapLayerResponse['style_config'],
      }),
      parent_group_id: 'group-1',
    } as MapLayerResponse;

    // The user collapsed the group after the last save: persisted marker says
    // expanded=true, live groupMeta says false. Nothing else changed.
    const result = buildLayerDiff(
      [group, child],
      [group, child],
      { 'group-1': { expanded: false } },
    );

    expect(result.diff.updated).toEqual([
      {
        id: 'layer-1',
        style_config: {
          builder: {
            folderGroupId: 'group-1',
            folderGroupName: 'Field layers',
            folderGroupExpanded: false,
          },
        },
      },
    ]);
  });

  // fix(#833 codex): collapse→save→expand→save round-trip. The post-save
  // baseline used to be a verbatim copy of localLayers, whose markers still
  // said "expanded" from load — so the collapse-save left a baseline the
  // following expand-save could not diff against, and reload restored the
  // stale collapsed state.
  it('an expand saved after a saved collapse still reaches the diff (baseline round-trip)', () => {
    const group = {
      ...makeLayer({ id: 'group-1', display_name: 'Field layers' }),
      layer_type: 'group:folder',
    } as unknown as MapLayerResponse;
    const child = {
      ...makeLayer({
        id: 'layer-1',
        sort_order: 1,
        style_config: {
          builder: {
            folderGroupId: 'group-1',
            folderGroupName: 'Field layers',
            folderGroupExpanded: true,
          },
        } as MapLayerResponse['style_config'],
      }),
      parent_group_id: 'group-1',
    } as MapLayerResponse;

    // Save 1 — collapse-only: the diff persists expanded=false.
    const collapseSave = buildLayerDiff(
      [group, child],
      [group, child],
      { 'group-1': { expanded: false } },
    );
    expect(collapseSave.diff.updated?.[0]?.style_config).toEqual({
      builder: {
        folderGroupId: 'group-1',
        folderGroupName: 'Field layers',
        folderGroupExpanded: false,
      },
    });

    // Successful save snapshots the baseline with the SENT collapse state
    // (stampPersistedFolderGroupExpanded — what handleSave and the
    // baseline-refresh effect store), not the loaded markers.
    const postSaveBaseline = stampPersistedFolderGroupExpanded(
      [group, child],
      { 'group-1': { expanded: false } },
    );

    // Save 2 — expand-only: must diff back to expanded=true.
    const expandSave = buildLayerDiff(
      postSaveBaseline,
      [group, child],
      { 'group-1': { expanded: true } },
    );
    expect(expandSave.diff.updated).toEqual([
      {
        id: 'layer-1',
        style_config: {
          builder: {
            folderGroupId: 'group-1',
            folderGroupName: 'Field layers',
            folderGroupExpanded: true,
          },
        },
      },
    ]);

    // And a same-state save after that stays empty (no #805 regression).
    const noop = buildLayerDiff(
      stampPersistedFolderGroupExpanded([group, child], { 'group-1': { expanded: true } }),
      [group, child],
      { 'group-1': { expanded: true } },
    );
    expect(noop.diff).toEqual({});
  });

  it('returns an empty diff for no-op layers', () => {
    const baseline = makeLayer({ id: 'layer-1' });
    const current = makeLayer({ id: 'layer-1' });

    const result = buildLayerDiff([baseline], [current]);

    expect(result.diff).toEqual({});
  });

  it('normalizes legacy DEM image mode to hillshade before comparing save diffs', () => {
    const baseline = makeLayer({
      id: 'dem-1',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      dataset_record_type: 'raster_dataset',
      is_dem: true,
      style_config: { render_mode: 'hillshade' } as MapLayerResponse['style_config'],
    });
    const current = makeLayer({
      ...baseline,
      style_config: { render_mode: 'image' } as unknown as MapLayerResponse['style_config'],
    });

    const result = buildLayerDiff([baseline], [current]);

    expect(result.diff.updated).toBeUndefined();
  });

  it('ignores dataset metadata changes that are not saved on map layers', () => {
    const baseline = makeLayer({ id: 'layer-1', dataset_name: 'Old name', dataset_feature_count: 10 });
    const current = makeLayer({ id: 'layer-1', dataset_name: 'New name', dataset_feature_count: 25 });

    const result = buildLayerDiff([baseline], [current]);

    expect(result.diff).toEqual({});
  });

  // fix(#430 V-01): P0 data-loss regression test. A raster layer's style_config is
  // managed by RasterLayerControls, which never writes style_config at all —
  // so a raster layer's local `style_config` can be `null`/undefined even
  // when the server-side baseline has real data from an earlier session.
  // Before this fix, buildLayerDiff emitted an explicit `style_config: null`
  // in this case, which the backend's PATCH handler applies literally
  // (`_NULLABLE_PATCH_FIELDS` — an explicit null NULLs the column), silently
  // wiping real server-side data the builder never touched.
  it('omits style_config from the patch for a raster layer whose local state never carries it, instead of nulling server-side data', () => {
    const baseline = makeLayer({
      id: 'raster-1',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      dataset_record_type: 'raster_dataset',
      style_config: { someRasterKey: 'value' } as unknown as MapLayerResponse['style_config'],
    });
    // Local builder state for this raster layer never carries style_config
    // (RasterLayerControls doesn't manage it) — simulate that as null, while
    // also changing a field RasterLayerControls DOES manage (opacity) so the
    // layer produces a real patch to assert against.
    const current = makeLayer({
      ...baseline,
      style_config: null,
      opacity: 0.5,
    });

    const result = buildLayerDiff([baseline], [current]);

    expect(result.diff.updated).toEqual([{ id: 'raster-1', opacity: 0.5 }]);
    expect(result.diff.updated?.[0]).not.toHaveProperty('style_config');
  });

  it('still applies an explicit style_config on a VECTOR layer (the editor genuinely manages that field)', () => {
    const baseline = makeLayer({
      id: 'vector-1',
      style_config: { mode: 'categorical', column: 'name' } as unknown as MapLayerResponse['style_config'],
    });
    const current = makeLayer({ ...baseline, style_config: null });

    const result = buildLayerDiff([baseline], [current]);

    expect(result.diff.updated).toEqual([{ id: 'vector-1', style_config: null }]);
  });

  // fix(#767 B8): ungrouping a raster layer clears the folder-group markers,
  // compacting its style_config to null. The V-01 unmanaged-field guard used
  // to swallow that null-out (rasters have no style editor), so no PATCH was
  // emitted and the group resurrected on reload. Folder-group markers are
  // managed for every layer type — the intentional clear must patch through.
  it('emits style_config: null when ungrouping a raster layer whose baseline carried folder-group markers', () => {
    const groupRow = makeLayer({
      id: 'group-1',
      // Synthetic group rows use the builder-local 'group:folder' type, which
      // sits outside the persisted MapLayerType union (see GroupedLayer).
      layer_type: 'group:folder' as unknown as MapLayerResponse['layer_type'],
      display_name: 'My Group',
      sort_order: 0,
    });
    const rasterChild = makeLayer({
      id: 'raster-1',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      dataset_record_type: 'raster_dataset',
      sort_order: 1,
      parent_group_id: 'group-1',
      style_config: null,
    } as Partial<MapLayerResponse>);

    // Baseline: grouped (prepareLayersForPersistence writes the builder
    // folderGroup* markers onto the child). Current: ungrouped, markers
    // cleared — style_config compacts back to null.
    const ungrouped = makeLayer({
      ...rasterChild,
      sort_order: 0,
      parent_group_id: null,
      style_config: null,
    } as Partial<MapLayerResponse>);

    const result = buildLayerDiff([groupRow, rasterChild], [ungrouped]);

    expect(result.diff.updated).toEqual(
      expect.arrayContaining([expect.objectContaining({ id: 'raster-1', style_config: null })]),
    );
  });

  it('still omits style_config for a raster null-out when the baseline had real (non-group) data', () => {
    const baseline = makeLayer({
      id: 'raster-2',
      layer_type: 'raster_geolens',
      dataset_geometry_type: null,
      dataset_record_type: 'raster_dataset',
      style_config: { someRasterKey: 'value' } as unknown as MapLayerResponse['style_config'],
    });
    const current = makeLayer({ ...baseline, style_config: null, opacity: 0.4 });

    const result = buildLayerDiff([baseline], [current]);

    expect(result.diff.updated).toEqual([{ id: 'raster-2', opacity: 0.4 }]);
  });
});

describe('useBuilderSave', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // SP-16: clear any pending debounced thumbnail captures from a prior test
    // so module-level state doesn't bleed across cases.
    __resetThumbnailDebounceForTests();
    mockEnabledPlugins.value = null;
    mockEdition.isEnterprise = false;
    mockUpdateMapMutateAsync.mockImplementation(async (payload) => {
      mockMutate(payload);
      return { id: payload.id, layers: [] };
    });
    mockPatchMapLayersMutateAsync.mockResolvedValue({ id: 'map-1', layers: [] });
    mockDuplicateMapMutateAsync.mockResolvedValue({ id: 'new-map-1', excluded_layer_count: 0 });
    usePluginStore.getState().replace([]);
  });

  it('handleSave calls updateMap.mutate with correct payload', () => {
    const state = makeSaveState();
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => {
      result.current.handleSave();
    });

    expect(mockMutate).toHaveBeenCalledTimes(1);
    const [payload] = mockMutate.mock.calls[0];
    expect(payload.id).toBe('map-1');
    expect(payload.data.name).toBe('Test Map');
    expect(payload.data.basemap_style).toBe('openfreemap-positron');
    expect(payload.data.basemap_config).toBeNull();
    expect(payload.data.terrain_config).toBeNull();
    expect(payload.data.center_lng).toBe(-73.9);
    expect(payload.data.center_lat).toBe(40.7);
    expect(payload.data.zoom).toBe(10);
    expect(payload.data.layers).toBeUndefined();
  });

  it('uses layer PATCH for meaningful layer changes and saves metadata separately', async () => {
    const baseline = makeLayer({ paint: { 'fill-color': '#000000' } });
    let state = makeSaveState({ localLayers: [baseline] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));

    state = makeSaveState({
      localLayers: [makeLayer({ paint: { 'fill-color': '#ff0000' } })],
      hasUnsavedChanges: true,
    });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockPatchMapLayersMutateAsync).toHaveBeenCalledWith({
      id: 'map-1',
      diff: { updated: [{ id: 'layer-1', paint: { 'fill-color': '#ff0000' } }] },
    });
    expect(mockUpdateMapMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'map-1',
        data: expect.not.objectContaining({ layers: expect.any(Array) }),
      }),
    );
    expect(state.setHasUnsavedChanges).toHaveBeenCalledWith(false);
  });

  it('fix(#756): keeps the dirty flag when an edit lands while the save is in flight', async () => {
    // The added-layer PATCH is handleSave's first await; deferring it holds
    // the save in flight while the test lands an edit.
    let resolvePatch!: (v: unknown) => void;
    mockPatchMapLayersMutateAsync.mockImplementationOnce(
      () => new Promise((resolve) => { resolvePatch = resolve; }),
    );
    const setHasUnsavedChanges = vi.fn();
    let state = makeSaveState({
      localLayers: [makeLayer()],
      hasUnsavedChanges: true,
      setHasUnsavedChanges,
    });
    const { result, rerender } = renderHook(() => useBuilderSave(state));

    let savePromise!: Promise<void>;
    act(() => {
      savePromise = result.current.handleSave();
    });

    // An edit lands while the network round-trip is still awaiting: the
    // dirty flag must survive the save, or the baseline effect absorbs the
    // edit and the query-invalidation resync overwrites it on screen.
    state = makeSaveState({
      localLayers: [makeLayer({ paint: { 'fill-color': '#ff0000' } })],
      hasUnsavedChanges: true,
      setHasUnsavedChanges,
    });
    rerender();

    await act(async () => {
      resolvePatch({});
      await savePromise;
    });

    expect(setHasUnsavedChanges).not.toHaveBeenCalledWith(false);
  });

  it('codex(#792): keeps the dirty flag when a plugin toggles while the save is in flight', async () => {
    let resolvePatch!: (v: unknown) => void;
    mockPatchMapLayersMutateAsync.mockImplementationOnce(
      () => new Promise((resolve) => { resolvePatch = resolve; }),
    );
    const setHasUnsavedChanges = vi.fn();
    const state = makeSaveState({
      localLayers: [makeLayer()],
      hasUnsavedChanges: true,
      setHasUnsavedChanges,
    });
    const { result } = renderHook(() => useBuilderSave(state));

    let savePromise!: Promise<void>;
    act(() => {
      savePromise = result.current.handleSave();
    });

    // The plugins payload reads usePluginStore directly, not SaveState — a
    // mid-save toggle must keep the map dirty or the toggle never persists.
    act(() => {
      usePluginStore.getState().toggle('legend');
    });

    await act(async () => {
      resolvePatch({});
      await savePromise;
    });

    expect(setHasUnsavedChanges).not.toHaveBeenCalledWith(false);
  });

  it('fix(#756): still clears the dirty flag when nothing changed during the save', async () => {
    const setHasUnsavedChanges = vi.fn();
    const state = makeSaveState({
      localLayers: [makeLayer()],
      hasUnsavedChanges: true,
      setHasUnsavedChanges,
    });
    const { result } = renderHook(() => useBuilderSave(state));

    await act(async () => {
      await result.current.handleSave();
    });

    expect(setHasUnsavedChanges).toHaveBeenCalledWith(false);
  });

  it('persists terrain config in metadata saves without forcing layer replacement', async () => {
    const state = makeSaveState({
      terrainConfig: {
        enabled: true,
        source_dataset_id: 'dem-dataset-1',
        exaggeration: 1.8,
      },
    });
    const { result } = renderHook(() => useBuilderSave(state));

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockPatchMapLayersMutateAsync).not.toHaveBeenCalled();
    expect(mockUpdateMapMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'map-1',
        data: expect.objectContaining({
          terrain_config: {
            enabled: true,
            source_dataset_id: 'dem-dataset-1',
            exaggeration: 1.8,
          },
        }),
      }),
    );
    expect(mockUpdateMapMutateAsync.mock.calls[0][0].data.layers).toBeUndefined();
  });

  // A save that changes a layer (zoom range) AND terrain uses the normal split
  // path: minimal layer PATCH + metadata PUT. HT-13 note: the overlay and
  // terrain authorities are independent in the composable model, so a partial
  // persist is recoverable (not a contradiction) — no need to force the lossy
  // full-replacement PUT here.
  it('saves duplicate renderings, basemap config, terrain config, and zoom range through existing fields', async () => {
    const layerA = makeLayer({
      id: 'layer-a',
      dataset_id: 'dataset-shared',
      display_name: 'Shared fill',
      sort_order: 0,
      layout: { _minzoom: 0, _maxzoom: 22 },
    });
    const layerB = makeLayer({
      id: 'layer-b',
      dataset_id: 'dataset-shared',
      display_name: 'Shared outline',
      sort_order: 1,
      paint: { 'fill-outline-color': '#111111' },
    });
    let state = makeSaveState({ localLayers: [layerA, layerB] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));

    state = makeSaveState({
      localLayers: [
        makeLayer({
          ...layerA,
          layout: { _minzoom: 3, _maxzoom: 17 },
        }),
        layerB,
      ],
      localBasemap: 'openfreemap-dark',
      showBasemapLabels: false,
      basemapConfig: {
        label_mode: 'hidden',
        road_visibility: 'subtle',
        boundary_visibility: 'hidden',
        building_visibility: false,
        land_water_tone: 'contrast',
        relief_contrast: 'strong',
      },
      terrainConfig: {
        enabled: true,
        source_dataset_id: 'dataset-dem',
        exaggeration: 2.25,
      },
      hasUnsavedChanges: true,
    });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockPatchMapLayersMutateAsync).toHaveBeenCalledWith({
      id: 'map-1',
      diff: {
        updated: [{ id: 'layer-a', layout: { _minzoom: 3, _maxzoom: 17 } }],
      },
    });
    expect(mockUpdateMapMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'map-1',
        data: expect.objectContaining({
          basemap_style: 'openfreemap-dark',
          show_basemap_labels: false,
          basemap_config: {
            label_mode: 'hidden',
            road_visibility: 'subtle',
            boundary_visibility: 'hidden',
            building_visibility: false,
            land_water_tone: 'contrast',
            relief_contrast: 'strong',
          },
          terrain_config: {
            enabled: true,
            source_dataset_id: 'dataset-dem',
            exaggeration: 2.25,
          },
        }),
      }),
    );
    // Metadata PUT carries no layers on the split path.
    expect(mockUpdateMapMutateAsync.mock.calls[0][0].data.layers).toBeUndefined();
  });

  it('persists basemap_config opacity, background color, and sublayer opacity', async () => {
    const layer = makeLayer();
    let state = makeSaveState({ localLayers: [layer] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));

    state = makeSaveState({
      localLayers: [layer],
      basemapConfig: {
        label_mode: 'full',
        road_visibility: 'full',
        boundary_visibility: 'full',
        building_visibility: true,
        land_water_tone: 'default',
        relief_contrast: null,
        opacity: 0.55,
        background_color: '#123456',
        sublayer_overrides: {
          road: { opacity: 0.45 },
        },
      },
      hasUnsavedChanges: true,
    });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockUpdateMapMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          basemap_config: expect.objectContaining({
            opacity: 0.55,
            background_color: '#123456',
            sublayer_overrides: {
              road: { opacity: 0.45 },
            },
          }),
        }),
      }),
    );
  });

  it('skips layer PATCH when the layer diff is empty', async () => {
    const layer = makeLayer();
    let state = makeSaveState({ localLayers: [layer] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));
    state = makeSaveState({ localLayers: [layer], hasUnsavedChanges: true });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockPatchMapLayersMutateAsync).not.toHaveBeenCalled();
    expect(mockUpdateMapMutateAsync).toHaveBeenCalledTimes(1);
    expect(mockUpdateMapMutateAsync.mock.calls[0][0].data.layers).toBeUndefined();
  });

  it('falls back to full layer replacement when PATCH returns a structural error', async () => {
    mockPatchMapLayersMutateAsync.mockRejectedValueOnce(
      // fix(#1778): 405 is now the only shape that escalates to a full PUT. A
      // 400 with a diff-integrity detail is a conflict, covered separately below.
      new ApiError('Method Not Allowed', 405, 'Method Not Allowed'),
    );
    const baseline = makeLayer({ paint: { 'fill-color': '#000000' } });
    let state = makeSaveState({ localLayers: [baseline] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));
    state = makeSaveState({
      localLayers: [makeLayer({ paint: { 'fill-color': '#ff0000' } })],
      hasUnsavedChanges: true,
    });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockPatchMapLayersMutateAsync).toHaveBeenCalledTimes(1);
    expect(mockUpdateMapMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'map-1',
        data: expect.objectContaining({
          layers: [expect.objectContaining({ dataset_id: 'dataset-1', paint: { 'fill-color': '#ff0000' } })],
        }),
      }),
    );
    expect(state.setHasUnsavedChanges).toHaveBeenCalledWith(false);
  });

  it('omits virtual folder rows from full replacement fallback payloads', async () => {
    mockPatchMapLayersMutateAsync.mockRejectedValueOnce(
      // fix(#1778): 405 is now the only shape that escalates to a full PUT. A
      // 400 with a diff-integrity detail is a conflict, covered separately below.
      new ApiError('Method Not Allowed', 405, 'Method Not Allowed'),
    );
    const baseline = makeLayer({ id: 'layer-1' });
    const group = {
      ...makeLayer({ id: 'group-1', display_name: 'Field layers' }),
      layer_type: 'group:folder',
    } as unknown as MapLayerResponse;
    const child = {
      ...baseline,
      parent_group_id: 'group-1',
    } as MapLayerResponse & { parent_group_id: string };
    let state = makeSaveState({ localLayers: [baseline] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));
    state = makeSaveState({
      localLayers: [group, child],
      groupMeta: { 'group-1': { expanded: true } },
      hasUnsavedChanges: true,
    });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    const fallbackPayload = mockUpdateMapMutateAsync.mock.calls[0][0].data;
    expect(fallbackPayload.layers).toHaveLength(1);
    expect(fallbackPayload.layers[0]).toMatchObject({
      dataset_id: 'dataset-1',
      layer_type: 'vector_geolens',
      style_config: {
        builder: {
          folderGroupId: 'group-1',
          folderGroupName: 'Field layers',
          folderGroupExpanded: true,
        },
      },
    });
  });

  // -------------------------------------------------------------------------
  // fix(#1778): "a stale-diff 400 from PATCH /maps/{id}/layers is misread as
  // 'endpoint unsupported' and escalated to a full PUT that overwrites the
  // server's layer set" (codebase audit 2026-08-30).
  //
  // The backend raises these exact details when the diff names layer ids the
  // map no longer has, which means another session changed the map. The old
  // predicate matched them with /layer|order|.../i on statuses 400/404/409/422
  // and converted the one conflict signal into an unconditional overwrite.
  //
  // Counterfactual on main: every case below sees updateMap called with a
  // `layers` array (this session's whole local list, sent as a wholesale
  // replacement) instead of a re-diffed PATCH.
  // -------------------------------------------------------------------------
  it('re-diffs against the server instead of overwriting when the diff is stale', async () => {
    mockPatchMapLayersMutateAsync.mockRejectedValueOnce(
      new ApiError(
        'Layer diff references layer ids outside this map',
        400,
        'Layer diff references layer ids outside this map',
      ),
    );
    // The server no longer has layer-2: another session deleted it.
    mockGetMap.mockResolvedValueOnce({ id: 'map-1', layers: [{ id: 'layer-1' }] });

    const kept = makeLayer({ id: 'layer-1', paint: { 'fill-color': '#000000' } });
    const goneElsewhere = makeLayer({ id: 'layer-2', dataset_id: 'dataset-2', sort_order: 1 });
    let state = makeSaveState({ localLayers: [kept, goneElsewhere] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));
    state = makeSaveState({
      localLayers: [makeLayer({ id: 'layer-1', paint: { 'fill-color': '#ff0000' } })],
      hasUnsavedChanges: true,
    });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockGetMap).toHaveBeenCalledWith('map-1');
    expect(mockPatchMapLayersMutateAsync).toHaveBeenCalledTimes(2);
    // First attempt named the id the server had already dropped.
    expect(mockPatchMapLayersMutateAsync.mock.calls[0][0].diff.removed).toEqual(['layer-2']);
    // The retry drops it and keeps the real edit.
    const retried = mockPatchMapLayersMutateAsync.mock.calls[1][0].diff;
    expect(retried.removed).toBeUndefined();
    expect(retried.updated).toEqual([{ id: 'layer-1', paint: { 'fill-color': '#ff0000' } }]);
    // The metadata PUT carries NO layers array, so nothing is overwritten.
    expect(mockUpdateMapMutateAsync).toHaveBeenCalledTimes(1);
    expect(mockUpdateMapMutateAsync.mock.calls[0][0].data.layers).toBeUndefined();
  });

  it('skips the retry PATCH when nothing survives the reconcile', async () => {
    mockPatchMapLayersMutateAsync.mockRejectedValueOnce(
      new ApiError(
        'Layer order references unknown or removed layers',
        400,
        'Layer order references unknown or removed layers',
      ),
    );
    mockGetMap.mockResolvedValueOnce({ id: 'map-1', layers: [] });

    const goneElsewhere = makeLayer({ id: 'layer-9' });
    let state = makeSaveState({ localLayers: [goneElsewhere] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));
    state = makeSaveState({ localLayers: [], hasUnsavedChanges: true });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockPatchMapLayersMutateAsync).toHaveBeenCalledTimes(1);
    expect(mockUpdateMapMutateAsync.mock.calls[0][0].data.layers).toBeUndefined();
  });

  it('warns that layers changed elsewhere after a recovered save', async () => {
    const { toast } = await import('sonner');
    mockPatchMapLayersMutateAsync.mockRejectedValueOnce(
      new ApiError(
        'Layer diff references layer ids outside this map',
        400,
        'Layer diff references layer ids outside this map',
      ),
    );
    mockGetMap.mockResolvedValueOnce({ id: 'map-1', layers: [{ id: 'layer-1' }] });

    let state = makeSaveState({ localLayers: [makeLayer({ id: 'layer-1' }), makeLayer({ id: 'layer-2' })] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));
    state = makeSaveState({ localLayers: [makeLayer({ id: 'layer-1' })], hasUnsavedChanges: true });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(toast.warning).toHaveBeenCalledWith('toasts.mapSavedAfterRemoteChange');
    expect(toast.warning).not.toHaveBeenCalledWith('toasts.mapSavedFullResync');
    expect(state.setHasUnsavedChanges).toHaveBeenCalledWith(false);
  });

  it('reports a conflict rather than overwriting when the recovery itself fails', async () => {
    const { toast } = await import('sonner');
    mockPatchMapLayersMutateAsync.mockRejectedValueOnce(
      new ApiError(
        'Layer diff references layer ids outside this map',
        400,
        'Layer diff references layer ids outside this map',
      ),
    );
    mockGetMap.mockRejectedValueOnce(new Error('offline'));

    let state = makeSaveState({ localLayers: [makeLayer({ id: 'layer-1' }), makeLayer({ id: 'layer-2' })] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));
    state = makeSaveState({ localLayers: [makeLayer({ id: 'layer-1' })], hasUnsavedChanges: true });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(toast.error).toHaveBeenCalledWith('toasts.saveConflictReload');
    expect(mockUpdateMapMutateAsync).not.toHaveBeenCalled();
    expect(state.setHasUnsavedChanges).not.toHaveBeenCalledWith(false);
    expect(result.current.saveStatus).toBe('failed');
  });

  it('leaves a genuine validation rejection on the failure path', async () => {
    const { toast } = await import('sonner');
    // A 422 with prose the OLD predicate matched via /validation/i. It is not a
    // stale diff and not a missing endpoint, so it must simply fail.
    mockPatchMapLayersMutateAsync.mockRejectedValueOnce(
      new ApiError('Layer validation failed', 422, 'Layer validation failed'),
    );
    let state = makeSaveState({ localLayers: [makeLayer({ paint: { 'fill-color': '#000000' } })] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));
    state = makeSaveState({
      localLayers: [makeLayer({ paint: { 'fill-color': '#ff0000' } })],
      hasUnsavedChanges: true,
    });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockGetMap).not.toHaveBeenCalled();
    expect(mockUpdateMapMutateAsync).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith('toasts.saveFailed');
  });

  it('does not clear unsaved changes when save fails', async () => {
    mockPatchMapLayersMutateAsync.mockRejectedValueOnce(new Error('network down'));
    const baseline = makeLayer({ paint: { 'fill-color': '#000000' } });
    let state = makeSaveState({ localLayers: [baseline] });
    const { result, rerender } = renderHook(() => useBuilderSave(state));
    state = makeSaveState({
      localLayers: [makeLayer({ paint: { 'fill-color': '#ff0000' } })],
      hasUnsavedChanges: true,
    });
    rerender();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(state.setHasUnsavedChanges).not.toHaveBeenCalledWith(false);
    expect(result.current.saveStatus).toBe('failed');
    expect(result.current.isSaveRetryable).toBe(true);
  });

  it('surfaces popupConfigInvalidNamed toast with dedupe id + extended duration for named layer (Test A)', async () => {
    const { toast } = await import('sonner');
    const state = makeSaveState({
      hasUnsavedChanges: true,
      localLayers: [
        makeLayer({
          display_name: 'My Test Layer',
          popup_config: { enabled: true, expression: '{{missing_column}}', visible_fields: null },
          dataset_column_info: [{ name: 'present_column', type: 'text' }],
        }),
      ],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    await act(async () => {
      await result.current.handleSave();
    });

    // t() mock returns the key; we verify the NEW key (not popupConfigInvalid) is used
    // and the toast options preserve dedupe id + extended duration
    expect(toast.error).toHaveBeenCalledWith(
      'toasts.popupConfigInvalidNamed',
      expect.objectContaining({ id: 'popup-config-invalid', duration: 6000 }),
    );
    expect(mockUpdateMapMutateAsync).not.toHaveBeenCalled();
    expect(mockPatchMapLayersMutateAsync).not.toHaveBeenCalled();
  });

  it('surfaces popupConfigInvalidNamed toast with fallback name when display_name is null (Test B)', async () => {
    const { toast } = await import('sonner');
    const state = makeSaveState({
      hasUnsavedChanges: true,
      localLayers: [
        makeLayer({
          display_name: null,
          popup_config: { enabled: true, expression: '{{missing_column}}', visible_fields: null },
          dataset_column_info: [{ name: 'present_column', type: 'text' }],
        }),
      ],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    await act(async () => {
      await result.current.handleSave();
    });

    // Same key, same options — fallback name path also goes through popupConfigInvalidNamed
    expect(toast.error).toHaveBeenCalledWith(
      'toasts.popupConfigInvalidNamed',
      expect.objectContaining({ id: 'popup-config-invalid', duration: 6000 }),
    );
    expect(mockUpdateMapMutateAsync).not.toHaveBeenCalled();
    expect(mockPatchMapLayersMutateAsync).not.toHaveBeenCalled();
  });

  it('allows save when popup is enabled but dataset_column_info is null (CR-01 regression)', async () => {
    // dataset_column_info is null (column metadata not yet fetched).
    // Pre-check must skip validation and let the server be the authoritative gate.
    const state = makeSaveState({
      hasUnsavedChanges: true,
      localLayers: [
        makeLayer({
          popup_config: { enabled: true, expression: '{{some_column}}', visible_fields: null },
          dataset_column_info: null,
        }),
      ],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    await act(async () => {
      await result.current.handleSave();
    });

    // Save must proceed — no blocking toast, mutation called
    const { toast } = await import('sonner');
    expect(toast.error).not.toHaveBeenCalledWith(
      'toasts.popupConfigInvalidNamed',
      expect.anything(),
    );
    expect(mockUpdateMapMutateAsync).toHaveBeenCalled();
  });

  it('routes backend 422 popup_config rejection to popupConfigBackendRejected toast (Test C)', async () => {
    const { toast } = await import('sonner');
    // Layer has no popup_config — bypasses frontend pre-check; save proceeds to API
    const state = makeSaveState({
      hasUnsavedChanges: true,
      localLayers: [makeLayer({ popup_config: null })],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    // Reject with a FastAPI 422 whose detail array tags popup_config
    mockUpdateMapMutateAsync.mockRejectedValueOnce(
      new ApiError('Unprocessable Entity', 422, [
        { loc: ['body', 'layers', 0, 'popup_config', 'expression'], msg: 'String should have at most 500 characters', type: 'string_too_long' },
      ]),
    );

    await act(async () => {
      await result.current.handleSave();
    });

    // t() mock returns the key; verify it is the popup-specific key, not saveFailed
    expect(toast.error).toHaveBeenCalledWith(
      'toasts.popupConfigBackendRejected',
      expect.anything(),
    );
    expect(result.current.saveStatus).toBe('failed');
  });

  it('routes non-popup ApiError (500) to generic saveFailed toast (Test D)', async () => {
    const { toast } = await import('sonner');
    const state = makeSaveState({
      hasUnsavedChanges: true,
      localLayers: [makeLayer({ popup_config: null })],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    mockUpdateMapMutateAsync.mockRejectedValueOnce(new ApiError('Server Error', 500, undefined));

    await act(async () => {
      await result.current.handleSave();
    });

    expect(toast.error).toHaveBeenCalledWith('toasts.saveFailed');
    expect(result.current.saveStatus).toBe('failed');
  });

  it('omits plugins when active plugins match client defaults already saved as defaults', () => {
    usePluginStore.getState().open('legend');
    const state = makeSaveState();
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => {
      result.current.handleSave();
    });

    const [payload] = mockMutate.mock.calls[0];
    expect(payload.data.plugins).toBeUndefined();
  });

  it('sends plugins null when active plugins return to client defaults from explicit state', () => {
    usePluginStore.getState().open('legend');
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    queryClient.setQueryData(queryKeys.maps.detail('map-1'), { plugins: [] });
    const state = makeSaveState();
    const { result } = renderHookWithQueryClient(state, queryClient);

    act(() => {
      result.current.handleSave();
    });

    const [payload] = mockMutate.mock.calls[0];
    expect(payload.data.plugins).toBeNull();
  });

  it('persists explicit plugin state when it differs from client defaults', () => {
    usePluginStore.getState().open('legend');
    usePluginStore.getState().open('measurement');
    const state = makeSaveState();
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => {
      result.current.handleSave();
    });

    const [payload] = mockMutate.mock.calls[0];
    expect(payload.data.plugins).toEqual(['legend', 'measurement']);
  });

  it('does not persist admin-disabled active plugins', () => {
    mockEnabledPlugins.value = ['legend'];
    usePluginStore.getState().open('legend');
    usePluginStore.getState().open('measurement');
    const state = makeSaveState();
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => {
      result.current.handleSave();
    });

    const [payload] = mockMutate.mock.calls[0];
    expect(payload.data.plugins).toBeUndefined();
  });

  it('handleSave is a no-op when mapId is undefined', () => {
    const state = makeSaveState({ mapId: undefined });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => {
      result.current.handleSave();
    });

    expect(mockMutate).not.toHaveBeenCalled();
  });

  it('handleFork calls duplicateMutation.mutateAsync and navigates on success', async () => {
    mockDuplicateMapMutateAsync.mockResolvedValue({ id: 'new-map-1', excluded_layer_count: 0 });
    const state = makeSaveState();
    const { result } = renderHook(() => useBuilderSave(state));

    await act(async () => {
      await result.current.handleFork();
    });

    expect(mockDuplicateMapMutateAsync).toHaveBeenCalledWith('map-1');
    // toast.success should be called for successful fork
    const { toast } = await import('sonner');
    expect(toast.success).toHaveBeenCalled();
  });

  it('handleFork shows warning toast when excluded_layer_count > 0', async () => {
    mockDuplicateMapMutateAsync.mockResolvedValue({ id: 'new-map-2', excluded_layer_count: 3 });
    const state = makeSaveState();
    const { result } = renderHook(() => useBuilderSave(state));

    await act(async () => {
      await result.current.handleFork();
    });

    const { toast } = await import('sonner');
    expect(toast.warning).toHaveBeenCalled();
  });

  it('handleExportPNG captures immediately when map is loaded', () => {
    const mockMap = createMockMap({ loaded: true });
    const state = makeSaveState({ mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'] });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => {
      result.current.handleExportPNG();
    });

    // PERF-08 (Phase 274): export now registers `once('render', ...)` and
    // triggers a repaint instead of reading the canvas inline. Simulate the
    // render event firing so the canvas-read path runs.
    expect(mockMap.once).toHaveBeenCalledWith('render', expect.any(Function));
    expect(mockMap.triggerRepaint).toHaveBeenCalled();
    act(() => { fireRenderCallback(mockMap); });

    expect(mockMap.getCanvas).toHaveBeenCalled();
    expect(mockMap.once).not.toHaveBeenCalledWith('idle', expect.any(Function));
  });

  it('Ctrl+S keydown calls handleSave', () => {
    const state = makeSaveState();
    renderHook(() => useBuilderSave(state));

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 's', metaKey: true, bubbles: true }),
      );
    });

    expect(mockMutate).toHaveBeenCalledTimes(1);
  });

  describe('EASY-02: Cmd/Ctrl+S keyboard shortcut gating', () => {
    it('EASY-02 — no-op when a Radix dialog is open (role=dialog data-state=open)', () => {
      const dialog = document.createElement('div');
      dialog.setAttribute('role', 'dialog');
      dialog.setAttribute('data-state', 'open');
      document.body.appendChild(dialog);

      const state = makeSaveState();
      renderHook(() => useBuilderSave(state));

      act(() => {
        window.dispatchEvent(
          new KeyboardEvent('keydown', { key: 's', metaKey: true, bubbles: true }),
        );
      });

      expect(mockMutate).not.toHaveBeenCalled();

      document.body.removeChild(dialog);
    });

    it('EASY-02 — handleSave fires when no dialog is open', () => {
      const state = makeSaveState();
      renderHook(() => useBuilderSave(state));

      act(() => {
        window.dispatchEvent(
          new KeyboardEvent('keydown', { key: 's', ctrlKey: true, bubbles: true }),
        );
      });

      expect(mockMutate).toHaveBeenCalledTimes(1);
    });

    it('EASY-02 — preventDefault fires even when save is pending', () => {
      const preventDefaultSpy = vi.fn();
      const event = new KeyboardEvent('keydown', {
        key: 's',
        metaKey: true,
        bubbles: true,
        cancelable: true,
      });
      event.preventDefault = preventDefaultSpy;

      const state = makeSaveState();
      renderHook(() => useBuilderSave(state));

      act(() => { window.dispatchEvent(event); });

      expect(preventDefaultSpy).toHaveBeenCalledTimes(1);
    });

    it('EASY-02 — plain s without modifier does NOT trigger handleSave or preventDefault', () => {
      const preventDefaultSpy = vi.fn();
      const event = new KeyboardEvent('keydown', {
        key: 's',
        bubbles: true,
        cancelable: true,
      });
      event.preventDefault = preventDefaultSpy;

      const state = makeSaveState();
      renderHook(() => useBuilderSave(state));

      act(() => { window.dispatchEvent(event); });

      expect(mockMutate).not.toHaveBeenCalled();
      expect(preventDefaultSpy).not.toHaveBeenCalled();
    });

    it('EASY-02 — keydown listener is removed on hook unmount (negative-control)', () => {
      const state = makeSaveState();
      const { unmount } = renderHook(() => useBuilderSave(state));

      unmount();

      act(() => {
        window.dispatchEvent(
          new KeyboardEvent('keydown', { key: 's', metaKey: true, bubbles: true }),
        );
      });

      expect(mockMutate).not.toHaveBeenCalled();
    });
  });

  it('returns blocker from hook', () => {
    const state = makeSaveState();
    const { result } = renderHook(() => useBuilderSave(state));

    expect(result.current.blocker).toBeDefined();
    expect(result.current.blocker.state).toBe('unblocked');
  });

  it('adds beforeunload listener when hasUnsavedChanges is true', () => {
    const addSpy = vi.spyOn(window, 'addEventListener');
    const removeSpy = vi.spyOn(window, 'removeEventListener');

    const state = makeSaveState({ hasUnsavedChanges: true });
    const { unmount } = renderHook(() => useBuilderSave(state));

    expect(addSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function));

    unmount();

    expect(removeSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function));

    addSpy.mockRestore();
    removeSpy.mockRestore();
  });

  it('does not add beforeunload listener when hasUnsavedChanges is false', () => {
    const addSpy = vi.spyOn(window, 'addEventListener');

    const state = makeSaveState({ hasUnsavedChanges: false });
    renderHook(() => useBuilderSave(state));

    const beforeUnloadCalls = addSpy.mock.calls.filter(
      ([event]) => event === 'beforeunload',
    );
    expect(beforeUnloadCalls).toHaveLength(0);

    addSpy.mockRestore();
  });

  it('isSaving reflects updateMap.isPending state', () => {
    const state = makeSaveState();
    const { result } = renderHook(() => useBuilderSave(state));

    // Default mock returns isPending: false
    expect(result.current.isSaving).toBe(false);
  });

  describe('captureThumbnail (via handleSave onSuccess)', () => {
    const origCreateElement = document.createElement.bind(document);
    let createElementSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
      createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag === 'canvas') {
          return createMockCanvas() as unknown as HTMLCanvasElement;
        }
        return origCreateElement(tag, options);
      });
    });

    afterEach(() => {
      createElementSpy.mockRestore();
    });

    async function triggerSaveSuccess(mockMap: ReturnType<typeof createMockMap>) {
      const state = makeSaveState({ mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'] });
      const { result } = renderHook(() => useBuilderSave(state));
      await act(async () => { await result.current.handleSave(); });
      return result;
    }

    it('captures immediately when map is already loaded', async () => {
      // SP-16: captureThumbnail is now wrapped in a 500ms trailing
      // debounce; advance fake timers past the boundary to drive the
      // capture path that this test exercises.
      vi.useFakeTimers();
      const mockMap = createMockMap({ loaded: true });
      await triggerSaveSuccess(mockMap);

      // Before the debounce boundary, no capture has been requested.
      expect(mockMap.once).not.toHaveBeenCalledWith('render', expect.any(Function));

      act(() => { vi.advanceTimersByTime(500); });

      // PERF-08 (Phase 274): doCapture registers `once('render', ...)` then
      // calls triggerRepaint(); fire the render callback to simulate the
      // next animation frame.
      expect(mockMap.once).toHaveBeenCalledWith('render', expect.any(Function));
      expect(mockMap.triggerRepaint).toHaveBeenCalled();
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

      expect(mockMap.getCanvas).toHaveBeenCalled();
      expect(mockUploadThumbnail).toHaveBeenCalledWith('map-1', expect.stringContaining('data:image/jpeg'));
      expect(mockMap.once).not.toHaveBeenCalledWith('idle', expect.any(Function));

      vi.useRealTimers();
    });

    it('defers capture via idle event when map is not loaded', async () => {
      // SP-16: the 500ms debounce sits in front of whenMapIdle now;
      // advance past it to reach the idle-deferral path.
      vi.useFakeTimers();
      const mockMap = createMockMap({ loaded: false });
      await triggerSaveSuccess(mockMap);

      act(() => { vi.advanceTimersByTime(500); });

      expect(mockMap.once).toHaveBeenCalledWith('idle', expect.any(Function));
      // Not captured yet
      expect(mockUploadThumbnail).not.toHaveBeenCalled();

      // Simulate idle event — this registers `once('render', ...)` per PERF-08.
      const idleCallback = mockMap.once.mock.calls.find(
        (c: unknown[]) => c[0] === 'idle',
      )![1] as () => void;
      act(() => { idleCallback(); });

      // Idle alone is not enough now; render frame has to fire.
      expect(mockMap.once).toHaveBeenCalledWith('render', expect.any(Function));
      expect(mockMap.triggerRepaint).toHaveBeenCalled();

      // The uploadThumbnail microtask resolves on real timers.
      vi.useRealTimers();
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

      expect(mockUploadThumbnail).toHaveBeenCalledWith('map-1', expect.stringContaining('data:image/jpeg'));
    });

    it('timeout captures and removes idle listener when idle never fires', async () => {
      vi.useFakeTimers();
      const mockMap = createMockMap({ loaded: false });
      await triggerSaveSuccess(mockMap);

      // SP-16: clear the 500ms debounce first so the whenMapIdle safety
      // timer (which fires at +3000ms after the debounce flushes) becomes
      // observable.
      act(() => { vi.advanceTimersByTime(500); });
      expect(mockUploadThumbnail).not.toHaveBeenCalled();

      // Advance past 3s timeout — whenMapIdle's safety timer fires the
      // capture path, which now registers `once('render', ...)`.
      act(() => { vi.advanceTimersByTime(3000); });

      expect(mockMap.off).toHaveBeenCalledWith('idle', expect.any(Function));
      expect(mockMap.once).toHaveBeenCalledWith('render', expect.any(Function));
      expect(mockMap.triggerRepaint).toHaveBeenCalled();

      // Simulate the render frame (PERF-08).
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });
      expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);

      vi.useRealTimers();
    });

    it('SHARE-08: doCapture uploads both 1200x630 OG image and 400x250 thumbnail in one render event (triggerRepaint called once)', async () => {
      // TDD RED: this test should fail until uploadOgImage is wired into doCapture.
      vi.useFakeTimers();
      const mockMap = createMockMap({ loaded: true });
      await triggerSaveSuccess(mockMap);

      // Advance past 500ms debounce
      act(() => { vi.advanceTimersByTime(500); });

      // One render event registered; one repaint fired
      expect(mockMap.once).toHaveBeenCalledWith('render', expect.any(Function));
      expect(mockMap.triggerRepaint).toHaveBeenCalledTimes(1);

      // Fire the render callback — both uploads happen synchronously in the same onRender
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

      // Thumbnail upload unchanged
      expect(mockUploadThumbnail).toHaveBeenCalledOnce();
      expect(mockUploadThumbnail).toHaveBeenCalledWith('map-1', expect.stringContaining('data:image/jpeg'));

      // OG image upload: new requirement
      expect(mockUploadOgImage).toHaveBeenCalledOnce();
      expect(mockUploadOgImage).toHaveBeenCalledWith('map-1', expect.stringContaining('data:image/jpeg'));

      // triggerRepaint MUST NOT be called a second time (Pitfall #5: one repaint only)
      expect(mockMap.triggerRepaint).toHaveBeenCalledTimes(1);

      vi.useRealTimers();
    });

    it('backs thumbnail and OG crops with the globe space color (fix(#1479))', async () => {
      // The WebGL canvas is transparent where a ray missed the planet, so a
      // crop with nothing under it hands the encoder alpha and the sphere
      // lands on whatever it substitutes — white for PNG, black for JPEG.
      vi.useFakeTimers();
      const canvases: ReturnType<typeof createMockCanvas>[] = [];
      createElementSpy.mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag !== 'canvas') return origCreateElement(tag, options);
        const canvas = createMockCanvas();
        canvases.push(canvas);
        return canvas as unknown as HTMLCanvasElement;
      });

      const mockMap = createMockMap({ loaded: true, globeSpace: true });
      await triggerSaveSuccess(mockMap);
      act(() => { vi.advanceTimersByTime(500); });
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

      // Two crops: the 400x250 thumbnail and the 1200x630 OG image.
      const crops = canvases.filter((c) => c.fills.length > 0);
      expect(crops).toHaveLength(2);
      expect(crops.map((c) => c.fills[0])).toEqual([
        { style: MAP_COLORS.exportImage.globeBackground, rect: [0, 0, 400, 250] },
        { style: MAP_COLORS.exportImage.globeBackground, rect: [0, 0, 1200, 630] },
      ]);

      // Under the map, not over it.
      for (const crop of crops) {
        expect(crop.ctx.fillRect.mock.invocationCallOrder[0])
          .toBeLessThan(crop.ctx.drawImage.mock.invocationCallOrder[0]);
      }

      vi.useRealTimers();
    });

    it('leaves mercator crops unpainted (fix(#1479))', async () => {
      // A mercator map fills its own canvas edge to edge, so a backdrop would
      // be dead paint and any color drift behind it would be invisible.
      vi.useFakeTimers();
      const canvases: ReturnType<typeof createMockCanvas>[] = [];
      createElementSpy.mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag !== 'canvas') return origCreateElement(tag, options);
        const canvas = createMockCanvas();
        canvases.push(canvas);
        return canvas as unknown as HTMLCanvasElement;
      });

      const mockMap = createMockMap({ loaded: true });
      await triggerSaveSuccess(mockMap);
      act(() => { vi.advanceTimersByTime(500); });
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

      // feat(#1486): names the backdrop rather than counting fills — the
      // attribution scrim is also a fillRect, and it is drawn on every crop.
      expect(
        canvases.some((c) =>
          c.fills.some((f) => f.style === MAP_COLORS.exportImage.globeBackground),
        ),
      ).toBe(false);
      expect(canvases.some((c) => c.ctx.drawImage.mock.calls.length > 0)).toBe(true);

      vi.useRealTimers();
    });

    // feat(#1486): the crops composite from the WebGL canvas, so MapLibre's own
    // attribution control — a DOM overlay — is invisible to them by
    // construction. The credit reaches a distributed image only if it is drawn
    // INTO the canvas, which is what these two assert.
    it('draws the map credit into BOTH the thumbnail and the OG crop (#1486)', async () => {
      vi.useFakeTimers();
      const canvases: ReturnType<typeof createMockCanvas>[] = [];
      createElementSpy.mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag !== 'canvas') return origCreateElement(tag, options);
        const canvas = createMockCanvas();
        canvases.push(canvas);
        return canvas as unknown as HTMLCanvasElement;
      });

      const mockMap = createMockMap({ loaded: true });
      await triggerSaveSuccess(mockMap);
      act(() => { vi.advanceTimersByTime(500); });
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

      const credited = canvases.filter((c) =>
        c.ctx.fillText.mock.calls.some((call: unknown[]) => call[0] === MOCK_ATTRIBUTION),
      );
      expect(credited).toHaveLength(2);
      for (const crop of credited) {
        // Over the map, not under it: the reverse order would bury the credit.
        expect(crop.ctx.drawImage.mock.invocationCallOrder[0])
          .toBeLessThan(crop.ctx.fillText.mock.invocationCallOrder[0]);
        // A scrim behind it, so it stays legible over arbitrary tiles.
        expect(crop.fills.some((f) => f.style === MAP_COLORS.exportImage.attributionScrim))
          .toBe(true);
      }

      vi.useRealTimers();
    });

    // fix(#1541 codex P1): the sibling above uses a two-credit line that fits
    // whole, so it could never have caught `maxLines: 1`. This one drives the
    // same pipeline — crop, overlay, upload — with the five-credit load that
    // measurably lost two providers, and asserts at the crops rather than at
    // the fitter: the credit has to survive the path, not just the helper.
    it('carries every credit into BOTH crops when the set needs wrapping (#1541)', async () => {
      vi.useFakeTimers();
      const canvases: ReturnType<typeof createMockCanvas>[] = [];
      createElementSpy.mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag !== 'canvas') return origCreateElement(tag, options);
        const canvas = createMockCanvas();
        canvases.push(canvas);
        return canvas as unknown as HTMLCanvasElement;
      });

      const credits = [
        'MapLibre',
        '© OpenStreetMap contributors, climbing route geometry retrieved via the Overpass API, licensed under ODbL 1.0',
        '© U.S. Geological Survey Earthquake Hazards Program, ANSS Comprehensive Earthquake Catalog (ComCat), public domain',
        '© swisstopo swissALTI3D, 2m lidar digital elevation model, Federal Office of Topography, reproduced with authorisation',
        'OpenFreeMap © OpenMapTiles Data from OpenStreetMap',
      ];
      const mockMap = createMockMap({ loaded: true, attribution: credits.join(' | ') });
      await triggerSaveSuccess(mockMap);
      act(() => { vi.advanceTimersByTime(500); });
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

      const credited = canvases.filter((c) => c.ctx.fillText.mock.calls.length > 0);
      // The 400x250 thumbnail and the 1200x630 OG card.
      expect(credited).toHaveLength(2);
      expect(credited.map((c) => `${c.width}x${c.height}`)).toEqual(['400x250', '1200x630']);

      for (const crop of credited) {
        const drawn = crop.ctx.fillText.mock.calls.map((call: unknown[]) => String(call[0]));
        // It wrapped rather than fitting by luck, and lost nothing doing it.
        expect(drawn.length).toBeGreaterThan(1);
        const rendered = drawn.join(' ');
        for (const credit of credits) {
          expect(rendered, `missing credit on ${crop.width}x${crop.height}: ${credit}`).toContain(
            credit,
          );
        }
        expect(rendered).not.toContain('…');
        // The scrim was sized for every line, so none of them sits on bare map.
        const scrim = crop.fills.find((f) => f.style === MAP_COLORS.exportImage.attributionScrim)!;
        expect(scrim).toBeDefined();
        const spec = crop.width === 400 ? THUMBNAIL_ATTRIBUTION : OG_ATTRIBUTION;
        expect(scrim.rect[3]).toBe(drawn.length * spec.lineHeight + spec.paddingY * 2);
      }

      // Ate map pixels rather than dropping a provider, and the image itself is
      // unchanged: a fixed-size crop stays fixed-size.
      expect(mockUploadThumbnail).toHaveBeenCalled();

      vi.useRealTimers();
    });

    /* fix(#1541 codex P2 round 3): `BasemapEntry.attribution` permits HTML, so
     * a provider may credit itself with a logo. Its alt text is not DOM text,
     * so the old `textContent` read skipped the source entirely and all three
     * images shipped uncredited while the interactive map visibly showed the
     * credit. Asserted at the outputs, on all three at once: this is a
     * whole-pipeline property, and the reader is only where it broke. */
    it('carries an image-only credit into all three images (#1541)', async () => {
      vi.useFakeTimers();
      const canvases: ReturnType<typeof createMockCanvas>[] = [];
      createElementSpy.mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag !== 'canvas') return origCreateElement(tag, options);
        const canvas = createMockCanvas();
        canvases.push(canvas);
        return canvas as unknown as HTMLCanvasElement;
      });

      const mockMap = createMockMap({
        loaded: true,
        attribution: '<img src="https://tiles.example.com/logo.svg" alt="© Logo Provider">',
      });
      const result = await triggerSaveSuccess(mockMap);
      act(() => { vi.advanceTimersByTime(500); });
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

      // Same hook, same map: now the PNG export, whose render callback is the
      // second one registered (the crop capture consumed the first).
      act(() => { result.current.handleExportPNG(); });
      act(() => {
        const renders = mockMap.once.mock.calls.filter((c: unknown[]) => c[0] === 'render');
        (renders[renders.length - 1][1] as () => void)();
      });

      const credited = canvases.filter((c) =>
        c.ctx.fillText.mock.calls.some((call: unknown[]) =>
          String(call[0]).includes('© Logo Provider'),
        ),
      );
      // The 400x250 thumbnail, the 1200x630 OG card, and the PNG export.
      expect(credited).toHaveLength(3);
      const sizes = credited.map((c) => `${c.width}x${c.height}`);
      expect(sizes).toContain('400x250');
      expect(sizes).toContain('1200x630');
      // The export's own band, on the default named-and-described state:
      // 84 title + 600 map + 40 band (12 gap + 1 line + 12 gap) + 32 footer.
      expect(sizes).toContain('800x756');

      vi.useRealTimers();
    });

    it('draws no credit when the map exposes none (#1486)', async () => {
      vi.useFakeTimers();
      const canvases: ReturnType<typeof createMockCanvas>[] = [];
      createElementSpy.mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag !== 'canvas') return origCreateElement(tag, options);
        const canvas = createMockCanvas();
        canvases.push(canvas);
        return canvas as unknown as HTMLCanvasElement;
      });

      const mockMap = createMockMap({ loaded: true, attribution: null });
      await triggerSaveSuccess(mockMap);
      act(() => { vi.advanceTimersByTime(500); });
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

      // Still captured and uploaded — a missing credit never blocks a capture.
      expect(mockUploadThumbnail).toHaveBeenCalled();
      expect(canvases.some((c) => c.ctx.fillText.mock.calls.length > 0)).toBe(false);
      expect(
        canvases.some((c) =>
          c.fills.some((f) => f.style === MAP_COLORS.exportImage.attributionScrim),
        ),
      ).toBe(false);

      vi.useRealTimers();
    });

    it('idle event clears timeout to prevent double-capture', async () => {
      vi.useFakeTimers();
      const mockMap = createMockMap({ loaded: false });
      await triggerSaveSuccess(mockMap);

      // SP-16: advance past the 500ms trailing debounce so the
      // whenMapIdle path runs and registers the idle listener.
      act(() => { vi.advanceTimersByTime(500); });

      // Simulate idle event fires quickly — this registers the render
      // listener (PERF-08) but does not yet capture.
      const idleCallback = mockMap.once.mock.calls.find(
        (c: unknown[]) => c[0] === 'idle',
      )![1] as () => void;
      act(() => { idleCallback(); });

      // Fire the render frame to actually capture pixels.
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });
      expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);

      // Advance past timeout — should NOT double-capture
      act(() => { vi.advanceTimersByTime(3000); });

      expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);

      vi.useRealTimers();
    });
  });

  // SP-16: trailing 500ms debounce around the captureThumbnail entry point.
  // Two back-to-back saves (or save + maybeAutoCaptureThumbnail) within
  // 500ms must collapse into exactly one capture → one PUT /thumbnail/.
  describe('SP-16 — captureThumbnail trailing debounce', () => {
    const origCreateElement = document.createElement.bind(document);
    let createElementSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
      createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag === 'canvas') {
          return createMockCanvas() as unknown as HTMLCanvasElement;
        }
        return origCreateElement(tag, options);
      });
    });

    afterEach(() => {
      createElementSpy.mockRestore();
    });

    function renderCallbackCount(mockMap: ReturnType<typeof createMockMap>): number {
      return mockMap.once.mock.calls.filter((c: unknown[]) => c[0] === 'render').length;
    }

    it('coalesces two saves within 500ms into a single capture (one render-frame registration)', async () => {
      vi.useFakeTimers();
      const mockMap = createMockMap({ loaded: true });
      const state = makeSaveState({
        mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
      });
      const { result } = renderHook(() => useBuilderSave(state));

      // Two back-to-back saves 100ms apart. The second save resets the
      // debounce timer; the trailing edge fires 500ms after that LATEST
      // call, i.e. at t = 100 + 500 = 600ms. Before then no capture (and
      // therefore no `once('render')` registration) should occur.
      await act(async () => { await result.current.handleSave(); });
      act(() => { vi.advanceTimersByTime(100); });
      await act(async () => { await result.current.handleSave(); });

      expect(renderCallbackCount(mockMap)).toBe(0);
      expect(mockUploadThumbnail).not.toHaveBeenCalled();

      // Advance to just before the 500ms trailing boundary from the second save.
      act(() => { vi.advanceTimersByTime(499); });
      expect(renderCallbackCount(mockMap)).toBe(0);

      // Cross the boundary — exactly one capture fires for the final state,
      // not two: the first save's debounced capture was cancelled by the second.
      act(() => { vi.advanceTimersByTime(1); });
      expect(renderCallbackCount(mockMap)).toBe(1);

      // Fire the single registered render frame to drive the upload.
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });
      expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);

      vi.useRealTimers();
    });

    it('a single save still results in exactly one capture after the 500ms window', async () => {
      vi.useFakeTimers();
      const mockMap = createMockMap({ loaded: true });
      const state = makeSaveState({
        mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
      });
      const { result } = renderHook(() => useBuilderSave(state));

      await act(async () => { await result.current.handleSave(); });

      // No capture before the trailing edge.
      expect(renderCallbackCount(mockMap)).toBe(0);
      act(() => { vi.advanceTimersByTime(499); });
      expect(renderCallbackCount(mockMap)).toBe(0);

      // At/after 500ms one capture fires.
      act(() => { vi.advanceTimersByTime(1); });
      expect(renderCallbackCount(mockMap)).toBe(1);

      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });
      expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);

      vi.useRealTimers();
    });
  });

  describe('handleExportPNG (idle handling)', () => {
    // fix(#1479): the spy is installed and restored by the hooks rather than
    // inline, so a failing assertion cannot leave it in place — a leaked spy
    // becomes the next test's `origCreateElement` and recurses forever.
    const origCreateElement = document.createElement.bind(document);
    let createElementSpy: ReturnType<typeof vi.spyOn>;
    let canvases: ReturnType<typeof createMockCanvas>[] = [];

    beforeEach(() => {
      canvases = [];
      createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag !== 'canvas') return origCreateElement(tag, options);
        const canvas = createMockCanvas();
        canvases.push(canvas);
        return canvas as unknown as HTMLCanvasElement;
      });
    });

    afterEach(() => {
      createElementSpy.mockRestore();
    });

    it('defers export via idle event when map is not loaded', () => {
      const mockMap = createMockMap({ loaded: false });
      const state = makeSaveState({ mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'] });
      const { result } = renderHook(() => useBuilderSave(state));

      act(() => { result.current.handleExportPNG(); });

      expect(mockMap.once).toHaveBeenCalledWith('idle', expect.any(Function));
    });

    it('paints the space color under the map band only (fix(#1479))', () => {
      // The chrome bands keep the white fill: exportImage.text is #0a0a0a, so
      // darkening the whole sheet would take the title and legend with it.
      const mockMap = createMockMap({ loaded: true, globeSpace: true });
      const state = makeSaveState({
        mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
        localName: 'Globe',
        localDescription: '',
      });
      const { result } = renderHook(() => useBuilderSave(state));
      act(() => { result.current.handleExportPNG(); });
      act(() => { fireRenderCallback(mockMap); });

      const sheet = canvases.find((c) => c.fills.length > 0);
      expect(sheet).toBeDefined();
      const [chrome, mapBand] = sheet!.fills;

      // Whole sheet white first, then the map band alone in space color. The
      // source canvas is 800x600 and a title with no description adds 56px.
      expect(chrome.style).toBe(MAP_COLORS.exportImage.background);
      expect(mapBand).toEqual({
        style: MAP_COLORS.exportImage.globeBackground,
        rect: [0, 56, 800, 600],
      });
      expect(sheet!.ctx.drawImage).toHaveBeenCalledWith(expect.anything(), 0, 56);
      expect(sheet!.ctx.fillRect.mock.invocationCallOrder[1])
        .toBeLessThan(sheet!.ctx.drawImage.mock.invocationCallOrder[0]);
    });

    it('leaves a mercator export sheet white (fix(#1479))', () => {
      const mockMap = createMockMap({ loaded: true });
      const state = makeSaveState({
        mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
        localName: 'Flat',
      });
      const { result } = renderHook(() => useBuilderSave(state));
      act(() => { result.current.handleExportPNG(); });
      act(() => { fireRenderCallback(mockMap); });

      const sheet = canvases.find((c) => c.fills.length > 0);
      expect(sheet).toBeDefined();
      expect(sheet!.fills.map((f) => f.style)).not.toContain(
        MAP_COLORS.exportImage.globeBackground,
      );
    });
  });

  describe('maybeAutoCaptureThumbnail', () => {
    it('waits for visible layer sources before capturing a missing thumbnail', async () => {
      vi.useFakeTimers();
      const origCreateElement = document.createElement.bind(document);
      const createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag === 'canvas') {
          return createMockCanvas() as unknown as HTMLCanvasElement;
        }
        return origCreateElement(tag, options);
      });

      const sources = new Map<string, object>();
      const mockMap = createMockMap({ loaded: false });
      mockMap.getSource.mockImplementation((sourceId: string) => sources.get(sourceId));

      const state = makeSaveState({
        hasThumbnail: false,
        localLayers: [makeLayer()],
        mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
      });

      const { result } = renderHook(() => useBuilderSave(state));

      act(() => {
        result.current.maybeAutoCaptureThumbnail(mockMap as never);
      });

      expect(mockUploadThumbnail).not.toHaveBeenCalled();

      act(() => {
        vi.advanceTimersByTime(1000);
      });

      expect(mockUploadThumbnail).not.toHaveBeenCalled();
      expect(mockMap.once).not.toHaveBeenCalledWith('idle', expect.any(Function));

      act(() => {
        // CR-01 (Phase 1050-rev): waitForVisibleLayerSources now routes
        // through `getSourceIdForLayer`, so non-cluster vector layers with
        // a `dataset_table_name` resolve to the deduped
        // `source-data-${table}` key, not the legacy `source-${layer.id}`.
        sources.set('source-data-layer_1', { type: 'vector' });
        vi.advanceTimersByTime(100);
      });

      expect(mockMap.once).toHaveBeenCalledWith('idle', expect.any(Function));
      expect(mockUploadThumbnail).not.toHaveBeenCalled();

      const idleCallback = mockMap.once.mock.calls.find(
        (c: unknown[]) => c[0] === 'idle',
      )![1] as () => void;

      act(() => {
        idleCallback();
      });

      // PERF-08 (Phase 274): idle alone schedules the render listener; the
      // render frame must fire to actually upload pixels.
      expect(mockMap.once).toHaveBeenCalledWith('render', expect.any(Function));
      expect(mockMap.triggerRepaint).toHaveBeenCalled();

      // Use real timers briefly to let the uploadThumbnail microtask resolve.
      vi.useRealTimers();
      await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

      expect(mockUploadThumbnail).toHaveBeenCalledWith(
        'map-1',
        expect.stringContaining('data:image/jpeg'),
      );

      createElementSpy.mockRestore();
    });

    // SF-07 (Phase 1050-04): in Vite dev StrictMode (and any case where the
    // ref-callback in MapBuilderPage fires twice for the same `map`), the
    // per-hook-instance `thumbCaptured` guard resets on remount, letting a
    // second auto-capture slip through after the first's debounce window has
    // already fired and the PUT has been issued. The fix tracks per-mapId
    // auto-capture initiation at module scope so a second hook instance for
    // the same map is idempotent.
    describe('SF-07 — single PUT per initial map mount', () => {
      const origCreateElement = document.createElement.bind(document);
      let createElementSpy: ReturnType<typeof vi.spyOn>;

      beforeEach(() => {
        createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string, options?: ElementCreationOptions) => {
          if (tag === 'canvas') {
            return createMockCanvas() as unknown as HTMLCanvasElement;
          }
          return origCreateElement(tag, options);
        });
      });

      afterEach(() => {
        createElementSpy.mockRestore();
      });

      it('collapses two synchronous maybeAutoCaptureThumbnail calls into exactly one PUT', async () => {
        vi.useFakeTimers();
        const mockMap = createMockMap({ loaded: true });
        const state = makeSaveState({
          hasThumbnail: false,
          mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
        });

        const { result } = renderHook(() => useBuilderSave(state));

        act(() => {
          result.current.maybeAutoCaptureThumbnail(mockMap as never);
          result.current.maybeAutoCaptureThumbnail(mockMap as never);
        });

        act(() => { vi.advanceTimersByTime(500); });

        // Exactly one render-frame registration — the debounce collapses
        // both calls into one capture.
        const renderCalls = mockMap.once.mock.calls.filter((c: unknown[]) => c[0] === 'render');
        expect(renderCalls).toHaveLength(1);

        vi.useRealTimers();
        await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

        expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);
      });

      it('survives a StrictMode-style hook remount (second hook instance for the same mapId does NOT fire a second PUT)', async () => {
        vi.useFakeTimers();
        const mockMap = createMockMap({ loaded: true });
        const state1 = makeSaveState({
          hasThumbnail: false,
          mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
        });

        // First hook instance fires auto-capture
        const { result: result1, unmount: unmount1 } = renderHook(() => useBuilderSave(state1));
        act(() => { result1.current.maybeAutoCaptureThumbnail(mockMap as never); });

        // Let the first capture's debounce settle and issue its PUT before remount.
        act(() => { vi.advanceTimersByTime(500); });
        vi.useRealTimers();
        await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });
        expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);

        // Snapshot how many render-frame registrations have happened so we
        // can detect any extra ones from the second hook instance.
        const renderCallsAfterFirst = mockMap.once.mock.calls.filter(
          (c: unknown[]) => c[0] === 'render',
        ).length;

        // Simulate StrictMode unmount + remount of the hook (component-level
        // `thumbCaptured` ref resets), with a fresh second hook instance for
        // the SAME mapId being asked to auto-capture again.
        unmount1();
        const state2 = makeSaveState({
          hasThumbnail: false,
          mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
        });
        vi.useFakeTimers();
        const { result: result2 } = renderHook(() => useBuilderSave(state2));
        act(() => { result2.current.maybeAutoCaptureThumbnail(mockMap as never); });
        act(() => { vi.advanceTimersByTime(1000); });

        // Module-level guard must prevent a second capture for this mapId,
        // even though the new hook instance has a fresh thumbCaptured ref.
        // Verify via render-frame registrations (the deterministic signal
        // before the async fireRenderCallback step would otherwise lift the
        // PUT count).
        const renderCallsAfterSecond = mockMap.once.mock.calls.filter(
          (c: unknown[]) => c[0] === 'render',
        ).length;
        expect(renderCallsAfterSecond).toBe(renderCallsAfterFirst);

        vi.useRealTimers();
        await act(async () => { await Promise.resolve(); });
        expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);
      });

      it('reset helper clears the module-level guard so a fresh test (or page) can auto-capture again', async () => {
        vi.useFakeTimers();
        const mockMap = createMockMap({ loaded: true });
        const state = makeSaveState({
          hasThumbnail: false,
          mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
        });

        const { result } = renderHook(() => useBuilderSave(state));
        act(() => { result.current.maybeAutoCaptureThumbnail(mockMap as never); });
        act(() => { vi.advanceTimersByTime(500); });
        vi.useRealTimers();
        await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });
        expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);

        // After clearing the module-level guard, a fresh hook instance for
        // the same mapId may auto-capture again (mirrors the page-navigation
        // / new-session reload case where the in-memory module re-evaluates).
        __resetThumbnailDebounceForTests();

        vi.useFakeTimers();
        const { result: result2 } = renderHook(() => useBuilderSave(state));
        act(() => { result2.current.maybeAutoCaptureThumbnail(mockMap as never); });
        act(() => { vi.advanceTimersByTime(500); });
        vi.useRealTimers();
        await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

        expect(mockUploadThumbnail).toHaveBeenCalledTimes(2);
      });
    });

    // CR-01 (Phase 1050-rev): regression — verify that the source-readiness
    // poll resolves on the dedupe-aware key (`source-data-{dataset_table_name}`)
    // and the render frame fires WITHOUT advancing past the 5000 ms deadline.
    // Before the fix, `waitForVisibleLayerSources` polled `source-{layer.id}`
    // (legacy key) and never found the deduped source, causing every
    // non-cluster vector auto-capture to wait the full 5s timeout.
    it('CR-01: resolves source-readiness on the deduped source id before the 5s deadline', async () => {
      vi.useFakeTimers();
      const origCreateElement = document.createElement.bind(document);
      const createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag === 'canvas') {
          return createMockCanvas() as unknown as HTMLCanvasElement;
        }
        return origCreateElement(tag, options);
      });

      const sources = new Map<string, object>();
      const mockMap = createMockMap({ loaded: false });
      mockMap.getSource.mockImplementation((sourceId: string) => sources.get(sourceId));

      const state = makeSaveState({
        hasThumbnail: false,
        // dataset_table_name: 'shared_table' → dedupe key 'source-data-shared_table'
        localLayers: [makeLayer({ id: 'layer-99', dataset_table_name: 'shared_table' })],
        mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
      });

      const { result } = renderHook(() => useBuilderSave(state));

      act(() => {
        result.current.maybeAutoCaptureThumbnail(mockMap as never);
      });

      // Walk the trailing-edge debounce (500 ms) so `runCaptureNow` fires
      // and the source-readiness poll begins.
      act(() => { vi.advanceTimersByTime(500); });
      // No idle listener yet — source is not registered yet.
      expect(mockMap.once).not.toHaveBeenCalledWith('idle', expect.any(Function));

      // Seed the deduped source key (NOT the legacy `source-${id}` key) and
      // advance 100 ms — the next poll tick should resolve immediately.
      act(() => {
        sources.set('source-data-shared_table', { type: 'vector' });
        vi.advanceTimersByTime(100);
      });

      // poll has resolved → idle listener registered well before the 5s mark
      expect(mockMap.once).toHaveBeenCalledWith('idle', expect.any(Function));

      // Sanity: legacy key was NEVER queried after fix
      const legacyKeyQueried = mockMap.getSource.mock.calls.some(
        (c: unknown[]) => c[0] === 'source-layer-99',
      );
      expect(legacyKeyQueried).toBe(false);

      createElementSpy.mockRestore();
      vi.useRealTimers();
    });

    // POLISH-01 regression: new-map created via AddToMapButton has localLayers=[]
    // when maybeAutoCaptureThumbnail fires (the ?add_dataset effect adds the layer
    // later). Without pendingLayerAdd:true the current code takes the empty-layers
    // idle path and locks in a blank thumbnail. With the fix the first capture is
    // deferred until localLayersRef.current becomes non-empty.
    describe('POLISH-01 — deferred first-capture on new-map + ?add_dataset path', () => {
      const origCreateElement = document.createElement.bind(document);
      let createElementSpy: ReturnType<typeof vi.spyOn>;

      beforeEach(() => {
        createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string, options?: ElementCreationOptions) => {
          if (tag === 'canvas') {
            return createMockCanvas() as unknown as HTMLCanvasElement;
          }
          return origCreateElement(tag, options);
        });
      });

      afterEach(() => {
        createElementSpy.mockRestore();
        vi.useRealTimers();
      });

      it('defers capture when pendingLayerAdd is true and localLayers is empty; fires exactly once after layer arrives', async () => {
        vi.useFakeTimers();

        const sources = new Map<string, object>();
        const mockMap = createMockMap({ loaded: true });
        mockMap.getSource.mockImplementation((sourceId: string) => sources.get(sourceId));

        // Initial state: no layers yet (new-map path), pending layer add in flight
        let state = makeSaveState({
          hasThumbnail: false,
          localLayers: [],
          pendingLayerAdd: true,
          mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
        });

        const { result, rerender } = renderHook(() => useBuilderSave(state));

        // Trigger auto-capture with empty layers
        act(() => {
          result.current.maybeAutoCaptureThumbnail(mockMap as never);
        });

        // Advance past 500ms debounce — capture should be deferred, not fire
        act(() => { vi.advanceTimersByTime(500); });

        // Assert 1: no render-frame or upload yet — the fix defers until layers arrive
        const renderCallsAfterDebounce = mockMap.once.mock.calls.filter(
          (c: unknown[]) => c[0] === 'render',
        );
        expect(renderCallsAfterDebounce).toHaveLength(0);
        expect(mockUploadThumbnail).not.toHaveBeenCalled();

        // Simulate the ?add_dataset effect: layer arrives in localLayers
        state = makeSaveState({
          hasThumbnail: false,
          localLayers: [makeLayer()],
          pendingLayerAdd: true,
          mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
        });
        rerender();

        // Make the map source available for this layer
        // (source-data-layer_1 matches dataset_table_name='layer_1')
        act(() => {
          sources.set('source-data-layer_1', { type: 'vector' });
          // Advance one poll tick (100ms) — the deferred poll sees layers
          vi.advanceTimersByTime(100);
        });

        // waitForVisibleLayerSources has now resolved.
        // With loaded:true, whenMapIdle calls fn() directly (no idle event),
        // so doCapture fires immediately → render listener is registered.
        expect(mockMap.once).toHaveBeenCalledWith('render', expect.any(Function));
        expect(mockMap.triggerRepaint).toHaveBeenCalled();
        expect(mockUploadThumbnail).not.toHaveBeenCalled();

        vi.useRealTimers();
        await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });

        // Assert 2: exactly one upload fired (for the real layer, not the empty frame)
        expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);
        expect(mockUploadThumbnail).toHaveBeenCalledWith(
          'map-1',
          expect.stringContaining('data:image/jpeg'),
        );
      });

      it('negative control — genuinely empty map (pendingLayerAdd absent) still resolves via idle path', async () => {
        vi.useFakeTimers();

        const mockMap = createMockMap({ loaded: true });

        // No pendingLayerAdd: existing SF-05 behavior (idle path fires for empty map)
        const state = makeSaveState({
          hasThumbnail: false,
          localLayers: [],
          // pendingLayerAdd intentionally omitted
          mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
        });

        const { result } = renderHook(() => useBuilderSave(state));

        act(() => {
          result.current.maybeAutoCaptureThumbnail(mockMap as never);
        });

        // Advance past debounce — the existing idle path should proceed as before
        act(() => { vi.advanceTimersByTime(500); });

        // SF-05: whenMapIdle fires immediately (loaded:true) → doCapture registers
        // render listener; the idle-path branch is NOT deferred/blocked
        const renderCalls = mockMap.once.mock.calls.filter(
          (c: unknown[]) => c[0] === 'render',
        );
        expect(renderCalls).toHaveLength(1);

        vi.useRealTimers();
        await act(async () => { fireRenderCallback(mockMap); await Promise.resolve(); });
        expect(mockUploadThumbnail).toHaveBeenCalledTimes(1);
      });
    });
  });
});

/* ── SHARE-09: export PNG composition regression pins ── */

describe('SHARE-09 export PNG composition', () => {
  let fillTextSpy: ReturnType<typeof vi.fn>;
  let fillRectSpy: ReturnType<typeof vi.fn>;
  let strokeStyleAtStroke: string[];
  let createGradientSpy: ReturnType<typeof vi.fn>;
  let addColorStopSpy: ReturnType<typeof vi.fn>;
  let toBlobSpy: ReturnType<typeof vi.fn>;
  /** What the toBlob stub actually handed back — null for a canvas past the
   *  engine limits, exactly as a browser would. */
  let encodedBlobs: (Blob | null)[];
  let createElementSpy: ReturnType<typeof vi.spyOn>;
  // feat(#1486): hoisted so a test can read the height the export reserved.
  let offscreenCanvas: {
    width: number;
    height: number;
    getContext: ReturnType<typeof vi.fn>;
    toBlob: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
    __resetThumbnailDebounceForTests();
    mockEdition.isEnterprise = false;

    fillTextSpy = vi.fn();
    fillRectSpy = vi.fn();
    strokeStyleAtStroke = [];
    // Mimic the browser: CanvasGradient.addColorStop throws on an unparseable color.
    addColorStopSpy = vi.fn((_offset: number, color: unknown) => {
      if (typeof color !== 'string' || color === '') throw new SyntaxError('unparseable color');
    });
    createGradientSpy = vi.fn(() => ({ addColorStop: addColorStopSpy }));
    // fix(#1541 codex P2 round 2): mimic the browser. A canvas past an engine's
    // per-side or total-area limit is unusable with nothing raised to say so —
    // toBlob simply yields null and the export fails. A stub that always hands
    // back a blob lets a test assert a successful export from a canvas no
    // browser would encode, which is exactly how the unbounded band passed here.
    encodedBlobs = [];
    toBlobSpy = vi.fn((cb: (b: Blob | null) => void) => {
      const { width, height } = offscreenCanvas;
      const encodable =
        width <= EXPORT_CANVAS_MAX_DIMENSION &&
        height <= EXPORT_CANVAS_MAX_DIMENSION &&
        width * height <= EXPORT_CANVAS_MAX_AREA;
      const blob = encodable ? new Blob(['png'], { type: 'image/png' }) : null;
      encodedBlobs.push(blob);
      cb(blob);
    });

    const ctx2d = {
      fillStyle: '' as string | CanvasGradient,
      strokeStyle: '',
      font: '',
      textBaseline: '',
      lineWidth: 1,
      fillText: fillTextSpy,
      fillRect: fillRectSpy,
      // Record the border color used for each swatch (stroke-color border).
      strokeRect: vi.fn(() => { strokeStyleAtStroke.push(ctx2d.strokeStyle); }),
      createLinearGradient: createGradientSpy,
      drawImage: vi.fn(),
      // fix(#1541 codex P1): length-proportional, not a constant 120. A
      // constant makes every string "fit" on one line, so it cannot exercise
      // the band's line growth — which is precisely how the two-line cap that
      // dropped credits went unnoticed here.
      measureText: vi.fn((text: string) => ({ width: text.length * 6 })),
    };

    offscreenCanvas = {
      width: 800,
      height: 600,
      getContext: vi.fn(() => ctx2d),
      toBlob: toBlobSpy,
    };

    const origCreateElement = document.createElement.bind(document);
    createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string, options?: ElementCreationOptions) => {
      if (tag === 'canvas') {
        return offscreenCanvas as unknown as HTMLCanvasElement;
      }
      return origCreateElement(tag, options);
    });
  });

  afterEach(() => {
    createElementSpy.mockRestore();
    mockEdition.isEnterprise = false;
  });

  function makeExportMap() {
    return createMockMap({ loaded: true });
  }

  it('renders title and description in the title block when localName is non-empty', () => {
    const mockMap = makeExportMap();
    const state = makeSaveState({
      localName: 'My Map',
      localDescription: 'Test desc',
      localLayers: [],
      mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => { result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(mockMap); });

    const calls = fillTextSpy.mock.calls.map((c: unknown[]) => c[0]);
    expect(calls.some((text: unknown) => text === 'My Map')).toBe(true);
    expect(calls.some((text: unknown) => text === 'Test desc')).toBe(true);
  });

  it('renders legend header and one row per visible legend layer', () => {
    const mockMap = makeExportMap();
    const streetsLayer = makeLayer({
      id: 'layer-streets',
      display_name: 'Streets',
      visible: true,
      show_in_legend: true,
    });
    const hiddenLayer = makeLayer({
      id: 'layer-hidden',
      display_name: 'Hidden',
      visible: true,
      show_in_legend: false,
    });
    const invisibleLayer = makeLayer({
      id: 'layer-invisible',
      display_name: 'Invisible',
      visible: false,
      show_in_legend: true,
    });
    const state = makeSaveState({
      localName: '',
      localDescription: '',
      localLayers: [streetsLayer, hiddenLayer, invisibleLayer],
      mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => { result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(mockMap); });

    const calls = fillTextSpy.mock.calls.map((c: unknown[]) => c[0] as string);
    // Legend header text (i18n key returns the key itself in test setup)
    expect(calls.some((text) => /legend/i.test(text))).toBe(true);
    // Streets layer row
    expect(calls.some((text) => text === 'Streets')).toBe(true);
    // Color swatch fill rect for the qualifying layer
    expect(fillRectSpy).toHaveBeenCalled();
  });

  // fix(#769): the synthetic group:folder row is built by spreading the group's
  // first child, so it inherits visible/show_in_legend — the export filter must
  // exclude it or the PNG ships a phantom legend row labeled with the group name.
  it('excludes folder-group rows from the exported legend (#769)', () => {
    const mockMap = makeExportMap();
    const streetsLayer = makeLayer({
      id: 'layer-streets',
      display_name: 'Streets',
      visible: true,
      show_in_legend: true,
    });
    const groupRow = {
      ...makeLayer({
        id: 'group-1',
        display_name: 'Transit group',
        visible: true,
        show_in_legend: true,
      }),
      layer_type: 'group:folder',
    } as unknown as MapLayerResponse;
    const state = makeSaveState({
      localName: '',
      localDescription: '',
      localLayers: [groupRow, streetsLayer],
      mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => { result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(mockMap); });

    const calls = fillTextSpy.mock.calls.map((c: unknown[]) => c[0] as string);
    expect(calls.some((text) => text === 'Streets')).toBe(true);
    expect(calls.some((text) => text === 'Transit group')).toBe(false);
  });

  it('swatch border uses the layer stroke color for hollow-circle styles', () => {
    const mockMap = makeExportMap();
    // Light fill + colored stroke (hollow circle). The old export drew the near-white
    // fill with a faint 0.15 border, so the swatch was effectively invisible.
    const hollow = makeLayer({
      id: 'layer-eruptions',
      display_name: 'Eruptions',
      dataset_geometry_type: 'MULTIPOINT',
      paint: { 'circle-color': '#fff7ed', 'circle-stroke-color': '#ea580c' },
      visible: true,
      show_in_legend: true,
    });
    const state = makeSaveState({
      localName: '',
      localDescription: '',
      localLayers: [hollow],
      mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => { result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(mockMap); });

    // The swatch border is the visible stroke color, not the transparent fallback.
    expect(strokeStyleAtStroke).toContain('#ea580c');
  });

  it('does not draw the stroke-color border when the stroke is disabled', () => {
    const mockMap = makeExportMap();
    // Stroke turned off in the builder leaves a stale circle-stroke-color in paint;
    // the export must not reintroduce it as a border (mirrors the map, which hides it).
    const disabled = makeLayer({
      id: 'layer-eruptions-off',
      display_name: 'Eruptions (no ring)',
      dataset_geometry_type: 'MULTIPOINT',
      paint: { 'circle-color': '#fff7ed', 'circle-stroke-color': '#ea580c', 'circle-stroke-width': 0 },
      style_config: { builder: { strokeDisabled: true } } as MapLayerResponse['style_config'],
      visible: true,
      show_in_legend: true,
    });
    const state = makeSaveState({
      localName: '',
      localDescription: '',
      localLayers: [disabled],
      mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => { result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(mockMap); });

    expect(strokeStyleAtStroke).not.toContain('#ea580c');
    expect(strokeStyleAtStroke).toContain('rgba(0,0,0,0.35)');
  });

  it('draws a gradient swatch for a multi-stop ramp layer', () => {
    const mockMap = makeExportMap();
    // Empty paint + style_config.colors makes getLayerColors return the ramp array.
    const graduated = makeLayer({
      id: 'layer-graduated',
      display_name: 'Graduated',
      paint: {},
      style_config: { colors: ['#111111', '#999999'] } as MapLayerResponse['style_config'],
      visible: true,
      show_in_legend: true,
    });
    const state = makeSaveState({
      localName: '',
      localDescription: '',
      localLayers: [graduated],
      mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => { result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(mockMap); });

    expect(createGradientSpy).toHaveBeenCalled();
    const stops = addColorStopSpy.mock.calls.map((c: unknown[]) => c[1]);
    expect(stops).toEqual(['#111111', '#999999']);
  });

  it('an unparseable ramp color falls back to solid instead of aborting the export', () => {
    const mockMap = makeExportMap();
    // The empty-string second stop makes the mocked addColorStop throw (as the browser
    // would). The export must still complete rather than failing entirely.
    const badRamp = makeLayer({
      id: 'layer-bad-ramp',
      display_name: 'Bad ramp',
      paint: {},
      style_config: { colors: ['#111111', ''] } as MapLayerResponse['style_config'],
      visible: true,
      show_in_legend: true,
    });
    const state = makeSaveState({
      localName: '',
      localDescription: '',
      localLayers: [badRamp],
      mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => { result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(mockMap); });

    // Gradient was attempted (and threw) ...
    expect(createGradientSpy).toHaveBeenCalled();
    // ... but the export ran to completion: the footer drew and the canvas serialized.
    const texts = fillTextSpy.mock.calls.map((c: unknown[]) => String(c[0]));
    expect(texts.some((t) => /poweredBy|Powered by GeoLens/.test(t))).toBe(true);
    expect(toBlobSpy).toHaveBeenCalled();
  });

  it('renders Powered by GeoLens footer when isEnterprise is false', () => {
    mockEdition.isEnterprise = false;
    const mockMap = makeExportMap();
    const state = makeSaveState({
      localName: '',
      localDescription: '',
      localLayers: [],
      mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => { result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(mockMap); });

    // i18n mock returns key as-is; use-builder-save calls t('export.poweredBy', { defaultValue: ... })
    const calls = fillTextSpy.mock.calls.map((c: unknown[]) => c[0] as string);
    expect(calls.some((text) => /export\.poweredBy|Powered by GeoLens/.test(text))).toBe(true);
  });

  it('suppresses Powered by GeoLens footer when isEnterprise is true', () => {
    mockEdition.isEnterprise = true;
    const mockMap = makeExportMap();
    const state = makeSaveState({
      localName: '',
      localDescription: '',
      localLayers: [],
      mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => { result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(mockMap); });

    // Neither the key form nor the human-readable form should appear
    expect(fillTextSpy).not.toHaveBeenCalledWith(
      expect.stringMatching(/export\.poweredBy|Powered by GeoLens/),
      expect.anything(),
      expect.anything(),
    );
  });

  /* feat(#1486): the exported PNG carries the map's credit line. */

  it('draws the map credit in its own band (#1486)', () => {
    const mockMap = makeExportMap();
    const state = makeSaveState({
      localName: '',
      localDescription: '',
      localLayers: [],
      mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => { result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(mockMap); });

    expect(fillTextSpy).toHaveBeenCalledWith(
      MOCK_ATTRIBUTION,
      expect.any(Number),
      expect.any(Number),
    );
    // Its own band on the white chrome, not a scrim over the map: the credit
    // is drawn below the map region (the canvas is 600px of map plus chrome).
    const call = fillTextSpy.mock.calls.find((c: unknown[]) => c[0] === MOCK_ATTRIBUTION)!;
    expect(call[2] as number).toBeGreaterThanOrEqual(600);
  });

  // The whole point of a separate band. "Powered by GeoLens" is promotion an
  // enterprise licence may suppress; a basemap or dataset credit is a
  // licensing obligation and must survive the same toggle.
  it('still draws the map credit when branding is suppressed (#1486)', () => {
    mockEdition.isEnterprise = true;
    const mockMap = makeExportMap();
    const state = makeSaveState({
      localName: '',
      localDescription: '',
      localLayers: [],
      mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => { result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(mockMap); });

    const texts = fillTextSpy.mock.calls.map((c: unknown[]) => String(c[0]));
    expect(texts).toContain(MOCK_ATTRIBUTION);
    expect(texts.some((t) => /export\.poweredBy|Powered by GeoLens/.test(t))).toBe(false);
  });

  // fix(#1541 codex P1): five real credits on a 1056px export used to lose two
  // of them, the basemap's included, because the band was capped at two lines.
  // The canvas has no height constraint, so it grows instead.
  it('exports every credit for a credit-heavy map, growing the band (#1541)', () => {
    const credits = [
      'MapLibre',
      '© OpenStreetMap contributors, climbing route geometry retrieved via the Overpass API, licensed under ODbL 1.0',
      '© U.S. Geological Survey Earthquake Hazards Program, ANSS Comprehensive Earthquake Catalog (ComCat), public domain',
      '© swisstopo swissALTI3D, 2m lidar digital elevation model, Federal Office of Topography, reproduced with authorisation',
      'OpenFreeMap © OpenMapTiles Data from OpenStreetMap',
    ];
    const mockMap = createMockMap({ loaded: true, attribution: credits.join(' | ') });
    const state = makeSaveState({
      localName: '',
      localDescription: '',
      localLayers: [],
      mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => { result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(mockMap); });

    const drawn = fillTextSpy.mock.calls.map((c: unknown[]) => String(c[0])).join(' ');
    for (const credit of credits) {
      expect(drawn, `missing credit: ${credit}`).toContain(credit);
    }
    expect(drawn).not.toContain('…');
    // The band grew past the old two-line ceiling, and the canvas with it.
    expect(offscreenCanvas.height).toBeGreaterThan(600 + 12 + 2 * 16 + 12 + 32);
  });

  /* fix(#1541 codex P2 round 2): the band's measured height is assigned
   * straight to the export canvas, and #1541 review had ruled that growth
   * unlimited because the canvas is sized after the band is measured. Browsers
   * cap a canvas per side and by total area; past either one `toBlob` returns
   * null and NO image is produced. The API permits 200 layers and 5,000
   * characters of `attribution` each, so the contract's own maximum reached it
   * — which made the unlimited ruling a total-export-failure bug rather than
   * the partial-credit one it was avoiding. */

  /** 5,000 characters — the schema maximum — of ordinary short words, so
   *  wrapping breaks on spaces and the credit can be found again in the joined
   *  output. Distinct per index, so the dedupe keeps all 200. */
  function maxedCredit(i: number): string {
    return `© Provider ${i} ${'licensing statement for the exported map image '.repeat(120)}`
      .slice(0, 5000)
      .trimEnd()
      .padEnd(5000, 'x');
  }

  it('keeps the export canvas encodable at 200 credits x 5,000 characters (#1541)', async () => {
    const { toast } = await import('sonner');
    const credits = Array.from({ length: 200 }, (_, i) => maxedCredit(i));
    for (const c of credits) expect(c).toHaveLength(5000);

    const mockMap = createMockMap({ loaded: true, attribution: credits.join(' | ') });
    const state = makeSaveState({
      localName: '',
      localDescription: '',
      // The other half of the contract maximum: 200 layers, each a legend row.
      localLayers: Array.from({ length: 200 }, (_, i) =>
        makeLayer({ id: `layer-${i}`, dataset_name: `Layer ${i}` }),
      ),
      mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => { result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(mockMap); });

    // A canvas a browser will still hand back a blob for, on both limits.
    expect(offscreenCanvas.height).toBeLessThanOrEqual(EXPORT_CANVAS_MAX_DIMENSION);
    expect(offscreenCanvas.width).toBeLessThanOrEqual(EXPORT_CANVAS_MAX_DIMENSION);
    expect(offscreenCanvas.width * offscreenCanvas.height).toBeLessThanOrEqual(
      EXPORT_CANVAS_MAX_AREA,
    );

    // And it did: a real blob, and the success toast rather than the failure one.
    expect(encodedBlobs).toEqual([expect.any(Blob)]);
    expect(toast.success).toHaveBeenCalledWith('toasts.exportSuccess');
    expect(toast.error).not.toHaveBeenCalled();

    // Rendered whole + marked == input. Nothing falls between the two, and
    // both terms are non-zero, so neither side of the sum is carrying it alone.
    const drawn = fillTextSpy.mock.calls.map((c: unknown[]) => String(c[0]));
    const joined = drawn.join(' ');
    const rendered = credits.filter((c) => joined.includes(c)).length;
    const markerLine = drawn.find((text) => /\+\d+ more credit/.test(text));
    const marked = markerLine ? Number(/\+(\d+)/.exec(markerLine)![1]) : 0;
    expect(rendered).toBeGreaterThan(0);
    expect(marked).toBeGreaterThan(0);
    expect(rendered + marked).toBe(credits.length);
    expect(joined).not.toContain('…');
  });

  /* fix(#1541 codex P2 round 4): the budget used to be a DESKTOP figure while
   * the comment above it named iOS Safari's smaller one. codex's case, and the
   * numbers here are iOS Safari's measured ceiling written out rather than read
   * from the constant — the whole point is that the bound holds on the smallest
   * engine, so a test that reads the constant would relax with it. */
  it('keeps an iPad-sized export inside iOS Safari\'s ceiling (#1541)', async () => {
    const { toast } = await import('sonner');
    const IOS_MAX_AREA = 4096 * 4096; // 16,777,216
    const IOS_CEILING_AT_2048 = IOS_MAX_AREA / 2048; // 8,192px tall

    const credits = Array.from({ length: 200 }, (_, i) => maxedCredit(i));
    const mockMap = createMockMap({ loaded: true, attribution: credits.join(' | ') });
    // A valid iPad canvas, which exports fine today.
    const iPadCanvas = createMockCanvas();
    iPadCanvas.width = 2048;
    iPadCanvas.height = 2732;
    mockMap.getCanvas = vi.fn(() => iPadCanvas);

    const state = makeSaveState({
      localName: '',
      localDescription: '',
      localLayers: [],
      mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => { result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(mockMap); });

    expect(offscreenCanvas.width).toBe(2048);
    expect(offscreenCanvas.height).toBeLessThanOrEqual(IOS_CEILING_AT_2048);
    expect(offscreenCanvas.width * offscreenCanvas.height).toBeLessThanOrEqual(IOS_MAX_AREA);
    expect(encodedBlobs).toEqual([expect.any(Blob)]);
    expect(toast.error).not.toHaveBeenCalled();

    // Still crediting: what fits, plus a marker for the rest.
    const drawn = fillTextSpy.mock.calls.map((c: unknown[]) => String(c[0]));
    const joined = drawn.join(' ');
    const rendered = credits.filter((c) => joined.includes(c)).length;
    const markerLine = drawn.find((text) => /\+\d+ more credit/.test(text));
    expect(rendered).toBeGreaterThan(0);
    expect(markerLine).toBeDefined();
    expect(rendered + Number(/\+(\d+)/.exec(markerLine!)![1])).toBe(credits.length);
  });

  it('leaves an ordinary multi-credit export growing and complete (#1541)', () => {
    // 40 credits: many lines, and still three orders of magnitude below the cap.
    const credits = Array.from(
      { length: 40 },
      (_, i) => `© Data Provider ${i}, a licensing statement of some reasonable length`,
    );
    const mockMap = createMockMap({ loaded: true, attribution: credits.join(' | ') });
    const state = makeSaveState({
      localName: '',
      localDescription: '',
      localLayers: [],
      mapInstanceRef: { current: mockMap } as unknown as SaveState['mapInstanceRef'],
    });
    const { result } = renderHook(() => useBuilderSave(state));

    act(() => { result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(mockMap); });

    const drawn = fillTextSpy.mock.calls.map((c: unknown[]) => String(c[0]));
    const joined = drawn.join(' ');
    for (const credit of credits) {
      expect(joined, `missing credit: ${credit}`).toContain(credit);
    }
    // No marker at all: the cap must not start truncating a normal export.
    expect(joined).not.toMatch(/more credit/);
    // The band still grew a line at a time, and the canvas with it.
    expect(offscreenCanvas.height).toBeGreaterThan(600 + 12 + 5 * 16 + 12 + 32);
    expect(offscreenCanvas.height).toBeLessThanOrEqual(EXPORT_CANVAS_MAX_DIMENSION);
  });

  it('reserves canvas height for the credit band, and none when there is no credit (#1486)', () => {
    const withCredit = makeExportMap();
    const state = makeSaveState({
      localName: '',
      localDescription: '',
      localLayers: [],
      mapInstanceRef: { current: withCredit } as unknown as SaveState['mapInstanceRef'],
    });
    const { result } = renderHook(() => useBuilderSave(state));
    act(() => { result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(withCredit); });
    const creditedHeight = offscreenCanvas.height;

    const bare = createMockMap({ loaded: true, attribution: null });
    const bareState = makeSaveState({
      localName: '',
      localDescription: '',
      localLayers: [],
      mapInstanceRef: { current: bare } as unknown as SaveState['mapInstanceRef'],
    });
    const bareHook = renderHook(() => useBuilderSave(bareState));
    act(() => { bareHook.result.current.handleExportPNG(); });
    act(() => { fireRenderCallback(bare); });

    // 12 gap + 16 line + 12 gap at dpr 1.
    expect(creditedHeight - offscreenCanvas.height).toBe(40);
  });
});
