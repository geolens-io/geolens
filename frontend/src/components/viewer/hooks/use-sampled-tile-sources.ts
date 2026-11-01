import { useEffect, useState, type RefObject } from 'react';
import type { Map as MapLibreMap, VectorTileSource } from 'maplibre-gl';
import { isTileSampled, subscribeTileSampling } from '@/lib/tile-sampling';

const NONE: ReadonlySet<string> = new Set();

function tileUrl(template: string, { z, x, y }: { z: number; x: number; y: number }): string {
  return template.replaceAll('{z}', String(z)).replaceAll('{x}', String(x)).replaceAll('{y}', String(y));
}

function sampledInView(map: MapLibreMap, sourceIds: ReadonlySet<string>): ReadonlySet<string> {
  const sampled = new Set<string>();
  for (const id of sourceIds) {
    const source = map.getSource(id);
    if (source?.type !== 'vector') continue;
    const { tiles, tileSize, minzoom, maxzoom } = source as VectorTileSource;
    if (!tiles?.length) continue;
    const inView = map
      .coveringTiles({ tileSize, minzoom, maxzoom })
      .some(({ canonical }) => tiles.some((template) => isTileSampled(tileUrl(template, canonical))));
    if (inView) sampled.add(id);
  }
  return sampled;
}

function sameMembers(a: ReadonlySet<string>, b: ReadonlySet<string>): boolean {
  return a.size === b.size && [...a].every((id) => b.has(id));
}

/** The vector sources among `sourceIds` with a sampled tile in the current view. */
export function useSampledTileSources(
  mapRef: RefObject<MapLibreMap | null>,
  mapReady: boolean,
  sourceIds: ReadonlySet<string>,
): ReadonlySet<string> {
  const [sampled, setSampled] = useState(NONE);
  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map) {
      setSampled(NONE);
      return;
    }
    const update = () => {
      const next = sampledInView(map, sourceIds);
      setSampled((prev) => (sameMembers(prev, next) ? prev : next));
    };
    update();
    map.on('moveend', update);
    const unsubscribe = subscribeTileSampling(update);
    return () => {
      map.off('moveend', update);
      unsubscribe();
    };
  }, [mapRef, mapReady, sourceIds]);
  return sampled;
}
