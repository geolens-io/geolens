// DatasetPage offers its feature-table and map-layer actions only for record
// types whose capabilities include them.
import { act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useParams } from 'react-router';
import { render, screen } from '@/test/test-utils';
import { useDataset, useUpdateDataset } from '@/components/dataset/hooks/use-dataset';
import { useAuthStore } from '@/stores/auth-store';
import { DatasetPage } from '@/pages/DatasetPage';
import type { DatasetResponse, RecordType, UserResponse } from '@/types/api';

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

vi.mock('@/stores/drawing-store', () => ({
  useDrawingStore: (selector: (state: Record<string, unknown>) => unknown) =>
    selector({ isDrawing: false, isEditDirty: false, setDrawing: vi.fn(), clearDrawing: vi.fn() }),
}));

const mapInstances = vi.hoisted(() => ({ count: 0 }));

vi.mock('@/components/dataset/DatasetMap', async () => {
  const { useState } = await import('react');
  return {
    DatasetMap: ({ canEdit }: { canEdit?: boolean }) => {
      const [instance] = useState(() => ++mapInstances.count);
      return (
        <div
          data-testid="dataset-map"
          data-can-edit={String(Boolean(canEdit))}
          data-instance={instance}
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
    expect(screen.getByRole('button', { name: 'Add to map' })).toBeInTheDocument();
    expect(map).toHaveAttribute('data-can-edit', 'true');
    expect(screen.getByTestId('dataset-chat-panel')).toBeInTheDocument();
    await openMoreActions();
    expect(screen.getByRole('menuitem', { name: 'Re-Upload' })).toBeInTheDocument();
    expect(screen.getByTestId('reupload-dialog')).toBeInTheDocument();
  });

  it('offers none of them for an unknown record type', async () => {
    const map = await renderAs('point_cloud_dataset');

    expect(screen.queryByTestId('dataset-table-readout')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add to map' })).not.toBeInTheDocument();
    expect(map).toHaveAttribute('data-can-edit', 'false');
    expect(screen.queryByTestId('dataset-chat-panel')).not.toBeInTheDocument();
    await openMoreActions();
    expect(screen.queryByRole('menuitem', { name: 'Re-Upload' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('reupload-dialog')).not.toBeInTheDocument();
  });

  it('gives an unknown record type its own map after a vector dataset', async () => {
    vi.mocked(useDataset).mockImplementation(((id: string) => ({
      data: id === 'dataset-2'
        ? { ...makeDataset('point_cloud_dataset'), id: 'dataset-2' }
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
});
