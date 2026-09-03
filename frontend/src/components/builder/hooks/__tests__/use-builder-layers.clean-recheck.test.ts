import { describe, it, expect, vi } from 'vitest';
import { act } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import {
  makeBuilderLayer,
  makeBuilderMap,
} from '@/components/builder/__tests__/fixtures/map-builder-fixtures';
import type { MapLayerResponse, MapResponse } from '@/types/api';

type MaplibreMap = import('maplibre-gl').Map;

/**
 * fix(#913): a banner Revert restored the saved layer through the ordinary
 * mutation handlers, all of which mark the map dirty — so the revert itself
 * re-dirtied the map and the header kept claiming unsaved work. The recheck
 * clears the flag only when the WHOLE map matches its saved state.
 */
function render(mapData: MapResponse) {
  const mapRef = { current: null } as React.RefObject<MaplibreMap | null>;
  return renderHook(() =>
    useBuilderLayers(
      mapData,
      mapRef,
      'map-1',
      { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[3],
      { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4],
      { current: { add: () => {}, remove: () => {} } } as unknown as Parameters<typeof useBuilderLayers>[5],
    ),
  );
}

describe('useBuilderLayers — clean-state recheck', () => {
  it('clears the flag when a layer edit is undone back to the baseline', () => {
    const layer = makeBuilderLayer();
    const { result } = render(makeBuilderMap([layer]));

    act(() => result.current.handlePaintChange(layer.id, { 'fill-color': '#123456' }));
    expect(result.current.hasUnsavedChanges).toBe(true);

    act(() => {
      result.current.handlePaintChange(layer.id, layer.paint as Record<string, unknown>);
      result.current.requestCleanRecheck();
    });
    expect(result.current.hasUnsavedChanges).toBe(false);
  });

  it('keeps the flag when another layer still has pending edits', () => {
    const a = makeBuilderLayer({ id: 'layer-a' });
    const b = makeBuilderLayer({ id: 'layer-b' });
    const { result } = render(makeBuilderMap([a, b]));

    act(() => {
      result.current.handlePaintChange('layer-a', { 'fill-color': '#123456' });
      result.current.handlePaintChange('layer-b', { 'fill-color': '#654321' });
    });
    act(() => {
      result.current.handlePaintChange('layer-b', b.paint as Record<string, unknown>);
      result.current.requestCleanRecheck();
    });

    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('keeps the flag when the map name is still renamed', () => {
    const layer = makeBuilderLayer();
    const { result } = render(makeBuilderMap([layer]));

    act(() => {
      result.current.setLocalName('Renamed');
      result.current.handlePaintChange(layer.id, { 'fill-color': '#123456' });
    });
    act(() => {
      result.current.handlePaintChange(layer.id, layer.paint as Record<string, unknown>);
      result.current.requestCleanRecheck();
    });

    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('keeps the flag for an outstanding opacity change on another layer', () => {
    const a = makeBuilderLayer({ id: 'layer-a' });
    const b = makeBuilderLayer({ id: 'layer-b' });
    const { result } = render(makeBuilderMap([a, b]));

    act(() => {
      result.current.handleOpacityChange('layer-a', 0.4);
      result.current.handlePaintChange('layer-b', { 'fill-color': '#654321' });
    });
    act(() => {
      result.current.handlePaintChange('layer-b', b.paint as Record<string, unknown>);
      result.current.requestCleanRecheck();
    });

    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('clears the flag after a re-derivable edit is put back (markDirty)', () => {
    const layer = makeBuilderLayer();
    const { result } = render(makeBuilderMap([layer]));

    // MapTitleBar / basemap controls mark dirty for fields the hook DOES compare;
    // treating those as opaque made the indicator unclearable for the session.
    act(() => {
      result.current.markDirty();
      result.current.handlePaintChange(layer.id, { 'fill-color': '#123456' });
    });
    act(() => {
      result.current.handlePaintChange(layer.id, layer.paint as Record<string, unknown>);
      result.current.requestCleanRecheck();
    });

    expect(result.current.hasUnsavedChanges).toBe(false);
  });

  // Text fields hydrate RAW but save as `value.trim() || null`, so "dirty" means
  // "saving would change the stored value" — not raw inequality, and not trimmed
  // equality either.
  describe.each([
    ['untouched whitespace in the saved value', '  notes  ', (d: string) => d, false],
    ['the user trimming that whitespace', '  notes  ', () => 'notes', true],
    ['a whitespace-only local value over an empty server one', null, () => '   ', false],
    ['a whitespace-only local value over a real server one', '  x  ', () => '   ', true],
  ])('description: %s', (_name, saved, edit, expectDirty) => {
    it(`reports ${expectDirty ? 'dirty' : 'clean'}`, () => {
      const layer = makeBuilderLayer();
      const { result } = render({ ...makeBuilderMap([layer]), description: saved } as MapResponse);

      act(() => {
        result.current.setLocalDescription(edit(saved ?? ''));
        result.current.handlePaintChange(layer.id, { 'fill-color': '#123456' });
      });
      act(() => {
        result.current.handlePaintChange(layer.id, layer.paint as Record<string, unknown>);
        result.current.requestCleanRecheck();
      });

      expect(result.current.hasUnsavedChanges).toBe(expectDirty);
    });
  });

  it('keeps the flag when a folder expansion is still pending', () => {
    // Folder expansion IS persisted (prepareLayersForPersistence reads groupMeta),
    // so a still-expanded folder must not read as clean.
    const group = { ...makeBuilderLayer({ id: 'group-1' }), layer_type: 'group:folder' } as unknown as MapLayerResponse;
    const child = makeBuilderLayer({ id: 'layer-1' });
    const { result } = render(makeBuilderMap([group, child]));

    act(() => {
      result.current.handleToggleGroupExpand('group-1');
      result.current.handlePaintChange('layer-1', { 'fill-color': '#123456' });
    });
    expect(result.current.hasUnsavedChanges).toBe(true);

    act(() => {
      result.current.handlePaintChange('layer-1', child.paint as Record<string, unknown>);
      result.current.requestCleanRecheck();
    });

    expect(result.current.hasUnsavedChanges).toBe(true);
  });

  it('ignores the UI-only basemap row expansion', () => {
    // handleToggleGroupExpand writes a groupMeta entry for the basemap row but
    // deliberately does NOT dirty the map — it has no persisted carrier — so a
    // whole-object compare would pin the flag on forever.
    const layer = makeBuilderLayer();
    const { result } = render(makeBuilderMap([layer]));

    act(() => {
      result.current.handleToggleGroupExpand('basemap-group');
      result.current.handlePaintChange(layer.id, { 'fill-color': '#123456' });
    });
    act(() => {
      result.current.handlePaintChange(layer.id, layer.paint as Record<string, unknown>);
      result.current.requestCleanRecheck();
    });

    expect(result.current.hasUnsavedChanges).toBe(false);
  });

  it('keeps the flag for page-owned dirt it cannot re-derive (markOpaqueDirty)', () => {
    const layer = makeBuilderLayer();
    const { result } = render(makeBuilderMap([layer]));

    act(() => {
      result.current.markOpaqueDirty();
      result.current.handlePaintChange(layer.id, { 'fill-color': '#123456' });
    });
    act(() => {
      result.current.handlePaintChange(layer.id, layer.paint as Record<string, unknown>);
      result.current.requestCleanRecheck();
    });

    expect(result.current.hasUnsavedChanges).toBe(true);
  });
});
