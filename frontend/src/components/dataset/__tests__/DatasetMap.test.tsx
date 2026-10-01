import type { StyleSpecification } from 'maplibre-gl';
import { toast } from 'sonner';
import { render, screen, fireEvent, act, within } from '@/test/test-utils';
import type { BasemapEntry } from '@/api/settings';
import { DatasetMap } from '@/components/dataset/DatasetMap';
import { previewSourceId } from '@/components/maps/hooks/use-map-layers';
import { BLANK_BASEMAP_ID } from '@/lib/basemap-utils';

// fix(#1004): what the map was actually told to draw and where to point. The
// three camera/extent sites derive from the bbox prop alone, so recording the
// props MapGL and Source receive is enough to pin all three.
const mapSpy = vi.hoisted(() => ({
  initialViewState: null as Record<string, unknown> | null,
  sourceData: null as { features: { geometry: { coordinates: number[][][][] } }[] } | null,
  bboxSourceAttribution: undefined as string | undefined,
  fitBounds: vi.fn(),
  flyTo: vi.fn(),
  // Opt-in: driving onLoad instantiates the whole tile/recovery wiring, which
  // the other blocks in this file neither need nor mock.
  attachMapInstance: false,
  reset() {
    this.initialViewState = null;
    this.sourceData = null;
    this.bboxSourceAttribution = undefined;
    this.fitBounds.mockReset();
    this.flyTo.mockReset();
    this.attachMapInstance = false;
  },
}));

// Any method DatasetMap's onLoad reaches for resolves to a no-op; only the
// camera calls are asserted.
const fakeMap = vi.hoisted(
  () =>
    new Proxy({} as Record<string, unknown>, {
      get(target, prop: string) {
        if (prop === 'fitBounds' || prop === 'flyTo') return mapSpy[prop];
        if (!(prop in target)) target[prop] = vi.fn();
        return target[prop];
      },
    }),
);

const drawingState = vi.hoisted(() => ({
  isDrawing: false,
  activeMode: null as string | null,
  // null means "no target adopted" and is treated as a match (see
  // DatasetMap.tsx's targetsDataset) — most fixtures below never call the
  // real setDrawing, so this must default to null, not a stale dataset id.
  targetDatasetId: null as string | null,
  setDrawing: vi.fn(),
  setMode: vi.fn(),
  clearDrawing: vi.fn(),
  selectedFeature: null as { gid: number; tdId: string; properties: Record<string, unknown> } | null,
  setSelectedFeature: vi.fn(),
  clearSelectedFeature: vi.fn(),
  setEditDirty: vi.fn(),
  setHasUnsavedMapWork: vi.fn(),
  isEditDirty: false,
  // fix(#1761 review round 3 P1): identity-change session counter. Real
  // usage never resets this to 0 mid-life, so tests that bump it use a high
  // starting value to avoid colliding with any other test's leftover state.
  sessionEpoch: 0,
}));

vi.mock('@vis.gl/react-maplibre', async () => {
  const { useEffect } = await import('react');
  return {
    Map: ({
      children,
      interactive,
      initialViewState,
      onLoad,
    }: {
      children?: React.ReactNode;
      interactive?: boolean;
      initialViewState?: Record<string, unknown>;
      onLoad?: (e: { target: unknown }) => void;
    }) => {
      mapSpy.initialViewState = initialViewState ?? null;
      useEffect(() => {
        if (mapSpy.attachMapInstance) onLoad?.({ target: fakeMap });
      }, [onLoad]);
      return (
        <div data-testid="mapgl" data-interactive={String(interactive)}>
          {children}
        </div>
      );
    },
    Source: ({ id, children, data, attribution }: {
      id?: string;
      children?: React.ReactNode;
      data?: unknown;
      attribution?: string;
    }) => {
      if (data !== undefined) mapSpy.sourceData = data as typeof mapSpy.sourceData;
      if (id === 'bbox-source') mapSpy.bboxSourceAttribution = attribution;
      return children ?? null;
    },
    Layer: () => null,
    NavigationControl: () => <div data-testid="nav-control" />,
  };
});

vi.mock('@/components/theme-provider', () => ({
  useTheme: () => ({ resolvedTheme: 'light' }),
}));

const tileConfigState = vi.hoisted(() => ({
  data: null as { mvt_source_layer_prefix: string | null } | null,
}));
const basemapState = vi.hoisted(() => ({ data: [] as BasemapEntry[] }));

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({ data: basemapState.data }),
  useMapDefaults: () => ({ data: null }),
  useTileConfig: () => ({ data: tileConfigState.data }),
}));

// A spy (not a plain stub) so a test can assert what datasetId it was
// called with — undefined means the record type never asked for a token.
const useTileTokenSpy = vi.hoisted(() => vi.fn(() => ({ data: null })));
vi.mock('@/hooks/use-tile-token', () => ({
  useInvalidateTileTokens: () => vi.fn(),
  useTileToken: useTileTokenSpy,
}));

vi.mock('@/stores/drawing-store', () => {
  const useDrawingStore = (selector: (state: typeof drawingState) => unknown) => selector(drawingState);
  // fix(#1761 review round 3 P1): finishDrawingSession reads
  // useDrawingStore.getState() directly (not via the selector hook), the
  // same static-access pattern the real zustand store supports.
  useDrawingStore.getState = () => drawingState;
  useDrawingStore.subscribe = vi.fn(() => vi.fn());
  return { useDrawingStore };
});

// fix(#1761 review round 3 P1): a stable hoisted object (not a fresh
// literal per render) so a test can hold onto `terraDrawState.clear` and
// assert it was invoked by the identity-change cleanup effect.
const terraDrawState = vi.hoisted(() => ({
  handleDrawFinish: null as ((feature: {
    type: 'Feature';
    geometry: { type: 'Point'; coordinates: number[] };
    properties: Record<string, unknown>;
  }) => void) | null,
  setMode: vi.fn(),
  isReady: false,
  addFeatures: vi.fn(),
  removeFeatures: vi.fn(),
  selectFeature: vi.fn(),
  getSnapshotFeature: vi.fn(),
  clear: vi.fn(),
  undo: vi.fn(),
  canUndo: false,
  resetHistory: vi.fn(),
}));

vi.mock('@/components/drawing/hooks/use-terra-draw', () => ({
  useTerraDraw: (_map: unknown, handleDrawFinish: typeof terraDrawState.handleDrawFinish) => {
    terraDrawState.handleDrawFinish = handleDrawFinish;
    return terraDrawState;
  },
  getModeName: () => 'polygon',
  getAvailableModes: vi.fn(() => ['select', 'point', 'linestring', 'polygon']),
}));

import { getAvailableModes } from '@/components/drawing/hooks/use-terra-draw';

// fix(#1761 review round 4): a stable hoisted mutateAsync (not a fresh
// vi.fn() per render) so a test can control WHEN the update mutation
// resolves, to simulate an identity change while it is in flight.
const updateFeatureMutateAsync = vi.hoisted(() => vi.fn().mockResolvedValue({}));
const createFeatureMutateAsync = vi.hoisted(() => vi.fn().mockResolvedValue({}));
// A spy (not an inline vi.fn()) so a test can assert a Delete never went out.
const deleteFeatureMutateAsync = vi.hoisted(() => vi.fn().mockResolvedValue({}));
vi.mock('@/hooks/use-features', () => ({
  useCreateFeature: () => ({ mutateAsync: createFeatureMutateAsync }),
  useUpdateFeature: () => ({ mutateAsync: updateFeatureMutateAsync }),
  useDeleteFeature: () => ({ mutateAsync: deleteFeatureMutateAsync }),
}));

vi.mock('@/api/features', () => ({
  getFeature: vi.fn(),
}));

// fix(#1761 review round 3 P1): keep useFeatureEditing's real implementation
// (performDeselect etc. are exercised elsewhere in this file) but replace
// showAllFeaturesInTiles with a spy, so the identity-change cleanup test
// below can assert the tile-filter restore ran without needing a real
// MapLibre map's getLayer/getFilter/setFilter machinery.
const showAllFeaturesInTilesMock = vi.hoisted(() => vi.fn());
vi.mock('@/components/dataset/hooks/use-feature-editing', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/dataset/hooks/use-feature-editing')>();
  return {
    ...actual,
    showAllFeaturesInTiles: showAllFeaturesInTilesMock,
  };
});

// targetDatasetId is shared across describes and most of them never set it,
// so reset it here to keep a mismatched value from leaking between tests.
// A describe that tests the mismatch overrides it in its own beforeEach.
beforeEach(() => {
  drawingState.targetDatasetId = null;
});

