import { useEffect, useMemo, useState } from 'react';
import { useControl, useMap } from '@vis.gl/react-maplibre';
import { MapLibreOverlay } from '@deck.gl/maplibre';
import type { Layer } from '@deck.gl/core';
import { useTranslation } from 'react-i18next';
import { useDataset } from '@/components/dataset/hooks/use-dataset';
import { makeTilesetFetch } from './tileset-fetch';

interface Props {
  datasetId: string;
  /** Fit the camera to the tileset when the dataset has no recorded extent. */
  fitToTileset: boolean;
}

const VIEW_PITCH = 55;

/**
 * Draws a 3D Tiles tileset over the dataset page's MapLibre map. The overlay
 * is not interleaved: deck.gl owns a second canvas, whose context is lost and
 * restored separately from the map's, so a restore remounts the overlay.
 */
export default function Dataset3DOverlay({ datasetId, fitToTileset }: Props) {
  const [generation, setGeneration] = useState(0);
  return (
    <OverlayLayers
      key={generation}
      datasetId={datasetId}
      fitToTileset={fitToTileset}
      onDeckRestored={() => setGeneration((g) => g + 1)}
    />
  );
}

function OverlayLayers({
  datasetId,
  fitToTileset,
  onDeckRestored,
}: Props & { onDeckRestored: () => void }) {
  const { t } = useTranslation('dataset');
  const { current: mapRef } = useMap();
  const { data: dataset } = useDataset(datasetId);
  const datasetFetch = useMemo(() => makeTilesetFetch(datasetId), [datasetId]);
  const overlay = useControl(() => new MapLibreOverlay({ interleaved: false, layers: [] }));
  const [layers, setLayers] = useState<Layer[]>([]);
  const [failed, setFailed] = useState(false);
  const tilesetUrl = dataset?.tileset?.url;

  useEffect(() => {
    if (!tilesetUrl) return;
    let cancelled = false;
    void import('./tileset-layers').then(
      ({ createTilesetLayers }) => {
        if (cancelled) return;
        setLayers(
          createTilesetLayers(tilesetUrl, datasetFetch, {
            onLoad: ({ cartographicCenter, zoom }) => {
              const map = mapRef?.getMap();
              if (!map) return;
              map.easeTo({
                pitch: VIEW_PITCH,
                duration: 0,
                ...(fitToTileset ? { center: [cartographicCenter[0], cartographicCenter[1]], zoom } : {}),
              });
            },
            onError: () => setFailed(true),
          }),
        );
      },
      () => setFailed(true),
    );
    return () => {
      cancelled = true;
    };
  }, [tilesetUrl, datasetFetch, mapRef, fitToTileset]);

  useEffect(() => {
    overlay.setProps({ layers });
  }, [overlay, layers]);

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
