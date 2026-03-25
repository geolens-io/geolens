import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Map as MapGL } from '@vis.gl/react-maplibre';
import {
  TerraDraw,
  TerraDrawRectangleMode,
  TerraDrawPolygonMode,
} from 'terra-draw';
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useTranslation } from 'react-i18next';
import { Square, Pentagon, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { useTheme } from '@/components/theme-provider';
import { useBasemaps } from '@/hooks/use-settings';
import { getThemeBasemap, toMaplibreStyle } from '@/lib/basemap-utils';
import { MAP_COLORS } from '@/lib/map-colors';
import 'maplibre-gl/dist/maplibre-gl.css';

type DrawMode = 'rectangle' | 'polygon';

// Persist viewport across component unmount/remount
let savedViewport = { longitude: 0, latitude: 20, zoom: 1 };

interface SpatialFilterPanelProps {
  open: boolean;
  onClose: () => void;
  onApply: (bbox: string, predicate: string, geometry?: GeoJSON.Geometry) => void;
  initialBbox?: string;
  initialPredicate?: string;
}

function bboxToPolygon(bbox: string): GeoJSON.Feature<GeoJSON.Polygon> {
  const [minX, minY, maxX, maxY] = bbox.split(',').map(Number);
  return {
    type: 'Feature',
    properties: {},
    geometry: {
      type: 'Polygon',
      coordinates: [
        [
          [minX, minY],
          [maxX, minY],
          [maxX, maxY],
          [minX, maxY],
          [minX, minY],
        ],
      ],
    },
  };
}

function extractBbox(coords: number[][]): string {
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
  return `${minX},${minY},${maxX},${maxY}`;
}

export function SpatialFilterPanel({
  open,
  onClose,
  onApply,
  initialBbox,
  initialPredicate,
}: SpatialFilterPanelProps) {
  const { t } = useTranslation('search');
  const { resolvedTheme } = useTheme();
  const { data: basemaps } = useBasemaps();

  const [drawMode, setDrawMode] = useState<DrawMode>('rectangle');
  const [pendingBbox, setPendingBbox] = useState('');
  const [predicate, setPredicate] = useState<'intersects' | 'within'>(
    (initialPredicate as 'intersects' | 'within') || 'intersects',
  );

  const drawRef = useRef<TerraDraw | null>(null);
  const drawnFeatureIdRef = useRef<string | number | null>(null);
  const mapRef = useRef<MaplibreMap | null>(null);
  const initializedRef = useRef(false);
  const hasOpenedRef = useRef(false);
  const panelRef = useRef<HTMLDivElement>(null);

  if (open) hasOpenedRef.current = true;

  const basemapStyle = useMemo(() => {
    const themeBasemap = getThemeBasemap(basemaps ?? [], resolvedTheme);
    if (themeBasemap) return toMaplibreStyle(themeBasemap.url);
    return toMaplibreStyle(
      resolvedTheme === 'dark'
        ? 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
        : 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
    );
  }, [basemaps, resolvedTheme]);

  // Restore drawn feature when panel reopens
  useEffect(() => {
    if (!open) return;

    const td = drawRef.current;
    if (!td) return;

    // If we have a drawn feature ID, it's already on the map from Terra Draw state
    if (drawnFeatureIdRef.current != null) {
      // Feature should still be in Terra Draw's store
      const feature = td.getSnapshotFeature(drawnFeatureIdRef.current);
      if (feature) {
        const coords = (feature.geometry as GeoJSON.Polygon).coordinates[0];
        setPendingBbox(extractBbox(coords));
        return;
      }
      // Feature was lost, clear ref
      drawnFeatureIdRef.current = null;
    }

    // Restore from initialBbox if no drawn feature
    if (initialBbox && !drawnFeatureIdRef.current) {
      try {
        const poly = bboxToPolygon(initialBbox);
        const ids = td.addFeatures([poly]);
        if (ids.length > 0) {
          drawnFeatureIdRef.current = ids[0];
          setPendingBbox(initialBbox);
        }
      } catch {
        // Ignore restore errors
      }
    }
  }, [open, initialBbox]);

  const handleModeChange = useCallback(
    (value: string) => {
      if (!value) return;
      const newMode = value as DrawMode;
      setDrawMode(newMode);

      const td = drawRef.current;
      if (!td) return;

      // Clear existing drawn feature
      if (drawnFeatureIdRef.current != null) {
        try {
          td.removeFeatures([drawnFeatureIdRef.current]);
        } catch {
          // Already removed
        }
        drawnFeatureIdRef.current = null;
        setPendingBbox('');
      }

      td.setMode(newMode);
    },
    [],
  );

  const handleClear = useCallback(() => {
    const td = drawRef.current;
    if (!td) return;

    if (drawnFeatureIdRef.current != null) {
      try {
        td.removeFeatures([drawnFeatureIdRef.current]);
      } catch {
        // Already removed
      }
      drawnFeatureIdRef.current = null;
    }
    setPendingBbox('');
    setPredicate('intersects');
  }, []);

  const handleApply = useCallback(() => {
    if (!pendingBbox) return;
    let geom: GeoJSON.Geometry | undefined;
    if (drawMode === 'polygon' && drawnFeatureIdRef.current != null) {
      const td = drawRef.current;
      if (td) {
        const feature = td.getSnapshotFeature(drawnFeatureIdRef.current);
        if (feature) {
          geom = feature.geometry as GeoJSON.Geometry;
        }
      }
    }
    onApply(pendingBbox, predicate, geom);
    onClose();
  }, [pendingBbox, predicate, drawMode, onApply, onClose]);

  const handleMapLoad = useCallback(
    (e: { target: MaplibreMap }) => {
      const map = e.target;
      mapRef.current = map;

      const modeStyles = {
        fillColor: MAP_COLORS.default.fill,
        fillOpacity: MAP_COLORS.default.fillOpacity,
        outlineColor: MAP_COLORS.default.stroke,
        outlineWidth: MAP_COLORS.default.strokeWidth,
      };

      const td = new TerraDraw({
        adapter: new TerraDrawMapLibreGLAdapter({ map }),
        modes: [
          new TerraDrawRectangleMode({ styles: modeStyles }),
          new TerraDrawPolygonMode({ styles: modeStyles }),
        ],
      });

      td.start();
      td.setMode('rectangle');

      td.on('finish', (id: string | number) => {
        const feature = td.getSnapshotFeature(id);
        if (!feature || feature.geometry.type !== 'Polygon') return;

        // Remove previous feature if exists
        if (drawnFeatureIdRef.current != null && drawnFeatureIdRef.current !== id) {
          try {
            td.removeFeatures([drawnFeatureIdRef.current]);
          } catch {
            // Already removed
          }
        }

        drawnFeatureIdRef.current = id;
        const coords = (feature.geometry as GeoJSON.Polygon).coordinates[0];
        setPendingBbox(extractBbox(coords));
      });

      drawRef.current = td;
      initializedRef.current = true;

      // Restore initial bbox after Terra Draw is ready
      if (initialBbox) {
        try {
          const poly = bboxToPolygon(initialBbox);
          const ids = td.addFeatures([poly]);
          if (ids.length > 0) {
            drawnFeatureIdRef.current = ids[0];
            setPendingBbox(initialBbox);
          }
        } catch {
          // Ignore restore errors
        }
      }
    },
    [initialBbox],
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (drawRef.current) {
        drawRef.current.stop();
        drawRef.current = null;
      }
      initializedRef.current = false;
    };
  }, []);

  // Escape key handler + focus management
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    panelRef.current?.focus();
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <>
      <button
        type="button"
        tabIndex={-1}
        aria-hidden="true"
        className="fixed inset-0 z-40 bg-black/10"
        onClick={onClose}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('spatial.title', { defaultValue: 'Search area' })}
        tabIndex={-1}
        className="fixed inset-y-0 right-0 z-50 w-[400px] border-l border-border/50 bg-background shadow-xl"
      >
        <div className="flex h-full flex-col overflow-y-auto p-4">
          {/* Header */}
          <div className="flex items-center justify-between pb-3">
            <h3 className="text-sm font-semibold">
              {t('spatial.title', { defaultValue: 'Search area' })}
            </h3>
            <Button
              variant="ghost"
              size="sm"
              className="size-7 p-0"
              onClick={onClose}
              aria-label={t('spatial.close', { defaultValue: 'Close' })}
            >
              <X className="size-4" />
            </Button>
          </div>

          {/* Mode toggle */}
          <ToggleGroup
            type="single"
            value={drawMode}
            onValueChange={handleModeChange}
            className="mb-3 w-full"
          >
            <ToggleGroupItem value="rectangle" className="flex-1 text-xs">
              <Square className="mr-1 size-3" />
              {t('spatial.rectangle', { defaultValue: 'Rectangle' })}
            </ToggleGroupItem>
            <ToggleGroupItem value="polygon" className="flex-1 text-xs">
              <Pentagon className="mr-1 size-3" />
              {t('spatial.polygon', { defaultValue: 'Polygon' })}
            </ToggleGroupItem>
          </ToggleGroup>

          {/* Map */}
          <div className="min-h-[300px] overflow-hidden rounded-lg border">
            {hasOpenedRef.current && (
              <MapGL
                initialViewState={savedViewport}
                style={{ width: '100%', height: 300 }}
                mapStyle={basemapStyle as string}
                onLoad={handleMapLoad}
                onMoveEnd={(e) => {
                  const { lng, lat } = e.target.getCenter();
                  savedViewport = { longitude: lng, latitude: lat, zoom: e.target.getZoom() };
                }}
                attributionControl={false}
              />
            )}
          </div>

          {/* Area summary / instruction */}
          {pendingBbox ? (
            <p className="mt-2 text-xs text-muted-foreground">
              {drawMode === 'rectangle'
                ? `Bbox: ${pendingBbox.split(',').map((n) => Number(n).toFixed(2)).join(', ')}`
                : '1 polygon selected'}
            </p>
          ) : (
            <p className="mt-2 text-xs text-muted-foreground">
              {drawMode === 'rectangle'
                ? t('spatial.rectangleInstruction', {
                    defaultValue: 'Click and drag to draw a bounding box',
                  })
                : t('spatial.polygonInstruction', {
                    defaultValue: 'Click to add points, double-click to finish',
                  })}
            </p>
          )}

          {/* Predicate toggle */}
          <div className="mt-2 flex items-center gap-2">
            <span className="text-xs text-muted-foreground">
              {t('spatial.predicate', { defaultValue: 'Mode:' })}
            </span>
            <ToggleGroup
              type="single"
              value={predicate}
              onValueChange={(v) => v && setPredicate(v as 'intersects' | 'within')}
              className="h-7"
            >
              <ToggleGroupItem value="intersects" className="h-7 px-2 text-xs">
                {t('spatial.intersects', { defaultValue: 'Intersects' })}
              </ToggleGroupItem>
              <ToggleGroupItem value="within" className="h-7 px-2 text-xs">
                {t('spatial.within', { defaultValue: 'Within' })}
              </ToggleGroupItem>
            </ToggleGroup>
          </div>

          {/* Use current map extent */}
          <Button
            variant="outline"
            size="sm"
            className="mt-2 w-full text-xs"
            onClick={() => {
              const map = mapRef.current;
              if (!map) return;
              const bounds = map.getBounds();
              const bboxStr = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;
              const td = drawRef.current;
              if (td && drawnFeatureIdRef.current != null) {
                try {
                  td.removeFeatures([drawnFeatureIdRef.current]);
                } catch {
                  // Already removed
                }
                drawnFeatureIdRef.current = null;
              }
              if (td) {
                const poly = bboxToPolygon(bboxStr);
                const ids = td.addFeatures([poly]);
                if (ids.length > 0) drawnFeatureIdRef.current = ids[0];
              }
              setPendingBbox(bboxStr);
              setDrawMode('rectangle');
              if (td) {
                td.setMode('rectangle');
              }
            }}
          >
            {t('spatial.useExtent', { defaultValue: 'Use current map extent' })}
          </Button>

          {/* Actions */}
          <div className="mt-auto flex items-center gap-2 pt-4">
            {pendingBbox && (
              <Button variant="ghost" size="sm" onClick={handleClear}>
                {t('spatial.clearArea', { defaultValue: 'Clear area' })}
              </Button>
            )}
            <Button
              size="sm"
              className="ml-auto"
              disabled={!pendingBbox}
              onClick={handleApply}
            >
              {t('filters.apply')}
            </Button>
          </div>
        </div>
      </div>
    </>,
    document.body,
  );
}
