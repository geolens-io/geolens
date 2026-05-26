import userEvent from '@testing-library/user-event';
import { useParams } from 'react-router';
import { render, screen } from '@/test/test-utils';
import { MapBuilderPage } from '@/pages/MapBuilderPage';

let mockIsEditorHidden = false;
let mockMapData: Record<string, unknown>;

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return {
    ...actual,
    useParams: vi.fn(),
  };
});

vi.mock('@/components/builder/BuilderMap', () => ({
  BuilderMap: () => <div data-testid="builder-map" />,
}));

vi.mock('@/components/builder/SharePanel', () => ({
  ShareDialog: () => <div data-testid="share-dialog" />,
}));

vi.mock('@/components/map-widgets', () => ({
  WidgetHost: () => null,
  WidgetSidebar: () => null,
  getWidgets: () => [],
  getEnabledWidgetDefinitions: () => [],
  getDefaultWidgetIds: () => [],
  resolveAvailableWidgetIds: () => [],
  usePartitionedWidgets: () => ({ byAnchor: {} }),
}));

vi.mock('@/hooks/use-maps', () => ({
  useMap: () => ({
    data: mockMapData,
    isLoading: false,
    error: null,
  }),
  useAddLayer: () => ({}),
  useRemoveLayer: () => ({}),
  useExportMapStyleJson: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useImportMapStyleJson: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('@/hooks/use-ai-availability', () => ({
  useAIAvailability: () => ({ isAIAvailable: false }),
}));

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

vi.mock('@/hooks/use-settings', () => ({
  useEnabledWidgets: () => ({ data: null }),
  useBasemaps: () => ({ data: [] }),
}));

vi.mock('@/components/builder/hooks/use-builder-layout', () => ({
  useBuilderLayout: () => ({
    isRail: false,
    isEditorHidden: mockIsEditorHidden,
    isCompact: false,
    isMobile: mockIsEditorHidden,
    viewportWidth: mockIsEditorHidden ? 600 : 1440,
  }),
}));

vi.mock('@/components/builder/hooks/use-builder-dialogs', () => ({
  useBuilderDialogs: () => ({
    showChat: false,
    setShowChat: vi.fn(),
    showAddData: false,
    setShowAddData: vi.fn(),
    showShare: false,
    setShowShare: vi.fn(),
    showInfo: false,
    setShowInfo: vi.fn(),
    sidebarCollapsed: false,
    setSidebarCollapsed: vi.fn(),
  }),
}));

vi.mock('@/components/builder/hooks/use-builder-layers', () => ({
  useBuilderLayers: () => ({
    localLayers: [],
    localName: 'Operations Map',
    setLocalName: vi.fn(),
    localDescription: 'Map description',
    setLocalDescription: vi.fn(),
    localBasemap: 'openfreemap-positron',
    showBasemapLabels: true,
    basemapConfig: null,
    localTerrainConfig: null,
    setLocalTerrainConfig: vi.fn(),
    setLocalBasemap: vi.fn(),
    setShowBasemapLabels: vi.fn(),
    setBasemapConfig: vi.fn(),
    setHasUnsavedChanges: vi.fn(),
    hasUnsavedChanges: false,
    expandedLayerId: null,
    activeEditorTab: 'style',
    initialViewState: null,
    ephemeralResult: null,
    groupMeta: {},
    markDirty: vi.fn(),
    handleToggleExpand: vi.fn(),
    handleTabChange: vi.fn(),
    handlePaintChange: vi.fn(),
    handleOpacityChange: vi.fn(),
    handleFilterChange: vi.fn(),
    handlePopupChange: vi.fn(),
    handleLabelChange: vi.fn(),
    handleStyleConfigChange: vi.fn(),
    handleLayoutChange: vi.fn(),
    handleToggleVisibility: vi.fn(),
    handleMoveUp: vi.fn(),
    handleMoveDown: vi.fn(),
    handleReorder: vi.fn(),
    handleDisplayNameChange: vi.fn(),
    handleRemove: vi.fn(),
    handleZoomToLayer: vi.fn(),
    handleToggleLegend: vi.fn(),
    handleAddDataset: vi.fn(),
    handleRenderAsChange: vi.fn(),
    handleDuplicateRendering: vi.fn(),
    dispatchLayerAction: vi.fn(),
    handleAiRemoveLayer: vi.fn(),
    handleQueryResult: vi.fn(),
    handleDismissEphemeral: vi.fn(),
    handleRenderModeChange: vi.fn(),
    chatLayerActions: {
      onFilterChange: vi.fn(),
      onPaintChange: vi.fn(),
      onStyleConfigChange: vi.fn(),
      onLabelChange: vi.fn(),
      onToggleVisibility: vi.fn(),
      onAddDataset: vi.fn(),
      onRemove: vi.fn(),
      onOpacityChange: vi.fn(),
    },
    handleToggleGroupExpand: vi.fn(),
    handleDEMTerrainBind: vi.fn(),
    handleCreateGroupWithLayer: vi.fn(),
    handleRenameGroup: vi.fn(),
    handleUngroup: vi.fn(),
    handleDeleteGroup: vi.fn(),
    handleAddLayerToExistingGroup: vi.fn(),
    handleMoveLayerOutOfGroup: vi.fn(),
  }),
}));

vi.mock('@/components/builder/hooks/use-builder-save', () => ({
  useBuilderSave: () => ({
    handleSave: vi.fn(),
    isSaving: false,
    handleExportPNG: vi.fn(),
    handleFork: vi.fn(),
    isForkPending: false,
    saveStatus: 'saved',
    isSaveRetryable: false,
    maybeAutoCaptureThumbnail: vi.fn(),
    blocker: { state: 'unblocked', reset: vi.fn(), proceed: vi.fn() },
  }),
}));

const mockUseParams = vi.mocked(useParams);

function makeMapData(overrides: Record<string, unknown> = {}) {
  return {
    id: 'map-1',
    name: 'Operations Map',
    description: 'Map description',
    notes: null,
    visibility: 'private',
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-02T00:00:00Z',
    created_by_username: 'editor-user',
    layer_count: 0,
    thumbnail_url: null,
    layers: [],
    ...overrides,
  };
}

describe('MapBuilderPage notes migration and AI rail polish', () => {
  beforeEach(() => {
    mockUseParams.mockReturnValue({ id: 'map-1' });
    mockIsEditorHidden = false;
    mockMapData = makeMapData();
    localStorage.clear();
  });

  it('does not resurrect migrated local notes when server notes are null', async () => {
    const user = userEvent.setup();
    localStorage.setItem('geolens-map-notes-map-1', 'stale migrated note');
    mockMapData = makeMapData({ notes: null });

    render(<MapBuilderPage />, { route: '/maps/map-1' });

    await user.click(document.body.querySelector('button[title="dock.notes"]') as HTMLButtonElement);

    expect(screen.getByPlaceholderText('dock.notesPlaceholder')).toHaveValue('');
    expect(localStorage.getItem('geolens-map-notes-map-1')).toBeNull();
  });

  it('still migrates local notes when the server response has no notes field', async () => {
    const user = userEvent.setup();
    localStorage.setItem('geolens-map-notes-map-1', 'legacy local note');
    const { notes: _notes, ...legacyMapData } = makeMapData();
    mockMapData = legacyMapData;

    render(<MapBuilderPage />, { route: '/maps/map-1' });

    await user.click(document.body.querySelector('button[title="dock.notes"]') as HTMLButtonElement);

    expect(screen.getByPlaceholderText('dock.notesPlaceholder')).toHaveValue('legacy local note');
  });

  it('opens the AI unavailable message from the mobile rail button', async () => {
    const user = userEvent.setup();
    mockIsEditorHidden = true;

    render(<MapBuilderPage />, { route: '/maps/map-1' });

    const aiButton = document.body.querySelector('button[title="rail.aiUnavailable"]') as HTMLButtonElement;
    expect(aiButton).toHaveAttribute('data-unavailable', 'true');
    expect(aiButton).not.toBeDisabled();

    await user.click(aiButton);

    expect(screen.getByText('rail.aiUnavailableTitle')).toBeInTheDocument();
  });
});