describe('DatasetMap interaction state', () => {
  beforeEach(() => {
    drawingState.isDrawing = false;
    drawingState.activeMode = null;
    drawingState.setDrawing.mockReset();
    createFeatureMutateAsync.mockReset();
    createFeatureMutateAsync.mockResolvedValue({});
  });

  it('does not let an older create completion clear a replacement draft', async () => {
    let resolveCreate!: (value: unknown) => void;
    createFeatureMutateAsync.mockReturnValueOnce(new Promise((resolve) => {
      resolveCreate = resolve;
    }));
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Point"
        datasetId="dataset-1"
        columnInfo={[{ name: 'population', type: 'integer' }]}
        canEdit
      />,
    );

    act(() => {
      terraDrawState.handleDrawFinish?.({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [1, 1] },
        properties: {},
      });
    });
    fireEvent.change(screen.getByLabelText('population'), { target: { value: '100' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(createFeatureMutateAsync).toHaveBeenCalledTimes(1);

    act(() => {
      terraDrawState.handleDrawFinish?.({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [2, 2] },
        properties: {},
      });
    });
    await act(async () => {
      resolveCreate({});
    });

    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('keeps the hero map static until edit mode starts', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
      />,
    );

    expect(screen.getByTestId('dataset-map-shell')).toHaveAttribute('data-map-interactive', 'false');
    expect(screen.getByTestId('mapgl')).toHaveAttribute('data-interactive', 'true');
    expect(screen.getByTestId('nav-control')).toBeInTheDocument();
    expect(screen.getByTestId('dataset-map-edit-trigger')).toBeInTheDocument();
    expect(screen.getByTitle('Zoom to dataset extent')).toBeInTheDocument();
  });

  it('enables interaction and editing controls once edit mode is active', () => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'select';

    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
      />,
    );

    expect(screen.getByTestId('dataset-map-shell')).toHaveAttribute('data-map-interactive', 'true');
    expect(screen.getByTestId('mapgl')).toHaveAttribute('data-interactive', 'true');
    expect(screen.getByTestId('nav-control')).toBeInTheDocument();
    expect(screen.queryByTestId('dataset-map-edit-trigger')).not.toBeInTheDocument();
    expect(screen.getByTitle('Zoom to dataset extent')).toBeInTheDocument();
  });

  it('shows zoom-to-extent for vector dataset in read-only mode', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
      />,
    );

    expect(screen.getByTitle('Zoom to dataset extent')).toBeInTheDocument();
    expect(screen.getByTestId('nav-control')).toBeInTheDocument();
  });

  it('shows zoom-to-extent for raster dataset', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName={null}
        geometryType={null}
        recordType="raster_dataset"
        rasterTileUrl="/raster-tiles/test/{z}/{x}/{y}.png"
      />,
    );

    expect(screen.getByTitle('Zoom to dataset extent')).toBeInTheDocument();
  });

  it('does not show zoom-to-extent when no bbox', () => {
    render(
      <DatasetMap
        bbox={null}
        tableName="example_table"
        geometryType="Polygon"
      />,
    );

    expect(screen.queryByTitle('Zoom to dataset extent')).not.toBeInTheDocument();
  });
});

describe('DatasetMap accessibility', () => {
  beforeEach(() => {
    drawingState.isDrawing = false;
    drawingState.activeMode = null;
  });

  it('map container has role="region" and aria-label', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
      />,
    );

    const shell = screen.getByTestId('dataset-map-shell');
    expect(shell).toHaveAttribute('role', 'region');
    expect(shell).toHaveAttribute('aria-label', 'Dataset map');
  });

  it('edit geometry button has aria-label', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
      />,
    );

    const editBtn = screen.getByTestId('dataset-map-edit-trigger');
    expect(editBtn).toHaveAttribute('aria-label', 'Edit Features');
  });

  it('zoom-to-extent button has aria-label when drawing', () => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'select';

    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
      />,
    );

    const zoomBtn = screen.getByTitle('Zoom to dataset extent');
    expect(zoomBtn).toHaveAttribute('aria-label', 'Zoom to dataset extent');
  });

  it('fullscreen button has aria-label', () => {
    const containerRef = { current: document.createElement('div') };

    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        containerRef={containerRef}
      />,
    );

    const fullscreenBtn = screen.getByTitle('Enter fullscreen');
    expect(fullscreenBtn).toHaveAttribute('aria-label', 'Enter fullscreen');
  });
});

describe('DatasetMap editing UI states', () => {
  beforeEach(() => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'select';
    drawingState.selectedFeature = null;
    drawingState.isEditDirty = false;
    drawingState.setDrawing.mockReset();
    drawingState.clearSelectedFeature.mockReset();
    drawingState.setSelectedFeature.mockReset();
    drawingState.setEditDirty.mockReset();
  });

  it('shows drawing toolbar when in drawing mode', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
      />,
    );

    expect(screen.getByRole('button', { name: /Select/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Polygon/i })).toBeInTheDocument();
  });

  it('shows edit action bar when a feature is selected', () => {
    drawingState.selectedFeature = { gid: 42, tdId: 'td-1', properties: {} };

    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
      />,
    );

    expect(screen.getByRole('button', { name: /Save changes/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Cancel editing/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Edit attributes/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Delete feature/i })).toBeInTheDocument();
  });

  it('does NOT show edit action bar when no feature is selected', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
      />,
    );

    expect(screen.queryByRole('button', { name: /Save changes/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Delete feature/i })).not.toBeInTheDocument();
  });

  it('shows delete confirmation dialog when delete is clicked', () => {
    drawingState.selectedFeature = { gid: 42, tdId: 'td-1', properties: {} };

    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Delete feature/i }));

    expect(screen.getByText('Delete Feature')).toBeInTheDocument();
    expect(screen.getByText('Delete this feature? This cannot be undone.')).toBeInTheDocument();
  });

  it('shows feature ID in delete confirmation dialog', () => {
    drawingState.selectedFeature = { gid: 42, tdId: 'td-1', properties: {} };

    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Delete feature/i }));

    expect(screen.getByText('Feature ID: 42')).toBeInTheDocument();
  });

  it('hides edit button when canEdit is false', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit={false}
      />,
    );

    expect(screen.queryByTestId('dataset-map-edit-trigger')).not.toBeInTheDocument();
  });

  it('accepts tileVersion prop without error', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        tileVersion="2026-03-20T12:00:00Z"
      />,
    );

    expect(screen.getByTestId('dataset-map-shell')).toBeInTheDocument();
  });
});

// The Ctrl/Meta+Z listener is attached at the document level, so it still
// fires while this instance is mounted but hidden (isDataTabExpanded keeps
// a dirty session's map alive off-screen — see DatasetPage) and while focus
// is anywhere else on the page, including inputs the expanded Data tab's
// own table renders. It must not hijack the browser/input's native undo.
describe('DatasetMap undo shortcut ignores editable targets', () => {
  beforeEach(() => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'polygon';
    terraDrawState.undo.mockClear();
  });

  function renderDrawing() {
    return render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
      />,
    );
  }

  it('does not undo the sketch or preventDefault for Ctrl+Z or Meta+Z with focus in an input', () => {
    renderDrawing();
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();

    const ctrlEvent = new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true, cancelable: true });
    input.dispatchEvent(ctrlEvent);
    const metaEvent = new KeyboardEvent('keydown', { key: 'z', metaKey: true, bubbles: true, cancelable: true });
    input.dispatchEvent(metaEvent);

    expect(terraDrawState.undo).not.toHaveBeenCalled();
    expect(ctrlEvent.defaultPrevented).toBe(false);
    expect(metaEvent.defaultPrevented).toBe(false);

    document.body.removeChild(input);
  });

  it('does not undo while a feature write is in flight', () => {
    createFeatureMutateAsync.mockReturnValueOnce(new Promise(() => {}));
    renderDrawing();
    act(() => {
      terraDrawState.handleDrawFinish?.({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [1, 1] },
        properties: {},
      });
    });
    expect(createFeatureMutateAsync).toHaveBeenCalledTimes(1);

    const event = new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true, cancelable: true });
    document.body.dispatchEvent(event);

    expect(terraDrawState.undo).not.toHaveBeenCalled();
  });

  it('still undoes the sketch for Ctrl+Z when focus has no editable target', () => {
    renderDrawing();

    const event = new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true, cancelable: true });
    document.body.dispatchEvent(event);

    expect(terraDrawState.undo).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(true);
  });
});

