import { useCallback, useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Table2, X } from 'lucide-react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useBuilderLayout } from '@/components/builder/hooks/use-builder-layout';
import { canOpenAttributeTable } from '@/lib/layer-capabilities';
import { Sheet, SheetContent } from '@/components/ui/sheet';
import { AttributeTable } from '@/components/dataset/AttributeTable';
import { geometryBounds } from '@/components/viewer/accessible-map-data';
import { getFeature } from '@/api/features';
import { layerFilterToServerCql2 } from '@/lib/maplibre-filter-utils';
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
// Map height kept above the table: a row fit pads 40px on each side.
const MIN_MAP_HEIGHT = 160;

// Measured from the map's top edge, since the navbar and title bar above it
// vary in height; on a short window the table yields first, down to its minimum.
function maxDrawerHeight(map: MaplibreMap | null): number {
  const mapTop = map?.getContainer().getBoundingClientRect().top ?? 0;
  const available = window.innerHeight - mapTop - MIN_MAP_HEIGHT;
  return Math.round(clampDrawerHeight(available, window.innerHeight * MAX_DRAWER_HEIGHT_RATIO));
}

function clampDrawerHeight(next: number, max: number): number {
  return Math.max(MIN_DRAWER_HEIGHT, Math.min(max, next));
}

export interface AttributeTableDrawerProps {
  /** The layer whose dataset the table reads; must satisfy canOpenAttributeTable. */
  layer: MapLayerResponse;
  open: boolean;
  onClose: () => void;
  /** The builder map, for the fit-and-highlight on a row click. */
  mapRef: React.RefObject<MaplibreMap | null>;
  /**
   * The map's layers in map order, for the header's layer picker (options:
   * the ones passing canOpenAttributeTable). Omitted, no picker renders.
   */
  layers?: MapLayerResponse[];
  /** Receives the picker's chosen layer id; omitted, the picker never renders. */
  onLayerChange?: (layerId: string) => void;
}

/**
 * Read-only attribute table for one builder layer, docked under the map at
 * >=800px and a bottom sheet below that. The layer's filter applies to
 * the table via the rows endpoint's CQL2 `filter` param; when the layer filter
 * cannot be converted to CQL2 the table falls back to every row plus a notice,
 * so the table never silently disagrees with the map.
 */
