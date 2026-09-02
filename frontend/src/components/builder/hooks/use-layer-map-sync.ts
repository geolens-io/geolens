import { useCallback, useLayoutEffect, useRef } from 'react';
import type { Map as MaplibreMap, FilterSpecification } from 'maplibre-gl';
import { getLayerType, getSourceIdForLayer, resolveAdapterType, applyMasterOpacity, isDemTerrainVisualSuppressed } from '@/components/builder/map-sync';
import { getAdapter } from '@/components/builder/layer-adapters/registry';
import {
  getBuilderStyleConfig,
  setDynamicLayoutProperty,
  setDynamicPaintProperty,
} from '@/components/builder/layer-adapters/shared';
import type { PaintPropertyName } from '@/components/builder/layer-adapters/shared';
import { mixedFamilyFilter } from '@/components/builder/layer-adapters/mixed-adapter';
import { coalesceFrame } from '@/lib/builder/raf-coalesce';
// fix(#394) VT-03/VT-04: single source of truth for the MVT source-layer name.
import { getMvtSourceLayerName } from '@/lib/tile-utils';
import { reconcileColorClassification } from '@/lib/color-ramps';
import { deepEqual } from '@/components/builder/LayerStyleEditor/utils';
import { effectiveDemRenderMode, normalizeDemStyleConfig } from '@/lib/dem-render-mode';
import type { AdapterLayerInput } from '@/components/builder/layer-adapters/types';
import { buildLabelLayerSpec, syncLabelLayer } from '@/components/builder/label-layer-utils';
import type { MapLayerResponse, LabelConfig, PopupConfig, StyleConfig } from '@/types/api';
import { sanitizeNullableNumericFilter } from '@/lib/maplibre-filter-utils';
import { getCompanionLayerIds, COLOR_RELIEF_SUFFIX } from '@/components/builder/companion-ids';

type LayerUpdater = (layer: MapLayerResponse) => MapLayerResponse;
type LayerSideEffect = (map: MaplibreMap, updated: MapLayerResponse) => void;

function removeColorReliefLayer(map: MaplibreMap, layerId: string) {
  const colorReliefId = `${layerId}${COLOR_RELIEF_SUFFIX}`;
  if (map.getLayer(colorReliefId)) map.removeLayer(colorReliefId);
}

function resolveLayerAdapterType(layer: MapLayerResponse, paint: Record<string, unknown>, styleConfig?: StyleConfig | null): string {
  if (layer.layer_type === 'raster_geolens') {
    return layer.is_dem === true && effectiveDemRenderMode(styleConfig, layer.is_dem) === 'hillshade'
      ? 'hillshade'
      : 'raster';
  }
  return resolveAdapterType(layer.dataset_geometry_type, styleConfig ?? layer.style_config, paint);
}

