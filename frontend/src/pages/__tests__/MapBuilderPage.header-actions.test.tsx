import userEvent from '@testing-library/user-event';
import { useParams } from 'react-router';
import { render, screen } from '@/test/test-utils';
import { MapBuilderPage } from '@/pages/MapBuilderPage';

const dialogsState = {
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
};
let mockIsEditorHidden = false;
let mockIsRail = false;

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

vi.mock('@/components/builder/LayerPanel', () => ({
  LayerPanel: () => <div data-testid="layer-panel" />,
}));

vi.mock('@/components/builder/DatasetSearchPanel', () => ({
  DatasetSearchPanel: () => <div data-testid="dataset-search-panel" />,
}));

vi.mock('@/components/builder/SharePanel', () => ({
  ShareDialog: () => <div data-testid="share-dialog" />,
}));

vi.mock('@/components/builder/BasemapPicker', () => ({
  BasemapPicker: () => <div data-testid="basemap-picker" />,
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
    data: {
      id: 'map-1',
      name: 'Operations Map',
      description: 'Map description',
      visibility: 'private',
      created_at: '2026-03-01T00:00:00Z',
      updated_at: '2026-03-02T00:00:00Z',
      created_by_username: 'editor-user',
      layer_count: 0,
      thumbnail_url: null,
      layers: [],
    },
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
    isRail: mockIsRail,
    isEditorHidden: mockIsEditorHidden,
    // Backward-compat aliases
    isCompact: mockIsRail,
    isMobile: mockIsEditorHidden,
    viewportWidth: mockIsEditorHidden ? 600 : mockIsRail ? 1024 : 1440,
  }),
}));

vi.mock('@/components/builder/hooks/use-builder-dialogs', () => ({
  useBuilderDialogs: () => dialogsState,
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
    handleAiRemoveLayer: vi.fn(),
    handleQueryResult: vi.fn(),
    handleDismissEphemeral: vi.fn(),
    handleRenderModeChange: vi.fn(),
    chatLayerActions: [],
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

describe('MapBuilderPage header actions', () => {
  beforeEach(() => {
    mockUseParams.mockReturnValue({ id: 'map-1' });
    mockIsEditorHidden = false;
    mockIsRail = false;
    dialogsState.sidebarCollapsed = false;
    dialogsState.setShowShare.mockReset();
    localStorage.clear();
  });

  it('surfaces share as a primary desktop action for existing maps', async () => {
    const user = userEvent.setup();

    render(<MapBuilderPage />, { route: '/maps/map-1' });

    const shareButton = screen.getByRole('button', { name: 'share.title' });
    expect(shareButton).toBeInTheDocument();

    await user.click(shareButton);

    expect(dialogsState.setShowShare).toHaveBeenCalledWith(true);
  });

  it('renders SidebarRail in column 1 and 44px rail buttons when isEditorHidden=true', () => {
    mockIsEditorHidden = true;

    render(<MapBuilderPage />, { route: '/maps/map-1' });

    // The old sidebar Sheet is gone — the SidebarRail is in Column 1 of the grid
    const sidebar = screen.getByTestId('builder-sidebar');
    expect(sidebar).toBeInTheDocument();

    // No sidebar Sheet present (sidebar Sheet was removed in Plan 1034-02)
    // (only rail Sheet remains, but it needs railPanel != null to open)
    const sheetContents = document.body.querySelectorAll('[data-slot="sheet-content"]');
    expect(sheetContents.length).toBe(0);

    // Rail buttons rendered as 44px targets when isEditorHidden
    const notesRailButton = document.body.querySelector('button[title="dock.notes"]');
    expect(notesRailButton?.className).toContain('h-11');
    expect(notesRailButton?.className).toContain('w-11');
  });

  it('renders the three-column grid builder body on desktop (no resizable sidebar)', () => {
    render(<MapBuilderPage />, { route: '/maps/map-1' });

    // Desktop: sidebar is present as a fixed-width grid column (no resize handle)
    const sidebar = screen.getByTestId('builder-sidebar');
    expect(sidebar).toBeInTheDocument();

    // No resize handle in the new layout
    const resizeHandle = document.body.querySelector('[data-testid="builder-sidebar-resize-handle"]');
    expect(resizeHandle).toBeNull();
  });

  it('renders sidebar at 64px rail class when isRail=true', () => {
    mockIsRail = true;
    mockIsEditorHidden = false;

    render(<MapBuilderPage />, { route: '/maps/map-1' });

    // Sidebar is still present in the grid
    const sidebar = screen.getByTestId('builder-sidebar');
    expect(sidebar).toBeInTheDocument();

    // The builder body grid should include the 64px rail column class
    const builderBody = sidebar.parentElement;
    expect(builderBody?.className).toContain('grid-cols-[64px_1fr]');
  });
});
