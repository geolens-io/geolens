import { useEffect, useMemo, useRef, useState } from 'react';
import { useControl, useMap } from '@vis.gl/react-maplibre';
import { MapLibreOverlay } from '@deck.gl/maplibre';
import { useTranslation } from 'react-i18next';
import { makeTilesetFetch } from './tileset-fetch';

interface Props {
  datasetId: string;
  tilesetUrl: string;
  /** Fit the camera to the tileset when the dataset has no recorded extent. */
  fitToTileset: boolean;
}

const VIEW_PITCH = 55;

/**
 * Draws a 3D Tiles tileset over the dataset page's MapLibre map. The overlay
 * is not interleaved: deck.gl owns a second canvas, whose context is lost and
 * restored separately from the map's and does not recover on its own, so a
 * restore remounts the overlay.
 */
export default function Dataset3DOverlay(props: Props) {
  const [generation, setGeneration] = useState(0);
  return (
    <OverlayLayers
      key={generation}
      {...props}
      onDeckRestored={() => setGeneration((g) => g + 1)}
    />
  );
}

function OverlayLayers({
  datasetId,
  tilesetUrl,
  fitToTileset,
  onDeckRestored,
}: Props & { onDeckRestored: () => void }) {
  const { t } = useTranslation('dataset');
  const { current: mapRef } = useMap();
  const datasetFetch = useMemo(() => makeTilesetFetch(datasetId), [datasetId]);
  const overlay = useControl(() => new MapLibreOverlay({ interleaved: false, layers: [] }));
  const [failed, setFailed] = useState(false);
  // Read when the tileset finishes loading, so an extent or map that arrives
  // later does not rebuild the layer and refetch the tiles.
  const mapRefLatest = useRef(mapRef);
  mapRefLatest.current = mapRef;
  const fitRef = useRef(fitToTileset);
  fitRef.current = fitToTileset;

  useEffect(() => {
    let cancelled = false;
    void import('./tileset-layers').then(
      ({ createTilesetLayers }) => {
        if (cancelled) return;
        overlay.setProps({
          layers: createTilesetLayers(tilesetUrl, datasetFetch, {
            onLoad: ({ cartographicCenter, zoom }) => {
              mapRefLatest.current?.getMap().easeTo({
                pitch: VIEW_PITCH,
                duration: 0,
                ...(fitRef.current
                  ? { center: [cartographicCenter[0], cartographicCenter[1]], zoom }
                  : {}),
              });
            },
            onError: () => setFailed(true),
          }),
        });
      },
      () => setFailed(true),
    );
    return () => {
      cancelled = true;
    };
  }, [overlay, tilesetUrl, datasetFetch]);

  useEffect(() => {
    const canvas = overlay.getCanvas();
    if (!canvas) return;
    const onLost = (event: Event) => event.preventDefault();
    canvas.addEventListener('webglcontextlost', onLost);
    canvas.addEventListener('webglcontextrestored', onDeckRestored);
    return () => {
      canvas.removeEventListener('webglcontextlost', onLost);
      canvas.removeEventListener('webglcontextrestored', onDeckRestored);
    };
  }, [overlay, onDeckRestored]);

  if (!failed) return null;
  return (
    <p
      role="alert"
      className="absolute start-2 top-2 z-10 rounded-sm bg-background/90 px-2 py-1 text-xs text-destructive"
    >
      {t('tileset.viewerError')}
    </p>
  );
}
