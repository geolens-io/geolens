import React from 'react';
import { render, screen, act } from '@/test/test-utils';
import { useParams } from 'react-router';
import { useDataset, useUpdateDataset } from '@/components/dataset/hooks/use-dataset';
import { useAuthStore } from '@/stores/auth-store';
import { DatasetPage } from '@/pages/DatasetPage';
import type { DatasetResponse, UserResponse } from '@/types/api';

const drawingStoreState = vi.hoisted(() => ({
  isDrawing: false,
  isEditDirty: false,
  setDrawing: vi.fn(),
  clearDrawing: vi.fn(),
}));

/** When true, the DatasetMap mock auto-fires onMapReady after render */
const mockMapConfig = vi.hoisted(() => ({
  autoFireMapReady: false,
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
  useAttributes: () => ({ data: [] }),
  useUpdateAttribute: () => ({ mutateAsync: vi.fn() }),
  useDatasetHistory: () => ({ data: { history: [], total: 0 }, isLoading: false }),
  useDatasetRows: () => ({ data: { rows: [], total: 0 }, isLoading: false }),
  // fix(#1285 codex round 4): mounted at the page level now.
  useDatasetRefreshWatch: () => ({ latestRun: undefined, isBusy: false, trackDispatchedRun: vi.fn() }),
}));

vi.mock('@/hooks/use-settings', () => ({
  useAllSettings: () => ({ data: { tabs: { general: [] } } }),
  useFeatureFlags: () => ({ data: { enable_dataset_editing: false, require_metadata_for_publish: false } }),
  useTileConfig: () => ({ data: null }),
}));

vi.mock('@/hooks/use-mobile', () => ({
  useIsMobile: () => false,
}));

vi.mock('@/stores/drawing-store', () => ({
  useDrawingStore: (selector: (state: {
    isDrawing: boolean;
    isEditDirty: boolean;
    setDrawing: () => void;
    clearDrawing: () => void;
  }) => unknown) => selector(drawingStoreState),
}));

vi.mock('@/components/dataset/DatasetMap', () => ({
  DatasetMap: (props: { onMapReady?: () => void; onTileError?: () => void }) => {
    const { onMapReady, onTileError } = props;
    React.useEffect(() => {
      if (mockMapConfig.autoFireMapReady && onMapReady) {
        onMapReady();
      }
    }, [onMapReady]);
    return (
      <div
        data-testid="dataset-map"
        data-has-on-map-ready={String(!!onMapReady)}
        data-has-on-tile-error={String(!!onTileError)}
      />
    );
  },
}));

vi.mock('@/components/import/hooks/use-vrt', () => ({
  useVrtGenerations: () => ({ data: { generations: [] } }),
  useVrtStatus: () => ({ data: null }),
}));

vi.mock('@/components/dataset/DatasetDeleteDialog', () => ({
  DatasetDeleteDialog: () => null,
}));

