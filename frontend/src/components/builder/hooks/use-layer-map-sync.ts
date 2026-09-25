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
import { deepEqual } from '@/components/builder/LayerStyleEditor/utils';
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
 * Set each key of the new layout on the layer's primary map layer, and clear each key
 * it dropped. The sync pass writes only the layout keys a spec owns.
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
 * fix(#910/#918, codex P2): the EDIT-05 paint exclusions, factored out because
 * they have to hold on EVERY write path, not just the style-editor funnel.
 *
 * Two incompatible pairs, and MapLibre picks the winner for us in both cases:
 * `fill-pattern` beats `fill-color`, and a `line-gradient` beats a solid
 * `line-color`. Persisting either pair leaves the map drawing one thing while
 * the appearance section, the legend and the saved JSON claim the other.
 *
 * Which key loses depends on what the user just asked for. A data-driven colour
 * expression is the explicit request, so it takes the fill and the pattern goes;
 * anything else (a paste, a bulk apply) means the pattern is what arrived, so the
 * stray colour goes instead and is handed back through `strandedFillColor` for
 * the caller to stash.
 */
/**
 * fix(#910, codex P2): is this fill key ACTIVELY set, as opposed to merely present?
 *
 * An imported, API-authored or Advanced-JSON layer can carry `fill-pattern: null`, which
 * MapLibre reads as "no pattern" — and a presence test read it as a collision, so an
 * unrelated `fill-opacity` edit fell through to pattern-wins and deleted the visible
 * solid colour, leaving the layer on MapLibre's spec default. `FillEditor` already draws
 * this distinction with `paint['fill-pattern'] != null`; this is the same rule, applied
 * at every place the exclusions ask whether a key is set.
 */
function hasActiveFill(paint: Record<string, unknown>, key: string): boolean {
  return paint[key] !== undefined && paint[key] !== null;
}

export function resolveFillExclusions(
  config: StyleConfig | null,
  paint: Record<string, unknown>,
  previousPaint?: Record<string, unknown>,
): {
  paint: Record<string, unknown>;
  strandedFillColor: string | undefined;
} {
  // P1-07: a data-driven SOLID color (categorical, or graduated with the color
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
  // fix(#910/#918, codex P2): which key wins is decided by PROVENANCE, read off the
  // diff against the layer's previous paint — the key the write just TOUCHED is the one
  // the user asked for, so the other goes. Deriving it here rather than having each
  // caller declare its intent is what makes the rule hold on paths nobody enumerated:
  // the style-config funnel, a paint-only write from Advanced JSON or the AI
  // `set_style` action, a paste, and a bulk apply all diff the same way.
  //
  // With no previous paint to compare — or when the write touched both keys, or neither
  // — it falls back to pattern-wins, which is what MapLibre draws regardless.
  const collides = hasActiveFill(effectivePaint, 'fill-color')
    && hasActiveFill(effectivePaint, 'fill-pattern');
  // Compares VALUES, not just presence: on a layer that already carried both keys,
  // changing the colour is as much a request as adding one, and a presence-only check
  // read it as "nothing introduced" and deleted the new colour. An absent key compares
  // unequal to any value, so this subsumes the added case rather than sitting beside it.
  //
  // fix(#910, codex P2): STRUCTURALLY, not by reference. Advanced JSON applies
  // `JSON.parse` of the whole block, so an untouched expression comes back as a fresh
  // array — `!==` read a `fill-opacity` edit as a colour change and deleted the layer's
  // pattern. `deepEqual` is the same comparison the dirty check already uses on paint,
  // so "same JSON, new object" means unchanged in both places. Comparing values is also
  // why this stays keyed off state: propagating which JSON keys the editor touched
  // would put intent back in the caller's hands, one caller at a time.
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
  // fix(#910, codex P2): a SOLID colour only. `fillColorSaved` can hold nothing else,
  // so a solid colour is the only fill None can bring back — deleting an expression
  // here would be unrecoverable, and it is reachable without any data-driven config
  // (Advanced JSON writes an expression into `fill-color`, and then ANY later builder
  // edit re-sends that paint through this resolver). LayerStyleEditor already refuses
  // to touch an expression when a pattern is applied; the funnel must not undo that.
  // Both keys then persist, which the pattern wins on the map — a pre-existing
  // Advanced-JSON quirk, and far cheaper than destroying the user's classification.
  const fillColor = effectivePaint['fill-color'];
  const patternOwnsFill = collides && !colorWins && typeof fillColor === 'string';
  let strandedFillColor: string | undefined;
  if (patternOwnsFill) {
    const { 'fill-color': _droppedColor, ...rest } = effectivePaint;
    strandedFillColor = fillColor;
    effectivePaint = rest;
  } else if (hasActiveFill(effectivePaint, 'fill-pattern')
    && !hasActiveFill(effectivePaint, 'fill-color')) {
    // fix(#910, codex P2): the displacement does not always arrive as a collision.
    // Advanced JSON replacing paint wholesale, or an AI `set_style` with
    // `replace_paint`, hands over a pattern-only object that already dropped the
    // colour — nothing collides, so the previous colour was never recorded and None
    // fell back to default blue. What matters is the TRANSITION to a
    // pattern-owned fill, so the displaced colour is read from the previous paint
    // when the incoming write no longer carries it. Strings only, as everywhere else.
    const previousFillColor = previousPaint?.['fill-color'];
    if (typeof previousFillColor === 'string') strandedFillColor = previousFillColor;
  }
  return { paint: effectivePaint, strandedFillColor };
}

/**
 * fix(#910/#918, codex P2): the builder-stash half of the exclusions above.
 *
 * `fillColorSaved` is what a later None click restores, so it has to track which
 * key won the fill. An expression takes ownership → the old stash is stale and
 * would resurrect a colour from several edits ago. A pattern takes ownership →
 * the colour it displaced becomes the stash, but only when the incoming config
 * did not bring one of its own: on a paste or bulk apply that value is the SOURCE
 * layer's colour, which is the one the user actually copied.
 *
 * The stash is a solid colour by construction — `resolveFillExclusions` only ever
 * displaces a string, because the extrusion companion and #914's tint resolver both
 * read this value as a colour and an expression cannot serve as one.
 */
export function stashExcludedFillColor(
  config: StyleConfig | null,
  flags: { paint: Record<string, unknown>; strandedFillColor: string | undefined },
): StyleConfig | null {
  let next = config;
  // fix(#910, codex P2): the stash is stale the moment a pattern stops owning the fill,
  // whatever took over — a ramp, or a solid colour written straight to paint. Keyed off
  // the RESOLVED paint rather than the reason, because enumerating reasons is what let
  // a solid-colour win keep a stale stash: the next pattern write then found the slot
  // occupied, and None restored a colour from two edits ago while the extrusion
  // companion painted it too.
  // Active, not merely present: a `fill-pattern: null` no longer owns the fill, so the
  // stash it would have justified is just as stale as an absent key's.
  if (!hasActiveFill(flags.paint, 'fill-pattern') && next?.builder?.fillColorSaved !== undefined) {
    const { fillColorSaved: _dropped, ...restBuilder } = next.builder;
    next = { ...next, builder: Object.keys(restBuilder).length > 0 ? restBuilder : undefined };
  }
  // Keyed on there BEING a displaced colour, not on a second flag that has to agree
  // with it: `strandedFillColor` is set only where a pattern took the fill, so the
  // extra condition was redundant at best and a way for the two to diverge at worst.
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
) {
  // Mirror current layers in a ref so the memoized callbacks can read fresh
  // state without having `localLayers` in their dependency list. Without this
  // ref, every layer mutation would invalidate all callbacks, tearing down
  // React.memo() on StackRow and re-rendering every layer for every tweak
  // (KISS-2 / PERF-N2).
  const layersRef = useRef(localLayers);
  useLayoutEffect(() => {
    layersRef.current = localLayers;
  }, [localLayers]);

  // fix(#1778 codex round 3): map writes deferred to `idle` because the style
  // was mid-swap, keyed by layer id and replayed in order. See applyLayerUpdate.
  const pendingMapWritesRef = useRef(
    new Map<string, { writes: ((target: MaplibreMap) => void)[]; listener: () => void }>(),
  );

  // Shared state-mutation + live-map-update pipeline for layer edits.
  // Collapses the dup 30-line boilerplate from paint/opacity/layout/style
  // handlers into one place (KISS-2). `updater` produces the new layer spec
  // inside the functional setState; `applyFn` runs the imperative MapLibre
  // sync using the freshly-computed layer.
  const applyLayerUpdate = useCallback(
    (
      layerId: string,
      updater: LayerUpdater,
      applyFn?: LayerSideEffect,
      opts?: { verbatim?: boolean },
    ) => {
      // Pre-check existence against the synchronous ref so we can gate the
      // dirty-flag BEFORE React schedules the functional setState (whose
      // callback may not run until the next render). Closes the side-finding
      // from quick-260516-9g9: previously `setHasUnsavedChanges(true)` fired
      // unconditionally, which falsely marked dirty when a caller (e.g. the
      // dead BasemapGroupRow row slider via id="basemap-group") passed an id
      // that matched no layer.
      const existing = layersRef.current.find((l) => l.id === layerId);
      if (!existing) return;

      // BUG-019: apply the updater INSIDE the functional setState so that
      // multiple synchronous applyLayerUpdate calls compose against the latest
      // `prev` rather than clobbering each other off the stale `layersRef`
      // snapshot. The existence gate above (ref-based) still guards the
      // dirty-flag; the actual mutation moves inside prev.map() so React's
      // functional update queue accumulates correctly.
      // fix(#910/#918, codex P2): EDIT-05 is enforced HERE, at the one boundary every
      // handler in this hook commits through, instead of inside each handler. The
      // handlers are an open set — the style-config funnel, paint-only writes, and
      // whatever is added next — and a rule inlined per handler is only ever as
      // complete as the list someone remembered. Two guards keep it honest:
      //
      // `verbatim` opts out for a restore. Revert-to-saved has to reproduce the saved
      // baseline exactly, and the dirty check compares against that baseline, so
      // normalizing a restore leaves the layer permanently dirty. NOTE this is NOT the
      // same as the funnel's `replace`: 7 of the 8 `replace` callers are forward edits
      // (Reset, the pattern picker, the data-driven clears) that DO need normalizing.
      //
      // A reference-equal paint means the write never touched paint (visibility,
      // opacity, layout, popup), so there is no new intent to act on and the layer is
      // left alone.
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
          // Same boundary, same reason: a classification the resolved paint does not
          // carry is a claim no surface can honour. The write that breaks it is a
          // paint replacement (Advanced JSON, an AI `replace_paint`), so it is caught
          // here rather than wherever a downstream control first trips over it.
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
    [setLocalLayers, setHasUnsavedChanges, mapInstanceRef],
  );

  const handleToggleVisibility = useCallback(
    (layerId: string, visible?: boolean) => {
      const current = layersRef.current.find((l) => l.id === layerId);
      const nextVisible = visible !== undefined ? visible : !current?.visible;
      applyLayerUpdate(layerId, (l) => ({ ...l, visible: nextVisible }), writeBuilderLayer);
    },
    [applyLayerUpdate],
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
    [applyLayerUpdate],
  );

  const handleStyleConfigChange = useCallback(
    (
      layerId: string,
      config: StyleConfig | null,
      paint: Record<string, unknown>,
      opts?: { replace?: boolean; restore?: boolean },
    ) => {
      // The EDIT-05 exclusions are applied by applyLayerUpdate, at the commit boundary
      // every write path shares. Only the `builder.lineGradient` intent stub is handled
      // here: dropping the gradient paint without it lets map-sync's
      // lineGradientNeededFor() put the gradient straight back.
      const isDataDrivenColor =
        !!config &&
        (config.mode === 'categorical' || config.mode === 'graduated') &&
        (config.target === undefined || config.target === 'color');
      applyLayerUpdate(
        layerId,
        (l) => {
          // fix(#461, codex P2): `replace` restores the config verbatim — used by
          // Revert-to-saved, which must NOT keep the draft's style_config.builder.
          // The default branch below deliberately preserves that builder when the
          // incoming config omits one (so setting a data-driven color doesn't wipe
          // your outline width), but on revert that preservation would strand a
          // discarded builder-only edit and keep the layer dirty.
          let mergedConfig: StyleConfig | null = opts?.replace
            ? config
            : config
              ? {
                  ...config,
                  ...(config.builder === undefined && l.style_config?.builder
                    ? { builder: l.style_config.builder }
                    : {}),
                }
              : l.style_config?.builder
                ? ({ builder: l.style_config.builder } as StyleConfig)
                : null;
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
    [applyLayerUpdate],
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
