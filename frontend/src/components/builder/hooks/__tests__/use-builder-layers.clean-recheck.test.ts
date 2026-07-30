import { describe, it, expect, vi } from 'vitest';
import { act } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import {
  makeBuilderLayer,
  makeBuilderMap,
} from '@/components/builder/__tests__/fixtures/map-builder-fixtures';
import type { MapResponse } from '@/types/api';

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
      { current: () => {} } as unknown as Parameters<typeof useBuilderLayers>[5],
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

  it('keeps the flag for page-owned dirt it cannot re-derive (markDirty)', () => {
    const layer = makeBuilderLayer();
    const { result } = render(makeBuilderMap([layer]));

    act(() => {
      result.current.markDirty();
      result.current.handlePaintChange(layer.id, { 'fill-color': '#123456' });
    });
    act(() => {
      result.current.handlePaintChange(layer.id, layer.paint as Record<string, unknown>);
      result.current.requestCleanRecheck();
    });

    expect(result.current.hasUnsavedChanges).toBe(true);
  });
});
