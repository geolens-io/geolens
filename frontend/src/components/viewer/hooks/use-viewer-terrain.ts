import { useEffect, useMemo, useRef, useState } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { SharedLayerResponse } from '@/types/api';

/** Pre-seed the raster-dem terrain source if it doesn't already exist. */
function seedTerrainSource(map: MaplibreMap, tileUrl: string) {
  if (!map.getSource('terrain-dem')) {
    map.addSource('terrain-dem', {
      type: 'raster-dem',
      tiles: [`${window.location.origin}${tileUrl}`],
      tileSize: 256,
      encoding: 'mapbox',
    });
  }
}

/**
 * Manages terrain source seeding, terrain toggle pitch animation,
 * and basemap-swap terrain re-seeding for the viewer map.
 */
export function useViewerTerrain({
  layers,
  mapRef,
  mapReady,
}: {
  layers: SharedLayerResponse[];
  mapRef: React.RefObject<MaplibreMap | null>;
  mapReady: boolean;
}) {
  const [terrainReady, setTerrainReady] = useState(false);
  const terrainActiveRef = useRef(false);

  // Find the first DEM raster layer in the shared map composition
  const demLayer = useMemo(
    () => layers.find((l) => l.is_dem && (l.dataset_record_type === 'raster_dataset' || l.dataset_record_type === 'vrt_dataset')),
    [layers],
  );

  // Tile URL for the DEM source — used to seed the raster-dem terrain source
  const demTileUrl = useMemo(() => demLayer?.tile_url ?? null, [demLayer]);

  // Keep a stable ref to demTileUrl so style.load (registered once) sees latest value
  const demTileUrlRef = useRef(demTileUrl);
  demTileUrlRef.current = demTileUrl;

  // Pre-seed the raster-dem terrain source when the map is ready and a DEM layer is present.
  // The source exists but terrain is NOT enabled until the user clicks TerrainControl.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !demTileUrl) {
      setTerrainReady(false);
      return;
    }
    seedTerrainSource(map, demTileUrl);
    setTerrainReady(true);
  }, [mapReady, demTileUrl, mapRef]);

  // Listen for the 'terrain' event to drive pitch animation when TerrainControl toggles.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const onTerrain = () => {
      const active = map.getTerrain() != null;
      terrainActiveRef.current = active;
      if (active) {
        map.easeTo({ pitch: 45, duration: 300, easing: (t: number) => t * (2 - t) });
      } else {
        map.easeTo({ pitch: 0, bearing: 0, duration: 300, easing: (t: number) => t * (2 - t) });
      }
    };

    map.on('terrain', onTerrain);
    return () => { map.off('terrain', onTerrain); };
  }, [mapReady, mapRef]);

  /** Re-seed terrain after a basemap/style swap (call from style.load handler). */
  const reseedTerrainOnStyleLoad = () => {
    const currentDemTileUrl = demTileUrlRef.current;
    if (currentDemTileUrl) {
      const m = mapRef.current;
      if (!m) return;
      // SH-10: Wait for map idle instead of arbitrary setTimeout
      m.once('idle', () => {
        const map = mapRef.current;
        if (!map) return;
        seedTerrainSource(map, currentDemTileUrl);
        setTerrainReady(true);
        // Re-enable terrain if it was active before the basemap swap
        if (terrainActiveRef.current) {
          map.setTerrain({ source: 'terrain-dem' });
        }
      });
    }
  };

  return { terrainReady, reseedTerrainOnStyleLoad };
}