// STATE-01 / SYNC-04: the canonical per-layer visibility map side-effect. The
// single-layer (`handleToggleVisibility`) AND the bulk
// (`handleBulkVisibility`) paths both call this so the strokeDisabled gate and
// the full companion set (including colorrelief + cluster) can never diverge.
// Companion ids are derived through `getCompanionLayerIds` — the one place the
// suffix convention lives.
export function applyLayerVisibilityToMap(
  map: MaplibreMap,
  layer: MapLayerResponse,
  nextVisible: boolean,
): void {
  const ids = getCompanionLayerIds(layer.id);
  const newVis = nextVisible ? 'visible' : 'none';
  if (map.getLayer(ids.layer)) map.setLayoutProperty(ids.layer, 'visibility', newVis);
  // BUG-036: a disabled fill outline carries its state as the outline layer's
  // layout visibility. Restoring it on the raw newVis resurrects a 1px outline
  // the user turned off (render-as 'Fill only'). Gate the outline on
  // strokeDisabled — mirror of fillAdapter.syncVisibility.
  if (map.getLayer(ids.outline)) {
    const builder = getBuilderStyleConfig(layer);
    const rawPaint = (layer.paint ?? {}) as Record<string, unknown>;
    const strokeDisabled = builder.strokeDisabled ?? !!rawPaint['_stroke-disabled'];
    map.setLayoutProperty(ids.outline, 'visibility', nextVisible && !strokeDisabled ? 'visible' : 'none');
  }
  if (map.getLayer(ids.label)) map.setLayoutProperty(ids.label, 'visibility', newVis);
  if (map.getLayer(ids.extrusion)) map.setLayoutProperty(ids.extrusion, 'visibility', newVis);
  if (map.getLayer(ids.arrow)) map.setLayoutProperty(ids.arrow, 'visibility', newVis);
  if (map.getLayer(ids.colorRelief)) map.setLayoutProperty(ids.colorRelief, 'visibility', newVis);
  if (map.getLayer(ids.cluster)) map.setLayoutProperty(ids.cluster, 'visibility', newVis);
  // codex(#841): mirror clusterAdapter.syncVisibility — re-showing a layer
  // (single, bulk, or group path) must not resurrect counts the user turned
  // off via ux(#839) clusterShowCounts.
  if (map.getLayer(ids.clusterCount)) {
    const countsOn = getBuilderStyleConfig(layer).clusterShowCounts !== false;
    map.setLayoutProperty(ids.clusterCount, 'visibility', nextVisible && countsOn ? 'visible' : 'none');
  }
  if (map.getLayer(ids.mixedLines)) map.setLayoutProperty(ids.mixedLines, 'visibility', newVis);
  if (map.getLayer(ids.mixedPoints)) map.setLayoutProperty(ids.mixedPoints, 'visibility', newVis);
}

