import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Map as MapGL } from '@vis.gl/react-maplibre';
import {
  TerraDraw,
  TerraDrawRectangleMode,
  TerraDrawPolygonMode,
  type GeoJSONStoreFeatures,
} from 'terra-draw';
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useTranslation } from 'react-i18next';
import { Square, Pentagon, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { useTheme } from '@/components/theme-provider';
import { useBasemaps } from '@/hooks/use-settings';
import { useMapLocale } from '@/hooks/use-map-locale';
import {
  getThemeBasemap,
  toMaplibreStyle,
  FALLBACK_BASEMAP_STYLE_URL,
  FALLBACK_BASEMAP_STYLE_URL_DARK,
} from '@/lib/basemap-utils';
import { MAP_COLORS } from '@/lib/map-colors';
import { normalizeBboxLongitudes } from '@/lib/bbox';
import { randomId } from '@/lib/random-id';
import 'maplibre-gl/dist/maplibre-gl.css';
// feat(#846): wires maplibre v6's worker URL. Side-effect import, kept out of
// main.tsx so map-vendor stays out of the eager entry graph (fix(#1624)).
import '@/lib/maplibre-worker';

type DrawMode = 'rectangle' | 'polygon';

// Persist viewport across component unmount/remount
let savedViewport = { longitude: 0, latitude: 20, zoom: 1 };

interface SpatialFilterPanelProps {
  open: boolean;
  onClose: () => void;
  onApply: (bbox: string, predicate: string, geometry?: GeoJSON.Geometry) => void;
  initialBbox?: string;
  /** The applied polygon as GeoJSON text; it takes precedence over the bbox. */
  initialGeometry?: string;
  initialPredicate?: string;
}

/**
 * Bridge between GeoJSON.Feature<Polygon> and the store's feature type.
 * The store uses a branded/extended GeoJSON type that is structurally
 * compatible but nominally distinct — an explicit cast is required here.
 * A runtime check would be pointless since the shape is guaranteed by the caller.
 */
function toStoreFeature(feature: GeoJSON.Feature<GeoJSON.Polygon>): GeoJSONStoreFeatures {
  return feature as unknown as GeoJSONStoreFeatures;
}

// Terra Draw rejects longitudes outside +/-180 and more than nine decimals.
const roundCoord = (n: number) => Math.round(n * 1e9) / 1e9;

function rectangleRing(west: number, south: number, east: number, north: number): number[][] {
  const [w, s, e, n] = [west, south, east, north].map(roundCoord);
  return [[w, s], [e, s], [e, n], [w, n], [w, s]];
}

/**
 * The rings that draw a bbox. A normalized box that crosses the seam has
 * west > east and cannot be one polygon within +/-180, so it is drawn as the
 * two halves either side of the seam.
 */
export function bboxToRings(bbox: string): number[][][] {
  const [minX, minY, maxX, maxY] = bbox.split(',').map(Number);
  if (maxX >= minX) return [rectangleRing(minX, minY, maxX, maxY)];
  return [rectangleRing(minX, minY, 180, maxY), rectangleRing(-180, minY, maxX, maxY)];
}

function ringFeature(ring: number[][], id: string): GeoJSONStoreFeatures {
  return toStoreFeature({
    type: 'Feature',
    id,
    properties: { mode: 'rectangle' },
    geometry: { type: 'Polygon', coordinates: [ring] },
  } as GeoJSON.Feature<GeoJSON.Polygon>);
}

/**
 * Draws a bbox as rectangle(s); returns the drawn ids (empty when Terra Draw
 * rejects it, which needs a registered mode and an id).
 */
function addRectangle(td: TerraDraw, bbox: string): Array<string | number> {
  const ids = bboxToRings(bbox).map(() => randomId());
  const results = td.addFeatures(bboxToRings(bbox).map((ring, i) => ringFeature(ring, ids[i])));
  return results.every((r) => r.valid) ? ids : [];
}

function parsePolygon(text: string | undefined): GeoJSON.Polygon | null {
  if (!text) return null;
  try {
    const geometry = JSON.parse(text) as GeoJSON.Geometry;
    return geometry.type === 'Polygon' ? geometry : null;
  } catch {
    return null;
  }
}

function addPolygon(td: TerraDraw, polygon: GeoJSON.Polygon): Array<string | number> {
  const id = randomId();
  const feature = { type: 'Feature', id, properties: { mode: 'polygon' }, geometry: polygon };
  const [result] = td.addFeatures([feature as unknown as GeoJSONStoreFeatures]);
  return result?.valid ? [id] : [];
}

function fitToBbox(map: MaplibreMap | null, bbox: string) {
  const [minX, minY, maxX, maxY] = bbox.split(',').map(Number);
  map?.fitBounds([[minX, minY], [maxX < minX ? maxX + 360 : maxX, maxY]], { padding: 40, duration: 0 });
}

function hasArea(coords: number[][]): boolean {
  const [minX, minY, maxX, maxY] = extractBbox(coords).split(',').map(Number);
  return maxX > minX && maxY > minY;
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
  initialGeometry,
  initialPredicate,
}: SpatialFilterPanelProps) {
  const { t } = useTranslation('search');
  const mapLocale = useMapLocale();
  const { resolvedTheme } = useTheme();
  const { data: basemaps } = useBasemaps();

  const [drawMode, setDrawMode] = useState<DrawMode>('rectangle');
  const [pendingBbox, setPendingBbox] = useState('');
  const [predicate, setPredicate] = useState<'intersects' | 'within'>(
    (initialPredicate as 'intersects' | 'within') || 'intersects',
  );

  const drawRef = useRef<TerraDraw | null>(null);
  const drawnFeatureIdRef = useRef<string | number | null>(null);
  // The far half of a rectangle drawn across the seam.
  const extraDrawnIdsRef = useRef<Array<string | number>>([]);
  const mapRef = useRef<MaplibreMap | null>(null);
  // The applied polygon until the user draws or clears another area. Terra Draw
  // can refuse to re-add a polygon it finished (longitudes past 180), and
  // applying again must not turn that polygon into its bounding box.
  const restoredPolygonRef = useRef<GeoJSON.Polygon | null>(null);

  const basemapStyle = useMemo(() => {
    const themeBasemap = getThemeBasemap(basemaps ?? [], resolvedTheme);
    if (themeBasemap) return toMaplibreStyle(themeBasemap.url, themeBasemap.attribution);
    return toMaplibreStyle(
      resolvedTheme === 'dark' ? FALLBACK_BASEMAP_STYLE_URL_DARK : FALLBACK_BASEMAP_STYLE_URL,
    );
  }, [basemaps, resolvedTheme]);

  const storedPolygon = useMemo(() => parsePolygon(initialGeometry), [initialGeometry]);

  // Draws the applied area (a polygon wins over its bounding box) and selects
  // the matching draw mode.
  const restoreStoredArea = useCallback(
    (td: TerraDraw, map: MaplibreMap | null) => {
      if (!initialBbox) return;
      const ids = storedPolygon ? addPolygon(td, storedPolygon) : addRectangle(td, initialBbox);
      drawnFeatureIdRef.current = ids[0] ?? null;
      extraDrawnIdsRef.current = ids.slice(1);
      restoredPolygonRef.current = storedPolygon;
      // The stored bbox is the active filter whether or not it could be drawn.
      setPendingBbox(initialBbox);
      if (storedPolygon) {
        setDrawMode('polygon');
        td.setMode('polygon');
      }
      fitToBbox(map, initialBbox);
    },
    [initialBbox, storedPolygon],
  );

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
        // A seam box is drawn as two halves; the first alone is not the area.
        if (extraDrawnIdsRef.current.length === 0) {
          const coords = (feature.geometry as GeoJSON.Polygon).coordinates[0];
          setPendingBbox(extractBbox(coords));
        }
        return;
      }
      // Feature was lost, clear ref
      drawnFeatureIdRef.current = null;
    }

    // Restore from initialBbox if no drawn feature
    if (initialBbox && !drawnFeatureIdRef.current) {
      try {
        restoreStoredArea(td, mapRef.current);
      } catch {
        // Ignore restore errors
      }
    }
  }, [open, initialBbox, restoreStoredArea]);

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
          td.removeFeatures([drawnFeatureIdRef.current, ...extraDrawnIdsRef.current]);
          extraDrawnIdsRef.current = [];
        } catch {
          // Already removed
        }
        drawnFeatureIdRef.current = null;
      }
      // A restored area Terra Draw refused has no feature id but is still pending.
      setPendingBbox('');
      restoredPolygonRef.current = null;

      td.setMode(newMode);
    },
    [],
  );

  const handleClear = useCallback(() => {
    const td = drawRef.current;
    if (!td) return;

    if (drawnFeatureIdRef.current != null) {
      try {
        td.removeFeatures([drawnFeatureIdRef.current, ...extraDrawnIdsRef.current]);
        extraDrawnIdsRef.current = [];
      } catch {
        // Already removed
      }
      drawnFeatureIdRef.current = null;
    }
    restoredPolygonRef.current = null;
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
    if (!geom && drawMode === 'polygon') geom = restoredPolygonRef.current ?? undefined;
    onApply(normalizeBboxLongitudes(pendingBbox), predicate, geom);
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

        // A click-click with no movement on one axis yields a line, not an area.
        if (!hasArea(feature.geometry.coordinates[0])) {
          td.removeFeatures([id]);
          return;
        }

        restoredPolygonRef.current = null;

        // Remove previous feature if exists
        if (drawnFeatureIdRef.current != null && drawnFeatureIdRef.current !== id) {
          try {
            td.removeFeatures([drawnFeatureIdRef.current, ...extraDrawnIdsRef.current]);
            extraDrawnIdsRef.current = [];
          } catch {
            // Already removed
          }
        }

        drawnFeatureIdRef.current = id;
        const coords = (feature.geometry as GeoJSON.Polygon).coordinates[0];
        setPendingBbox(extractBbox(coords));
      });

      drawRef.current = td;

      // Restore initial bbox after Terra Draw is ready
      if (initialBbox) {
        try {
          restoreStoredArea(td, map);
        } catch {
          // Ignore restore errors
        }
      }
    },
    [initialBbox, restoreStoredArea],
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (drawRef.current) {
        drawRef.current.stop();
        drawRef.current = null;
      }
    };
  }, []);

  if (!open) return null;

  return (
    <Sheet
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose();
      }}
    >
      <SheetContent
        side="right"
        showCloseButton={false}
        className="w-full max-w-[420px] gap-0 border-s border-border/50 p-0 shadow-lg sm:max-w-[420px]"
      >
        <div className="flex h-full flex-col overflow-y-auto">
          <SheetHeader className="border-b border-border/40 pb-3 pe-14">
            <SheetTitle className="text-sm">
              {t('spatial.title', { defaultValue: 'Search area' })}
            </SheetTitle>
            <SheetDescription>
              {t('spatial.description', {
                defaultValue: 'Draw a rectangle or polygon to limit search results to a specific area.',
              })}
            </SheetDescription>
          </SheetHeader>
          <Button
            variant="ghost"
            size="icon"
            className="absolute top-4 end-4"
            onClick={onClose}
            aria-label={t('spatial.close', { defaultValue: 'Close' })}
          >
            <X className="size-4" />
          </Button>

          <div className="flex h-full flex-col px-4 pb-4">
            {/* Mode toggle */}
            <ToggleGroup
              type="single"
              value={drawMode}
              onValueChange={handleModeChange}
              className="mb-3 mt-4 w-full"
            >
              <ToggleGroupItem value="rectangle" className="flex-1 text-xs">
                <Square className="me-1 size-3" />
                {t('spatial.rectangle', { defaultValue: 'Rectangle' })}
              </ToggleGroupItem>
              <ToggleGroupItem value="polygon" className="flex-1 text-xs">
                <Pentagon className="me-1 size-3" />
                {t('spatial.polygon', { defaultValue: 'Polygon' })}
              </ToggleGroupItem>
            </ToggleGroup>

            {/* Map */}
            {/* audit(w3-maps): aria-label on <MapGL> is silently dropped —
                @vis.gl/react-maplibre v8 forwards only id/ref/style, and
                MapLibre labels its canvas "Map". Label the wrapper region
                instead (same pattern as DatasetMap's shell). */}
            <div
              className="min-h-[300px] overflow-hidden rounded-lg border"
              role="region"
              aria-label={t('spatial.mapAriaLabel', { defaultValue: 'Search area map' })}
            >
              <MapGL
                initialViewState={savedViewport}
                style={{ width: '100%', height: 300 }}
                mapStyle={basemapStyle as string}
                locale={mapLocale}
                onLoad={handleMapLoad}
                onMoveEnd={(e) => {
                  const { lng, lat } = e.target.getCenter();
                  savedViewport = { longitude: lng, latitude: lat, zoom: e.target.getZoom() };
                }}
              />
            </div>

            {/* Area summary / instruction */}
            {pendingBbox ? (
              <p className="mt-2 text-xs text-muted-foreground">
                {drawMode === 'rectangle'
                  ? `Bbox: ${normalizeBboxLongitudes(pendingBbox).split(',').map((n) => Number(n).toFixed(2)).join(', ')}`
                  : t('spatial.polygonSelected', { count: 1 })}
              </p>
            ) : (
              <p className="mt-2 text-xs text-muted-foreground">
                {drawMode === 'rectangle'
                  ? t('spatial.rectangleInstruction', {
                      defaultValue: 'Click to start the box, then click again to finish it',
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
                const bboxStr = normalizeBboxLongitudes(
                  `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`,
                );
                const td = drawRef.current;
                restoredPolygonRef.current = null;
                if (td && drawnFeatureIdRef.current != null) {
                  try {
                    td.removeFeatures([drawnFeatureIdRef.current, ...extraDrawnIdsRef.current]);
                    extraDrawnIdsRef.current = [];
                  } catch {
                    // Already removed
                  }
                  drawnFeatureIdRef.current = null;
                }
                if (td) {
                  const ids = addRectangle(td, bboxStr);
                  drawnFeatureIdRef.current = ids[0] ?? null;
                  extraDrawnIdsRef.current = ids.slice(1);
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
                className="ms-auto"
                disabled={!pendingBbox}
                onClick={handleApply}
              >
                {t('filters.apply')}
              </Button>
            </div>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
