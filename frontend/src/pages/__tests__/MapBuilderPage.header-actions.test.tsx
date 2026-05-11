import userEvent from '@testing-library/user-event';
import { useParams } from 'react-router';
import { fireEvent, render, screen } from '@/test/test-utils';
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
let mockIsMobile = false;

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
}));

vi.mock('@/components/builder/hooks/use-builder-layout', () => ({
  useBuilderLayout: () => ({ isMobile: mockIsMobile }),
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
    localBasemap: 'carto',
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
    handleAiRemoveLayer: vi.fn(),
    handleQueryResult: vi.fn(),
    handleDismissEphemeral: vi.fn(),
    handleRenderModeChange: vi.fn(),
    chatLayerActions: [],
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
    mockIsMobile = false;
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

  it('uses 44px mobile sheet and rail targets while leaving map context visible', () => {
    mockIsMobile = true;

    render(<MapBuilderPage />, { route: '/maps/map-1' });

    const sheet = document.body.querySelector('[data-slot="sheet-content"]');
    expect(sheet?.className).toContain('max-w-[calc(100vw-5rem)]');

    expect(screen.getByRole('button', { name: 'actions.save' }).className).toContain('min-h-11');
    const notesRailButton = document.body.querySelector('button[title="dock.notes"]');
    expect(notesRailButton?.className).toContain('h-11');
    expect(notesRailButton?.className).toContain('w-11');
  });

  it('persists deterministic keyboard sidebar resizing through the resize slider', () => {
    render(<MapBuilderPage />, { route: '/maps/map-1' });

    const resizeHandle = screen.getByRole('slider', { name: 'tooltips.resizeSidebar' });
    expect(resizeHandle).toHaveAttribute('aria-valuenow', '260');
    expect(resizeHandle).toHaveAttribute('aria-valuemin', '200');
    expect(resizeHandle).toHaveAttribute('aria-valuemax', '600');

    fireEvent.keyDown(resizeHandle, { key: 'ArrowRight' });

    expect(resizeHandle).toHaveAttribute('aria-valuenow', '270');
    expect(localStorage.getItem('geolens-builder-sidebar-width')).toBe('270');
  });
});
