import { useCallback, useLayoutEffect, useRef } from 'react';
import type { Map as MaplibreMap, FilterSpecification } from 'maplibre-gl';
import { toSyncInput, writeLayerToMap } from '@/components/builder/map-sync';
import type { SyncLayerInput } from '@/components/builder/map-sync';
import {
  adapterInputFor,
  describeLayers,
  type DescribedLayer,
  type RenderContext,
} from '@/components/builder/layer-description';
import { setDynamicLayoutProperty } from '@/components/builder/layer-adapters/shared';
import { coalesceFrame } from '@/lib/builder/raf-coalesce';
import { reconcileColorClassification } from '@/lib/color-ramps';
import { deepEqual } from '@/lib/deep-equal';
import { normalizeDemStyleConfig } from '@/lib/dem-render-mode';
import type { AdapterLayerInput } from '@/components/builder/layer-adapters/types';
import type { MapLayerResponse, LabelConfig, PopupConfig, StyleConfig } from '@/types/api';
import { sanitizeNullableNumericFilter } from '@/lib/maplibre-filter-utils';
import { getCompanionLayerIds } from '@/components/builder/companion-ids';

type LayerUpdater = (layer: MapLayerResponse) => MapLayerResponse;
type LayerSideEffect = (map: MaplibreMap, updated: MapLayerResponse) => void;

// The render-mode swap has neither tile tokens nor cluster GeoJSON, so it reads
// ids, layout and filter from the description, never its sources or drawsAs.
function handlerContext(mvtSourceLayerPrefix: string | null | undefined): RenderContext {
  return {
    idPrefix: '',
    origin: window.location.origin,
    tileBaseUrl: undefined,
    sourceLayerPrefix: mvtSourceLayerPrefix,
    tokens: new Map(),
    boundedGeoJson: new Map(),
  };
}

function describeBuilderLayer(
  input: SyncLayerInput,
  mvtSourceLayerPrefix: string | null | undefined,
): DescribedLayer | undefined {
  return describeLayers([input], handlerContext(mvtSourceLayerPrefix)).layers[0];
}

/**
 * The input the render-mode swap hands its adapter, or null when the map draws
 * nothing for the layer. A `pending` paint or opacity stands in for the layer's own.
 */
export function builderAdapterInput(
  layer: MapLayerResponse,
  mvtSourceLayerPrefix: string | null | undefined,
  pending: { tileUrl?: string; paint?: Record<string, unknown>; opacity?: number } = {},
): AdapterLayerInput | null {
  const input = toSyncInput(layer);
  const described = describeBuilderLayer(input, mvtSourceLayerPrefix);
  return described ? adapterInputFor(input, described, pending) : null;
}

/** Write a builder layer to the map layers a sync pass drew for it. */
export function writeBuilderLayer(map: MaplibreMap, layer: MapLayerResponse): void {
  writeLayerToMap(map, toSyncInput(layer));
}

/**
 * Set each key of the new layout on the layer's primary map layer and clear
 * each key it dropped. The sync pass writes only the layout keys a spec owns.
 */
function writeGenericLayout(
  map: MaplibreMap,
  layerId: string,
  previous: Record<string, unknown>,
  next: Record<string, unknown>,
): void {
  const mapLayerId = getCompanionLayerIds(layerId).layer;
  if (!map.getLayer(mapLayerId)) return;
  for (const prop of new Set([...Object.keys(previous), ...Object.keys(next)])) {
    // Private keys are builder state, and the line spec draws a layout dash as paint.
    if (prop.startsWith('_') || prop === 'line-dasharray') continue;
    try {
      setDynamicLayoutProperty(map, mapLayerId, prop, next[prop] ?? undefined);
    } catch (e) {
      if (import.meta.env.DEV) console.debug(`[builder] Failed to set layout ${prop}:`, e);
    }
  }
}

/**
 * Whether this fill key is actively set, not merely present. An imported,
 * API-authored or Advanced-JSON layer can carry `fill-pattern: null`, which
 * MapLibre reads as "no pattern"; a presence test would read it as a collision,
 * so an unrelated `fill-opacity` edit would fall through to pattern-wins and
 * delete the visible solid colour. Same rule as `FillEditor`'s
 * `paint['fill-pattern'] != null`.
 */