describe('DatasetMap Escape shortcut ignores editable targets', () => {
  beforeEach(() => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'select';
    drawingState.targetDatasetId = 'dataset-1';
    drawingState.selectedFeature = null;
    drawingState.isEditDirty = false;
    drawingState.clearSelectedFeature.mockClear();
  });

  /** Selects a feature AFTER mount (a rerender, not the initial render), so
   *  the once-per-mount inherited-selection cleanup (which only ever checks
   *  what was already selected at that first render) never runs for it —
   *  this selection is made within this instance, like a real click would. */
  function renderWithSelection(isDirty: boolean) {
    // DatasetMap is memo()-wrapped: a shared props object across render and
    // rerender is Object.is-equal on every prop, so React bails out and
    // never re-runs this effect. A fresh bbox array literal each call (like
    // every other rerender in this file) is enough to force it through.
    const utils = render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        recordType="vector_dataset"
        canEdit
      />,
    );
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingState.isEditDirty = isDirty;
    utils.rerender(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        recordType="vector_dataset"
        canEdit
      />,
    );
    return utils;
  }

  it('does not deselect a clean selection for Escape with focus in an input', () => {
    renderWithSelection(false);
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();

    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));

    expect(drawingState.clearSelectedFeature).not.toHaveBeenCalled();

    document.body.removeChild(input);
  });

  it('still deselects a clean selection for Escape when focus has no editable target', () => {
    renderWithSelection(false);

    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));

    expect(drawingState.clearSelectedFeature).toHaveBeenCalled();
  });

  it('does not open the discard dialog for a dirty selection when Escape is pressed in an input', () => {
    renderWithSelection(true);
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();

    // Opening the dialog is a React state update (setDiscardConfirmOpen) —
    // wrapped in act() so a false "not open" isn't just React not having
    // re-rendered yet (see the sibling "still opens" test for the same).
    act(() => {
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    });

    expect(screen.queryByText('Discard unsaved map edits?')).not.toBeInTheDocument();

    document.body.removeChild(input);
  });

  it('ignores Escape while a feature save is in flight', async () => {
    let settle!: () => void;
    updateFeatureMutateAsync.mockReturnValueOnce(new Promise((resolve) => {
      settle = () => resolve({});
    }));
    terraDrawState.getSnapshotFeature.mockReturnValueOnce({
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [] },
      properties: {},
    });
    renderWithSelection(true);
    fireEvent.click(screen.getByRole('button', { name: /Save changes/i }));
    expect(updateFeatureMutateAsync).toHaveBeenCalledTimes(1);

    act(() => {
      document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    });
    expect(screen.queryByText('Discard unsaved map edits?')).not.toBeInTheDocument();

    await act(async () => {
      settle();
    });
    act(() => {
      document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    });
    expect(screen.getByText('Discard unsaved map edits?')).toBeInTheDocument();
  });

  it('still opens the discard dialog for a dirty selection when Escape has no editable target', () => {
    renderWithSelection(true);

    // Opening the dialog is a React state update (setDiscardConfirmOpen),
    // unlike the other assertions in this block which read a plain
    // function-call spy or the event's own property.
    act(() => {
      document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    });

    expect(screen.getByText('Discard unsaved map edits?')).toBeInTheDocument();
  });
});

// DatasetPage sets this false while this instance is kept mounted but
// hidden behind the expanded Data tab (see isDataTabExpanded), so its
// document-level shortcuts can't act on geometry the user can't see —
// covers focusable elements the table itself renders (e.g. a button),
// which isEditableTarget alone does not catch.
describe('DatasetMap shortcutsEnabled disables the document-level shortcuts', () => {
  beforeEach(() => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'polygon';
    drawingState.targetDatasetId = 'dataset-1';
    drawingState.selectedFeature = null;
    drawingState.isEditDirty = false;
    terraDrawState.undo.mockClear();
    drawingState.clearSelectedFeature.mockClear();
  });

  it('does not undo or preventDefault for Ctrl+Z on document.body when shortcutsEnabled is false', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
        shortcutsEnabled={false}
      />,
    );

    const event = new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true, cancelable: true });
    document.body.dispatchEvent(event);

    expect(terraDrawState.undo).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });

  it('does not deselect for Escape on document.body when shortcutsEnabled is false', () => {
    const utils = render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
        shortcutsEnabled={false}
      />,
    );
    // Selected after mount, like the sibling Escape-shortcut tests above —
    // DatasetMap is memo()-wrapped, so a fresh bbox literal on rerender is
    // what actually forces it to pick up the new store state.
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    utils.rerender(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
        shortcutsEnabled={false}
      />,
    );

    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));

    expect(drawingState.clearSelectedFeature).not.toHaveBeenCalled();
  });

  it('does not open the discard dialog for a dirty selection on Escape when shortcutsEnabled is false', () => {
    const utils = render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
        shortcutsEnabled={false}
      />,
    );
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingState.isEditDirty = true;
    utils.rerender(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
        shortcutsEnabled={false}
      />,
    );

    act(() => {
      document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    });

    expect(screen.queryByText('Discard unsaved map edits?')).not.toBeInTheDocument();
  });
});

// A client-side navigation with nothing dirty (unsaved guard lets it
// through) can land on a non-editable dataset's map while the global
// drawing store still holds the previous dataset's session. That map's
// mutation hooks are bound to the new dataset id/table, so a stale Delete
// would target the wrong dataset with the old gid.
describe('DatasetMap stale drawing session on a non-editable mount', () => {
  beforeEach(() => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'select';
    drawingState.targetDatasetId = null;
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingState.isEditDirty = false;
    drawingState.clearDrawing.mockClear();
    drawingState.clearSelectedFeature.mockClear();
  });

  it('ends the stale session and hides the toolbar for a non-editable dataset', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName={null}
        geometryType={null}
        datasetId="dataset-2"
        recordType="pointcloud_dataset"
        canEdit={false}
      />,
    );

    expect(screen.queryByRole('toolbar')).not.toBeInTheDocument();
    expect(drawingState.clearDrawing).toHaveBeenCalled();
  });

  it('keeps an active session but drops its inherited selection for a dataset that can edit (route resume)', () => {
    // A real resume: the session's target matches the dataset this map is
    // for, not just the permissive "nothing adopted yet" default.
    drawingState.targetDatasetId = 'dataset-1';
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        recordType="vector_dataset"
        canEdit
      />,
    );

    expect(screen.getByRole('toolbar')).toBeInTheDocument();
    expect(drawingState.clearDrawing).not.toHaveBeenCalled();
    // The session (isDrawing/mode/target) is kept, but a brand-new TerraDraw
    // instance never made the inherited selection (gid 7 from before this
    // remount) — performDeselect() drops it independently of the session.
    expect(drawingState.clearSelectedFeature).toHaveBeenCalled();
  });
});

// Between two editable datasets canEdit can't tell the sessions apart. A
// clean selection on A survives navigation to B, where B's mutation hooks
// would act on A's gid if B has a feature with the same id.
describe('DatasetMap stale drawing session across an editable-to-editable dataset change', () => {
  beforeEach(() => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'select';
    drawingState.targetDatasetId = 'dataset-A';
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingState.isEditDirty = false;
    drawingState.clearDrawing.mockClear();
    drawingState.clearSelectedFeature.mockClear();
    deleteFeatureMutateAsync.mockClear();
  });

  it('ends the session, hides the toolbar, and never sends a delete for the colliding gid', async () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="dataset_b_table"
        geometryType="Polygon"
        datasetId="dataset-B"
        recordType="vector_dataset"
        canEdit
      />,
    );

    expect(screen.queryByRole('toolbar')).not.toBeInTheDocument();
    expect(drawingState.clearDrawing).toHaveBeenCalled();
    // There is no toolbar to click Delete on; this pins that the mutation
    // itself never fires, not just that its button is hidden.
    expect(deleteFeatureMutateAsync).not.toHaveBeenCalled();
  });
});

// A to a page with no map preview and back to A: no DatasetMap mounted in
// between, so the store still holds A's selection, but the map that mounts
// on return has a new TerraDraw instance that never made it.
describe('DatasetMap drops an inherited selection when the same dataset remounts with no map in between', () => {
  beforeEach(() => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'select';
    drawingState.targetDatasetId = 'dataset-1';
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingState.isEditDirty = false;
    drawingState.clearDrawing.mockClear();
    drawingState.clearSelectedFeature.mockClear();
    deleteFeatureMutateAsync.mockClear();
  });

  function renderOnDatasetOne() {
    return render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        recordType="vector_dataset"
        canEdit
      />,
    );
  }

  it('drops the selection, keeps the session, and never sends a delete for the stale gid', () => {
    const { rerender } = renderOnDatasetOne();

    // The mount effect ran performDeselect(), which calls the store's
    // clearSelectedFeature — this mock has no real zustand reactivity (see
    // the identity-change cleanup tests above for the same pattern), so
    // simulate its result and re-render to observe the settled UI.
    expect(drawingState.clearSelectedFeature).toHaveBeenCalled();
    drawingState.selectedFeature = null;
    rerender(<DatasetMap
      bbox={[-10, -10, 10, 10]}
      tableName="example_table"
      geometryType="Polygon"
      datasetId="dataset-1"
      recordType="vector_dataset"
      canEdit
    />);

    // The session stays — the toolbar (mode buttons) is still there — but
    // its action bar for a selection this instance never made is gone.
    expect(screen.getByRole('toolbar')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Delete feature/i })).not.toBeInTheDocument();
    expect(drawingState.isDrawing).toBe(true);
    expect(drawingState.clearDrawing).not.toHaveBeenCalled();
    expect(deleteFeatureMutateAsync).not.toHaveBeenCalled();
  });
});

