// DatasetPage offers its feature-table and map-layer actions only for record
// types whose capabilities include them.
import { act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useParams } from 'react-router';
import { render, screen, within } from '@/test/test-utils';
import { useDataset, useUpdateDataset } from '@/components/dataset/hooks/use-dataset';
import { useAuthStore } from '@/stores/auth-store';
import { DatasetPage } from '@/pages/DatasetPage';
import type { DatasetResponse, RecordType, UserResponse } from '@/types/api';

const permissions = vi.hoisted(() => ({ editMetadata: true }));
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({ can: (capability: string) => capability === 'edit_metadata' && permissions.editMetadata }),
}));

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return {
    ...actual,
    useParams: vi.fn(),
  };
});

vi.mock('@/hooks/use-unsaved-guard', () => ({
  useUnsavedGuard: () => ({ state: 'unblocked', reset: vi.fn(), proceed: vi.fn() }),
}));

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDataset: vi.fn(),
  useUpdateDataset: vi.fn(),
  useSetTargetStatus: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useValidation: () => ({ data: { errors: [], warnings: [] } }),
  useDatasetVersions: () => ({ data: { versions: [], total: 0 }, isLoading: false }),
  useDatasetRefreshRuns: () => ({
    data: { runs: [], total: 0 },
    isLoading: false,
    isError: false,
    isFetching: false,
  }),
  useCancelRefreshJob: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAttributes: () => ({ data: [] }),
  useUpdateAttribute: () => ({ mutateAsync: vi.fn() }),
  useDatasetHistory: () => ({ data: { history: [], total: 0 }, isLoading: false }),
  useDatasetRows: () => ({ data: { rows: [], total: 0 }, isLoading: false }),
  useDatasetRefreshWatch: () => ({ latestRun: undefined, isBusy: false, trackDispatchedRun: vi.fn() }),
}));

vi.mock('@/hooks/use-settings', () => ({
  useAllSettings: () => ({ data: { tabs: { general: [] } } }),
  useFeatureFlags: () => ({ data: { enable_dataset_editing: true, require_metadata_for_publish: false } }),
  useTileConfig: () => ({ data: null }),
}));

vi.mock('@/hooks/use-mobile', () => ({
  useIsMobile: () => false,
}));

const drawingStoreState = vi.hoisted(() => ({
  isDrawing: false,
  isEditDirty: false,
  setDrawing: vi.fn(),
  clearDrawing: vi.fn(),
}));
vi.mock('@/stores/drawing-store', () => ({
  useDrawingStore: (selector: (state: typeof drawingStoreState) => unknown) => selector(drawingStoreState),
}));

const mapInstances = vi.hoisted(() => ({ count: 0 }));

vi.mock('@/components/dataset/DatasetMap', async () => {
  const { useState } = await import('react');
  return {
    DatasetMap: ({ canEdit, bbox, shortcutsEnabled }: {
      canEdit?: boolean;
      bbox?: [number, number, number, number] | null;
      shortcutsEnabled?: boolean;
    }) => {
      const [instance] = useState(() => ++mapInstances.count);
      return (
        <div
          data-testid="dataset-map"
          data-can-edit={String(Boolean(canEdit))}
          data-instance={instance}
          data-bbox={bbox ? JSON.stringify(bbox) : ''}
          data-shortcuts-enabled={String(shortcutsEnabled !== false)}
        />
      );
    },
  };
});

vi.mock('@/components/dataset/ReuploadDialog', () => ({
  ReuploadDialog: () => <div data-testid="reupload-dialog" />,
}));

vi.mock('@/components/dataset/AddToMapButton', () => ({
  AddToMapButton: () => <button type="button">Add to map</button>,
}));

vi.mock('@/components/dataset/DatasetChatPanel', () => ({
  DatasetChatPanel: () => <div data-testid="dataset-chat-panel" />,
}));

vi.mock('@/components/import/hooks/use-vrt', () => ({
  useVrtGenerations: () => ({ data: { generations: [] } }),
  useVrtStatus: () => ({ data: null }),
}));

vi.mock('@/components/dataset/DatasetDeleteDialog', () => ({
  DatasetDeleteDialog: () => null,
}));

