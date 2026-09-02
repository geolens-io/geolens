import { render, screen, fireEvent } from '@/test/test-utils';
import { DatasetMap } from '@/components/dataset/DatasetMap';

// fix(#1004): what the map was actually told to draw and where to point. The
// three camera/extent sites derive from the bbox prop alone, so recording the
// props MapGL and Source receive is enough to pin all three.
const mapSpy = vi.hoisted(() => ({
  initialViewState: null as Record<string, unknown> | null,
  sourceData: null as { features: { geometry: { coordinates: number[][][][] } }[] } | null,
  fitBounds: vi.fn(),
  flyTo: vi.fn(),
  // Opt-in: driving onLoad instantiates the whole tile/recovery wiring, which
  // the other blocks in this file neither need nor mock.
  attachMapInstance: false,
  reset() {
    this.initialViewState = null;
    this.sourceData = null;
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
  setDrawing: vi.fn(),
  setMode: vi.fn(),
  clearDrawing: vi.fn(),
  selectedFeature: null as { gid: number; tdId: string; properties: Record<string, unknown> } | null,
  setSelectedFeature: vi.fn(),
  clearSelectedFeature: vi.fn(),
  setEditDirty: vi.fn(),
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
    Source: ({ children, data }: { children?: React.ReactNode; data?: unknown }) => {
      if (data !== undefined) mapSpy.sourceData = data as typeof mapSpy.sourceData;
      return children ?? null;
    },
    Layer: () => null,
    NavigationControl: () => <div data-testid="nav-control" />,
  };
});

vi.mock('@/components/theme-provider', () => ({
  useTheme: () => ({ resolvedTheme: 'light' }),
}));

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({ data: [] }),
  useMapDefaults: () => ({ data: null }),
  useTileConfig: () => ({ data: null }),
}));

vi.mock('@/hooks/use-tile-token', () => ({
  useInvalidateTileTokens: () => vi.fn(),
  useTileToken: () => ({ data: null }),
}));

vi.mock('@/stores/drawing-store', () => {
  const useDrawingStore = (selector: (state: typeof drawingState) => unknown) => selector(drawingState);
  // fix(#1761 review round 3 P1): finishDrawingSession reads
  // useDrawingStore.getState() directly (not via the selector hook), the
  // same static-access pattern the real zustand store supports.
  useDrawingStore.getState = () => drawingState;
  return { useDrawingStore };
});

// fix(#1761 review round 3 P1): a stable hoisted object (not a fresh
// literal per render) so a test can hold onto `terraDrawState.clear` and
// assert it was invoked by the identity-change cleanup effect.
const terraDrawState = vi.hoisted(() => ({
  setMode: vi.fn(),
  isReady: false,
  addFeatures: vi.fn(),
  removeFeatures: vi.fn(),
  selectFeature: vi.fn(),
  getSnapshotFeature: vi.fn(),
  clear: vi.fn(),
  undo: vi.fn(),
  canUndo: false,
}));

vi.mock('@/components/drawing/hooks/use-terra-draw', () => ({
  useTerraDraw: () => terraDrawState,
  getModeName: () => 'polygon',
  getAvailableModes: vi.fn(() => ['select', 'point', 'linestring', 'polygon']),
}));

import { getAvailableModes } from '@/components/drawing/hooks/use-terra-draw';

vi.mock('@/hooks/use-features', () => ({
  useCreateFeature: () => ({ mutateAsync: vi.fn() }),
  useUpdateFeature: () => ({ mutateAsync: vi.fn() }),
  useDeleteFeature: () => ({ mutateAsync: vi.fn() }),
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

describe('DatasetMap interaction state', () => {
  beforeEach(() => {
    drawingState.isDrawing = false;
    drawingState.activeMode = null;
    drawingState.setDrawing.mockReset();
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
  });
});