function hasActiveFill(paint: Record<string, unknown>, key: string): boolean {
  return paint[key] !== undefined && paint[key] !== null;
}

/**
 * The paint exclusions, which must hold on every write path, not just the
 * style-editor funnel.
 *
 * Two incompatible pairs, where MapLibre picks the winner: `fill-pattern` beats
 * `fill-color`, and a `line-gradient` beats a solid `line-color`. Persisting
 * either pair leaves the map drawing one thing while the appearance section,
 * legend and saved JSON claim the other.
 *
 * Which key loses depends on what the user just asked for. A data-driven colour
 * expression is the explicit request, so it takes the fill and the pattern
 * goes; anything else (a paste, a bulk apply) means the pattern arrived, so the
 * stray colour goes instead and is handed back through `strandedFillColor` for
 * the caller to stash.
 */
export function resolveFillExclusions(
  config: StyleConfig | null,
  paint: Record<string, unknown>,
  previousPaint?: Record<string, unknown>,
): {
  paint: Record<string, unknown>;
  strandedFillColor: string | undefined;
} {
  // A data-driven solid color (categorical, or graduated with the color
  // target) is incompatible with a line-gradient.
  const isDataDrivenColor =
    !!config &&
    (config.mode === 'categorical' || config.mode === 'graduated') &&
    (config.target === undefined || config.target === 'color');
  let effectivePaint = paint;
  if (isDataDrivenColor && 'line-gradient' in effectivePaint) {
    const { 'line-gradient': _droppedGradient, ...rest } = effectivePaint;
    effectivePaint = rest;
  }
  // Which key wins is decided by provenance, read off the diff against the
  // layer's previous paint: the key the write just touched is the one the user
  // asked for, so the other goes. Deriving it here, not per caller, makes the
  // rule hold on paths nobody enumerated (the style-config funnel, Advanced
  // JSON, the AI `set_style` action, a paste, a bulk apply).
  //
  // With no previous paint, or when the write touched both keys or neither, it
  // falls back to pattern-wins, which is what MapLibre draws regardless.
  const collides = hasActiveFill(effectivePaint, 'fill-color')
    && hasActiveFill(effectivePaint, 'fill-pattern');
  // Compares values, not presence: on a layer that already carried both keys,
  // changing the colour is as much a request as adding one. An absent key
  // compares unequal to any value, which subsumes the added case.
  //
  // Structurally, not by reference: Advanced JSON applies `JSON.parse` of the
  // whole block, so an untouched expression comes back as a fresh array, and
  // `!==` would read a `fill-opacity` edit as a colour change and delete the
  // pattern. `deepEqual` is the dirty check's comparison. Keying off state also
  // avoids putting intent back in each caller's hands.
  const touched = (key: string) =>
    collides && !!previousPaint && !deepEqual(previousPaint[key], effectivePaint[key]);
  const changedFillColor = touched('fill-color');
  const changedFillPattern = touched('fill-pattern');
  const colorWins = collides && (isDataDrivenColor || (changedFillColor && !changedFillPattern));
  const dropsFillPattern = colorWins;
  if (dropsFillPattern) {
    const { 'fill-pattern': _droppedPattern, ...rest } = effectivePaint;
    effectivePaint = rest;
  }
  // A solid colour only: `fillColorSaved` can hold nothing else, so a solid
  // colour is the only fill None can bring back, and deleting an expression
  // would be unrecoverable. That is reachable without any data-driven config
  // (Advanced JSON writes an expression into `fill-color`, and any later builder
  // edit re-sends that paint here). LayerStyleEditor already refuses to touch an
  // expression when a pattern is applied. Both keys then persist and the pattern
  // wins on the map, far cheaper than destroying the user's classification.
  const fillColor = effectivePaint['fill-color'];
  const patternOwnsFill = collides && !colorWins && typeof fillColor === 'string';
  let strandedFillColor: string | undefined;
  if (patternOwnsFill) {
    const { 'fill-color': _droppedColor, ...rest } = effectivePaint;
    strandedFillColor = fillColor;
    effectivePaint = rest;
  } else if (hasActiveFill(effectivePaint, 'fill-pattern')
    && !hasActiveFill(effectivePaint, 'fill-color')) {
    // The displacement doesn't always arrive as a collision: Advanced JSON
    // replacing paint wholesale, or an AI `set_style` with `replace_paint`,
    // hands over a pattern-only object that already dropped the colour, so None
    // would fall back to default blue. What matters is the transition to a
    // pattern-owned fill, so the displaced colour is read from the previous
    // paint when the incoming write no longer carries it. Strings only.
    const previousFillColor = previousPaint?.['fill-color'];
    if (typeof previousFillColor === 'string') strandedFillColor = previousFillColor;
  }
  return { paint: effectivePaint, strandedFillColor };
}