// A DIRTY inherited selection (an in-progress, unsaved geometry edit, e.g.
// after the map crashed and Retry remounted it) is kept rather than
// dropped, unlike the clean case above: DatasetPage's unsaved-changes guard
// reads isEditDirty, so silently clearing it here would let the user
// navigate away from an edit with no warning at all. Its geometry lived
// only in the old TerraDraw instance, so Save could never work.
describe('DatasetMap keeps a dirty inherited selection and offers only a discard for it', () => {
  beforeEach(() => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'select';
    drawingState.targetDatasetId = 'dataset-1';
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingState.isEditDirty = true;
    drawingState.clearDrawing.mockClear();
    drawingState.clearSelectedFeature.mockClear();
    deleteFeatureMutateAsync.mockClear();
  });

  it('keeps the selection and isEditDirty, and offers a discard in place of Save', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        recordType="vector_dataset"
        canEdit
      />,
    );

    // No silent deselect: performDeselect (and its clearSelectedFeature
    // call) never ran for a dirty inherited selection.
    expect(drawingState.clearSelectedFeature).not.toHaveBeenCalled();
    expect(drawingState.selectedFeature).toEqual({ gid: 7, tdId: 'td-7', properties: {} });
    expect(drawingState.isEditDirty).toBe(true);
    expect(screen.getByRole('toolbar')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(/change to this feature was lost/i);
    expect(screen.queryByRole('button', { name: /Save changes/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Delete feature/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }));
    expect(drawingState.clearSelectedFeature).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Discard changes' }));
    expect(drawingState.clearSelectedFeature).toHaveBeenCalled();
    expect(drawingState.clearDrawing).not.toHaveBeenCalled();
  });

  it('shows Delete again once a fresh selection replaces the orphaned one', () => {
    const { rerender } = render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        recordType="vector_dataset"
        canEdit
      />,
    );
    expect(screen.queryByRole('button', { name: /Delete feature/i })).not.toBeInTheDocument();

    // A genuinely new selection made in THIS instance (a different tdId) —
    // the suppression is scoped to the one orphaned selection, not "ever".
    drawingState.selectedFeature = { gid: 9, tdId: 'td-9', properties: {} };
    rerender(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        recordType="vector_dataset"
        canEdit
      />,
    );

    expect(screen.getByRole('button', { name: /Delete feature/i })).toBeInTheDocument();
  });
});

// Edit rights can go away while this map is mounted: the editing flag is
// switched off, or a refetch changes the user's permission. The toolbar goes
// with them, so a dirty edit needs another way to be resolved.
describe('DatasetMap when edit rights are lost mid-session', () => {
  beforeEach(() => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'select';
    drawingState.targetDatasetId = 'dataset-1';
    drawingState.selectedFeature = null;
    drawingState.isEditDirty = false;
    drawingState.clearDrawing.mockClear();
    drawingState.clearSelectedFeature.mockClear();
  });

  function renderMap(canEdit: boolean, columnInfo?: { name: string; type: string }[]) {
    return (
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        recordType="vector_dataset"
        columnInfo={columnInfo}
        canEdit={canEdit}
      />
    );
  }

  it('ends a clean session', () => {
    const { rerender } = render(renderMap(true));
    expect(screen.getByRole('toolbar')).toBeInTheDocument();

    rerender(renderMap(false));

    expect(drawingState.clearDrawing).toHaveBeenCalled();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('ends a clean session only after a feature write in flight settles', async () => {
    let settle!: () => void;
    deleteFeatureMutateAsync.mockReturnValueOnce(new Promise((resolve) => {
      settle = () => resolve({});
    }));
    const { rerender } = render(renderMap(true));
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    rerender(renderMap(true));
    fireEvent.click(screen.getByRole('button', { name: /Delete feature/i }));
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete' }));
    expect(deleteFeatureMutateAsync).toHaveBeenCalledTimes(1);

    rerender(renderMap(false));
    expect(drawingState.clearDrawing).not.toHaveBeenCalled();

    await act(async () => {
      settle();
    });
    rerender(renderMap(false));

    expect(drawingState.clearDrawing).toHaveBeenCalled();
  });

  it('keeps a dirty edit and offers a discard that ends the session', () => {
    const { rerender } = render(renderMap(true));
    // A selection made and dragged in this instance, not an inherited one.
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingState.isEditDirty = true;
    rerender(renderMap(true));
    expect(screen.getByRole('button', { name: /Save changes/i })).toBeInTheDocument();

    rerender(renderMap(false));

    expect(drawingState.clearDrawing).not.toHaveBeenCalled();
    expect(drawingState.clearSelectedFeature).not.toHaveBeenCalled();
    expect(screen.queryByRole('toolbar')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(/can no longer edit this dataset/i);

    fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }));
    expect(drawingState.clearDrawing).not.toHaveBeenCalled();
    const dialog = screen.getByRole('alertdialog');
    expect(dialog).toHaveTextContent(/can no longer edit this dataset/i);
    expect(dialog).not.toHaveTextContent(/continue editing/i);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Discard changes' }));
    expect(drawingState.clearDrawing).toHaveBeenCalled();
  });

  it('holds the discard while a save is still in flight', async () => {
    let settle!: () => void;
    updateFeatureMutateAsync.mockReturnValueOnce(new Promise((resolve) => {
      settle = () => resolve({});
    }));
    terraDrawState.getSnapshotFeature.mockReturnValueOnce({
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [] },
      properties: {},
    });
    const { rerender } = render(renderMap(true));
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingState.isEditDirty = true;
    rerender(renderMap(true));
    fireEvent.click(screen.getByRole('button', { name: /Save changes/i }));
    expect(updateFeatureMutateAsync).toHaveBeenCalledTimes(1);

    rerender(renderMap(false));
    expect(screen.getByRole('button', { name: 'Discard changes' })).toBeDisabled();

    await act(async () => {
      settle();
    });
    rerender(renderMap(false));
    expect(screen.getByRole('button', { name: 'Discard changes' })).toBeEnabled();
  });

  it('keeps a session whose attribute editor is open', () => {
    const { rerender } = render(renderMap(true));
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    rerender(renderMap(true));
    fireEvent.click(screen.getByRole('button', { name: /Edit attributes/i }));

    rerender(renderMap(false));

    expect(drawingState.clearDrawing).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/can no longer edit this dataset/i);
  });

  it('holds a sketch finished after rights are lost until Discard', () => {
    drawingState.activeMode = 'polygon';
    terraDrawState.canUndo = true;
    terraDrawState.isReady = true;
    createFeatureMutateAsync.mockClear();
    terraDrawState.setMode.mockClear();
    try {
      const { rerender } = render(renderMap(true));
      rerender(renderMap(false));
      expect(screen.getByRole('alert')).toHaveTextContent(/can no longer edit this dataset/i);

      act(() => {
        terraDrawState.handleDrawFinish?.({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [1, 1] },
          properties: {},
        });
      });
      // TerraDraw resets its history once a sketch finishes.
      terraDrawState.canUndo = false;
      rerender(renderMap(false));

      expect(createFeatureMutateAsync).not.toHaveBeenCalled();
      expect(drawingState.clearDrawing).not.toHaveBeenCalled();
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(terraDrawState.setMode).toHaveBeenLastCalledWith('static');

      fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }));
      fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Discard changes' }));
      expect(drawingState.clearDrawing).toHaveBeenCalled();
    } finally {
      terraDrawState.canUndo = false;
      terraDrawState.isReady = false;
    }
  });

  it('closes an existing feature\'s attribute editor and keeps its session until Discard', () => {
    const columns = [{ name: 'population', type: 'integer' }];
    updateFeatureMutateAsync.mockClear();
    const { rerender } = render(renderMap(true, columns));
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    rerender(renderMap(true, columns));
    fireEvent.click(screen.getByRole('button', { name: /Edit attributes/i }));
    fireEvent.change(screen.getByLabelText('population'), { target: { value: '100' } });

    rerender(renderMap(false, columns));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(updateFeatureMutateAsync).not.toHaveBeenCalled();
    expect(drawingState.clearDrawing).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/can no longer edit this dataset/i);

    fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }));
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Discard changes' }));
    expect(drawingState.clearDrawing).toHaveBeenCalled();
  });

  it('keeps a selection with an undoable change not yet marked dirty', () => {
    const { rerender } = render(renderMap(true));
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    terraDrawState.canUndo = true;
    try {
      rerender(renderMap(true));

      rerender(renderMap(false));

      expect(drawingState.clearDrawing).not.toHaveBeenCalled();
      expect(drawingState.clearSelectedFeature).not.toHaveBeenCalled();
      expect(screen.getByRole('alert')).toHaveTextContent(/can no longer edit this dataset/i);
    } finally {
      terraDrawState.canUndo = false;
    }
  });

  it('ends a session whose selection has nothing to undo', () => {
    const { rerender } = render(renderMap(true));
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    rerender(renderMap(true));

    rerender(renderMap(false));

    expect(drawingState.clearDrawing).toHaveBeenCalled();
  });

  it('closes the delete confirmation and sends no delete', () => {
    deleteFeatureMutateAsync.mockClear();
    const { rerender } = render(renderMap(true));
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingState.isEditDirty = true;
    rerender(renderMap(true));
    fireEvent.click(screen.getByRole('button', { name: /Delete feature/i }));
    expect(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete' })).toBeInTheDocument();

    rerender(renderMap(false));

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
    expect(deleteFeatureMutateAsync).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/can no longer edit this dataset/i);

    fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }));
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Discard changes' }));
    expect(deleteFeatureMutateAsync).not.toHaveBeenCalled();
    expect(drawingState.clearDrawing).toHaveBeenCalled();
  });

  it('does not reopen the delete confirmation when rights return', () => {
    const { rerender } = render(renderMap(true));
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingState.isEditDirty = true;
    rerender(renderMap(true));
    fireEvent.click(screen.getByRole('button', { name: /Delete feature/i }));

    rerender(renderMap(false));
    rerender(renderMap(true));

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('keeps an open discard confirmation usable', () => {
    const { rerender } = render(renderMap(true));
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingState.isEditDirty = true;
    rerender(renderMap(true));
    fireEvent.click(screen.getByRole('button', { name: /Cancel editing/i }));

    rerender(renderMap(false));

    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Discard changes' }));
    expect(drawingState.clearSelectedFeature).toHaveBeenCalled();
  });

  async function saveAttributesThenLoseRights(outcome: 'reject' | 'resolve') {
    const columns = [{ name: 'population', type: 'integer' }];
    let settle!: () => void;
    updateFeatureMutateAsync.mockReturnValueOnce(new Promise((resolve, reject) => {
      settle = () => (outcome === 'reject' ? reject(new Error('forbidden')) : resolve({}));
    }));
    const { rerender } = render(renderMap(true, columns));
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    rerender(renderMap(true, columns));
    fireEvent.click(screen.getByRole('button', { name: /Edit attributes/i }));
    fireEvent.change(screen.getByLabelText('population'), { target: { value: '100' } });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Save' }));
    expect(updateFeatureMutateAsync).toHaveBeenCalledTimes(1);

    rerender(renderMap(false, columns));
    await act(async () => {
      settle();
    });
    rerender(renderMap(false, columns));
  }

  it('keeps an attribute edit whose save is refused after rights are lost', async () => {
    await saveAttributesThenLoseRights('reject');

    expect(drawingState.clearDrawing).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/can no longer edit this dataset/i);

    fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }));
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Discard changes' }));
    expect(drawingState.clearDrawing).toHaveBeenCalled();
  });

  it('closes an attribute edit whose save succeeds after rights are lost', async () => {
    await saveAttributesThenLoseRights('resolve');

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(drawingState.clearDrawing).toHaveBeenCalled();
  });

  async function finishSketchThenLoseRights(outcome: 'reject' | 'resolve') {
    let settle!: () => void;
    createFeatureMutateAsync.mockReset();
    createFeatureMutateAsync.mockReturnValueOnce(new Promise((resolve, reject) => {
      settle = () => (outcome === 'reject' ? reject(new Error('forbidden')) : resolve({}));
    }));
    drawingState.activeMode = 'point';
    terraDrawState.canUndo = true;
    const { rerender } = render(renderMap(true));
    act(() => {
      terraDrawState.handleDrawFinish?.({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [1, 1] },
        properties: {},
      });
    });
    terraDrawState.canUndo = false;
    expect(createFeatureMutateAsync).toHaveBeenCalledTimes(1);
    rerender(renderMap(false));
    expect(drawingState.clearDrawing).not.toHaveBeenCalled();
    await act(async () => {
      settle();
    });
    rerender(renderMap(false));
  }

  it('holds a sketch whose automatic save is refused after rights are lost', async () => {
    await finishSketchThenLoseRights('reject');

    expect(drawingState.clearDrawing).not.toHaveBeenCalled();
    expect(drawingState.setHasUnsavedMapWork).toHaveBeenLastCalledWith(true);
    expect(screen.getByRole('alert')).toHaveTextContent(/can no longer edit this dataset/i);

    fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }));
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Discard changes' }));
    expect(drawingState.clearDrawing).toHaveBeenCalled();
  });

  it('holds nothing when the automatic save succeeds after rights are lost', async () => {
    await finishSketchThenLoseRights('resolve');

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(drawingState.clearDrawing).toHaveBeenCalled();
  });

  it('keeps a dirty edit a non-editable map inherits on mount', () => {
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingState.isEditDirty = true;

    render(renderMap(false));

    expect(drawingState.clearDrawing).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/can no longer edit this dataset/i);
  });
});

