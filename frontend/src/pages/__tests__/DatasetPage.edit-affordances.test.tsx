import { act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useParams } from 'react-router';
import { render, screen } from '@/test/test-utils';
import { useDataset, useUpdateDataset } from '@/hooks/use-dataset';
import { useAuthStore } from '@/stores/auth-store';
import { DatasetPage } from '@/pages/DatasetPage';
import type { DatasetResponse, UserResponse } from '@/types/api';

const drawingStoreState = vi.hoisted(() => ({
  isDrawing: false,
  isEditDirty: false,
  setDrawing: vi.fn(),
  clearDrawing: vi.fn(),
}));

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return {
    ...actual,
    useParams: vi.fn(),
  };
});

vi.mock('@/hooks/use-dataset', () => ({
  useDataset: vi.fn(),
  useUpdateDataset: vi.fn(),
  useUpdatePublicationStatus: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useValidation: () => ({ data: { errors: [], warnings: [] } }),
}));

vi.mock('@/hooks/use-settings', () => ({
  useAllSettings: () => ({ data: { tabs: { general: [] } } }),
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
  DatasetMap: () => <div data-testid="dataset-map" />,
}));

vi.mock('@/hooks/use-vrt', () => ({
  useVrtGenerations: () => ({ data: { generations: [] } }),
  useVrtStatus: () => ({ data: null }),
}));

vi.mock('@/components/dataset/DatasetDeleteDialog', () => ({
  DatasetDeleteDialog: () => null,
}));

vi.mock('@/components/dataset/ReuploadDialog', () => ({
  ReuploadDialog: () => null,
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

vi.mock('@/hooks/use-records', () => ({
  useCreateKeyword: () => ({ mutateAsync: vi.fn() }),
  useKeywords: () => ({ data: { keywords: [] } }),
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
  created_at: '2026-03-01T00:00:00Z',
  roles: ['editor'],
};

const VIEWER_USER: UserResponse = {
  ...EDITOR_USER,
  id: 'user-viewer',
  username: 'viewer-user',
  email: 'viewer@example.com',
  roles: ['viewer'],
};

function makeDataset(): DatasetResponse {
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
    lineage_summary: 'Compiled from official country boundaries.',
    update_frequency: 'annually',
    usage_constraints: 'Public domain.',
    access_constraints: 'None.',
    sensitivity_classification: 'unclassified',
    theme_category: ['boundaries'],
    owner_org: 'Natural Earth',
    published_at: '2026-03-02T00:00:00Z',
    updated_by: 'user-editor',
    current_version: 1,
    source_url: 'https://example.test/world-countries',
    quality_statement: 'Validated against source metadata.',
    collections: [],
    quality_detail: {
      overall: 96,
      metadata_completeness: 95,
      geometry_validity: 99,
      attribute_completeness: 93,
      crs_defined: 100,
      computed_at: '2026-03-02T00:00:00Z',
    },
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

describe('DatasetPage editable affordance integration', () => {
  const mutateAsync = vi.fn();

  beforeEach(() => {
    mutateAsync.mockReset();
    mutateAsync.mockResolvedValue({});
    drawingStoreState.isDrawing = false;
    drawingStoreState.isEditDirty = false;
    drawingStoreState.setDrawing.mockReset();
    drawingStoreState.clearDrawing.mockReset();

    mockUseParams.mockReturnValue({ id: 'dataset-1' });
    mockUseDataset.mockReturnValue({
      data: makeDataset(),
      isLoading: false,
      error: null,
    } as ReturnType<typeof useDataset>);
    mockUseUpdateDataset.mockReturnValue({
      mutateAsync,
    } as unknown as ReturnType<typeof useUpdateDataset>);
  });

  afterEach(() => {
    setUser(null);
  });

  it('shows sticky pending controls for staged drafts and clears after save/cancel', async () => {
    setUser(EDITOR_USER);
    const user = userEvent.setup();

    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    expect(screen.queryByTestId('pending-edits-bar')).not.toBeInTheDocument();

    await user.click(screen.getByText('Original summary'));

    const summaryInput = screen.getByDisplayValue('Original summary');
    await user.clear(summaryInput);
    await user.type(summaryInput, 'Updated summary pending save');
    await user.tab();

    expect(await screen.findByTestId('pending-edits-bar')).toBeInTheDocument();
    expect(screen.getByTestId('pending-edits-count')).toHaveTextContent('1 unsaved change');

    await user.click(screen.getByTestId('pending-edits-save'));

    expect(mutateAsync).toHaveBeenCalledWith({
      datasetId: 'dataset-1',
      data: {
        summary: 'Updated summary pending save',
      },
    });

    await waitFor(() => {
      expect(screen.queryByTestId('pending-edits-bar')).not.toBeInTheDocument();
    });

    await user.click(screen.getByText('Original summary'));

    const secondEditInput = screen.getByDisplayValue('Original summary');
    await user.clear(secondEditInput);
    await user.type(secondEditInput, 'Summary that will be canceled');
    await user.tab();

    expect(await screen.findByTestId('pending-edits-bar')).toBeInTheDocument();

    await user.click(screen.getByTestId('pending-edits-cancel'));

    await waitFor(() => {
      expect(screen.queryByTestId('pending-edits-bar')).not.toBeInTheDocument();
    });

    expect(screen.getByText('Original summary')).toBeInTheDocument();
  });

  it('keeps viewer fields read-only and reveals denial hint only after attempted edit', async () => {
    setUser(VIEWER_USER);
    const user = userEvent.setup();

    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    const summaryShell = screen.getByTestId('editable-field-shell-summary');
    expect(summaryShell).toHaveAttribute('data-editable', 'false');
    const hintCountBeforeAttempt = screen.getAllByTestId('role-capability-hint').length;

    await user.click(summaryShell);

    expect(screen.getAllByTestId('role-capability-hint')).toHaveLength(hintCountBeforeAttempt + 1);
    expect(screen.getByText('You can view this field. Editors can make changes.')).toBeInTheDocument();
    expect(screen.queryByTestId('pending-edits-bar')).not.toBeInTheDocument();
  });

  it('normalizes legacy tab hashes to the new metadata route', async () => {
    setUser(EDITOR_USER);
    window.history.replaceState({}, '', '/datasets/dataset-1#source-coverage');

    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    await waitFor(() => {
      expect(window.location.hash).toBe('#metadata');
    });

    expect(screen.getByRole('tab', { name: 'Metadata' })).toHaveAttribute('aria-selected', 'true');
  });

  it('does not show metadata pending controls when only geometry edits are dirty', () => {
    setUser(EDITOR_USER);
    drawingStoreState.isEditDirty = true;

    render(<DatasetPage />, { route: '/datasets/dataset-1' });

    expect(screen.queryByTestId('pending-edits-bar')).not.toBeInTheDocument();
  });
});