vi.mock('@/components/dataset/ReuploadDialog', () => ({
  // codex(#1362 r1): exposes onReplaceComplete as a clickable stub so tests
  // can simulate "a raster reupload job just completed" without driving the
  // full dialog flow (that flow is covered in ReuploadDialog.test.tsx).
  ReuploadDialog: (props: { onReplaceComplete?: () => void }) => (
    <button
      type="button"
      data-testid="reupload-dialog-stub"
      onClick={() => props.onReplaceComplete?.()}
    >
      reupload dialog stub
    </button>
  ),
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

const mockUseParams = vi.mocked(useParams);
const mockUseDataset = vi.mocked(useDataset);
const mockUseUpdateDataset = vi.mocked(useUpdateDataset);

const EDITOR_USER: UserResponse = {
  id: 'user-editor',
  username: 'editor-user',
  email: 'editor@example.com',
  is_active: true,
  status: 'active',
  last_login_at: null,
  created_at: '2026-03-01T00:00:00Z',
  roles: ['editor'],
};

function makeDataset(overrides: Partial<DatasetResponse> = {}): DatasetResponse {
  return {
    id: 'dataset-1',
    record_id: 'record-1',
    table_name: 'world_countries',
    title: 'World Countries',
    summary: 'Original summary',
    srid: 4326,
    geometry_type: 'Polygon',
    feature_count: 195,
    extent_bbox: [-180, -90, 180, 90],
    column_info: [{ name: 'name', type: 'text' }],
    license: null,
    source_organization: 'Natural Earth',
    data_vintage_start: null,
    data_vintage_end: null,
    source_format: 'GeoJSON',
    source_filename: 'countries.geojson',
    original_srid: 4326,
    visibility: 'public',
    created_by: 'user-editor',
    created_by_display: 'editor-user',
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-02T00:00:00Z',
    last_edited_by_display: 'editor-user',
    last_edited_at: '2026-03-02T00:00:00Z',
    record_status: 'published',
    lineage_summary: null,
    update_frequency: null,
    usage_constraints: null,
    access_constraints: null,
    sensitivity_classification: null,
    theme_category: [],
    owner_org: null,
    published_at: '2026-03-02T00:00:00Z',
    updated_by: 'user-editor',
    current_version: 1,
    source_url: null,
    quality_statement: null,
    collections: [],
    record_type: 'vector_dataset',
    raster: null,
    ...overrides,
    tile_columns: overrides.tile_columns ?? null,
  };
}

function setUser(user: UserResponse | null) {
  const state = useAuthStore.getState();
  act(() => {
    useAuthStore.setState({
      ...state,
      user,
      token: user ? 'token' : null,
      refreshToken: user ? 'refresh-token' : null,
      expiresAt: user ? Date.now() + 60_000 : null,
    });
  });
}

function setup(datasetOverrides: Partial<DatasetResponse> = {}) {
  mockUseParams.mockReturnValue({ id: 'dataset-1' });
  mockUseDataset.mockReturnValue({
    data: makeDataset(datasetOverrides),
    isLoading: false,
    error: null,
  } as ReturnType<typeof useDataset>);
  mockUseUpdateDataset.mockReturnValue({
    mutateAsync: vi.fn(),
  } as unknown as ReturnType<typeof useUpdateDataset>);
  setUser(EDITOR_USER);
}

describe('DatasetPage hero state machine', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    drawingStoreState.isDrawing = false;
    drawingStoreState.isEditDirty = false;
    mockMapConfig.autoFireMapReady = false;
  });

  afterEach(() => {
    vi.useRealTimers();
    setUser(null);
  });

  it('shows skeleton loading state for raster datasets initially', async () => {
    setup({ record_type: 'raster_dataset', raster: { tile_url: '/raster-tiles/test/{z}/{x}/{y}.png' } as DatasetResponse['raster'] });
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    // PERF-06 (Phase 274): DatasetMap is lazy-loaded — flush the dynamic
    // import microtask under fake timers so the lazy module resolves before
    // we assert the mock is in the DOM. After this first test, the lazy
    // module is cached for the rest of the suite.
    await act(async () => {});

    expect(screen.getByTestId('hero-skeleton')).toBeInTheDocument();
    expect(screen.getByTestId('dataset-map')).toBeInTheDocument();
  });

  it('shows skeleton loading state for VRT datasets initially', () => {
    setup({ record_type: 'vrt_dataset', raster: { tile_url: '/raster-tiles/test/{z}/{x}/{y}.png', vrt_type: 'mosaic' } as DatasetResponse['raster'] });
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    expect(screen.getByTestId('hero-skeleton')).toBeInTheDocument();
    expect(screen.getByTestId('dataset-map')).toBeInTheDocument();
  });

  it('transitions from loading to loaded when onMapReady fires', async () => {
    mockMapConfig.autoFireMapReady = true;
    setup({ record_type: 'raster_dataset', raster: { tile_url: '/raster-tiles/test/{z}/{x}/{y}.png' } as DatasetResponse['raster'] });
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    // Flush pending effects and timers so onMapReady state update propagates
    await act(async () => {
      vi.runAllTimers();
    });

    expect(screen.queryByTestId('hero-skeleton')).not.toBeInTheDocument();
    expect(screen.getByTestId('dataset-map')).toBeInTheDocument();
  });

  it('vector datasets use the hero state machine: skeleton until onMapReady', async () => {
    mockMapConfig.autoFireMapReady = true;
    setup({ record_type: 'vector_dataset' });
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    // Flush the lazy DatasetMap import so the mock mounts and auto-fires
    // onMapReady; running the 10s timeout timer here would race it.
    await act(async () => {});

    expect(screen.getByTestId('dataset-map')).toHaveAttribute('data-has-on-map-ready', 'true');
    expect(screen.queryByTestId('hero-skeleton')).not.toBeInTheDocument();
    expect(screen.queryByText('Preview unavailable')).not.toBeInTheDocument();
  });

  it('shows error overlay with retry button when heroState is error (via timeout)', () => {
    setup({ record_type: 'raster_dataset', raster: { tile_url: '/raster-tiles/test/{z}/{x}/{y}.png' } as DatasetResponse['raster'] });
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    // Trigger 10s timeout
    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    expect(screen.getByText('Preview unavailable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('hides retry button after 3 retries and shows processing message', async () => {
    setup({ record_type: 'raster_dataset', raster: { tile_url: '/raster-tiles/test/{z}/{x}/{y}.png' } as DatasetResponse['raster'] });
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    // Trigger timeout then retry 3 times
    for (let i = 0; i < 3; i++) {
      act(() => { vi.advanceTimersByTime(10_000); });
      const retryBtn = screen.getByRole('button', { name: 'Retry' });
      act(() => { retryBtn.click(); });
    }

    // After 3rd retry, trigger timeout again
    act(() => { vi.advanceTimersByTime(10_000); });

    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.getByText('Tiles may still be processing')).toBeInTheDocument();
  });

  // codex(#1362 r1): a raster's tile URL is a fixed per-dataset route (not
  // content-versioned), and the hero map's MapLibre raster source is added
  // once and never re-added on prop change — so ReuploadDialog's
  // onReplaceComplete is wired to handleRetry (the same remount mechanism
  // the manual Retry button uses) to pick up a completed replacement.
  // codex(#1362 r4): onReplaceComplete must remount the hero map WITHOUT
  // spending the manual-retry budget — a successful replace is not a failed
  // retry, and routing it through handleRetry would leave a later genuine
  // tile failure unretryable once 3 replaces (or a mix of retries/replaces)
  // had accumulated.
  it('wires ReuploadDialog onReplaceComplete to a remount that resets the manual-retry budget', () => {
    setup({ record_type: 'raster_dataset', raster: { tile_url: '/raster-tiles/test/{z}/{x}/{y}.png' } as DatasetResponse['raster'] });
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    // Exhaust the manual-retry budget via the error overlay first.
    for (let i = 0; i < 3; i++) {
      act(() => { vi.advanceTimersByTime(10_000); });
      const retryBtn = screen.getByRole('button', { name: 'Retry' });
      act(() => { retryBtn.click(); });
    }
    act(() => { vi.advanceTimersByTime(10_000); });
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.getByText('Tiles may still be processing')).toBeInTheDocument();

    // A raster replacement completes — must hand back a fresh budget rather
    // than push retryCount even further past the cutoff.
    const replaceStub = screen.getByTestId('reupload-dialog-stub');
    act(() => { replaceStub.click(); });

    // A genuine tile failure on the freshly remounted hero must be
    // retryable again, proving the budget was reset, not spent.
    act(() => { vi.advanceTimersByTime(10_000); });
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('vector datasets pass onMapReady/onTileError to DatasetMap', () => {
    setup({ record_type: 'vector_dataset' });
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    const map = screen.getByTestId('dataset-map');
    expect(map).toHaveAttribute('data-has-on-map-ready', 'true');
    expect(map).toHaveAttribute('data-has-on-tile-error', 'true');
  });

  it('table datasets do not pass onMapReady/onTileError to DatasetMap', () => {
    setup({ record_type: 'table' });
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    const map = screen.queryByTestId('dataset-map');
    if (map) {
      expect(map).toHaveAttribute('data-has-on-map-ready', 'false');
      expect(map).toHaveAttribute('data-has-on-tile-error', 'false');
    }
  });
});

describe('DatasetPage no-tile badge', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    drawingStoreState.isDrawing = false;
    drawingStoreState.isEditDirty = false;
    mockMapConfig.autoFireMapReady = false;
  });

  afterEach(() => {
    vi.useRealTimers();
    setUser(null);
  });

  it('shows "No raster tiles available" badge for raster dataset with null tile_url', async () => {
    setup({
      record_type: 'raster_dataset',
      raster: { tile_url: null, band_count: 3 } as DatasetResponse['raster'],
    });

    await act(async () => {
      render(<DatasetPage />, { route: '/datasets/dataset-1' });
    });

    // Badge appears immediately — no timeout or mock onMapReady needed
    expect(screen.getByText('No raster tiles available')).toBeInTheDocument();
    expect(screen.queryByTestId('hero-skeleton')).not.toBeInTheDocument();
  });

  it('does not show no-tile badge for raster dataset WITH tile_url', () => {
    setup({
      record_type: 'raster_dataset',
      raster: { tile_url: '/raster-tiles/xyz/{z}/{x}/{y}.png', band_count: 3 } as DatasetResponse['raster'],
    });
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    expect(screen.queryByText('No raster tiles available')).not.toBeInTheDocument();
  });

  it('does not show no-tile badge for vector dataset', () => {
    setup({ record_type: 'vector_dataset' });
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    expect(screen.queryByText('No raster tiles available')).not.toBeInTheDocument();
  });
});