// Changing mode deselects the feature, so it must wait for the write that
// refers to that selection.
describe('DatasetMap while a feature write is in flight', () => {
  beforeEach(() => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'select';
    drawingState.targetDatasetId = 'dataset-1';
    drawingState.selectedFeature = null;
    drawingState.isEditDirty = false;
    drawingState.setMode.mockClear();
    drawingState.clearSelectedFeature.mockClear();
    terraDrawState.undo.mockClear();
  });

  afterEach(() => {
    terraDrawState.canUndo = false;
  });

  function renderMap() {
    return (
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Point"
        datasetId="dataset-1"
        recordType="vector_dataset"
        canEdit
      />
    );
  }

  function expectModeChangesBlocked() {
    expect(screen.getByRole('button', { name: 'Select' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Point' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Undo (Ctrl+Z)' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Point' }));
    expect(drawingState.setMode).not.toHaveBeenCalled();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(drawingState.clearSelectedFeature).not.toHaveBeenCalled();
  }

  it('blocks mode changes and Undo while a geometry save is in flight', async () => {
    let settle!: () => void;
    updateFeatureMutateAsync.mockReturnValueOnce(new Promise((resolve) => {
      settle = () => resolve({});
    }));
    terraDrawState.getSnapshotFeature.mockReturnValueOnce({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [1, 1] },
      properties: {},
    });
    terraDrawState.canUndo = true;
    const { rerender } = render(renderMap());
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    drawingState.isEditDirty = true;
    rerender(renderMap());
    fireEvent.click(screen.getByRole('button', { name: /Save changes/i }));
    expect(updateFeatureMutateAsync).toHaveBeenCalledTimes(1);

    expectModeChangesBlocked();

    await act(async () => {
      settle();
    });
    expect(screen.getByRole('button', { name: 'Point' })).toBeEnabled();
  });

  it('blocks mode changes while a delete is in flight, so its tiles reload on success', async () => {
    let settle!: () => void;
    deleteFeatureMutateAsync.mockReturnValueOnce(new Promise((resolve) => {
      settle = () => resolve({});
    }));
    terraDrawState.canUndo = true;
    const { rerender } = render(renderMap());
    drawingState.selectedFeature = { gid: 7, tdId: 'td-7', properties: {} };
    rerender(renderMap());
    fireEvent.click(screen.getByRole('button', { name: /Delete feature/i }));
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete' }));
    expect(deleteFeatureMutateAsync).toHaveBeenCalledTimes(1);

    expectModeChangesBlocked();

    await act(async () => {
      settle();
    });
    expect(drawingState.clearSelectedFeature).toHaveBeenCalledTimes(1);
  });
});

// DatasetPage's unsaved-changes guard reads this flag, so it covers every
// kind of unsaved map work, not just a dirty selection.
describe('DatasetMap reports unsaved map work to the page guard', () => {
  const setUnsaved = drawingState.setHasUnsavedMapWork;

  beforeEach(() => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'select';
    drawingState.targetDatasetId = 'dataset-1';
    drawingState.selectedFeature = null;
    drawingState.isEditDirty = false;
    drawingState.clearDrawing.mockClear();
    setUnsaved.mockClear();
    createFeatureMutateAsync.mockClear();
  });

  afterEach(() => {
    terraDrawState.canUndo = false;
  });

  function renderMap(canEdit: boolean, columnInfo?: { name: string; type: string }[]) {
    return (
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Point"
        datasetId="dataset-1"
        recordType="vector_dataset"
        columnInfo={columnInfo}
        canEdit={canEdit}
      />
    );
  }

  function finishSketch() {
    act(() => {
      terraDrawState.handleDrawFinish?.({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [1, 1] },
        properties: {},
      });
    });
    terraDrawState.canUndo = false;
  }

  it('reports a clean session as having none', () => {
    render(renderMap(true));

    expect(setUnsaved).toHaveBeenLastCalledWith(false);
    expect(setUnsaved).not.toHaveBeenCalledWith(true);
  });

  it('reports an unfinished sketch', () => {
    drawingState.activeMode = 'point';
    terraDrawState.canUndo = true;

    render(renderMap(true));

    expect(setUnsaved).toHaveBeenLastCalledWith(true);
  });

  it('reports a new feature whose attribute form is open', () => {
    const { rerender } = render(renderMap(true, [{ name: 'population', type: 'integer' }]));
    finishSketch();
    rerender(renderMap(true, [{ name: 'population', type: 'integer' }]));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(setUnsaved).toHaveBeenLastCalledWith(true);
  });

  it('reports a sketch held after rights are lost, and none once it is discarded', () => {
    drawingState.activeMode = 'point';
    terraDrawState.canUndo = true;
    const { rerender } = render(renderMap(true));
    rerender(renderMap(false));
    finishSketch();
    rerender(renderMap(false));

    expect(createFeatureMutateAsync).not.toHaveBeenCalled();
    expect(setUnsaved).toHaveBeenLastCalledWith(true);

    fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }));
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Discard changes' }));

    expect(setUnsaved).toHaveBeenLastCalledWith(false);
  });

  it('reports none once the map unmounts', () => {
    drawingState.activeMode = 'point';
    terraDrawState.canUndo = true;
    const { unmount } = render(renderMap(true));
    expect(setUnsaved).toHaveBeenLastCalledWith(true);

    unmount();

    expect(setUnsaved).toHaveBeenLastCalledWith(false);
  });
});

