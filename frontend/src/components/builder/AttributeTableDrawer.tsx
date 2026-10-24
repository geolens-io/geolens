import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Table2, X } from 'lucide-react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { AttributeTable } from '@/components/dataset/AttributeTable';
import { getFeature } from '@/api/features';
import { maplibreFilterToCql2 } from '@/lib/maplibre-filter-utils';
import { toFitBounds } from '@/lib/bbox';
import { MAP_COLORS } from '@/lib/map-colors';
import type { MapLayerResponse } from '@/types/api';

// The map highlight the drawer draws for a clicked row. Own source and layer
// ids, cleared on close, layer switch, and unmount — never the ephemeral
// preview's overlay, which has its own lifecycle and owner.
const HIGHLIGHT_SOURCE = 'attribute-table-highlight';
const HIGHLIGHT_LINE_LAYER = 'attribute-table-highlight-line';
const HIGHLIGHT_POINT_LAYER = 'attribute-table-highlight-point';

const MIN_DRAWER_HEIGHT = 120;
const MAX_DRAWER_HEIGHT_RATIO = 0.7;

/** Fold one GeoJSON geometry's coordinates into a [w, s, e, n] bbox. */
function geometryBbox(geometry: GeoJSON.Geometry): [number, number, number, number] | null {
  if (!('coordinates' in geometry)) return null;
  let bbox: [number, number, number, number] | null = null;
  const fold = (coords: unknown): void => {
    if (!Array.isArray(coords) || coords.length === 0) return;
    if (typeof coords[0] === 'number') {
      const [x, y] = coords as number[];
      if (!Number.isFinite(x) || !Number.isFinite(y)) return;
      if (bbox === null) {
        bbox = [x, y, x, y];
        return;
      }
      bbox[0] = Math.min(bbox[0], x);
      bbox[1] = Math.min(bbox[1], y);
      bbox[2] = Math.max(bbox[2], x);
      bbox[3] = Math.max(bbox[3], y);
    }
    for (const part of coords) fold(part);
  };
  fold(geometry.coordinates as unknown);
  return bbox;
}

export interface AttributeTableDrawerProps {
  /** The layer whose dataset the table reads; must satisfy canOpenAttributeTable. */
  layer: MapLayerResponse;
  open: boolean;
  onClose: () => void;
  /** The builder map, for the fit-and-highlight on a row click. */
  mapRef: React.RefObject<MaplibreMap | null>;
}

/**
 * Read-only attribute table for one builder layer, in a resizable drawer under
 * the map. The layer's filter applies to the table via the rows endpoint's
 * CQL2 `filter` param; when the layer filter cannot be converted to CQL2 the
 * table falls back to every row plus a notice, so the table never silently
 * disagrees with the map.
 */