// STATE-03 / SYNC-04: the canonical per-layer opacity map side-effect. The
// single-layer (`handleOpacityChange`) AND the bulk (`handleBulkOpacity`)
// paths both call this so the applyMasterOpacity split and the dedicated
// cluster branch can never diverge.
export function applyLayerOpacityToMap(
  map: MaplibreMap,
  layer: MapLayerResponse,
  opacity: number,
  mvtSourceLayerPrefix?: string | null,
): void {
  if (isDemTerrainVisualSuppressed(layer)) return;

  const ids = getCompanionLayerIds(layer.id);
  const mapLayerId = ids.layer;
  const paint = layer.paint ?? {};
  const adapterType = resolveLayerAdapterType(layer, paint, layer.style_config);

  if (adapterType === 'hillshade') {
    const input: AdapterLayerInput & { style_config?: StyleConfig | null } = {
      id: layer.id,
      dataset_table_name: layer.dataset_table_name,
      dataset_geometry_type: layer.dataset_geometry_type,
      opacity,
      visible: layer.visible,
      paint,
      layout: layer.layout ?? {},
      filter: layer.filter ?? null,
      sourceId: getSourceIdForLayer(layer),
      layerId: mapLayerId,
      sourceLayer: getMvtSourceLayerName(layer.dataset_table_name, mvtSourceLayerPrefix),
      tileUrl: '',
      style_config: layer.style_config ?? null,
      is_dem: layer.is_dem,
    };
    getAdapter('hillshade').syncPaint(map, input);
  } else if (layer.layer_type === 'raster_geolens') {
    if (map.getLayer(mapLayerId)) {
      map.setPaintProperty(mapLayerId, 'raster-opacity', opacity);
    }
  } else if (adapterType === 'heatmap') {
    if (map.getLayer(mapLayerId)) {
      const storedHeatmapOpacity = (paint['heatmap-opacity'] as number) ?? 0.8;
      map.setPaintProperty(mapLayerId, 'heatmap-opacity', opacity * storedHeatmapOpacity);
    }
  } else if (adapterType === 'cluster') {
    const input: AdapterLayerInput & { style_config?: StyleConfig | null } = {
      id: layer.id,
      dataset_table_name: layer.dataset_table_name,
      dataset_geometry_type: layer.dataset_geometry_type,
      opacity,
      visible: layer.visible,
      paint,
      layout: layer.layout ?? {},
      filter: layer.filter ?? null,
      // SF-04: cluster layers keep their per-layer source id; the helper routes
      // them through the cluster branch.
      sourceId: getSourceIdForLayer(layer),
      layerId: mapLayerId,
      sourceLayer: getMvtSourceLayerName(layer.dataset_table_name, mvtSourceLayerPrefix),
      tileUrl: '',
      style_config: layer.style_config ?? null,
      is_dem: layer.is_dem,
    };
    getAdapter('cluster').syncPaint(map, input);
  } else if (adapterType === 'mixed') {
    // fix(#430 codex r23): mixed-geometry layers spread opacity across four
    // family sublayers — route through the adapter like the cluster branch so
    // the slider affects points/lines too, not just the fill primary.
    const input: AdapterLayerInput & { style_config?: StyleConfig | null } = {
      id: layer.id,
      dataset_table_name: layer.dataset_table_name,
      dataset_geometry_type: layer.dataset_geometry_type,
      opacity,
      visible: layer.visible,
      paint,
      layout: layer.layout ?? {},
      filter: layer.filter ?? null,
      sourceId: getSourceIdForLayer(layer),
      layerId: mapLayerId,
      sourceLayer: getMvtSourceLayerName(layer.dataset_table_name, mvtSourceLayerPrefix),
      tileUrl: '',
      style_config: layer.style_config ?? null,
      is_dem: layer.is_dem,
    };
    getAdapter('mixed').syncPaint(map, input);
  } else if (adapterType === 'fill' || adapterType === 'line' || adapterType === 'circle') {
    if (map.getLayer(mapLayerId)) {
      // fix(#1625): same split as the adapters' syncPaint — fill/line put the
      // master on `-layer-opacity`, circle still multiplies.
      applyMasterOpacity(map, mapLayerId, paint, adapterType, opacity);
    }
    if (adapterType === 'fill' && map.getLayer(ids.outline)) {
      map.setPaintProperty(ids.outline, 'line-layer-opacity', opacity);
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
 *
 * Returns the flags as well as the paint: the live map needs an imperative clear
 * for a key that merely *stopped being present*, which a paint object cannot
 * express — see `clearExcludedPaintOnMap`.
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
  isDataDrivenColor: boolean;
  dropsFillPattern: boolean;
  patternOwnsFill: boolean;
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
  return { paint: effectivePaint, isDataDrivenColor, dropsFillPattern, patternOwnsFill, strandedFillColor };
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

/**
 * fix(#910/#918, codex P2): drop an excluded key from the LIVE map.
 *
 * Handing the adapter a paint object that simply omits a key leaves the old value
 * painted, so the removal needs an explicit `undefined` write. Each is wrapped
 * because the property is invalid on the wrong geometry — `line-gradient` on a
 * fill layer throws rather than no-opping.
 */
export function clearExcludedPaintOnMap(
  map: MaplibreMap,
  layerId: string,
  flags: { isDataDrivenColor: boolean; dropsFillPattern: boolean; patternOwnsFill: boolean },
) {
  const mapLayerId = `layer-${layerId}`;
  if (!map.getLayer(mapLayerId)) return;
  // fix(#846): typed as the real MapLibre key union rather than `string[]` — the
  // three keys pushed below are literals, so v6's generic `setPaintProperty` accepts
  // them directly and no cast is needed for the clearing write.
  const keys: PaintPropertyName[] = [];
  if (flags.isDataDrivenColor) keys.push('line-gradient');
  if (flags.dropsFillPattern) keys.push('fill-pattern');
  if (flags.patternOwnsFill) keys.push('fill-color');
  for (const key of keys) {
    try {
      map.setPaintProperty(mapLayerId, key, undefined);
    } catch {
      /* wrong geometry for this key — not a valid paint property here */
    }
  }
}

export function useLayerMapSync(
  localLayers: MapLayerResponse[],
  setLocalLayers: React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
  setHasUnsavedChanges: React.Dispatch<React.SetStateAction<boolean>>,
  mapInstanceRef: React.RefObject<MaplibreMap | null>,
  mvtSourceLayerPrefix?: string | null,
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
      const normalize = (prevLayer: MapLayerResponse, nextLayer: MapLayerResponse) => {
        if (opts?.verbatim || nextLayer.paint === prevLayer.paint) {
          return { layer: nextLayer, exclusions: null };
        }
        const exclusions = resolveFillExclusions(
          nextLayer.style_config ?? null,
          nextLayer.paint ?? {},
          prevLayer.paint ?? {},
        );
        return {
          layer: {
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
          },
          exclusions,
        };
      };

      setLocalLayers((prev) =>
        prev.map((l) => (l.id === layerId ? normalize(l, updater(l)).layer : l)),
      );
      setHasUnsavedChanges(true);

      if (!applyFn) return;
      const map = mapInstanceRef.current;
      if (!map) return;
      // For the map side-effect we re-apply updater to the ref snapshot: the
      // map call is idempotent and the stale-ref issue only affects React state
      // composition, not the live-map sync. This keeps the applyFn signature
      // stable (it receives the just-computed updated layer, not a stale one).
      const { layer: normalized, exclusions } = normalize(existing, updater(existing));
      const writeToMap = (target: MaplibreMap) => {
        // A key that merely stopped being present cannot be expressed in a paint object,
        // so the removal needs an explicit undefined write before the adapter repaint.
        if (exclusions) clearExcludedPaintOnMap(target, layerId, exclusions);
        applyFn(target, normalized);
      };
      // fix(#1778): React state is already committed above, so dropping the map
      // write here left the two permanently out of step for anything
      // syncLayersToMap does not re-apply, and generic LAYOUT is exactly that
      // class, since only handleLayoutChange ever writes it. Retry on idle,
      // matching BuilderMap's sync effect and use-render-mode-layers.
      if (!map.isStyleLoaded()) {
        map.once?.('idle', () => writeToMap(map));
        return;
      }
      writeToMap(map);
    },
    [setLocalLayers, setHasUnsavedChanges, mapInstanceRef],
  );

  const handleToggleVisibility = useCallback(
    (layerId: string, visible?: boolean) => {
      const current = layersRef.current.find((l) => l.id === layerId);
      const nextVisible = visible !== undefined ? visible : !current?.visible;
      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, visible: nextVisible }),
        (map, updated) => applyLayerVisibilityToMap(map, updated, nextVisible),
      );
    },
    [applyLayerUpdate],
  );

  const handlePaintChange = useCallback(
    (layerId: string, newPaint: Record<string, unknown>) => {
      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, paint: newPaint }),
        (map, layer) => {
          const mapLayerId = `layer-${layerId}`;
          // fix(#910/#918, codex P2): the EDIT-05 normalization happens at the commit
          // boundary, so the winning paint is `layer.paint` — NOT the raw `newPaint`
          // this handler was called with. Feeding the adapter the raw object would
          // repaint the very key the commit just dropped.
          const effectivePaint = layer.paint ?? {};
          const adapterType = resolveLayerAdapterType(layer, effectivePaint);
          const adapter = getAdapter(adapterType);

          const input: AdapterLayerInput & { style_config?: StyleConfig | null } = {
            id: layer.id,
            dataset_table_name: layer.dataset_table_name,
            dataset_geometry_type: layer.dataset_geometry_type,
            opacity: layer.opacity ?? 1,
            visible: layer.visible,
            paint: effectivePaint,
            layout: layer.layout ?? {},
            filter: layer.filter ?? null,
            // SF-04 dedupe: source id is per-dataset for non-cluster vector
            // layers, per-layer for cluster/raster/hillshade.
            sourceId: getSourceIdForLayer(layer),
            layerId: mapLayerId,
            sourceLayer: getMvtSourceLayerName(
              layer.dataset_table_name,
              mvtSourceLayerPrefix,
            ),
            tileUrl: '',
            is_dem: layer.is_dem,
          };
          input.style_config = layer.style_config ?? null;

          // Paint writes coalesce via rAF (PERF-04); visibility/filter/order remain
          // synchronous because they're idempotent and cheap, and synchronous
          // semantics let UI toggles feel instant.
          coalesceFrame(`paint:${layerId}`, () => adapter.syncPaint(map, input));
        },
      );
    },
    [applyLayerUpdate, mvtSourceLayerPrefix],
  );

  // Map-only side-effect for a style_config change — extracted so the bulk
  // "Apply style to selection" handler (ENH-03, Phase 1201-01) can drive the
  // live-map repaint per target WITHOUT triggering a second setLocalLayers
  // (its state write is a single atomic pass). `layer` must already carry the
  // post-merge paint + style_config.
  const syncStyleConfigToMap = useCallback(
    (map: MaplibreMap, layer: MapLayerResponse, paint: Record<string, unknown>) => {
      const mapLayerId = `layer-${layer.id}`;
      const nextConfig = layer.style_config;
      const sourceId = getSourceIdForLayer(layer);

      if (isDemTerrainVisualSuppressed({ is_dem: layer.is_dem, style_config: nextConfig })) {
        removeColorReliefLayer(map, mapLayerId);
        if (map.getLayer(mapLayerId)) map.removeLayer(mapLayerId);
        if (map.getSource(sourceId)) map.removeSource(sourceId);
        return;
      }

      if (!map.getLayer(mapLayerId)) return;

      const adapterType = resolveLayerAdapterType(layer, paint, nextConfig);
      const adapter = getAdapter(adapterType);
      // SF-04 dedupe: read from the shared per-dataset source for
      // non-cluster vector layers so tile URL inheritance still works.
      const existingSource = map.getSource(sourceId) as { tiles?: string[] } | undefined;
      const rawTileUrl = existingSource?.tiles?.[0] ?? '';
      const tileUrl = rawTileUrl.startsWith(window.location.origin)
        ? rawTileUrl.slice(window.location.origin.length)
        : rawTileUrl;
      const input: AdapterLayerInput & { style_config?: StyleConfig | null } = {
        id: layer.id,
        dataset_table_name: layer.dataset_table_name,
        dataset_geometry_type: layer.dataset_geometry_type,
        opacity: layer.opacity ?? 1,
        visible: layer.visible,
        paint,
        layout: layer.layout ?? {},
        filter: layer.filter ?? null,
        sourceId,
        layerId: mapLayerId,
        sourceLayer: getMvtSourceLayerName(
          layer.dataset_table_name,
          mvtSourceLayerPrefix,
        ),
        tileUrl,
        is_dem: layer.is_dem,
      };
      input.style_config = nextConfig;

      if (layer.layer_type === 'raster_geolens' && tileUrl) {
        removeColorReliefLayer(map, mapLayerId);
        if (map.getLayer(mapLayerId)) map.removeLayer(mapLayerId);
        if (map.getSource(sourceId)) map.removeSource(sourceId);
        adapter.addLayers(map, input);
        // BUG-01: re-assert visibility after the raster re-add. The
        // adapter's addLayers honors input.visible (raster-adapter:76-78),
        // but this defense-in-depth call mirrors the swapLayerOnMap fix
        // and guarantees the swap path never produces a layer in the
        // wrong visibility state — even if a future adapter forgets the
        // contract.
        adapter.syncVisibility(map, input);
      } else {
        adapter.syncPaint(map, input);
      }
    },
    [mvtSourceLayerPrefix],
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
        // `layer` arrives already normalized, and applyLayerUpdate has done the
        // imperative clear for whichever key lost, so the repaint just follows it.
        (map, layer) => syncStyleConfigToMap(map, layer, layer.paint ?? {}),
        { verbatim: opts?.restore },
      );
    },
    [applyLayerUpdate, syncStyleConfigToMap],
  );

  const handleOpacityChange = useCallback(
    (layerId: string, newOpacity: number) => {
      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, opacity: newOpacity }),
        (map, layer) =>
          applyLayerOpacityToMap(map, layer, newOpacity, mvtSourceLayerPrefix),
      );
    },
    [applyLayerUpdate, mvtSourceLayerPrefix],
  );

  // fix(#1778): this is the SOLE writer of generic layout on a live layer, by
  // design rather than by accident. syncLayersToMap re-applies paint, filter and
  // the private _minzoom/_maxzoom keys on every state change, but never a
  // layer's `layout` block, and only the line/symbol/cluster/mixed adapters
  // touch layout at all. The clear-removed-props loop below is likewise the only
  // code anywhere that unsets a layout key. Anything that changes a layer's
  // layout must therefore route through here, or the map keeps the old value.
  const handleLayoutChange = useCallback(
    (layerId: string, newLayout: Record<string, unknown>) => {
      const prevLayout = (layersRef.current.find((l) => l.id === layerId)?.layout ?? {}) as Record<string, unknown>;
      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, layout: newLayout }),
        (map) => {
          const ids = getCompanionLayerIds(layerId);
          const mapLayerId = ids.layer;
          if (!map.getLayer(mapLayerId)) return;

          // Apply layer zoom range from custom layout props (main + outline companion)
          const minzoom = (newLayout['_minzoom'] as number) ?? 0;
          const maxzoom = (newLayout['_maxzoom'] as number) ?? 22;
          map.setLayerZoomRange(mapLayerId, minzoom, maxzoom);
          if (map.getLayer(ids.outline)) {
            map.setLayerZoomRange(ids.outline, minzoom, maxzoom);
          }
          // fix(HT-07): the DEM color-relief companion rides the same source
          // and must honor the layer's custom zoom range too.
          if (map.getLayer(ids.colorRelief)) {
            map.setLayerZoomRange(ids.colorRelief, minzoom, maxzoom);
          }
          if (map.getLayer(ids.cluster)) {
            map.setLayerZoomRange(ids.cluster, minzoom, maxzoom);
          }
          if (map.getLayer(ids.clusterCount)) {
            map.setLayerZoomRange(ids.clusterCount, minzoom, maxzoom);
          }

          for (const [prop, value] of Object.entries(newLayout)) {
            // Skip custom props — not real MapLibre layout properties
            if (prop.startsWith('_')) continue;
            try {
              // line-dasharray is stored in layout JSON but is a MapLibre paint property
              if (prop === 'line-dasharray') {
                setDynamicPaintProperty(map, mapLayerId, prop, value ?? undefined);
              } else {
                setDynamicLayoutProperty(map, mapLayerId, prop, value ?? undefined);
              }
            } catch (e) {
              if (import.meta.env.DEV) console.debug(`[builder] Failed to set layout ${prop}:`, e);
            }
          }
          // Clear removed props (e.g., removing line-dasharray sets solid)
          for (const prop of Object.keys(prevLayout)) {
            if (prop.startsWith('_')) continue;
            if (!(prop in newLayout)) {
              try {
                if (prop === 'line-dasharray') {
                  setDynamicPaintProperty(map, mapLayerId, prop, undefined);
                } else {
                  setDynamicLayoutProperty(map, mapLayerId, prop, undefined);
                }
              } catch (e) {
                if (import.meta.env.DEV) console.debug(`[builder] Failed to clear layout ${prop}:`, e);
              }
            }
          }
        },
      );
    },
    [applyLayerUpdate],
  );

  const handleFilterChange = useCallback(
    (layerId: string, expression: FilterSpecification | null) => {
      const filter = sanitizeNullableNumericFilter(expression);
      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, filter }),
        (map) => {
          const ids = getCompanionLayerIds(layerId);
          // fix(#430 codex r23): mixed-geometry sublayers carry per-family
          // geometry-type filters as part of their identity — COMPOSE the data
          // filter with them (never replace), mirroring the dataset-page fix
          // for the same clobber class (codex r22).
          if (map.getLayer(ids.mixedPoints)) {
            map.setFilter(ids.layer, mixedFamilyFilter('polygon', filter));
            map.setFilter(ids.outline, mixedFamilyFilter('polygon', filter));
            map.setFilter(ids.mixedLines, mixedFamilyFilter('line', filter));
            map.setFilter(ids.mixedPoints, mixedFamilyFilter('point', filter));
            if (map.getLayer(ids.label)) {
              map.setFilter(ids.label, filter);
            }
            return;
          }
          // fix(#394) FL-01/B-020: cluster layers keep the bare point_count
          // predicate — cluster features carry no data properties, so ANDing
          // the data filter in hid every cluster bubble (mirrors the same fix
          // in cluster-adapter's clusterFilter).
          const clusterFilter = ['has', 'point_count'] as FilterSpecification;
          const unclusteredFilter = filter ? ['all', ['!', ['has', 'point_count']], filter] as FilterSpecification : ['!', ['has', 'point_count']] as FilterSpecification;
          if (map.getLayer(ids.layer)) {
            map.setFilter(ids.layer, map.getLayer(ids.cluster) ? unclusteredFilter : filter);
          }
          if (map.getLayer(ids.cluster)) {
            map.setFilter(ids.cluster, clusterFilter);
          }
          if (map.getLayer(ids.clusterCount)) {
            map.setFilter(ids.clusterCount, clusterFilter);
          }
          // Also filter outline layer for polygons
          if (map.getLayer(ids.outline)) {
            map.setFilter(ids.outline, filter);
          }
          // Also filter label layer
          if (map.getLayer(ids.label)) {
            map.setFilter(ids.label, filter);
          }
          // Also filter fill-extrusion companion layer
          if (map.getLayer(ids.extrusion)) {
            map.setFilter(ids.extrusion, filter);
          }
          // Also filter the line-arrow companion (B-004) so arrow symbols hide
          // for features removed by the filter.
          if (map.getLayer(ids.arrow)) {
            map.setFilter(ids.arrow, filter);
          }
        },
      );
    },
    [applyLayerUpdate],
  );

  const handleLabelChange = useCallback(
    (layerId: string, config: LabelConfig | null) => {
      // Normalize empty column to null to prevent persisting non-functional config
      if (config && !config.column) {
        config = null;
      }
      const layer = layersRef.current.find((l) => l.id === layerId);
      if (!layer) return;
      const geomType = getLayerType(layer.dataset_geometry_type);

      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, label_config: config }),
        (map) => {
          const ids = getCompanionLayerIds(layerId);
          const labelLayerId = ids.label;

          // B-008/B-009: symbol-mode point layers carry their text in the
          // PRIMARY symbol layer (synced by syncLayersToMap on the state change
          // above); a companion *-label layer would duplicate it for one sync
          // cycle (flicker). Heatmaps carry no feature labels at all — the UI
          // gates the Labels tab, but the AI `set_label` action can bypass that
          // gate. In both modes tear down any stale companion and let
          // syncLayersToMap own the primary-layer text.
          const renderMode = (layer.style_config as { render_mode?: string } | null)
            ?.render_mode;
          if (renderMode === 'symbol' || renderMode === 'heatmap') {
            if (map.getLayer(labelLayerId)) {
              map.removeLayer(labelLayerId);
            }
            return;
          }

          // Remove label layer if config is null or column is empty
          if (!config || !config.column) {
            if (map.getLayer(labelLayerId)) {
              map.removeLayer(labelLayerId);
            }
            return;
          }

          // Update existing label layer
          if (map.getLayer(labelLayerId)) {
            syncLabelLayer(map, labelLayerId, config, geomType);
            return;
          }

          // Add new label layer
          if (!layer) return;

          // SF-04 dedupe: read from the shared per-dataset source.
          const sourceId = getSourceIdForLayer(layer);
          if (!map.getSource(sourceId)) return;

          const sourceLayer = getMvtSourceLayerName(
            layer.dataset_table_name,
            mvtSourceLayerPrefix,
          );
          const parentVis = (map.getLayer(ids.layer)
            ? (map.getLayoutProperty(ids.layer, 'visibility') ?? 'visible')
            : 'visible') as 'visible' | 'none';
          map.addLayer(buildLabelLayerSpec({ labelId: labelLayerId, sourceId, sourceLayer, lc: config, geomType, visibility: parentVis }));

          // Apply parent filter if any
          if (layer.filter) {
            map.setFilter(labelLayerId, sanitizeNullableNumericFilter(layer.filter));
          }
        },
      );
    },
    [applyLayerUpdate, mvtSourceLayerPrefix],
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
    // ENH-03 (Phase 1201-01): map-only style sync for bulk apply (single-setState
    // state write is owned by the bulk handler; this only repaints the map).
    syncStyleConfigToMap,
  };
}
