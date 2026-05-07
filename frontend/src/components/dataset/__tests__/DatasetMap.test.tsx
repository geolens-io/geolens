import { render, screen, fireEvent } from '@/test/test-utils';
import { DatasetMap } from '@/components/dataset/DatasetMap';

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
}));

vi.mock('@vis.gl/react-maplibre', () => ({
  Map: ({
    children,
    interactive,
  }: {
    children?: React.ReactNode;
    interactive?: boolean;
  }) => (
    <div data-testid="mapgl" data-interactive={String(interactive)}>
      {children}
    </div>
  ),
  Source: ({ children }: { children?: React.ReactNode }) => children ?? null,
  Layer: () => null,
  NavigationControl: () => <div data-testid="nav-control" />,
}));

vi.mock('@/components/theme-provider', () => ({
  useTheme: () => ({ resolvedTheme: 'light' }),
}));

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({ data: [] }),
  useMapDefaults: () => ({ data: null }),
  useTileConfig: () => ({ data: null }),
}));

vi.mock('@/hooks/use-tile-token', () => ({
  useTileToken: () => ({ data: null }),
}));

vi.mock('@/stores/drawing-store', () => ({
  useDrawingStore: (selector: (state: typeof drawingState) => unknown) => selector(drawingState),
}));

vi.mock('@/components/drawing/hooks/use-terra-draw', () => ({
  useTerraDraw: () => ({
    setMode: vi.fn(),
    isReady: false,
    addFeatures: vi.fn(),
    removeFeatures: vi.fn(),
    selectFeature: vi.fn(),
    getSnapshotFeature: vi.fn(),
    clear: vi.fn(),
    undo: vi.fn(),
    canUndo: false,
  }),
  getModeName: () => 'polygon',
  getAvailableModes: () => ['select', 'point', 'linestring', 'polygon'],
}));

vi.mock('@/hooks/use-features', () => ({
  useCreateFeature: () => ({ mutateAsync: vi.fn() }),
  useUpdateFeature: () => ({ mutateAsync: vi.fn() }),
  useDeleteFeature: () => ({ mutateAsync: vi.fn() }),
}));

vi.mock('@/api/features', () => ({
  getFeature: vi.fn(),
}));

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
