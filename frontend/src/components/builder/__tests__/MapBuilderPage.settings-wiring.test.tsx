import { fireEvent, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useParams } from 'react-router';
import { render } from '@/test/test-utils';
import { MapBuilderPage } from '@/pages/MapBuilderPage';
import { usePluginStore } from '@/stores/map-plugin-store';

// Guards the MapBuilderPage wiring for two QA fixes (2026-05-30):
//   F2 — Settings plugin toggles must mark the map dirty.
//   F3 — Projection (Mercator/Globe) persists on basemap_config.projection:
//        the toggle writes the config, and the saved value seeds the pill on load.
// SettingsEditorScene.test.tsx already covers that the pills/switches fire their
// callbacks; this verifies MapBuilderPage's handlers do the right thing with them.

let mockMapData: Record<string, unknown>;

const { mockSetHasUnsavedChanges, mockSetBasemapConfig } = vi.hoisted(() => ({
  mockSetHasUnsavedChanges: vi.fn(),
  mockSetBasemapConfig: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // Resolve defaultValue + interpolate {{name}} so plugin aria-labels render as
    // "Enable measurement" etc. (mirrors SettingsEditorScene.test.tsx).
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) => {
      if (options?.defaultValue !== undefined) {
        let result = options.defaultValue as string;
        Object.keys(options).forEach((k) => {
          if (k !== 'defaultValue') result = result.replace(`{{${k}}}`, String(options[k]));
        });
        return result;
      }
      return key;
    },
  }),
}));

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useParams: vi.fn() };
});

vi.mock('@/components/builder/BuilderMap', () => ({
  BuilderMap: () => <div data-testid="builder-map" />,
}));

vi.mock('@/components/builder/SharePanel', () => ({
  ShareDialog: () => <div data-testid="share-dialog" />,
}));

vi.mock('@/components/ui/switch', () => ({
  Switch: ({
    checked,
    onCheckedChange,
    'aria-label': ariaLabel,
  }: {
    checked: boolean;
    onCheckedChange: (checked: boolean) => void;
    'aria-label': string;
  }) => (
    <input
      type="checkbox"
      role="switch"
      aria-label={ariaLabel}
      checked={checked}
      onChange={(e) => onCheckedChange(e.currentTarget.checked)}
    />
  ),
}));

vi.mock('@/components/map-plugins/registry', () => ({
  getPlugins: () => [
    { id: 'measurement', labelKey: 'widgets.measurement.label', icon: () => null },
  ],
}));

vi.mock('@/components/map-plugins', () => ({
  PluginHost: () => null,
  PluginSidebar: () => null,
  getPlugins: () => [],
  getEnabledPluginDefinitions: () => [],
  getDefaultPluginIds: () => [],
  resolveAvailablePluginIds: () => [],
  samePluginIds: () => true,
  usePartitionedPlugins: () => ({ byAnchor: {} }),
}));

vi.mock('@/hooks/use-maps', () => ({
  useMap: () => ({ data: mockMapData, isLoading: false, error: null }),
  useAddLayer: () => ({}),
  useRemoveLayer: () => ({}),
  useExportMapStyleJson: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useImportMapStyleJson: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('@/hooks/use-ai-availability', () => ({
  useAIAvailability: () => ({ isAIAvailable: false, reason: 'env_disabled', isLoading: false }),
}));

vi.mock('@/hooks/use-document-title', () => ({ useDocumentTitle: vi.fn() }));

vi.mock('@/hooks/use-settings', () => ({
  useEnabledWidgets: () => ({ data: null }),
  useBasemaps: () => ({ data: [] }),
}));

vi.mock('@/components/builder/hooks/use-builder-layout', () => ({
  useBuilderLayout: () => ({
    isRail: false,
    isEditorHidden: false,
    isCompact: false,
    isMobile: false,
    viewportWidth: 1440,
  }),
}));

vi.mock('@/components/builder/hooks/use-builder-dialogs', () => ({
  useBuilderDialogs: () => ({
    showChat: false, setShowChat: vi.fn(),
    showAddData: false, setShowAddData: vi.fn(),
    showShare: false, setShowShare: vi.fn(),
    showInfo: false, setShowInfo: vi.fn(),
    sidebarCollapsed: false, setSidebarCollapsed: vi.fn(),
  }),
}));

// expandedLayerId: 'settings' makes the real useBuilderEditorScene render the
// SettingsEditorScene without driving the sidebar cog.
vi.mock('@/components/builder/hooks/use-builder-layers', () => ({
  useBuilderLayers: () => ({
    localLayers: [],
    savedLayerBaseline: [],
    localName: 'Operations Map',
    setLocalName: vi.fn(),
    localDescription: '',
    setLocalDescription: vi.fn(),
    localBasemap: 'openfreemap-positron',
    showBasemapLabels: true,
    basemapConfig: null,
    localTerrainConfig: null,
    setLocalTerrainConfig: vi.fn(),
    setLocalBasemap: vi.fn(),
    setShowBasemapLabels: vi.fn(),
    setBasemapConfig: mockSetBasemapConfig,
    setHasUnsavedChanges: mockSetHasUnsavedChanges,
    hasUnsavedChanges: false,
    expandedLayerId: 'settings',
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
      onFilterChange: vi.fn(), onPaintChange: vi.fn(), onStyleConfigChange: vi.fn(),
      onLabelChange: vi.fn(), onToggleVisibility: vi.fn(), onAddDataset: vi.fn(),
      onRemove: vi.fn(), onOpacityChange: vi.fn(),
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
    description: '',
    notes: null,
    visibility: 'private',
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-02T00:00:00Z',
    created_by_username: 'editor-user',
    layer_count: 0,
    thumbnail_url: null,
    layers: [],
    basemap_config: null,
    ...overrides,
  };
}

describe('MapBuilderPage settings wiring (plugin dirty + projection persistence)', () => {
  beforeEach(() => {
    mockUseParams.mockReturnValue({ id: 'map-1' });
    mockMapData = makeMapData();
    mockSetHasUnsavedChanges.mockClear();
    mockSetBasemapConfig.mockClear();
    usePluginStore.getState().replace([]);
    localStorage.clear();
  });

  it('F2: toggling a plugin marks the map dirty', async () => {
    render(<MapBuilderPage />, { route: '/maps/map-1' });

    const measureSwitch = await screen.findByRole('switch', { name: 'Enable measurement' });
    fireEvent.click(measureSwitch);

    expect(mockSetHasUnsavedChanges).toHaveBeenCalledWith(true);
  });

  it('F3: choosing Globe writes projection into the basemap config', async () => {
    const user = userEvent.setup();
    render(<MapBuilderPage />, { route: '/maps/map-1' });

    const globePill = await screen.findByRole('radio', { name: 'Globe' });
    await user.click(globePill);

    expect(mockSetBasemapConfig).toHaveBeenCalled();
    const lastConfig = mockSetBasemapConfig.mock.calls.at(-1)?.[0];
    expect(lastConfig).toMatchObject({ projection: 'globe' });
  });

  it('F3: a saved projection seeds the active pill on load', async () => {
    mockMapData = makeMapData({ basemap_config: { projection: 'globe' } });

    render(<MapBuilderPage />, { route: '/maps/map-1' });

    const globePill = await screen.findByRole('radio', { name: 'Globe' });
    expect(globePill).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('radio', { name: 'Mercator' })).toHaveAttribute('aria-checked', 'false');
  });
});