describe('DatasetPage header status badge', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    drawingStoreState.isDrawing = false;
    drawingStoreState.isEditDirty = false;
    mockMapConfig.autoFireMapReady = false;
  });

  afterEach(() => {
    vi.useRealTimers();
    setUser(null);
  });

  // fix(#430 V-07): "Private" badge alone next to the "Unpublish" action read as a
  // contradiction (no visible cue explaining why "Unpublish" was offered).
  // Catalog publish-state and access visibility are orthogonal — both axes
  // are now always labeled explicitly ("Catalog: <status>" / "Access:
  // <visibility>") so a published-but-private dataset reads unambiguously.
  it('shows an explicit "Catalog: Published" badge alongside "Access: Private" for a published-but-private dataset', () => {
    setup({ record_status: 'published', visibility: 'private' });
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    expect(screen.getByText('Catalog: Published')).toBeInTheDocument();
    expect(screen.getByText('Access: Private')).toBeInTheDocument();
  });

  it('shows an explicit "Catalog: Draft" badge for a draft dataset', () => {
    setup({ record_status: 'draft', visibility: 'private' });
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    expect(screen.getByText('Catalog: Draft')).toBeInTheDocument();
    expect(screen.getByText('Access: Private')).toBeInTheDocument();
  });

  it('wires detail freshness and health fields into header chips', () => {
    setup({ source_freshness: 'overdue', source_health: 'missing' });
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    expect(screen.getByTestId('source-freshness-chip')).toHaveAttribute('data-state', 'overdue');
    expect(screen.getByText('Source refresh overdue')).toBeVisible();
    expect(screen.getByTestId('source-health-chip')).toHaveAttribute('data-state', 'missing');
    expect(screen.getByText('Source missing')).toBeVisible();
  });

  it('omits header chips for unknown source state', () => {
    setup({ source_freshness: 'unknown', source_health: 'unknown' });
    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    expect(screen.queryByTestId('source-freshness-chip')).not.toBeInTheDocument();
    expect(screen.queryByTestId('source-health-chip')).not.toBeInTheDocument();
  });
});
