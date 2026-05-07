/**
 * Plan 276-05 Task 3 — DOM-level smoke substitute for Playwright MCP UAT.
 *
 * Why this exists:
 * - The plan's Task 3 calls for a Playwright MCP visual UAT covering login,
 *   map builder, dataset map drawing, and search flows after CODE-04/CODE-05.
 * - The executor agent does not have `mcp__playwright__*` tools available
 *   (per the plan's <execution_rules>: "if mcp__playwright__* tools are
 *   available, run the UAT visually. Otherwise, mark as `## CHECKPOINT
 *   REACHED: Playwright UAT requires manual verification` and add DOM-level
 *   substitute tests proving the imports resolve").
 * - This file is that substitute. It imports each of the 4 zustand stores
 *   from their post-CODE-05 location (`@/stores/<name>-store`) and exercises
 *   each public API surface enough to prove:
 *     1. The module path resolves (CODE-05 — relocation complete)
 *     2. The store factory runs (zustand `create()` is invoked)
 *     3. The persisted auth store carries `version: 1` (CODE-04)
 *     4. Each store's actions update its observable state correctly
 *
 * Manual UAT remains a checkpoint requirement — see SUMMARY.md "Playwright
 * UAT" section for the human-verification checklist.
 */
import { useAuthStore } from '@/stores/auth-store';
import { useDrawingStore } from '@/stores/drawing-store';
import { useWidgetStore } from '@/stores/map-widget-store';
import { useSearchStore } from '@/stores/search-store';

describe('Plan 276-05 — store relocation smoke (CODE-04 + CODE-05)', () => {
  describe('CODE-05: all four stores import from @/stores/', () => {
    it('useAuthStore is a callable zustand store', () => {
      expect(typeof useAuthStore).toBe('function');
      expect(typeof useAuthStore.getState).toBe('function');
      expect(typeof useAuthStore.setState).toBe('function');
    });

    it('useDrawingStore is a callable zustand store', () => {
      expect(typeof useDrawingStore).toBe('function');
      expect(typeof useDrawingStore.getState).toBe('function');
    });

    it('useWidgetStore is a callable zustand store', () => {
      expect(typeof useWidgetStore).toBe('function');
      expect(typeof useWidgetStore.getState).toBe('function');
    });

    it('useSearchStore is a callable zustand store', () => {
      expect(typeof useSearchStore).toBe('function');
      expect(typeof useSearchStore.getState).toBe('function');
    });
  });

  describe('CODE-04: auth-store persist carries version: 1', () => {
    it('persist option exposes version 1', () => {
      expect(useAuthStore.persist.getOptions().version).toBe(1);
    });

    it('persist option exposes a defined migrate function', () => {
      expect(useAuthStore.persist.getOptions().migrate).toBeDefined();
    });
  });

  describe('CODE-05: each relocated store responds to its actions', () => {
    it('drawing-store: setDrawing toggles isDrawing and tracks target dataset', () => {
      // Reset state to defaults before exercising actions.
      useDrawingStore.setState({
        isDrawing: false,
        activeMode: null,
        targetDatasetId: null,
        targetTableName: null,
        targetGeometryType: null,
        selectedFeature: null,
        isEditDirty: false,
      });
      useDrawingStore.getState().setDrawing('dataset-uuid', 'table-name', 'Polygon');
      const state = useDrawingStore.getState();
      expect(state.isDrawing).toBe(true);
      expect(state.targetDatasetId).toBe('dataset-uuid');
      expect(state.targetGeometryType).toBe('Polygon');
      expect(state.activeMode).toBe('select');
      // Cleanup
      useDrawingStore.getState().clearDrawing();
      expect(useDrawingStore.getState().isDrawing).toBe(false);
    });

    it('map-widget-store: open, toggle, and replace mutate activeWidgets', () => {
      useWidgetStore.setState({ activeWidgets: new Set<string>() });
      useWidgetStore.getState().open('legend');
      expect(useWidgetStore.getState().activeWidgets.has('legend')).toBe(true);
      useWidgetStore.getState().toggle('legend'); // off
      expect(useWidgetStore.getState().activeWidgets.has('legend')).toBe(false);
      useWidgetStore.getState().replace(['scale-bar', 'compass']);
      expect(useWidgetStore.getState().activeWidgets.has('scale-bar')).toBe(true);
      expect(useWidgetStore.getState().activeWidgets.has('compass')).toBe(true);
    });

    it('search-store: setQuery, setFilter, and toParams round-trip', () => {
      useSearchStore.getState().resetFilters();
      useSearchStore.getState().setQuery('natural earth');
      useSearchStore.getState().setFilter('record_type', 'dataset');
      const params = useSearchStore.getState().toParams();
      expect(params.q).toBe('natural earth');
      expect(params.record_type).toBe('dataset');
      // Cleanup
      useSearchStore.getState().resetFilters();
    });
  });
});
