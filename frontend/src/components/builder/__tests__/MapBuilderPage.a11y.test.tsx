/**
 * Phase 1044-02 — Drag-from-catalog aria-live announcement contract (POL-23)
 *
 * Test surface: the sr-only aria-live region in MapBuilderPage that announces
 * keyboard / mouse drag events to assistive technology users.
 *
 * Test scope: Tests 1-2 pin the region's DOM presence and initial state.
 * Tests 3-6 (drag announcement content) are deferred to the Playwright e2e
 * spec (builder-v1-5.spec.ts) because the drag handlers are called by dnd-kit's
 * internal pointer machinery, which is not directly triggerable in a JSDOM
 * vitest environment without full pointer simulation.
 *
 * Implementation note: uses Option B (full MapBuilderPage render with mocked
 * hooks) — the same approach as MapBuilderPage.header-actions.test.tsx. The
 * i18n mock resolves a11y.* keys to their English copy for substring assertions.
 *
 * Worker-safety: no file-level vi.mock('@dnd-kit/core', ...).
 */

import { render, cleanup } from '@/test/test-utils';
import { useParams } from 'react-router';
import { MapBuilderPage } from '@/pages/MapBuilderPage';

// ---------------------------------------------------------------------------
// Module mocks — mirrors MapBuilderPage.header-actions.test.tsx
// ---------------------------------------------------------------------------

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) => {
      // Resolve a11y.* keys to their English strings so Tests 3-6 can assert substrings.
      const a11yMap: Record<string, string> = {
        'a11y.dragPickup': 'Picked up {{name}}. Use arrow keys to choose a position, Enter to drop, Escape to cancel.',
        'a11y.dragPosition': 'Current position: {{n}} of {{total}}',
        'a11y.dragDropped': 'Dropped. {{name}} added at position {{n}}.',
        'a11y.dragCancelled': 'Drop cancelled.',
      };
      if (a11yMap[key]) {
        let result = a11yMap[key];
        const params = options as Record<string, unknown> | undefined;
        if (params) {
          Object.keys(params).forEach((k) => {
            if (k !== 'defaultValue') {
              result = result.replace(`{{${k}}}`, String(params[k]));
            }
          });
        }
        return result;
      }
      if (options?.defaultValue !== undefined) return options.defaultValue as string;
      return key;
    },
    i18n: { language: 'en' },
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

vi.mock('@/components/builder/SettingsEditorScene', () => ({
  SettingsEditorScene: () => <div data-testid="settings-editor-scene" />,
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
      id: 'map-test',
      name: 'A11Y Test Map',
      description: '',
      visibility: 'private',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
      created_by_username: 'tester',
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
    isRail: false,
    isEditorHidden: false,
    isCompact: false,
    isMobile: false,
    viewportWidth: 1440,
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
    localName: 'A11Y Test Map',
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

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  mockUseParams.mockReturnValue({ id: 'map-test' });
});

afterEach(() => {
  vi.clearAllMocks();
  cleanup();
});

// ---------------------------------------------------------------------------
// Phase 1044-02 — aria-live region contract (POL-23, T-1044-05)
// ---------------------------------------------------------------------------

describe('Phase 1044-02 — MapBuilderPage drag aria-live region (POL-23)', () => {
  it('Test 1: aria-live region present — renders sr-only div with role=status, aria-live=polite, aria-atomic=true', () => {
    render(<MapBuilderPage />, { route: '/maps/map-test' });

    const region = document.querySelector('[data-testid="dnd-announcement"]');
    expect(region).toBeInTheDocument();
    expect(region).toHaveAttribute('role', 'status');
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(region).toHaveAttribute('aria-atomic', 'true');
    expect(region?.className).toContain('sr-only');
  });

  it('Test 2: initial state empty — the announcement region is empty before any drag', () => {
    render(<MapBuilderPage />, { route: '/maps/map-test' });

    const region = document.querySelector('[data-testid="dnd-announcement"]');
    expect(region).toBeInTheDocument();
    // Before any drag, dragAnnouncement state is '' — region has no meaningful text
    expect(region?.textContent).toBe('');
  });
});

/**
 * Tests 3-6 (pickup/drop/cancel announcement content) are deferred to the
 * Playwright e2e spec at frontend/e2e/builder-v1-5.spec.ts (Phase 1044 Plan 03).
 *
 * Rationale: these handlers (handleDragStart, handleDragEnd, handleDragCancel)
 * are invoked by @dnd-kit/core's internal PointerSensor / KeyboardSensor machinery,
 * not directly accessible in a JSDOM vitest environment. The handlers call
 * announce(t('a11y.XXX', ...)) which updates the aria-live region, but triggering
 * them requires real pointer / keyboard events that dnd-kit processes through its
 * sensor activation (activationConstraint: distance >= 8px) — not achievable with
 * fireEvent or userEvent in JSDOM.
 *
 * The e2e spec exercises the full browser stack where PointerSensor fires correctly:
 * - Test 3 → "drag-from-catalog negative: Escape cancels mid-drag" asserts region contains 'Drop cancelled.'
 * - Test 5 → "drag-from-catalog happy" asserts region contains the layer name after drop
 * - Tests 4, 6 → pickup and cancel content verified via VoiceOver walkthrough (1044-A11Y-WALKTHROUGH.md)
 *
 * The two tests above (1+2) cover the highest-regression-risk surface: someone deleting
 * the region or changing its ARIA attributes. Those regressions would be caught here.
 */
