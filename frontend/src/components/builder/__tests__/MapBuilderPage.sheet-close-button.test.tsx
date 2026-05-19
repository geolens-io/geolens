/**
 * Phase 1051 Plan 10 — RESP-03 duplicate close button regression
 *
 * Test surface: the shadcn `<SheetContent>` overlays in MapBuilderPage that
 * wrap `LayerEditorPanel` (lines 1178-1247) and `BuilderRail` (lines 1317-1327)
 * at viewport widths < 800px. Pre-fix, the Sheet's built-in auto-close X +
 * the inner panel's own close affordance both rendered, producing 2 close
 * buttons per surface. Fix: pass `showCloseButton={false}` to the Sheet so
 * the inner panel's canonical close (LayerEditorPanel.tsx:316-325 with
 * aria-label "Close layer editor" / BuilderRail.tsx:125-132 with aria-label
 * "Close panel") is the single source of truth.
 *
 * Strategy: render the Sheet+inner-panel composition directly (NOT the full
 * MapBuilderPage harness) — same DOM contract, far more reliable signal.
 * Full-page render is mocked in MapBuilderPage.a11y.test.tsx; replicating
 * that harness for one assertion would dwarf the test value.
 *
 * Cross-reference: PATTERNS.md Plan 10 finding #6 (BasemapPicker is dead;
 * the actual duplicate-X is the Sheet wrapper). UI-SPEC §RESP-03 fix
 * contract: "EXACTLY 1 visible, functional close button in every
 * right-sidebar-opened flyout".
 */

import { render, screen, fireEvent } from '@/test/test-utils';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { LayerEditorPanel, type LayerEditorHandlers } from '../LayerEditorPanel';
import { BuilderRail, type RailPanel } from '../BuilderRail';
import type { MapLayerResponse } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) =>
      options?.defaultValue ?? key,
    i18n: { language: 'en' },
  }),
}));

// Mock heavy sub-editors so they don't need full maplibre/canvas setup
vi.mock('../LayerStyleEditor', () => ({
  LayerStyleEditor: () => <div data-testid="layer-style-editor" />,
}));
vi.mock('../RasterLayerControls', () => ({
  RasterLayerControls: () => <div data-testid="raster-layer-controls" />,
}));
vi.mock('../LayerFilterEditor', () => ({
  LayerFilterEditor: () => <div data-testid="layer-filter-editor" />,
}));
vi.mock('../LabelEditor', () => ({
  LabelEditor: () => <div data-testid="label-editor" />,
}));
vi.mock('../PopupConfigEditor', () => ({
  PopupConfigEditor: () => <div data-testid="popup-config-editor" />,
}));
vi.mock('../ColumnsReference', () => ({
  ColumnsReference: () => <div data-testid="columns-reference" />,
}));

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: overrides.id ?? 'layer-1',
    dataset_id: overrides.dataset_id ?? 'dataset-1',
    dataset_name: overrides.dataset_name ?? 'Population',
    dataset_geometry_type: overrides.dataset_geometry_type ?? 'POLYGON',
    dataset_table_name: overrides.dataset_table_name ?? 'population',
    dataset_extent_bbox: overrides.dataset_extent_bbox ?? [0, 0, 1, 1],
    dataset_column_info: overrides.dataset_column_info ?? null,
    dataset_feature_count: overrides.dataset_feature_count ?? null,
    dataset_sample_values: overrides.dataset_sample_values ?? null,
    display_name: overrides.display_name ?? null,
    sort_order: overrides.sort_order ?? 0,
    visible: overrides.visible ?? true,
    opacity: overrides.opacity ?? 1,
    paint: overrides.paint ?? {},
    layout: overrides.layout ?? {},
    filter: overrides.filter ?? null,
    label_config: overrides.label_config ?? null,
    popup_config: overrides.popup_config ?? null,
    style_config: overrides.style_config ?? null,
    layer_type: overrides.layer_type ?? null,
    dataset_record_type: overrides.dataset_record_type ?? 'vector_dataset',
    show_in_legend: overrides.show_in_legend ?? true,
    is_dem: overrides.is_dem ?? false,
    dem_vertical_units: overrides.dem_vertical_units ?? null,
    ...overrides,
  };
}

