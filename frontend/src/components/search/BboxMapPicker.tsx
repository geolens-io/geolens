import { useEffect, useRef, useMemo } from 'react';
import { Map as MapGL } from '@vis.gl/react-maplibre';
import { TerraDraw, TerraDrawRectangleMode } from 'terra-draw';
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useTranslation } from 'react-i18next';
import { useTheme } from '@/components/theme-provider';
import { useBasemaps } from '@/hooks/use-settings';
import {
  getThemeBasemap,
  toMaplibreStyle,
  FALLBACK_BASEMAP_STYLE_URL,
  FALLBACK_BASEMAP_STYLE_URL_DARK,
} from '@/lib/basemap-utils';
import { MAP_COLORS } from '@/lib/map-colors';
import 'maplibre-gl/dist/maplibre-gl.css';
// feat(#846): wires maplibre v6's worker URL. Side-effect import, kept out of
// main.tsx so map-vendor stays out of the eager entry graph (fix(#1624)).
import '@/lib/maplibre-worker';

interface BboxMapPickerProps {
  onBboxSelected: (bbox: string) => void;
}

export function BboxMapPicker({ onBboxSelected }: BboxMapPickerProps) {
  const { t } = useTranslation('search');
  const { resolvedTheme } = useTheme();
  const { data: basemaps } = useBasemaps();
  const drawRef = useRef<TerraDraw | null>(null);
  const onBboxSelectedRef = useRef(onBboxSelected);
  onBboxSelectedRef.current = onBboxSelected;

  const basemapStyle = useMemo(() => {
    const themeBasemap = getThemeBasemap(basemaps ?? [], resolvedTheme);
    if (themeBasemap) return toMaplibreStyle(themeBasemap.url, themeBasemap.attribution);
    return toMaplibreStyle(
      resolvedTheme === 'dark' ? FALLBACK_BASEMAP_STYLE_URL_DARK : FALLBACK_BASEMAP_STYLE_URL,
    );
  }, [basemaps, resolvedTheme]);

  // Cleanup terra-draw on unmount
  useEffect(() => {
    return () => {
      if (drawRef.current) {
        drawRef.current.stop();
        drawRef.current = null;
      }
    };
  }, []);

  const handleMapLoad = (e: { target: MaplibreMap }) => {
    const map = e.target;

    const td = new TerraDraw({
      adapter: new TerraDrawMapLibreGLAdapter({ map }),
      modes: [
        new TerraDrawRectangleMode({
          styles: {
            fillColor: MAP_COLORS.default.fill,
            fillOpacity: MAP_COLORS.default.fillOpacity,
            outlineColor: MAP_COLORS.default.stroke,
            outlineWidth: MAP_COLORS.default.strokeWidth,
          },
        }),
      ],
    });

    td.start();
    td.setMode('rectangle');

    td.on('finish', (id: string | number) => {
      const feature = td.getSnapshotFeature(id);
      if (!feature || feature.geometry.type !== 'Polygon') return;

      const coords = (feature.geometry as GeoJSON.Polygon).coordinates[0];
      let minX = Infinity;
      let minY = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;
      for (const [lng, lat] of coords) {
        if (lng < minX) minX = lng;
        if (lat < minY) minY = lat;
        if (lng > maxX) maxX = lng;
        if (lat > maxY) maxY = lat;
      }

      onBboxSelectedRef.current(`${minX},${minY},${maxX},${maxY}`);
      td.removeFeatures([id]);
    });

    drawRef.current = td;
  };

  return (
    <div>
      {/* audit(w3-maps): aria-label on <MapGL> is silently dropped —
          @vis.gl/react-maplibre v8 forwards only id/ref/style, and MapLibre
          labels its canvas "Map". Label the wrapper region instead (same
          pattern as DatasetMap's shell). */}
      <div
        className="overflow-hidden rounded-md"
        role="region"
        aria-label={t('bbox.mapAriaLabel', { defaultValue: 'Bounding box map' })}
      >
        <MapGL
          initialViewState={{ longitude: 0, latitude: 20, zoom: 1 }}
          style={{ width: '100%', height: 250 }}
          mapStyle={basemapStyle as string}
          onLoad={handleMapLoad}
        />
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground">
        {t('bbox.instruction')}
      </p>
    </div>
  );
}
