// fix(#903): Zoom to Layer rejected any `west > east` bbox outright, so the
// stack menu's action was a silent no-op for exactly the layers a user most
// needs it for — an antimeridian-crossing extent is the RFC 7946 §5.2 spec
// form, not a malformed pair.
import { describe, it, expect, vi } from 'vitest';
import { act } from '@testing-library/react';
import { renderHook } from '@/test/test-utils';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import {
  makeBuilderLayer,
  makeBuilderMap,
  makeMapLibreMock,
} from '@/components/builder/__tests__/fixtures/map-builder-fixtures';

type MaplibreMap = import('maplibre-gl').Map;

function renderWithLayer(bbox: number[] | null) {
  const map = makeMapLibreMock();
  const mapRef = { current: map } as React.RefObject<MaplibreMap | null>;
  const mapData = makeBuilderMap([
    makeBuilderLayer({ id: 'layer-1', dataset_extent_bbox: bbox }),
  ]);

  const hook = renderHook(() =>
    useBuilderLayers(
      mapData,
      mapRef,
      'map-1',
      { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[3],
      { mutate: vi.fn() } as unknown as Parameters<typeof useBuilderLayers>[4],
      { current: { add: () => {}, remove: () => {} } } as unknown as Parameters<typeof useBuilderLayers>[5],
    ),
  );

  return { hook, fitBounds: map.fitBounds as unknown as ReturnType<typeof vi.fn> };
}

describe('handleZoomToLayer across the antimeridian (fix #903)', () => {
  it('zooms to a seam-crossing layer by letting east run past 180', () => {
    const { hook, fitBounds } = renderWithLayer([178.5, -20, -178.5, -15]);

    act(() => hook.result.current.handleZoomToLayer('layer-1'));

    expect(fitBounds).toHaveBeenCalledTimes(1);
    expect(fitBounds.mock.calls[0][0]).toEqual([
      [178.5, -20],
      [181.5, -15],
    ]);
  });

  it('passes an ordinary bbox through as the same corners', () => {
    const { hook, fitBounds } = renderWithLayer([-74.5, 40.5, -73.5, 41.5]);

    act(() => hook.result.current.handleZoomToLayer('layer-1'));

    expect(fitBounds.mock.calls[0][0]).toEqual([
      [-74.5, 40.5],
      [-73.5, 41.5],
    ]);
  });

  it('still rejects a malformed bbox and an inverted latitude range', () => {
    for (const bbox of [null, [1, 2, 3], [0, 10, 1, 5], [0, 0, Number.NaN, 1]]) {
      const { hook, fitBounds } = renderWithLayer(bbox);
      act(() => hook.result.current.handleZoomToLayer('layer-1'));
      expect(fitBounds).not.toHaveBeenCalled();
    }
  });
});