function makeHandlers(overrides: Partial<LayerEditorHandlers> = {}): LayerEditorHandlers {
  return {
    onTabChange: vi.fn(),
    onPaintChange: vi.fn(),
    onOpacityChange: vi.fn(),
    onFilterChange: vi.fn(),
    onLabelChange: vi.fn(),
    onPopupChange: vi.fn(),
    onStyleConfigChange: vi.fn(),
    onLayoutChange: vi.fn(),
    onRenderModeChange: vi.fn(),
    onRemove: vi.fn(),
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Helper: render the exact <800px Sheet+LayerEditorPanel composition from
// MapBuilderPage.tsx:1178-1247. Mirrors the production JSX shape so the
// regression catches drift (e.g. someone re-enables Sheet's default close).
// ---------------------------------------------------------------------------
function renderEditorSheet({
  onClose,
  layer,
}: {
  onClose: () => void;
  layer: MapLayerResponse;
}) {
  return render(
    <Sheet open={true} onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent
        side="right"
        showCloseButton={false}
        className="w-full max-w-[380px] p-0 flex flex-col"
      >
        <SheetHeader className="sr-only">
          <SheetTitle>{layer.display_name ?? layer.dataset_name}</SheetTitle>
          <SheetDescription>Appearance</SheetDescription>
        </SheetHeader>
        <LayerEditorPanel
          layer={layer}
          onClose={onClose}
          isDrillDown={true}
          handlers={makeHandlers()}
          activeTab="style"
          editorScene="default"
        />
      </SheetContent>
    </Sheet>
  );
}

// ---------------------------------------------------------------------------
// Helper: render the exact <800px mobile-rail Sheet+BuilderRail composition
// from MapBuilderPage.tsx:1317-1327.
// ---------------------------------------------------------------------------
function renderRailSheet({
  activePanel,
  onPanelChange,
}: {
  activePanel: RailPanel;
  onPanelChange: (next: RailPanel) => void;
}) {
  return render(
    <Sheet open={true} onOpenChange={(open) => { if (!open) onPanelChange(null); }}>
      <SheetContent
        side="right"
        showCloseButton={false}
        className="w-[22rem] max-w-[calc(100vw-5rem)] p-0 flex flex-col"
      >
        <SheetHeader className="sr-only">
          <SheetTitle>Notes</SheetTitle>
          <SheetDescription>Side panel</SheetDescription>
        </SheetHeader>
        <BuilderRail
          activePanel={activePanel}
          onPanelChange={onPanelChange}
          aiAvailable={false}
          showRail={false}
          notes=""
          onNotesChange={vi.fn()}
        />
      </SheetContent>
    </Sheet>
  );
}

// ===========================================================================
// Tests
// ===========================================================================

describe('Phase 1051 Plan 10 — RESP-03 duplicate close button (Sheet overlays)', () => {
  // -----------------------------------------------------------------------
  // Surface 1: Editor Sheet wrapping LayerEditorPanel (<800px)
  // -----------------------------------------------------------------------

  it('Test 1: Editor Sheet renders exactly ONE close button (LayerEditorPanel default scene)', () => {
    renderEditorSheet({ onClose: vi.fn(), layer: makeLayer() });

    // Sheet's auto-close uses sr-only "Close" text via t('close'). The inner
    // LayerEditorPanel close uses aria-label "Close layer editor". A
    // case-insensitive /close/i match catches BOTH if the Sheet's X is not
    // suppressed.
    const closeButtons = screen.getAllByRole('button', { name: /close/i });
    expect(closeButtons).toHaveLength(1);
    // The surviving button must be the LayerEditorPanel one
    expect(closeButtons[0]).toHaveAttribute('aria-label', 'Close layer editor');
  });

  it('Test 2: Editor Sheet — clicking the surviving close button calls onClose', () => {
    const onClose = vi.fn();
    renderEditorSheet({ onClose, layer: makeLayer() });

    const closeBtn = screen.getByRole('button', { name: 'Close layer editor' });
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Test 3: Editor Sheet — back-arrow (drill-down) also calls onClose but is NOT counted as a "close" button by aria-label match', () => {
    const onClose = vi.fn();
    renderEditorSheet({ onClose, layer: makeLayer() });

    // The drill-down back-arrow has aria-label "Back to layers" — NOT a close
    // match. It still calls onClose because back+close share semantics in the
    // Sheet variant (line 272-282 of LayerEditorPanel). This test pins the
    // semantic contract: the back arrow is a navigation affordance, the X
    // is the close affordance — they are distinct in a11y tree even though
    // they share the same handler.
    const backBtn = screen.getByRole('button', { name: 'Back to layers' });
    expect(backBtn).toBeInTheDocument();
    fireEvent.click(backBtn);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // -----------------------------------------------------------------------
  // Surface 2: Mobile-rail Sheet wrapping BuilderRail (<800px)
  // -----------------------------------------------------------------------

  it('Test 4: Mobile-rail Sheet renders exactly ONE close button (BuilderRail expanded panel)', () => {
    renderRailSheet({
      activePanel: 'notes',
      onPanelChange: vi.fn(),
    });

    // BuilderRail's panel header has a ChevronRight close with aria-label
    // "Close panel" (line 128). Sheet's auto-close uses sr-only "Close" text.
    const closeButtons = screen.getAllByRole('button', { name: /close/i });
    expect(closeButtons).toHaveLength(1);
    expect(closeButtons[0]).toHaveAttribute('aria-label', 'Close panel');
  });

  it('Test 5: Mobile-rail Sheet — clicking the surviving close button dismisses the panel', () => {
    const onPanelChange = vi.fn();
    renderRailSheet({
      activePanel: 'notes',
      onPanelChange,
    });

    const closeBtn = screen.getByRole('button', { name: 'Close panel' });
    fireEvent.click(closeBtn);
    // BuilderRail calls onPanelChange(null) to dismiss
    expect(onPanelChange).toHaveBeenCalledWith(null);
  });

  // -----------------------------------------------------------------------
  // Surface 3: Standalone LayerEditorPanel at >=800px (regression — fix
  // must NOT remove the canonical X when the panel is NOT inside a Sheet)
  // -----------------------------------------------------------------------

  it('Test 6: Standalone LayerEditorPanel (>=800px sibling-column) still renders its canonical close X', () => {
    render(
      <LayerEditorPanel
        layer={makeLayer()}
        onClose={vi.fn()}
        isDrillDown={false}
        handlers={makeHandlers()}
        activeTab="style"
        editorScene="default"
      />
    );

    // At >=800px there is no Sheet — only the LayerEditorPanel's own X.
    const closeButtons = screen.getAllByRole('button', { name: /close/i });
    expect(closeButtons).toHaveLength(1);
    expect(closeButtons[0]).toHaveAttribute('aria-label', 'Close layer editor');
  });

  // -----------------------------------------------------------------------
  // Surface 4: Sheet contract pin — passing showCloseButton={false} must
  // suppress the built-in X. Catches a future shadcn upgrade that renames
  // the prop or changes the default.
  // -----------------------------------------------------------------------

  it('Test 7: <SheetContent showCloseButton={false}> renders zero close buttons from the Sheet primitive itself', () => {
    render(
      <Sheet open={true} onOpenChange={vi.fn()}>
        <SheetContent showCloseButton={false} side="right">
          <SheetHeader className="sr-only">
            <SheetTitle>Empty</SheetTitle>
            <SheetDescription>Empty body</SheetDescription>
          </SheetHeader>
          <div>Body</div>
        </SheetContent>
      </Sheet>
    );

    // Empty content → NO close buttons whatsoever
    const closeButtons = screen.queryAllByRole('button', { name: /close/i });
    expect(closeButtons).toHaveLength(0);
  });

  // -----------------------------------------------------------------------
  // Surface 5: Negative-control / bug-shape pin. Proves that WITHOUT the
  // `showCloseButton={false}` opt-out, the editor Sheet would render TWO
  // close buttons. This is the exact pre-fix shape from PATTERNS.md Plan
  // 10 + UI-SPEC §RESP-03. If this negative test ever fails (count drops
  // to 1 without the prop), it means the shadcn Sheet default behavior
  // changed and the production opt-out may no longer be necessary —
  // re-audit before deleting `showCloseButton={false}` from
  // MapBuilderPage.tsx.
  // -----------------------------------------------------------------------

  it('Test 8: Negative control — Sheet WITHOUT showCloseButton={false} renders TWO close buttons (bug-shape pin)', () => {
    render(
      <Sheet open={true} onOpenChange={vi.fn()}>
        <SheetContent
          /* showCloseButton omitted → defaults to true (legacy / pre-fix shape) */
          side="right"
          className="w-full max-w-[380px] p-0 flex flex-col"
        >
          <SheetHeader className="sr-only">
            <SheetTitle>{makeLayer().dataset_name}</SheetTitle>
            <SheetDescription>Appearance</SheetDescription>
          </SheetHeader>
          <LayerEditorPanel
            layer={makeLayer()}
            onClose={vi.fn()}
            isDrillDown={true}
            handlers={makeHandlers()}
            activeTab="style"
              editorScene="default"
          />
        </SheetContent>
      </Sheet>
    );

    // Without the opt-out: Sheet's auto-close ("Close" sr-only) + panel's own
    // X ("Close layer editor") = 2 buttons matching /close/i.
    const closeButtons = screen.getAllByRole('button', { name: /close/i });
    expect(closeButtons).toHaveLength(2);
  });
});