/**
 * The builder-stash half of the exclusions above.
 *
 * `fillColorSaved` is what a later None click restores, so it tracks which key
 * won the fill. An expression takes ownership: the old stash is stale and would
 * resurrect a colour from several edits ago. A pattern takes ownership: the
 * colour it displaced becomes the stash, unless the incoming config brought its
 * own (on a paste or bulk apply that is the source layer's colour, the one the
 * user copied).
 *
 * The stash is a solid colour by construction (`resolveFillExclusions` only
 * displaces a string), because the extrusion companion and the tint resolver
 * read it as a colour.
 */
export function stashExcludedFillColor(
  config: StyleConfig | null,
  flags: { paint: Record<string, unknown>; strandedFillColor: string | undefined },
): StyleConfig | null {
  let next = config;
  // The stash is stale the moment a pattern stops owning the fill, whatever
  // took over (a ramp, or a solid colour written straight to paint). Keyed off
  // the resolved paint, not the reason: enumerating reasons let a solid-colour
  // win keep a stale stash, so the next pattern write found the slot occupied
  // and None restored an old colour. Active, not merely present: a
  // `fill-pattern: null` doesn't own the fill.
  if (!hasActiveFill(flags.paint, 'fill-pattern') && next?.builder?.fillColorSaved !== undefined) {
    const { fillColorSaved: _dropped, ...restBuilder } = next.builder;
    next = { ...next, builder: Object.keys(restBuilder).length > 0 ? restBuilder : undefined };
  }
  // Keyed on there being a displaced colour: `strandedFillColor` is set only
  // where a pattern took the fill, so a second flag could only diverge.
  if (typeof flags.strandedFillColor === 'string' && next?.builder?.fillColorSaved === undefined) {
    next = {
      ...(next ?? {}),
      builder: { ...(next?.builder ?? {}), fillColorSaved: flags.strandedFillColor },
    } as StyleConfig;
  }
  return next;
}