vi.mock('@/components/dataset/DatasetDetailSkeleton', () => ({
  DatasetDetailSkeleton: () => <div data-testid="dataset-detail-skeleton" />,
}));

vi.mock('@/components/dataset/tabs/StructureTab', () => ({
  StructureTab: () => <div data-testid="structure-tab-stub" />,
}));

vi.mock('@/components/dataset/tabs/MetadataTab', () => ({
  MetadataTab: () => <div data-testid="metadata-tab-stub" />,
}));

vi.mock('@/components/dataset/ValidationStatus', () => ({
  ValidationStatus: () => <span data-testid="validation-status-compact">validation</span>,
}));

vi.mock('@/components/search/RecordTypeBadge', () => ({
  RecordTypeBadge: () => <span data-testid="record-type-badge" />,
}));

vi.mock('@/hooks/use-admin', () => ({
  useAIStatus: () => ({ data: { enabled: false, configured: false } }),
}));

vi.mock('@/hooks/use-ai-metadata', () => ({
  useSummaryDraft: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useKeywordSuggestions: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useLineageDraft: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('@/components/dataset/hooks/use-records', () => ({
  useCreateKeyword: () => ({ mutateAsync: vi.fn() }),
  useKeywords: () => ({ data: { keywords: [] } }),
  useDistributions: () => ({ data: { distributions: [], total: 0 }, isLoading: false }),
}));

vi.mock('@/components/collections/DatasetCollectionBadges', () => ({
  DatasetCollectionBadges: () => null,
}));

vi.mock('@/components/dataset/ContactsEditor', () => ({
  ContactsEditor: () => <div data-testid="contacts-editor-stub" />,
}));

vi.mock('@/components/dataset/KeywordsEditor', () => ({
  KeywordsEditor: () => <div data-testid="keywords-editor-stub" />,
}));

vi.mock('@/components/dataset/AiAssistButton', () => ({
  AiAssistButton: () => null,
  AiDraftPreview: () => null,
  AiKeywordSuggestions: () => null,
}));

vi.mock('@/components/dataset/VersionHistory', () => ({
  VersionHistory: () => <div data-testid="version-history-stub" />,
}));

vi.mock('@/components/dataset/ChangeHistory', () => ({
  ChangeHistory: () => <div data-testid="change-history-stub" />,
}));

vi.mock('@/components/dataset/QualityScoreCard', () => ({
  QualityScoreCard: () => <div data-testid="quality-score-card-stub" />,
}));

vi.mock('@/components/dataset/RelatedDatasets', () => ({
  RelatedDatasets: () => null,
}));

vi.mock('@/components/dataset/UsedInMaps', () => ({
  UsedInMaps: () => null,
}));

const OWNER: UserResponse = {
  id: 'user-editor',
  username: 'editor-user',
  email: 'editor@example.com',
  is_active: true,
  status: 'active',
  last_login_at: null,
  created_at: '2026-03-01T00:00:00Z',
  roles: ['editor'],
};

function makeDataset(recordType: string): DatasetResponse {
  return {
    id: 'dataset-1',
    record_id: 'record-1',
    table_name: 'world_countries',
    title: 'World Countries',
    summary: 'Country boundaries',
    srid: 4326,
    geometry_type: 'Polygon',
    feature_count: 195,
    extent_bbox: [-180, -90, 180, 90],
    column_info: [{ name: 'name', type: 'text' }],
    license: null,
    attribution: null,
    source_organization: null,
    data_vintage_start: null,
    data_vintage_end: null,
    source_format: 'GeoJSON',
    source_filename: 'countries.geojson',
    original_srid: 4326,
    visibility: 'public',
    created_by: OWNER.id,
    created_by_display: OWNER.username,
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-02T00:00:00Z',
    last_edited_by_display: null,
    last_edited_at: null,
    record_status: 'published',
    lineage_summary: null,
    update_frequency: null,
    usage_constraints: null,
    access_constraints: null,
    sensitivity_classification: null,
    theme_category: null,
    owner_org: null,
    published_at: '2026-03-02T00:00:00Z',
    updated_by: null,
    current_version: 1,
    source_url: null,
    quality_statement: null,
    collections: [],
    tile_columns: null,
    record_type: recordType as RecordType,
    raster: null,
  };
}

async function renderAs(recordType: string) {
  vi.mocked(useDataset).mockReturnValue({
    data: makeDataset(recordType),
    isLoading: false,
    error: null,
  } as ReturnType<typeof useDataset>);
  render(<DatasetPage />, { route: '/datasets/dataset-1' });
  return screen.findByTestId('dataset-map');
}

// Opened last: an open menu hides the rest of the page from role queries.
async function openMoreActions() {
  await userEvent.setup().click(screen.getByRole('button', { name: 'More actions' }));
  await screen.findByRole('menuitem', { name: 'Delete' });
}

describe('DatasetPage actions by record type', () => {
  beforeEach(() => {
    permissions.editMetadata = true;
    drawingStoreState.isDrawing = false;
    drawingStoreState.isEditDirty = false;
    vi.mocked(useParams).mockReturnValue({ id: 'dataset-1' });
    vi.mocked(useUpdateDataset).mockReturnValue({
      mutateAsync: vi.fn(),
    } as unknown as ReturnType<typeof useUpdateDataset>);
    act(() => {
      useAuthStore.setState({
        user: OWNER,
        token: 'token',
        refreshToken: 'refresh-token',
        expiresAt: Date.now() + 60_000,
      });
    });
  });

  afterEach(() => {
    act(() => {
      useAuthStore.setState({ user: null, token: null, refreshToken: null, expiresAt: null });
    });
  });

  it('offers the table readout, re-upload, Add to map, editing and AI chat for a vector dataset', async () => {
    const map = await renderAs('vector_dataset');

    expect(screen.getByTestId('dataset-table-readout')).toBeInTheDocument();
    expect(
      within(screen.getByTestId('dataset-table-readout')).getByRole('button'),
    ).toHaveClass('pointer-coarse:size-11');
    expect(screen.getByRole('button', { name: 'Add to map' })).toBeInTheDocument();
    expect(map).toHaveAttribute('data-can-edit', 'true');
    expect(screen.getByTestId('dataset-chat-panel')).toBeInTheDocument();
    await openMoreActions();
    expect(screen.getByRole('menuitem', { name: 'Re-Upload' })).toBeInTheDocument();
    expect(screen.getByTestId('reupload-dialog')).toBeInTheDocument();
  });

  it('offers Add to map to a capable viewer who does not own the dataset', async () => {
    act(() => { useAuthStore.setState({ user: { ...OWNER, id: 'reader-id', roles: ['viewer'] } }); });
    await renderAs('vector_dataset');
    expect(screen.getByRole('button', { name: 'Add to map' })).toBeInTheDocument();
  });

  it('hides Add to map from an editor without the effective capability', async () => {
    permissions.editMetadata = false;
    await renderAs('vector_dataset');
    expect(screen.queryByRole('button', { name: 'Add to map' })).not.toBeInTheDocument();
  });

  it('offers none of them for an unknown record type', async () => {
    const map = await renderAs('hologram_dataset');

    expect(screen.queryByTestId('dataset-table-readout')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add to map' })).not.toBeInTheDocument();
    expect(map).toHaveAttribute('data-can-edit', 'false');
    expect(screen.queryByTestId('dataset-chat-panel')).not.toBeInTheDocument();
    await openMoreActions();
    expect(screen.queryByRole('menuitem', { name: 'Re-Upload' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('reupload-dialog')).not.toBeInTheDocument();
  });

  it('keeps the map preview for a vector dataset', async () => {
    await renderAs('vector_dataset');

    expect(screen.getByRole('region', { name: 'Map Preview' })).toBeInTheDocument();
  });

  it('has no map preview and none of the table actions for a 3D Tiles tileset with no extent', async () => {
    vi.mocked(useDataset).mockReturnValue({
      data: {
        ...makeDataset('tiles3d_dataset'),
        geometry_type: null,
        feature_count: null,
        column_info: null,
        extent_bbox: null,
      },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useDataset>);
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    await screen.findByRole('tab', { name: 'Overview' });
    expect(screen.queryByRole('region', { name: 'Map Preview' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('dataset-map')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add to map' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('dataset-table-readout')).not.toBeInTheDocument();
  });

  it('shows the extent as a map preview for a 3D Tiles tileset that has one', async () => {
    vi.mocked(useDataset).mockReturnValue({
      data: { ...makeDataset('tiles3d_dataset'), geometry_type: null, feature_count: null, column_info: null },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useDataset>);
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    await screen.findByRole('tab', { name: 'Overview' });
    const map = await screen.findByTestId('dataset-map');
    expect(screen.getByRole('region', { name: 'Map Preview' })).toBeInTheDocument();
    expect(map).toHaveAttribute('data-bbox', JSON.stringify([-180, -90, 180, 90]));
    // The 3D Tiles page keeps its own facts/connection content; adding a
    // footprint preview does not turn on feature-table actions.
    expect(screen.queryByRole('button', { name: 'Add to map' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('dataset-table-readout')).not.toBeInTheDocument();
  });

  it('shows a point cloud without a map preview or table actions when it has no extent', async () => {
    vi.mocked(useDataset).mockReturnValue({
      data: {
        ...makeDataset('pointcloud_dataset'),
        geometry_type: null,
        feature_count: null,
        column_info: null,
        extent_bbox: null,
        pointcloud: {
          url: '/api/datasets/dataset-1/copc/attempt-1/data.copc.laz',
          size_bytes: 1048576,
          point_count: 9000,
          point_format: 7,
          vertical_crs: null,
        },
      },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useDataset>);
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    expect(await screen.findByRole('heading', { name: 'COPC point cloud' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Map Preview' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('dataset-map')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add to map' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('dataset-table-readout')).not.toBeInTheDocument();
  });

  it('shows the extent as a map preview for a point cloud that has one', async () => {
    vi.mocked(useDataset).mockReturnValue({
      data: {
        ...makeDataset('pointcloud_dataset'),
        geometry_type: null,
        feature_count: null,
        column_info: null,
        pointcloud: {
          url: '/api/datasets/dataset-1/copc/attempt-1/data.copc.laz',
          size_bytes: 1048576,
          point_count: 9000,
          point_format: 7,
          vertical_crs: null,
        },
      },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useDataset>);
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    expect(await screen.findByRole('heading', { name: 'COPC point cloud' })).toBeInTheDocument();
    const map = await screen.findByTestId('dataset-map');
    expect(screen.getByRole('region', { name: 'Map Preview' })).toBeInTheDocument();
    expect(map).toHaveAttribute('data-bbox', JSON.stringify([-180, -90, 180, 90]));
    expect(screen.queryByRole('button', { name: 'Add to map' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('dataset-table-readout')).not.toBeInTheDocument();
  });

  it('resets an expanded Data tab when navigating to a dataset with a footprint-only map preview', async () => {
    vi.mocked(useDataset).mockImplementation(((datasetId: string) => ({
      data: datasetId === 'dataset-2'
        ? {
            ...makeDataset('pointcloud_dataset'),
            id: 'dataset-2',
            geometry_type: null,
            feature_count: null,
            column_info: null,
            pointcloud: {
              url: '/api/datasets/dataset-2/copc/attempt-1/data.copc.laz',
              size_bytes: 1048576,
              point_count: 9000,
              point_format: 7,
              vertical_crs: null,
            },
          }
        : makeDataset('vector_dataset'),
      isLoading: false,
      error: null,
    })) as unknown as typeof useDataset);
    const { rerender } = render(<DatasetPage />, { route: '/datasets/dataset-1' });
    await screen.findByTestId('dataset-map');

    const user = userEvent.setup();
    await user.click(screen.getByRole('tab', { name: 'Data' }));
    await user.click(await screen.findByRole('button', { name: 'Expand table' }));
    // Sanity: expanding the Data tab hides the map preview on THIS dataset too.
    expect(screen.queryByRole('region', { name: 'Map Preview' })).not.toBeInTheDocument();

    vi.mocked(useParams).mockReturnValue({ id: 'dataset-2' });
    rerender(<DatasetPage />);

    expect(await screen.findByRole('region', { name: 'Map Preview' })).toBeInTheDocument();
    // Not just present: a stale activeTab of 'data' (a tab pointcloud_dataset
    // doesn't have) would otherwise render this in its collapsed task-tab
    // state, behind a "Show map preview" toggle that only exists there.
    expect(screen.queryByRole('button', { name: /map preview/i })).not.toBeInTheDocument();
    expect(document.getElementById('dataset-map-preview')).not.toHaveClass('hidden');
  });

  it('keeps the same DatasetMap instance mounted through a Data-tab expand and collapse while a drawing session is dirty', async () => {
    drawingStoreState.isDrawing = true;
    drawingStoreState.isEditDirty = true;
    const map = await renderAs('vector_dataset');
    const instanceBefore = map.getAttribute('data-instance');

    const user = userEvent.setup();
    await user.click(screen.getByRole('tab', { name: 'Data' }));
    await user.click(await screen.findByRole('button', { name: 'Expand table' }));

    // The map preview section is hidden (not unmounted) while the Data tab
    // is expanded — hiding it, instead of unmounting it, keeps the same
    // DatasetMap (and its TerraDraw instance) alive, so an in-progress edit
    // — which lives only in that instance — survives.
    expect(screen.getByRole('region', { name: 'Map Preview' })).toHaveClass('hidden');
    expect(screen.getByTestId('dataset-map')).toHaveAttribute('data-instance', instanceBefore);
    // Hidden but mounted still handles document-level keydowns unless told
    // not to: shortcutsEnabled must go false so it can't act on geometry
    // the user can't see.
    expect(screen.getByTestId('dataset-map')).toHaveAttribute('data-shortcuts-enabled', 'false');

    await user.click(screen.getByRole('button', { name: 'Collapse table' }));

    expect(screen.getByRole('region', { name: 'Map Preview' })).not.toHaveClass('hidden');
    expect(screen.getByTestId('dataset-map')).toHaveAttribute('data-instance', instanceBefore);
    expect(screen.getByTestId('dataset-map')).toHaveAttribute('data-shortcuts-enabled', 'true');
  });

  it('gives an unknown record type its own map after a vector dataset', async () => {
    vi.mocked(useDataset).mockImplementation(((id: string) => ({
      data: id === 'dataset-2'
        ? { ...makeDataset('hologram_dataset'), id: 'dataset-2' }
        : makeDataset('vector_dataset'),
      isLoading: false,
      error: null,
    })) as unknown as typeof useDataset);
    const { rerender } = render(<DatasetPage />, { route: '/datasets/dataset-1' });
    const vectorMap = (await screen.findByTestId('dataset-map')).getAttribute('data-instance');

    vi.mocked(useParams).mockReturnValue({ id: 'dataset-2' });
    rerender(<DatasetPage />);

    await waitFor(() => {
      expect(screen.getByTestId('dataset-map')).not.toHaveAttribute('data-instance', vectorMap);
    });
  });

  it('gives a cached vector dataset its own map after another vector dataset', async () => {
    vi.mocked(useDataset).mockImplementation(((id: string) => ({
      data: id === 'dataset-2'
        ? { ...makeDataset('vector_dataset'), id: 'dataset-2', table_name: 'other_table' }
        : makeDataset('vector_dataset'),
      isLoading: false,
      error: null,
    })) as unknown as typeof useDataset);
    const { rerender } = render(<DatasetPage />, { route: '/datasets/dataset-1' });
    const firstMap = (await screen.findByTestId('dataset-map')).getAttribute('data-instance');

    vi.mocked(useParams).mockReturnValue({ id: 'dataset-2' });
    rerender(<DatasetPage />);

    await waitFor(() => {
      expect(screen.getByTestId('dataset-map')).not.toHaveAttribute('data-instance', firstMap);
    });
  });

  it('keeps the same map instance across a re-render of the same dataset, such as a query refetch', async () => {
    vi.mocked(useDataset).mockReturnValue({
      data: makeDataset('vector_dataset'),
      isLoading: false,
      error: null,
    } as ReturnType<typeof useDataset>);
    const { rerender } = render(<DatasetPage />, { route: '/datasets/dataset-1' });
    const instance = (await screen.findByTestId('dataset-map')).getAttribute('data-instance');

    // A refetch hands back a new dataset object with the same id and fields.
    vi.mocked(useDataset).mockReturnValue({
      data: makeDataset('vector_dataset'),
      isLoading: false,
      error: null,
    } as ReturnType<typeof useDataset>);
    rerender(<DatasetPage />);

    expect(screen.getByTestId('dataset-map')).toHaveAttribute('data-instance', instance);
  });
});