// A dataset with no attribute columns has no form to fill in, so a finished
// sketch is saved straight away. Until that save succeeds the shape is still
// unsaved work.
describe('DatasetMap new feature saved without an attribute form', () => {
  const setUnsaved = drawingState.setHasUnsavedMapWork;

  beforeEach(() => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'point';
    drawingState.targetDatasetId = 'dataset-1';
    drawingState.selectedFeature = null;
    drawingState.isEditDirty = false;
    drawingState.clearDrawing.mockClear();
    setUnsaved.mockClear();
    terraDrawState.setMode.mockClear();
    terraDrawState.isReady = true;
    createFeatureMutateAsync.mockReset();
  });

  afterEach(() => {
    terraDrawState.canUndo = false;
    terraDrawState.isReady = false;
    createFeatureMutateAsync.mockReset();
    createFeatureMutateAsync.mockResolvedValue({});
  });

  function renderMap() {
    return (
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Point"
        datasetId="dataset-1"
        recordType="vector_dataset"
        canEdit
      />
    );
  }

  function finishSketch() {
    act(() => {
      terraDrawState.handleDrawFinish?.({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [1, 1] },
        properties: {},
      });
    });
  }

  function pendingCreate(outcome: 'reject' | 'resolve') {
    let settle!: () => void;
    createFeatureMutateAsync.mockReturnValueOnce(new Promise((resolve, reject) => {
      settle = () => (outcome === 'reject' ? reject(new Error('refused')) : resolve({}));
    }));
    return async () => {
      await act(async () => {
        settle();
      });
    };
  }

  it('reports unsaved work while the automatic save is in flight, then none once it succeeds', async () => {
    const settle = pendingCreate('resolve');
    render(renderMap());

    finishSketch();

    expect(createFeatureMutateAsync).toHaveBeenCalledTimes(1);
    expect(setUnsaved).toHaveBeenLastCalledWith(true);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await settle();

    expect(setUnsaved).toHaveBeenLastCalledWith(false);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('stops drawing input while the automatic save is in flight and resumes once it succeeds', async () => {
    const settle = pendingCreate('resolve');
    render(renderMap());

    finishSketch();
    expect(terraDrawState.setMode).toHaveBeenLastCalledWith('static');

    await settle();
    expect(terraDrawState.setMode).toHaveBeenLastCalledWith('point');
  });

  it('holds Done until the automatic save has settled', async () => {
    const settle = pendingCreate('resolve');
    render(renderMap());
    finishSketch();

    expect(screen.getByRole('button', { name: 'Done' })).toBeDisabled();

    await settle();

    expect(screen.getByRole('button', { name: 'Done' })).toBeEnabled();
  });

  it('keeps the shape when the automatic save is refused and saves it again on request', async () => {
    const settle = pendingCreate('reject');
    render(renderMap());
    finishSketch();

    await settle();

    expect(setUnsaved).toHaveBeenLastCalledWith(true);
    expect(drawingState.clearDrawing).not.toHaveBeenCalled();
    const retry = within(screen.getByRole('dialog'));

    createFeatureMutateAsync.mockResolvedValueOnce({});
    await act(async () => {
      fireEvent.click(retry.getByRole('button', { name: 'Save' }));
    });

    expect(createFeatureMutateAsync).toHaveBeenCalledTimes(2);
    expect(createFeatureMutateAsync).toHaveBeenLastCalledWith(
      expect.objectContaining({ geometry: { type: 'Point', coordinates: [1, 1] } }),
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(setUnsaved).toHaveBeenLastCalledWith(false);
  });

  it('sends one idempotency key with rising attempt numbers for a sketch, and a new key for the next', async () => {
    const settle = pendingCreate('reject');
    render(renderMap());
    finishSketch();
    await settle();

    const dialog = within(screen.getByRole('dialog'));
    createFeatureMutateAsync.mockRejectedValueOnce(new Error('timed out'));
    await act(async () => {
      fireEvent.click(dialog.getByRole('button', { name: 'Skip' }));
    });
    createFeatureMutateAsync.mockResolvedValueOnce({});
    await act(async () => {
      fireEvent.click(dialog.getByRole('button', { name: 'Save' }));
    });
    expect(createFeatureMutateAsync).toHaveBeenCalledTimes(3);

    createFeatureMutateAsync.mockResolvedValueOnce({});
    finishSketch();
    expect(createFeatureMutateAsync).toHaveBeenCalledTimes(4);

    const keys = createFeatureMutateAsync.mock.calls.map(([vars]) => vars.idempotencyKey);
    const attempts = createFeatureMutateAsync.mock.calls.map(([vars]) => vars.attempt);
    expect(keys[0]).toEqual(expect.any(String));
    expect(keys[0]).not.toBe('');
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).toBe(keys[0]);
    expect(keys[3]).not.toBe(keys[0]);
    expect(attempts).toEqual([1, 2, 3, 1]);
  });

  it('starts one create when a second sketch finishes before the map re-renders, and keeps the first after a refusal', async () => {
    const info = vi.spyOn(toast, 'info').mockImplementation(() => 'toast-id');
    const settle = pendingCreate('reject');
    render(renderMap());

    act(() => {
      for (const x of [1, 2]) {
        terraDrawState.handleDrawFinish?.({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [x, x] },
          properties: {},
        });
      }
    });
    expect(createFeatureMutateAsync).toHaveBeenCalledTimes(1);
    expect(info).toHaveBeenCalledTimes(1);
    expect(info).toHaveBeenCalledWith('The previous feature is still saving. Try again once it has saved.');
    info.mockRestore();

    await settle();
    createFeatureMutateAsync.mockResolvedValueOnce({});
    await act(async () => {
      fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Save' }));
    });

    expect(createFeatureMutateAsync).toHaveBeenCalledTimes(2);
    expect(createFeatureMutateAsync).toHaveBeenLastCalledWith(
      expect.objectContaining({ geometry: { type: 'Point', coordinates: [1, 1] } }),
    );
  });

  it('saves the next sketch once the earlier automatic save has settled', async () => {
    const settle = pendingCreate('resolve');
    render(renderMap());
    finishSketch();
    await settle();

    createFeatureMutateAsync.mockResolvedValueOnce({});
    finishSketch();

    expect(createFeatureMutateAsync).toHaveBeenCalledTimes(2);
  });

  it('saves a new session\'s first sketch while the previous session\'s save is still in flight', () => {
    pendingCreate('resolve');
    const epoch = drawingState.sessionEpoch;
    try {
      const { rerender } = render(renderMap());
      finishSketch();
      expect(createFeatureMutateAsync).toHaveBeenCalledTimes(1);

      drawingState.sessionEpoch = epoch + 1;
      rerender(renderMap());
      createFeatureMutateAsync.mockResolvedValueOnce({});
      finishSketch();

      expect(createFeatureMutateAsync).toHaveBeenCalledTimes(2);
    } finally {
      drawingState.sessionEpoch = epoch;
    }
  });

  it('lets the user drop a shape whose automatic save was refused', async () => {
    const settle = pendingCreate('reject');
    render(renderMap());
    finishSketch();
    await settle();

    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(setUnsaved).toHaveBeenLastCalledWith(false);
  });
});