export function AttributeTableDrawer({
  layer,
  open,
  onClose,
  mapRef,
  layers,
  onLayerChange,
}: AttributeTableDrawerProps) {
  const { t } = useTranslation('builder');
  // The layer editor's breakpoint: the table docks at >=800px and uses a
  // bottom sheet below it. Never a separate media-query helper.
  const { isEditorHidden } = useBuilderLayout();
  const isEditorHiddenRef = useRef(isEditorHidden);
  isEditorHiddenRef.current = isEditorHidden;
  const titleId = useId();
  const [maxHeight, setMaxHeight] = useState(() => maxDrawerHeight(mapRef.current));
  const [height, setHeight] = useState(() => Math.min(320, maxHeight));
  const heightRef = useRef(height);
  heightRef.current = height;

  const datasetId = layer.dataset_id;
  const columns = layer.dataset_column_info;

  // null = no filter, 'unsupported' = the rows endpoint can't take it, so the
  // drawer shows the all-rows notice instead.
  const cql2 = useMemo(() => layerFilterToServerCql2(layer.filter, columns), [layer.filter, columns]);
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

  // The feature the highlight currently paints, kept so a style replacement
  // can repaint it: a style.load drops every imperatively added source/layer,
  // and the analysis mask re-adds its overlay the same way.
  const highlightFeatureRef = useRef<Awaited<ReturnType<typeof getFeature>> | null>(null);

  // Re-add the highlight source and both layers for a feature, with no fit —
  // the row-click path adds its fit after painting.
  const paintHighlight = useCallback(
    (feature: Awaited<ReturnType<typeof getFeature>>) => {
      const map = mapRef.current;
      if (!map || map.getSource(HIGHLIGHT_SOURCE)) return;
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
    },
    [mapRef],
  );

  // Monotonic token for the row-click request: bumped at every click start
  // below, and again in the cleanup (layer change and unmount), so neither an
  // older click on the same layer nor a response from the previous layer can
  // repaint the map.
  const rowRequestSeqRef = useRef(0);
  const pendingRowPaintCleanupRef = useRef<(() => void) | null>(null);

  // Clear on close, on layer change, and on unmount (the cleanup of the
  // previous effect run), so a replaced table never leaves the previous
  // layer's highlight on the map.
  useEffect(() => {
    if (!open) return;
    return () => {
      rowRequestSeqRef.current += 1;
      pendingRowPaintCleanupRef.current?.();
      pendingRowPaintCleanupRef.current = null;
      highlightFeatureRef.current = null;
      clearHighlight();
    };
  }, [open, layer.id, clearHighlight]);

  // A style replacement repaints the kept feature's highlight, exactly as long
  // as it can come back: the subscription ends with the close, the layer
  // switch, and the unmount, whose cleanup above drops the kept feature, so
  // nothing repaints after either. Redraw only — never a fit, never a camera
  // move; the stale-request token still rules any in-flight row response. No
  // dep array, like the analysis mask's subscription: the map instance can be
  // replaced under the stable ref (a Retry after a crash builds a new map),
  // and re-binding on every commit keeps exactly one live subscription, on
  // the current map.
  useEffect(() => {
    if (!open) return;
    const map = mapRef.current;
    if (!map) return;
    const repaint = () => {
      const feature = highlightFeatureRef.current;
      if (feature) paintHighlight(feature);
    };
    map.on('style.load', repaint);
    // A parsed style accepts mutations even while its sources are still loading.
    if (map.isStyleLoaded() || map.getStyle() !== undefined) repaint();
    return () => {
      map.off('style.load', repaint);
    };
  });

  // The selected row mirrors the map highlight: set where the highlight
  // paints (a click without usable geometry leaves it), cleared when the
  // layer changes and with the drawer itself.
  const [selectedGid, setSelectedGid] = useState<number | null>(null);
  useEffect(() => {
    setSelectedGid(null);
  }, [layer.id]);

  // The layer picker keeps focus across a switch: switching remounts
  // AttributeTable (key={datasetId}) and the focused select with it, so the
  // drawer — which persists — flags the switch and the fresh picker takes
  // focus here. Opening never steals focus: the flag starts false and is set
  // only in the picker's onChange.
  const pickerRef = useRef<HTMLSelectElement | null>(null);
  const pickerFocusOnSwitchRef = useRef(false);
  useEffect(() => {
    if (!pickerFocusOnSwitchRef.current) return;
    pickerFocusOnSwitchRef.current = false;
    pickerRef.current?.focus();
  }, [layer.id]);

  const handleRowClick = useCallback(
    async (gid: number) => {
      if (!datasetId) return;
      const seq = ++rowRequestSeqRef.current;
      pendingRowPaintCleanupRef.current?.();
      pendingRowPaintCleanupRef.current = null;
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
      // Bounds before paint: without usable geometry the map stays exactly as
      // it was — the previous highlight included.
      const bbox = geometryBounds(feature.geometry);
      if (!bbox) return;
      const paintAndFit = () => {
        if (seq !== rowRequestSeqRef.current || mapRef.current !== map) return;
        pendingRowPaintCleanupRef.current = null;
        try {
          setSelectedGid(gid);
          clearHighlight();
          highlightFeatureRef.current = feature;
          paintHighlight(feature);
          map.fitBounds(toFitBounds(bbox), {
            padding: isEditorHiddenRef.current
              ? { top: 40, right: 40, left: 40, bottom: 40 + heightRef.current }
              : 40,
            maxZoom: 18,
          });
        } catch {
          // Style changes or out-of-range coordinates leave the table usable.
        }
      };
      if (map.isStyleLoaded() || map.getStyle() !== undefined) paintAndFit();
      else {
        pendingRowPaintCleanupRef.current = () => map.off('style.load', paintAndFit);
        map.once('style.load', paintAndFit);
      }
    },
    [datasetId, mapRef, clearHighlight, paintHighlight],
  );

  // --- Resizing -------------------------------------------------------------
  const dragOrigin = useRef<{ pointerY: number; height: number } | null>(null);
  const clampHeight = useCallback(
    (next: number): number => clampDrawerHeight(next, maxHeight),
    [maxHeight],
  );
  // When the window shrinks the maximum with it, an over-tall table reclamps.
  useEffect(() => {
    const onWindowResize = () => {
      const max = maxDrawerHeight(mapRef.current);
      setMaxHeight(max);
      setHeight((current) => clampDrawerHeight(current, max));
    };
    window.addEventListener('resize', onWindowResize);
    return () => window.removeEventListener('resize', onWindowResize);
  }, [mapRef]);

  // map.resize() coalesced at most once per animation frame while the handle
  // drags, plus a final call on drag end: MapLibre re-reads its container's
  // size only on resize().
  const resizeFrameRef = useRef<number | null>(null);
  const scheduleMapResize = useCallback(() => {
    if (resizeFrameRef.current !== null) return;
    resizeFrameRef.current = window.requestAnimationFrame(() => {
      resizeFrameRef.current = null;
      mapRef.current?.resize();
    });
  }, [mapRef]);
  useEffect(
    () => () => {
      if (resizeFrameRef.current !== null) window.cancelAnimationFrame(resizeFrameRef.current);
    },
    [],
  );

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    dragOrigin.current = { pointerY: e.clientY, height: heightRef.current };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragOrigin.current) return;
    const delta = dragOrigin.current.pointerY - e.clientY;
    setHeight(clampHeight(dragOrigin.current.height + delta));
    scheduleMapResize();
  };
  const handlePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    dragOrigin.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    // Final resize now; drop any queued frame so it cannot double-call.
    if (resizeFrameRef.current !== null) {
      window.cancelAnimationFrame(resizeFrameRef.current);
      resizeFrameRef.current = null;
    }
    mapRef.current?.resize();
  };
  const handleResizeKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    // Proportional steps: a fixed ±px step returns to exactly the starting
    // height after up-then-down, while a proportional step scales the table
    // against its current size. Home/End still pin the exact bounds.
    const factor = e.shiftKey ? 0.25 : 0.1;
    let next: number | null = null;
    if (e.key === 'ArrowUp') next = heightRef.current * (1 + factor);
    else if (e.key === 'ArrowDown') next = heightRef.current * (1 - factor);
    else if (e.key === 'Home') next = maxHeight;
    else if (e.key === 'End') next = MIN_DRAWER_HEIGHT;
    if (next === null) return;
    e.preventDefault();
    setHeight(clampHeight(next));
    scheduleMapResize();
  };

  const layerName = layer.display_name ?? layer.dataset_name;
  const pickerLayers = layers?.filter(canOpenAttributeTable);
  // The name renders exactly once: with the picker shown it lives only as the
  // picker's selected option — which then carries titleId for the section's
  // aria-labelledby — and the title element yields to it.
  const pickerShown = Boolean(pickerLayers && onLayerChange);

  // The one merged header, composed from AttributeTable's own pieces: name or
  // picker, row count, then Columns and close kept together at the end. The
  // name truncates (the picker is capped at max-w-40) rather than wrap the row.
  const renderHeader = ({ count, columns }: { count: ReactNode; columns: ReactNode }) => (
    <header className="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b px-4 py-2">
      <Table2 className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
      {!pickerShown && (
        <h2
          id={titleId}
          data-testid="attribute-table-drawer-title"
          className="min-w-0 flex-1 truncate text-sm"
        >
          {layerName}
        </h2>
      )}
      {/* The raw condition, not pickerShown: it is the same truthiness and it
          narrows pickerLayers and onLayerChange for the handler below. */}
      {pickerLayers && onLayerChange && (
        <select
          ref={pickerRef}
          aria-label={t('attributeTableDrawer.layerPicker', { defaultValue: 'Attribute table layer' })}
          className="h-7 min-w-0 max-w-40 truncate cursor-pointer rounded-md border bg-transparent px-1.5 text-xs"
          value={layer.id}
          onChange={(e) => {
            pickerFocusOnSwitchRef.current = true;
            onLayerChange(e.target.value);
          }}
        >
          {pickerLayers.map((pickerLayer) => (
            <option
              key={pickerLayer.id}
              value={pickerLayer.id}
              id={pickerLayer.id === layer.id ? titleId : undefined}
            >
              {pickerLayer.display_name ?? pickerLayer.dataset_name}
            </option>
          ))}
        </select>
      )}
      <span className="text-xs">{count}</span>
      {filterUnsupported && (
        // Its own line under the controls, so a long translation never squeezes them.
        <p
          role="status"
          data-testid="attribute-table-filter-unsupported"
          className="order-last basis-full text-xs text-muted-foreground"
        >
          {t('attributeTableDrawer.filterUnsupported', {
            defaultValue: "The layer's filter could not be applied — showing every row.",
          })}
        </p>
      )}
      <div className="ms-auto flex shrink-0 items-center gap-1">
        {columns}
        <button
          type="button"
          onClick={onClose}
          aria-label={t('attributeTableDrawer.close', { defaultValue: 'Close attribute table' })}
          className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-[var(--surface-2)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </header>
  );

  // Resize handle: pointer drag or Arrow/Home/End keys, shared by dock and sheet.
  const resizeHandle = (
    /* eslint-disable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex -- role="separator" with aria-orientation is the WAI-ARIA separator (resizable) pattern; the rules' default interactive lists lag it. */
    <div
      role="separator"
      aria-orientation="horizontal"
      aria-label={t('attributeTableDrawer.resizeHandle', { defaultValue: 'Resize attribute table' })}
      aria-valuenow={height}
      aria-valuemin={MIN_DRAWER_HEIGHT}
      aria-valuemax={maxHeight}
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
  );

  const rows = datasetId && (
    <AttributeTable
      key={datasetId}
      datasetId={datasetId}
      compact
      cql2Filter={cql2Filter}
      onRowClick={handleRowClick}
      selectedGid={selectedGid}
      renderHeader={renderHeader}
    />
  );

  // Docked under the map at >=800px: a plain section beside the map, no dialog
  // semantics and no Escape handler — Escape stays with the map; the ✕ closes.
  if (!isEditorHidden) {
    return (
      <section
        aria-labelledby={titleId}
        className="flex flex-col overflow-hidden border-t bg-background shrink-0"
        style={{ height }}
      >
        {resizeHandle}
        {rows}
      </section>
    );
  }

  // Below 800px: bounded sheet on the editor's breakpoint; Escape stays
  // with the map, the ✕ closes.
  return (
    <Sheet open={open} modal={false} onOpenChange={(next) => { if (!next) onClose(); }}>
      <SheetContent
        side="bottom"
        overlay={false}
        showCloseButton={false}
        onEscapeKeyDown={(event) => event.preventDefault()}
        className="w-full gap-0 overflow-hidden border-t p-0"
        style={{ height, maxHeight }}
        aria-labelledby={titleId}
        aria-describedby={undefined}
      >
        {resizeHandle}
        {rows}
      </SheetContent>
    </Sheet>
  );
}