export function AttributeTableDrawer({ layer, open, onClose, mapRef }: AttributeTableDrawerProps) {
  const { t } = useTranslation('builder');
  const [height, setHeight] = useState(320);
  const heightRef = useRef(height);
  heightRef.current = height;

  const datasetId = layer.dataset_id;
  const columns = layer.dataset_column_info;

  // Same conversion the builder analysis sends: null = no filter, a CQL2
  // expression when it can be translated, 'unsupported' when it cannot.
  const cql2 = useMemo(
    () => maplibreFilterToCql2(layer.filter ?? null, columns, { requireKnownFields: true }),
    [layer.filter, columns],
  );
  const filterUnsupported = cql2 === 'unsupported';
  const cql2Filter = cql2 && cql2 !== 'unsupported' ? JSON.stringify(cql2) : undefined;

  const clearHighlight = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const id of [HIGHLIGHT_LINE_LAYER, HIGHLIGHT_POINT_LAYER] as const) {
      if (map.getLayer(id)) map.removeLayer(id);
    }
    if (map.getSource(HIGHLIGHT_SOURCE)) map.removeSource(HIGHLIGHT_SOURCE);
  }, [mapRef]);

  // Monotonic token for the row-click request: bumped at every click start
  // below, and again in the cleanup (layer change and unmount), so neither an
  // older click on the same layer nor a response from the previous layer can
  // repaint the map.
  const rowRequestSeqRef = useRef(0);

  // Clear on close, on layer change, and on unmount (the cleanup of the
  // previous effect run), so a replaced table never leaves the previous
  // layer's highlight on the map.
  useEffect(() => {
    if (!open) return;
    return () => {
      rowRequestSeqRef.current += 1;
      clearHighlight();
    };
  }, [open, layer.id, clearHighlight]);

  const handleRowClick = useCallback(
    async (gid: number) => {
      if (!datasetId) return;
      const seq = ++rowRequestSeqRef.current;
      let feature: Awaited<ReturnType<typeof getFeature>>;
      try {
        feature = await getFeature(datasetId, gid);
      } catch {
        // A deleted row (404) or a lost request: leave the table usable and
        // the map untouched.
        return;
      }
      if (seq !== rowRequestSeqRef.current) return;
      const map = mapRef.current;
      if (!map) return;
      clearHighlight();
      const bbox = feature.geometry ? geometryBbox(feature.geometry) : null;
      if (!bbox || !feature.geometry) return;
      map.addSource(HIGHLIGHT_SOURCE, {
        type: 'geojson',
        data: { type: 'Feature', geometry: feature.geometry, properties: {} },
      });
      map.addLayer({
        id: HIGHLIGHT_LINE_LAYER,
        type: 'line',
        source: HIGHLIGHT_SOURCE,
        filter: ['!=', '$type', 'Point'],
        paint: {
          'line-color': MAP_COLORS.selection.stroke,
          'line-width': 3,
        },
      });
      map.addLayer({
        id: HIGHLIGHT_POINT_LAYER,
        type: 'circle',
        source: HIGHLIGHT_SOURCE,
        filter: ['==', '$type', 'Point'],
        paint: {
          'circle-radius': 8,
          'circle-color': MAP_COLORS.selection.fill,
          'circle-stroke-color': MAP_COLORS.selection.stroke,
          'circle-stroke-width': 2,
        },
      });
      try {
        map.fitBounds(toFitBounds(bbox), { padding: 40, maxZoom: 18 });
      } catch {
        // Out-of-range coordinates: keep the highlight, skip the fit.
      }
    },
    [datasetId, mapRef, clearHighlight],
  );

  // --- Resizing -------------------------------------------------------------
  const dragOrigin = useRef<{ pointerY: number; height: number } | null>(null);
  const clampHeight = useCallback((next: number): number => {
    const max = Math.round(window.innerHeight * MAX_DRAWER_HEIGHT_RATIO);
    return Math.max(MIN_DRAWER_HEIGHT, Math.min(max, next));
  }, []);

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    dragOrigin.current = { pointerY: e.clientY, height: heightRef.current };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragOrigin.current) return;
    const delta = dragOrigin.current.pointerY - e.clientY;
    setHeight(clampHeight(dragOrigin.current.height + delta));
  };
  const handlePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    dragOrigin.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  };
  const handleResizeKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 64 : 24;
    let next: number | null = null;
    if (e.key === 'ArrowUp') next = heightRef.current + step;
    else if (e.key === 'ArrowDown') next = heightRef.current - step;
    else if (e.key === 'Home') next = window.innerHeight * MAX_DRAWER_HEIGHT_RATIO;
    else if (e.key === 'End') next = MIN_DRAWER_HEIGHT;
    if (next === null) return;
    e.preventDefault();
    setHeight(clampHeight(next));
  };

  const layerName = layer.display_name ?? layer.dataset_name;

  return (
    <Sheet open={open} modal={false} onOpenChange={(next) => { if (!next) onClose(); }}>
      <SheetContent
        side="bottom"
        overlay={false}
        showCloseButton={false}
        className="gap-0 border-t p-0"
        style={{ height }}
        aria-describedby={undefined}
      >
        {/* Resize handle: pointer drag or Arrow/Home/End keys. */}
        {/* eslint-disable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex -- role="separator" with aria-orientation is the WAI-ARIA separator (resizable) pattern; the rules' default interactive lists lag it. */}
        <div
          role="separator"
          aria-orientation="horizontal"
          aria-label={t('attributeTableDrawer.resizeHandle', { defaultValue: 'Resize attribute table' })}
          tabIndex={0}
          data-testid="attribute-table-drawer-resize"
          className="group/handle flex h-3 shrink-0 cursor-row-resize items-center justify-center touch-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          onKeyDown={handleResizeKeyDown}
        >
          <span aria-hidden="true" className="h-1 w-10 rounded-full bg-muted-foreground/40 group-hover/handle:bg-muted-foreground/70" />
        </div>

        <div className="flex items-center gap-2 border-b px-4 py-2 shrink-0">
          <Table2 className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <SheetHeader className="min-w-0 flex-1 p-0">
            <SheetTitle className="truncate text-sm" data-testid="attribute-table-drawer-title">
              {layerName}
            </SheetTitle>
            <SheetDescription className="sr-only">
              {t('attributeTableDrawer.description', {
                name: layerName,
                defaultValue: 'Attribute table for {{name}}',
              })}
            </SheetDescription>
          </SheetHeader>
          {filterUnsupported && (
            <p
              role="status"
              data-testid="attribute-table-filter-unsupported"
              className="shrink-0 text-xs text-muted-foreground"
            >
              {t('attributeTableDrawer.filterUnsupported', {
                defaultValue: "The layer's filter could not be applied — showing every row.",
              })}
            </p>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label={t('attributeTableDrawer.close', { defaultValue: 'Close attribute table' })}
            className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-[var(--surface-2)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        {datasetId && (
          <AttributeTable
            key={datasetId}
            datasetId={datasetId}
            compact
            cql2Filter={cql2Filter}
            onRowClick={handleRowClick}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}