describe('DatasetMap non-spatial behavior', () => {
  beforeEach(() => {
    drawingState.isDrawing = false;
    drawingState.activeMode = null;
    drawingState.setDrawing.mockReset();
  });

  it('renders shell without crash when geometryType is null', () => {
    render(
      <DatasetMap bbox={null} tableName="nonspatial_table" geometryType={null} />,
    );

    const shell = screen.getByTestId('dataset-map-shell');
    expect(shell).toBeInTheDocument();
    expect(shell).toHaveAttribute('role', 'region');
  });

  it('does not show edit trigger or zoom for non-spatial dataset', () => {
    render(
      <DatasetMap bbox={null} tableName="nonspatial_table" geometryType={null} datasetId="ds-1" canEdit />,
    );

    expect(screen.queryByTestId('dataset-map-edit-trigger')).not.toBeInTheDocument();
    expect(screen.queryByTitle('Zoom to dataset extent')).not.toBeInTheDocument();
  });
});

describe('DatasetMap callback props', () => {
  beforeEach(() => {
    drawingState.isDrawing = false;
    drawingState.activeMode = null;
    drawingState.setDrawing.mockReset();
  });

  it('accepts onMapReady and onTileError optional callback props without error', () => {
    const onMapReady = vi.fn();
    const onTileError = vi.fn();

    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        onMapReady={onMapReady}
        onTileError={onTileError}
      />,
    );

    expect(screen.getByTestId('dataset-map-shell')).toBeInTheDocument();
  });

  it('renders without error when onMapReady/onTileError are not provided (backward compat)', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
      />,
    );

    expect(screen.getByTestId('dataset-map-shell')).toBeInTheDocument();
  });
});

describe('DatasetMap generic-geometry draw gating (fix #430 codex r18/r19)', () => {
  beforeEach(() => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'select';
    vi.mocked(getAvailableModes).mockClear();
  });

  it('feeds the GEOMETRY sentinel to the drawing toolbar for generic datasets', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="sketch_table"
        geometryType="Point"
        hasGenericGeometry
        datasetId="dataset-1"
        canEdit
      />,
    );
    expect(vi.mocked(getAvailableModes)).toHaveBeenCalledWith('GEOMETRY');
  });

  it('keeps the concrete display type for typed datasets', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="typed_table"
        geometryType="Point"
        datasetId="dataset-1"
        canEdit
      />,
    );
    expect(vi.mocked(getAvailableModes)).toHaveBeenCalledWith('Point');
    expect(vi.mocked(getAvailableModes)).not.toHaveBeenCalledWith('GEOMETRY');
  });
});

// fix(#1004): the dataset payload now carries the RFC 7946 §5.2 spec bbox, so a
// seam-crossing extent arrives as west > east instead of flattened to
// [-180, s, 180, n]. All three consumers here carry #903 seam handling that the
// flattened pair made unreachable — isLargeExtent measured a 360° span and took
// the large-extent branch every time.
describe('DatasetMap antimeridian extent (fix #1004)', () => {
  // The reproduction fixture: points at 179.5, -179.5 and 178.44 near Fiji.
  const FIJI_BBOX: [number, number, number, number] = [178.44, -18.14, -179.5, -16.5];
  const GLOBAL_BBOX: [number, number, number, number] = [-180, -18.14, 180, -16.5];

  beforeEach(() => {
    drawingState.isDrawing = false;
    drawingState.activeMode = null;
    mapSpy.reset();
  });

  function renderMap(bbox: [number, number, number, number]) {
    return render(
      <DatasetMap
        bbox={bbox}
        tableName="fiji_points"
        geometryType="Point"
        datasetId="dataset-fiji"
      />,
    );
  }

  it('fits the initial camera to the seam extent instead of the whole world', () => {
    renderMap(FIJI_BBOX);

    // The seam branch: bounds with east run past 180 for MapLibre to normalize.
    expect(mapSpy.initialViewState).toMatchObject({ fitBoundsOptions: { padding: 60 } });
    const bounds = (mapSpy.initialViewState as { bounds: number[][] }).bounds;
    expect(bounds).toEqual([
      [178.44, -18.14],
      [180.5, -16.5],
    ]);
  });

  it('still takes the large-extent branch for a genuinely global bbox', () => {
    renderMap(GLOBAL_BBOX);

    expect(mapSpy.initialViewState).not.toHaveProperty('bounds');
    expect(mapSpy.initialViewState).toMatchObject({ zoom: expect.any(Number) });
  });

  it('draws the extent band as two rings split at the seam', () => {
    renderMap(FIJI_BBOX);

    const rings = mapSpy.sourceData!.features[0].geometry.coordinates;
    expect(rings).toHaveLength(2);
    const spans = rings.map((ring) => [ring[0][0][0], ring[0][2][0]]);
    expect(spans).toEqual([
      [178.44, 180],
      [-180, -179.5],
    ]);
  });

  it('draws one global rectangle for a genuinely global bbox', () => {
    renderMap(GLOBAL_BBOX);

    expect(mapSpy.sourceData!.features[0].geometry.coordinates).toHaveLength(1);
  });

  it('zooms to the seam extent rather than flying to a world view', () => {
    mapSpy.attachMapInstance = true;
    renderMap(FIJI_BBOX);

    fireEvent.click(screen.getByTitle('Zoom to dataset extent'));

    expect(mapSpy.flyTo).not.toHaveBeenCalled();
    expect(mapSpy.fitBounds).toHaveBeenCalledWith(
      [
        [178.44, -18.14],
        [180.5, -16.5],
      ],
      expect.objectContaining({ padding: 60 }),
    );
  });
});

// fix(#1761 review round 3 P1): the identity-change choke point
// (lib/auth-cache-reset.ts) only resets Zustand fields. DatasetMap's own
// finishDrawingSession is what tears down Terra Draw's drawn geometry, the
// map's hidden-tile filters, and this component's own open dialogs — none
// of which the choke point can reach. This pins that an identity change
// (a sessionEpoch bump) drives that cleanup even though nothing in the
// choke point itself knows this component exists.
describe('DatasetMap identity-change cleanup (fix #1761 review round 3 P1)', () => {
  // fix(#1761 review round 4): spy-able 'drawn-overlay' source, so the
  // "tears down..." test below can also assert resetOverlay() actually
  // reaches the map (not just that finishDrawingSession's OTHER cleanup
  // steps ran).
  let overlaySetData: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'select';
    drawingState.selectedFeature = { gid: 42, tdId: 'td-1', properties: {} };
    drawingState.isEditDirty = false;
    drawingState.sessionEpoch = 100;
    drawingState.clearDrawing.mockReset();
    drawingState.clearSelectedFeature.mockReset();
    terraDrawState.clear.mockReset();
    terraDrawState.removeFeatures.mockReset();
    showAllFeaturesInTilesMock.mockReset();
    mapSpy.reset();
    mapSpy.attachMapInstance = true;
    // activeMode === 'select' (a live sketch session) wires up the canvas
    // click handler, which needs a real-shaped canvas from the fakeMap.
    (fakeMap.getCanvas as ReturnType<typeof vi.fn>).mockReturnValue({
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      getBoundingClientRect: () => ({ left: 0, top: 0 }),
    });
    overlaySetData = vi.fn();
    (fakeMap.getSource as ReturnType<typeof vi.fn>).mockImplementation((id: string) =>
      id === 'drawn-overlay' ? { setData: overlaySetData } : undefined,
    );
  });

  it('does not run the cleanup on mount', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
      />,
    );

    expect(terraDrawState.clear).not.toHaveBeenCalled();
    expect(showAllFeaturesInTilesMock).not.toHaveBeenCalled();
    expect(drawingState.clearDrawing).not.toHaveBeenCalled();
  });

  it('tears down the local drawing session when the session epoch changes', () => {
    const { rerender } = render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
      />,
    );

    // Open the "edit existing feature" dialog, standing in for "this
    // identity's local UI state" the choke point cannot see.
    fireEvent.click(screen.getByRole('button', { name: /Edit attributes/i }));
    expect(screen.getByText('Edit Feature Attributes')).toBeInTheDocument();

    // The identity change: the choke point bumped the store's sessionEpoch
    // (and separately cleared its own Zustand fields — simulated here by
    // NOT changing isDrawing/selectedFeature, since the point of this test
    // is that the epoch alone drives DatasetMap's local cleanup).
    drawingState.sessionEpoch = 101;
    rerender(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
      />,
    );

    expect(terraDrawState.clear).toHaveBeenCalled();
    expect(showAllFeaturesInTilesMock).toHaveBeenCalled();
    expect(drawingState.clearDrawing).toHaveBeenCalled();
    expect(screen.queryByText('Edit Feature Attributes')).not.toBeInTheDocument();
    // fix(#1761 review round 4): a create in progress can leave a
    // not-yet-committed shape in the drawn-overlay source; the
    // identity-change cleanup must empty it too.
    expect(overlaySetData).toHaveBeenCalledWith({ type: 'FeatureCollection', features: [] });
  });
});