export function useLayerMapSync(
  localLayers: MapLayerResponse[],
  setLocalLayers: React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
  setHasUnsavedChanges: React.Dispatch<React.SetStateAction<boolean>>,
  mapInstanceRef: React.RefObject<MaplibreMap | null>,
  layersRef: React.RefObject<MapLayerResponse[]>,
) {
  // Callbacks read layers through the caller's ref, so `localLayers` stays out
  // of their deps (which would re-render every StackRow) and an edit's same-tick
  // write is visible to the caller's other handlers.
  useLayoutEffect(() => {
    layersRef.current = localLayers;
  }, [layersRef, localLayers]);

  // Map writes deferred to `idle` because the style was mid-swap, keyed by
  // layer id and replayed in order. See applyLayerUpdate.
  const pendingMapWritesRef = useRef(
    new Map<string, { writes: ((target: MaplibreMap) => void)[]; listener: () => void }>(),
  );

  // Shared state-mutation and live-map-update pipeline for layer edits.
  // `updater` produces the new layer spec inside the functional setState;
  // `applyFn` runs the imperative MapLibre sync with the computed layer.
  const applyLayerUpdate = useCallback(
    (
      layerId: string,
      updater: LayerUpdater,
      applyFn?: LayerSideEffect,
      opts?: { verbatim?: boolean },
    ) => {
      // Check existence against the synchronous ref so the dirty flag is gated
      // before React schedules the functional setState (which may not run until
      // the next render). Otherwise a caller passing an id that matches no layer
      // (e.g. the BasemapGroupRow slider via id="basemap-group") would falsely
      // mark dirty.
      const existing = layersRef.current.find((l) => l.id === layerId);
      if (!existing) return;

      // Apply the updater inside the functional setState so synchronous
      // applyLayerUpdate calls compose against the latest `prev` rather than
      // clobbering each other off the stale `layersRef` snapshot. The ref-based
      // existence gate above still guards the dirty flag.
      //
      // The fill exclusion rule is enforced here, at the one boundary every
      // handler in this hook commits through, since the handlers are an open set
      // (the style-config funnel, paint-only writes, whatever is added next) and
      // a per-handler rule is only as complete as the list someone remembered.
      //
      // `verbatim` opts out for a restore: Revert-to-saved must reproduce the
      // saved baseline exactly, and the dirty check compares against it, so
      // normalizing would leave the layer permanently dirty. This differs from
      // the funnel's `replace`: 7 of the 8 `replace` callers are forward edits
      // (Reset, the pattern picker, the data-driven clears) that need normalizing.
      //
      // A reference-equal paint means the write never touched paint (visibility,
      // opacity, layout, popup): no new intent, so the layer is left alone.
      const normalize = (prevLayer: MapLayerResponse, nextLayer: MapLayerResponse): MapLayerResponse => {
        if (opts?.verbatim || nextLayer.paint === prevLayer.paint) return nextLayer;
        const exclusions = resolveFillExclusions(
          nextLayer.style_config ?? null,
          nextLayer.paint ?? {},
          prevLayer.paint ?? {},
        );
        return {
          ...nextLayer,
          paint: exclusions.paint,
          // Same boundary: a classification the resolved paint doesn't carry is
          // a claim no surface can honour. A paint replacement (Advanced JSON, an
          // AI `replace_paint`) breaks it, so it is caught here.
          style_config: reconcileColorClassification(
            stashExcludedFillColor(nextLayer.style_config ?? null, exclusions),
            exclusions.paint,
            nextLayer.dataset_geometry_type,
          ),
        };
      };

      setLocalLayers((prev) =>
        prev.map((l) => (l.id === layerId ? normalize(l, updater(l)) : l)),
      );
      setHasUnsavedChanges(true);

      // The ref holds the layer as the next commit will, so a later edit in this
      // tick, a paint frame and an idle replay all write the newest state.
      const normalized = normalize(existing, updater(existing));
      layersRef.current = layersRef.current.map((l) => (l.id === layerId ? normalized : l));

      if (!applyFn) return;
      const map = mapInstanceRef.current;
      if (!map) return;
      const writeToMap = (target: MaplibreMap) =>
        applyFn(target, layersRef.current.find((l) => l.id === layerId) ?? normalized);
      // State is committed already, so a write made mid style swap retries on idle.
      // Replays run in order, since a layout write clears the keys its edit dropped.
      const pending = pendingMapWritesRef.current;
      const queued = pending.get(layerId);
      if (!map.isStyleLoaded()) {
        if (queued) {
          // A listener is already armed for this layer; ride it.
          queued.writes.push(writeToMap);
          return;
        }
        const writes: ((target: MaplibreMap) => void)[] = [writeToMap];
        const listener = () => {
          // Ignore a listener that was already flushed or superseded below.
          if (pending.get(layerId)?.listener !== listener) return;
          pending.delete(layerId);
          for (const write of writes) write(map);
        };
        pending.set(layerId, { writes, listener });
        map.once?.('idle', listener);
        return;
      }
      if (queued) {
        // The style finished loading before `idle`. Drain the backlog first so
        // this newer write is applied last and wins.
        pending.delete(layerId);
        map.off?.('idle', queued.listener);
        for (const write of queued.writes) write(map);
      }
      writeToMap(map);
    },
    [setLocalLayers, setHasUnsavedChanges, mapInstanceRef, layersRef],
  );

  const handleToggleVisibility = useCallback(
    (layerId: string, visible?: boolean) => {
      const current = layersRef.current.find((l) => l.id === layerId);
      const nextVisible = visible !== undefined ? visible : !current?.visible;
      applyLayerUpdate(layerId, (l) => ({ ...l, visible: nextVisible }), writeBuilderLayer);
    },
    [applyLayerUpdate, layersRef],
  );

  const handlePaintChange = useCallback(
    (layerId: string, newPaint: Record<string, unknown>) => {
      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, paint: newPaint }),
        // Paint edits coalesce per frame, and the frame writes the layer as it is then.
        (map) => coalesceFrame(`paint:${layerId}`, () => {
          const layer = layersRef.current.find((l) => l.id === layerId);
          if (layer) writeBuilderLayer(map, layer);
        }),
      );
    },
    [applyLayerUpdate, layersRef],
  );

  const handleStyleConfigChange = useCallback(
    (
      layerId: string,
      config: StyleConfig | null,
      paint: Record<string, unknown>,
      opts?: { replace?: boolean; restore?: boolean },
    ) => {
      // The exclusions are applied by applyLayerUpdate at the shared commit
      // boundary. Only the `builder.lineGradient` intent stub is handled here:
      // dropping the gradient paint without it lets map-sync's
      // lineGradientNeededFor() put the gradient straight back.
      const isDataDrivenColor =
        !!config &&
        (config.mode === 'categorical' || config.mode === 'graduated') &&
        (config.target === undefined || config.target === 'color');
      applyLayerUpdate(
        layerId,
        (l) => {
          // `replace` restores the config verbatim, as Revert-to-saved must (not
          // keeping the draft's builder or stash). The default branch keeps the
          // builder and the heatmap stash when the incoming config omits them, so
          // a data-driven color doesn't wipe your outline width or a heatmap's
          // tuning for a return trip; on revert that would strand discarded edits
          // and keep the layer dirty.
          const carried: Partial<StyleConfig> = {};
          if (config?.builder === undefined && l.style_config?.builder) carried.builder = l.style_config.builder;
          if (config?.heatmapPaint === undefined && l.style_config?.heatmapPaint) carried.heatmapPaint = l.style_config.heatmapPaint;
          let mergedConfig: StyleConfig | null = opts?.replace
            ? config
            : config
              ? { ...config, ...carried }
              : Object.keys(carried).length > 0 ? (carried as StyleConfig) : null;
          if (isDataDrivenColor && mergedConfig?.builder?.lineGradient) {
            const { lineGradient: _droppedLineGradient, ...restBuilder } = mergedConfig.builder;
            mergedConfig = {
              ...mergedConfig,
              builder: Object.keys(restBuilder).length > 0 ? restBuilder : undefined,
            };
          }
          return {
            ...l,
            style_config: normalizeDemStyleConfig(mergedConfig, l.is_dem),
            paint,
          };
        },
        writeBuilderLayer,
        { verbatim: opts?.restore },
      );
    },
    [applyLayerUpdate],
  );

  const handleOpacityChange = useCallback(
    (layerId: string, newOpacity: number) => {
      applyLayerUpdate(layerId, (l) => ({ ...l, opacity: newOpacity }), writeBuilderLayer);
    },
    [applyLayerUpdate],
  );

  const handleLayoutChange = useCallback(
    (layerId: string, newLayout: Record<string, unknown>) => {
      const prevLayout = (layersRef.current.find((l) => l.id === layerId)?.layout ?? {}) as Record<string, unknown>;
      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, layout: newLayout }),
        (map, layer) => {
          writeGenericLayout(map, layerId, prevLayout, (layer.layout ?? {}) as Record<string, unknown>);
          writeBuilderLayer(map, layer);
        },
      );
    },
    [applyLayerUpdate, layersRef],
  );

  const handleFilterChange = useCallback(
    (layerId: string, expression: FilterSpecification | null) => {
      const filter = sanitizeNullableNumericFilter(expression);
      applyLayerUpdate(layerId, (l) => ({ ...l, filter }), writeBuilderLayer);
    },
    [applyLayerUpdate],
  );

  const handleLabelChange = useCallback(
    (layerId: string, config: LabelConfig | null) => {
      // Normalize empty column to null to prevent persisting non-functional config
      if (config && !config.column) {
        config = null;
      }

      applyLayerUpdate(layerId, (l) => ({ ...l, label_config: config }), writeBuilderLayer);
    },
    [applyLayerUpdate],
  );

  const handlePopupChange = useCallback(
    (layerId: string, config: PopupConfig | null) => {
      // No map side-effect: popup is a React component, not a MapLibre layer.
      applyLayerUpdate(layerId, (l) => ({ ...l, popup_config: config }));
    },
    [applyLayerUpdate],
  );

  return {
    handleToggleVisibility,
    handlePaintChange,
    handleStyleConfigChange,
    handleOpacityChange,
    handleLayoutChange,
    handleFilterChange,
    handleLabelChange,
    handlePopupChange,
  };
}
