import { useEffect, useMemo, useRef, useState } from 'react';
import { useControl, useMap } from '@vis.gl/react-maplibre';
import { MapLibreOverlay } from '@deck.gl/maplibre';
import type { Layer } from '@deck.gl/core';
import { useTranslation } from 'react-i18next';
import { makeDatasetFetch } from './dataset-fetch';
import type { Viewer3DSource } from './viewer-support';

interface Props {
  datasetId: string;
  source: Viewer3DSource;
  /** Fit the camera to the data when the dataset has no recorded extent. */
  fitToData: boolean;
}

const VIEW_PITCH = 55;

/**
 * Draws a 3D Tiles tileset or a COPC point cloud over the dataset page's MapLibre map. The overlay
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
  source,
  fitToData,
  onDeckRestored,
}: Props & { onDeckRestored: () => void }) {
  const { t } = useTranslation('dataset');
  const { current: mapRef } = useMap();
  const datasetFetch = useMemo(() => makeDatasetFetch(datasetId, source.kind === 'tileset' ? 'tiles3d' : 'copc'), [datasetId, source.kind]);
  const onDeckRestoredRef = useRef(onDeckRestored);
  onDeckRestoredRef.current = onDeckRestored;
  // Deck creates its device, and so its canvas, asynchronously; the listeners
  // attach when it reports ready.
  const overlay = useControl(
    () =>
      new MapLibreOverlay({
        interleaved: false,
        layers: [],
        onDeviceInitialized: (device) => {
          const canvas = device.getDefaultCanvasContext().canvas as HTMLCanvasElement;
          canvas.addEventListener('webglcontextlost', (event) => event.preventDefault());
          canvas.addEventListener('webglcontextrestored', () => onDeckRestoredRef.current());
        },
      }),
  );
  const [failed, setFailed] = useState(false);
  // Read when the tileset finishes loading, so an extent or map that arrives
  // later does not rebuild the layer and refetch the tiles.
  const mapRefLatest = useRef(mapRef);
  mapRefLatest.current = mapRef;
  const fitRef = useRef(fitToData);
  fitRef.current = fitToData;

  const { kind, url } = source;
  const sizeBytes = source.kind === 'pointcloud' ? source.sizeBytes : null;
  useEffect(() => {
    let cancelled = false;
    let stopLoad: (() => void) | undefined;
    const tilt = () => mapRefLatest.current?.getMap().easeTo({ pitch: VIEW_PITCH, duration: 0 });
    if (kind === 'tileset') {
      void import('./tileset-layers').then(
        ({ createTilesetLayers }) => {
          if (cancelled) return;
          overlay.setProps({
            layers: createTilesetLayers(url, datasetFetch, {
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
    } else {
      void import('./pointcloud-layers').then(
        ({ loadPointCloud }) => {
          if (cancelled) return;
          const layers: Layer[] = [];
          stopLoad = loadPointCloud(url, sizeBytes, datasetFetch, {
            onLayer: (layer) => {
              if (layers.length === 0) tilt();
              layers.push(layer);
              overlay.setProps({ layers: [...layers] });
            },
            onError: () => setFailed(true),
          });
        },
        () => setFailed(true),
      );
    }
    return () => {
      cancelled = true;
      stopLoad?.();
    };
  }, [overlay, kind, url, sizeBytes, datasetFetch]);

  if (!failed) return null;
  return (
    <p
      role="alert"
      className="absolute start-2 top-2 z-10 rounded-sm bg-background/90 px-2 py-1 text-xs text-destructive"
    >
      {t(kind === 'tileset' ? 'tileset.viewerError' : 'pointcloud.viewerError')}
    </p>
  );
}