// fix(#1761 review round 4): the attribute-edit dialog's onSubmit used to
// close unconditionally once handleEditAttributeSubmit resolved, even when
// its own epoch check had refused the write as stale — discarding a SECOND
// identity's own now-open editor for their feature.
describe('DatasetMap attribute-edit dialog respects handleEditAttributeSubmit result (fix #1761 review round 4)', () => {
  beforeEach(() => {
    drawingState.isDrawing = true;
    drawingState.activeMode = 'select';
    drawingState.selectedFeature = { gid: 42, tdId: 'td-1', properties: {} };
    drawingState.isEditDirty = false;
    drawingState.sessionEpoch = 300;
    updateFeatureMutateAsync.mockReset();
  });

  it('keeps the dialog open when the identity changed while the update was in flight', async () => {
    let resolveUpdate!: (value: unknown) => void;
    updateFeatureMutateAsync.mockReturnValueOnce(
      new Promise((res) => {
        resolveUpdate = res;
      }),
    );

    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Edit attributes/i }));
    expect(screen.getByText('Edit Feature Attributes')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));

    // The session moves to another target while the update is in flight. The
    // map re-renders when the write settles, so an epoch bump would also tear
    // the editor down there; a new target leaves it alone.
    drawingState.targetDatasetId = 'dataset-2';

    await act(async () => {
      resolveUpdate({});
      await Promise.resolve();
      await Promise.resolve();
    });

    // Refused as stale: the dialog (a second identity's own editor, in the
    // real scenario) stays open rather than being discarded.
    expect(screen.getByText('Edit Feature Attributes')).toBeInTheDocument();
  });

  it('closes the dialog when the update succeeds and the identity has not changed', async () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="example_table"
        geometryType="Polygon"
        datasetId="dataset-1"
        canEdit
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Edit attributes/i }));
    expect(screen.getByText('Edit Feature Attributes')).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.queryByText('Edit Feature Attributes')).not.toBeInTheDocument();
  });
});

describe('DatasetMap record types', () => {
  beforeEach(() => {
    drawingState.isDrawing = false;
    drawingState.activeMode = null;
    mapSpy.reset();
    mapSpy.attachMapInstance = true;
    (fakeMap.getSource as ReturnType<typeof vi.fn>).mockReset();
    (fakeMap.addSource as ReturnType<typeof vi.fn>).mockClear();
  });

  afterEach(() => {
    mapSpy.reset();
    tileConfigState.data = null;
  });

  // The map loads first; the re-render stands in for the tile-config query settling.
  function loadThenSettleTileConfig(recordType: string) {
    const props = {
      bbox: [-10, -10, 10, 10] as [number, number, number, number],
      tableName: 'cloud',
      geometryType: 'Point',
      datasetId: 'dataset-1',
      recordType,
    };
    const { rerender } = render(<DatasetMap {...props} />);
    tileConfigState.data = { mvt_source_layer_prefix: '' };
    rerender(<DatasetMap {...props} tileVersion="settled" />);
  }

  it('adds the vector source once the tile config settles after load for a vector dataset', () => {
    loadThenSettleTileConfig('vector_dataset');

    expect(fakeMap.addSource).toHaveBeenCalledWith(previewSourceId('cloud'), expect.anything());
  });

  it('adds no vector source for an unknown record type when the tile config settles after load', () => {
    loadThenSettleTileConfig('hologram_dataset');

    expect(fakeMap.addSource).not.toHaveBeenCalledWith(previewSourceId('cloud'), expect.anything());
  });

  it('adds no tile or overlay source for an unknown record type and still reports ready', () => {
    const onMapReady = vi.fn();
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="cloud"
        geometryType="Point"
        datasetId="dataset-1"
        recordType="hologram_dataset"
        onMapReady={onMapReady}
      />,
    );

    expect(fakeMap.addSource).not.toHaveBeenCalled();
    expect(onMapReady).toHaveBeenCalled();
  });

  it.each(['tiles3d_dataset', 'pointcloud_dataset'])('adds no vector source for a %s when the tile config settles after load', (recordType) => {
    loadThenSettleTileConfig(recordType);

    expect(fakeMap.addSource).not.toHaveBeenCalledWith(previewSourceId('cloud'), expect.anything());
  });

  it.each(['tiles3d_dataset', 'pointcloud_dataset'])('adds no tile or overlay source for a %s and still reports ready', (recordType) => {
    const onMapReady = vi.fn();
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="cloud"
        geometryType="Point"
        datasetId="dataset-1"
        recordType={recordType}
        onMapReady={onMapReady}
      />,
    );

    expect(fakeMap.addSource).not.toHaveBeenCalled();
    expect(onMapReady).toHaveBeenCalled();
  });

  it.each(['tiles3d_dataset', 'pointcloud_dataset'])('draws only the extent outline for a %s, with no tile-token request', (recordType) => {
    useTileTokenSpy.mockClear();
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName={null}
        geometryType={null}
        datasetId="dataset-1"
        recordType={recordType}
      />,
    );

    // tileKind is null for these types, so useTileToken must be called with
    // undefined (its `enabled: !!datasetId` gate), never the real dataset id.
    expect(useTileTokenSpy).toHaveBeenCalledWith(undefined);
    expect(mapSpy.sourceData).not.toBeNull();
    expect(screen.getByRole('region', { name: /dataset map/i })).toBeInTheDocument();
  });

  it('carries the dataset attribution on the bbox source for a footprint-only pointcloud', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName={null}
        geometryType={null}
        datasetId="dataset-1"
        recordType="pointcloud_dataset"
        attribution="Autzen Stadium LiDAR (CC BY 4.0)"
      />,
    );

    expect(mapSpy.bboxSourceAttribution).toBe('Autzen Stadium LiDAR (CC BY 4.0)');
  });

  it('does not duplicate the attribution on a vector dataset\'s bbox source (its own vector source already carries it)', () => {
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="cloud"
        geometryType="Point"
        datasetId="dataset-1"
        recordType="vector_dataset"
        attribution="World Countries (public domain)"
      />,
    );

    expect(mapSpy.bboxSourceAttribution).toBeUndefined();
  });
});

describe('DatasetMap basemap switch', () => {
  const NEXT_STYLE: StyleSpecification = { version: 8, sources: {}, layers: [{ id: 'background', type: 'background' }] };

  beforeEach(() => {
    mapSpy.reset();
    mapSpy.attachMapInstance = true;
    (fakeMap.setStyle as ReturnType<typeof vi.fn>).mockReset();
    (fakeMap.getStyle as ReturnType<typeof vi.fn>).mockReturnValue({ version: 8, sources: {}, layers: [] });
  });

  afterEach(() => {
    mapSpy.reset();
    basemapState.data = [];
    (fakeMap.getStyle as ReturnType<typeof vi.fn>).mockReset();
  });

  /** The style transform a vector dataset's preview hands setStyle when it switches to a blank basemap. */
  function switchTransform() {
    basemapState.data = [{ id: 'blank', label: 'Blank', url: BLANK_BASEMAP_ID, enabled: true, is_preset: true }];
    render(
      <DatasetMap
        bbox={[-10, -10, 10, 10]}
        tableName="cloud"
        geometryType="Point"
        datasetId="dataset-1"
        recordType="vector_dataset"
      />,
    );
    const [, { transformStyle }] = (fakeMap.setStyle as ReturnType<typeof vi.fn>).mock.calls[0] as [
      unknown,
      { transformStyle: (previous: StyleSpecification, next: StyleSpecification) => StyleSpecification },
    ];
    return transformStyle;
  }

  it("carries the preview's vector source and layers onto the new basemap and drops the old basemap", () => {
    const transformStyle = switchTransform();
    const sourceId = previewSourceId('cloud');
    const previous: StyleSpecification = {
      version: 8,
      sources: {
        openmaptiles: { type: 'vector', url: 'https://basemap.example.test/tiles.json' },
        [sourceId]: { type: 'vector', tiles: ['https://maps.example.test/api/tiles/data.cloud/{z}/{x}/{y}.pbf'] },
      },
      layers: [
        { id: 'water', type: 'fill', source: 'openmaptiles', 'source-layer': 'water' },
        { id: 'preview-layer-dataset', type: 'circle', source: sourceId, 'source-layer': 'data.cloud' },
      ],
    };

    const merged = transformStyle(previous, NEXT_STYLE);

    expect(Object.keys(merged.sources)).toEqual([sourceId]);
    expect(merged.layers.map((layer) => layer.id)).toEqual(['background', 'preview-layer-dataset']);
  });

  it("drops an old basemap source whose id starts like the preview's", () => {
    const transformStyle = switchTransform();
    const previous: StyleSpecification = {
      version: 8,
      sources: { 'preview-foo': { type: 'vector', url: 'https://basemap.example.test/tiles.json' } },
      layers: [{ id: 'roads', type: 'line', source: 'preview-foo', 'source-layer': 'roads' }],
    };

    const merged = transformStyle(previous, NEXT_STYLE);

    expect(merged.sources).toEqual({});
    expect(merged.layers.map((layer) => layer.id)).toEqual(['background']);
  });
});
