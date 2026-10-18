import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { INTERNAL_FAILURE_REASON, fixedFailureReason } from '@/lib/failure-reason';
import { useMutation } from '@tanstack/react-query';
import { TerraDraw, TerraDrawPolygonMode } from 'terra-draw';
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { MAP_COLORS } from '@/lib/map-colors';
import { ApiError } from '@/api/client';
import { materializeAnalysis, previewAnalysis } from '@/api/analysis';
import { useDataset } from '@/components/dataset/hooks/use-dataset';
import { useJobStatus } from '@/components/import/hooks/use-ingest';
import { usePermissions } from '@/hooks/use-permissions';
import {
  useAnalysisFormStore,
  type SavedAnalysisForm,
} from '@/stores/analysis-form-store';
import { useAuthStore } from '@/stores/auth-store';
import { useAnalysisAddedStore, useAnalysisJobStore } from '@/stores/analysis-job-store';
import { useMapDrawStore } from '@/stores/map-draw-store';
import type { LayerActions } from '@/components/builder/ChatPanel';
import { isAnalysableLayer } from '@/components/builder/analysis-eligibility';
import type { EphemeralAnalysisHandoff } from '@/components/builder/hooks/use-ephemeral-layers';
import type { AnalysisOperation, MapLayerResponse } from '@/types/api';
import { randomId } from '@/lib/random-id';
import { maplibreFilterToCql2, type Cql2Expression } from '@/lib/maplibre-filter-utils';

const MAX_BUFFER_METERS = 100_000;
// shadcn Select items can't carry an empty value — sentinels for "none".
const BY_FIELD_NONE = '__none__';
const MASK_LAYER_NONE = '__none__';
// Mirrors _POLYGONAL_TYPES in
// backend/app/modules/catalog/datasets/api/router_analysis.py; the server
// rejects any other mask dataset with a 422.
const POLYGONAL_GEOMETRY_TYPES = new Set(['POLYGON', 'MULTIPOLYGON']);

/** The request field for one layer filter, omitted when there is none to send. */
function cql2Field<K extends string>(
  key: K,
  value: Cql2Expression | null | 'unsupported',
): Partial<Record<K, Cql2Expression>> {
  if (value === null || value === 'unsupported') return {};
  return { [key]: value } as Record<K, Cql2Expression>;
}
// Mirrors _ROW_FILTERING_OPERATIONS in
// backend/app/modules/catalog/datasets/domain/service_analysis.py. These drop
// or multiply source rows, so the source's feature count says nothing about the
// output and the server sends null for it. For them match_count IS the output
// total. spatial_join is absent on purpose: its match_count counts matched
// pairs beside a result that keeps every source row.
const ROW_FILTERING_OPERATIONS = ['clip', 'select_by_location', 'intersect'] as const;
// A column the server will refuse must not be offered. These mirror
// router_analysis.py: _SAFE_COLUMN_RE gates any column named as a group key or
// a transferred field, so `Área`, `2020_pop` and `:id` are rejected there. GDAL
// launders only case, `-` and `#`, so ingested tables hold such names routinely
// (see _list_carry_columns on why they are still CARRIED). _NON_GROUPABLE_TYPES
// rejects json and xml as group keys. Both pickers share the rule.
const SAFE_COLUMN_RE = /^[a-zA-Z_][a-zA-Z0-9_]*$/;
// Mirrors MAX_IDENTIFIER_LENGTH (PostgreSQL's NAMEDATALEN - 1) in
// backend/app/platform/analysis_sql/spatial_join.py. Safe as a character count
// because SAFE_COLUMN_RE has already restricted these names to ASCII.
const MAX_IDENTIFIER_LENGTH = 63;
const NON_GROUPABLE_COLUMN_TYPES = new Set(['json', 'xml']);
// The app turns focus refetching off globally; these queries need it.
const FRESH_COLUMNS = { staleTime: 0, refetchOnWindowFocus: true };
// Buffer distances are metres on the wire; the picker converts so a
// user thinking in feet or miles doesn't have to.
const BUFFER_UNIT_METERS = { m: 1, km: 1000, ft: 0.3048, mi: 1609.344 } as const;
type BufferUnit = keyof typeof BUFFER_UNIT_METERS;
// The cap in a display unit, floored to two decimals so the stated maximum is
// itself a legal value. Rounding to nearest could overstate it: 100 000 m in
// feet is 328,083.99 ft, which converts back to 100 000.0005 m, over the cap.
const maxBufferInUnit = (unit: BufferUnit): number =>
  Math.floor((MAX_BUFFER_METERS / BUFFER_UNIT_METERS[unit]) * 100) / 100;
// Switching the unit converts the displayed number so the PHYSICAL distance is
// preserved: '100 m' becomes '0.1 km', not a silent 1000x reinterpretation.
// Rounded to 6 significant digits to trim float tails (0.3 km is 300 m, not
// 300.00000000000006), still far finer than the buffer endpoint needs.
const convertDistanceBetweenUnits = (
  raw: string,
  from: BufferUnit,
  to: BufferUnit,
): string => {
  if (from === to) return raw;
  const value = Number(raw);
  // An empty or unparseable field has no physical distance to preserve.
  if (raw.trim() === '' || !Number.isFinite(value)) return raw;
  const converted = (value * BUFFER_UNIT_METERS[from]) / BUFFER_UNIT_METERS[to];
  let rounded = Number(converted.toPrecision(6));
  // A legal value must stay legal across a unit switch: 100 000 m rounded to 6
  // digits is 328 084 ft, over the cap. Round DOWN to the cap in the target
  // unit instead.
  if (
    value * BUFFER_UNIT_METERS[from] <= MAX_BUFFER_METERS &&
    rounded * BUFFER_UNIT_METERS[to] > MAX_BUFFER_METERS
  ) {
    rounded = maxBufferInUnit(to);
  }
  return String(rounded);
};
// Suffixes of the existing analysisTools.unit* keys, so the range message can
// name the unit in the user's language without a second set of strings.
const UNIT_KEY: Record<BufferUnit, string> = {
  m: 'Meters',
  km: 'Kilometers',
  ft: 'Feet',
  mi: 'Miles',
};

/**
 * A viewport-scoping bbox for the preview request, or `undefined` when the
 * viewport cannot be sent as one non-crossing envelope.
 *
 * `map.getBounds()` is monotonic and unwrapped: MapLibre takes min/max over the
 * four raw corner longitudes, so an antimeridian-straddling viewport or a pan
 * through extra world copies (`renderWorldCopies`) returns values like `[179.5,
 * …, 182, …]` or `[899.5, …, 902, …]`. `geom_4326` stores longitudes in [-180,
 * 180], so handing those raw values to `ST_MakeEnvelope` silently misses
 * on-screen data, and a wrong bbox is worse than none because it looks scoped.
 * This preview's single-envelope backend predicate cannot split at the
 * antimeridian, so the two cases that are not one increasing envelope (a
 * full-world viewport and a seam-crossing one) degrade to no bbox.
 *
 * West is wrapped once and east is rebuilt by adding back the raw width; the
 * ends are never wrapped independently. 180 and -180 are the same meridian, so
 * independent wrapping turns a box starting at the seam (e.g. [180, 190]) into
 * a false crossing.
 */
interface PreviewBoundsLike {
  getWest(): number;
  getSouth(): number;
  getEast(): number;
  getNorth(): number;
}

export function viewportPreviewBbox(
  bounds: PreviewBoundsLike,
): [number, number, number, number] | undefined {
  const south = bounds.getSouth();
  const north = bounds.getNorth();
  const rawWest = bounds.getWest();
  const rawEast = bounds.getEast();
  // Reject a decreasing raw pair and a span of a full turn or more. getBounds()
  // is monotonic, so a decreasing pair is outside this function's contract, and
  // a >=360 span leaves nothing for a bbox to restrict.
  if (!(rawEast >= rawWest) || rawEast - rawWest >= 360) return undefined;
  // Already representable as-is: skip the arithmetic, which would add float
  // noise (`-74.1` through `% 360` lands a ULP off) to every ordinary viewport.
  if (rawWest >= -180 && rawEast <= 180) return [rawWest, south, rawEast, north];
  // Wrap WEST only and derive east from it, so both ends use the same
  // representation of the seam.
  const west = (((rawWest + 180) % 360) + 360) % 360 - 180;
  const east = west + (rawEast - rawWest);
  // A normalized east past +180 means the box genuinely straddles the seam —
  // not representable as one non-crossing envelope.
  return east > 180 ? undefined : [west, south, east, north];
}

interface AnalysisPanelProps {
  layers: MapLayerResponse[];
  /** Keys the remembered form and the rehydrated job to
   *  the map they belong to. */
  mapId?: string;
  /** The layer currently selected in the builder's stack. When it is
   *  analysable, the panel opens targeting it instead of whatever sorts first —
   *  behind an explicit chat prefill, ahead of the remembered form's layer.
   *  Read at mount only, like every other initializer here. */
  selectedLayerId?: string | null;
  mapInstanceRef?: React.RefObject<MaplibreMap | null>;
  onPreviewResult?: (
    geojson: GeoJSON.FeatureCollection,
    bbox: [number, number, number, number],
    meta?: {
      truncated?: boolean;
      totalCount?: number;
      viewportScoped?: boolean;
      source?: 'analysis-panel';
    },
  ) => void;
  onClearPreview?: () => void;
  hasPreview?: boolean;
  /** Who drew the current ephemeral overlay. The
   *  stale-restore cleanup only clears the panel's own previews — never a
   *  chat result sharing the slot. */
  previewSource?: 'analysis-panel';
  layerActions?: LayerActions;
  /** Initial form values handed off from a chat run_analysis
   *  preview ("Save as dataset"). Applied on mount only — BuilderRail keys the
   *  panel on the handoff so a new one remounts it. */
  prefill?: EphemeralAnalysisHandoff;
  /** Notifies the app-level watcher of materialize-job changes so
   *  completion/failure still reports after this panel unmounts. The title
   *  rides along so a notification arriving minutes later has context. */
  onAnalysisJobChange?: (jobId: string | null, title?: string) => void;
}

/**
 * Analysis tools rail panel: pick a dataset layer, run a parameterized PostGIS
 * operation and preview the result as an ephemeral GeoJSON overlay via the
 * use-ephemeral-layers pipeline.
 */
export function AnalysisPanel({
  layers,
  mapId,
  selectedLayerId,
  mapInstanceRef,
  onPreviewResult,
  onClearPreview,
  hasPreview,
  previewSource,
  layerActions,
  prefill,
  onAnalysisJobChange,
}: AnalysisPanelProps) {
  const { t, i18n } = useTranslation('builder');
  const firstEligibleId = layers.find(isAnalysableLayer)?.id ?? '';
  // A handoff layer that has since left the map (or lost its
  // dataset) falls back to the default selection instead of an empty select.
  const prefillLayerId =
    prefill && layers.some((l) => l.id === prefill.layerId && isAnalysableLayer(l))
      ? prefill.layerId
      : undefined;
  // The stack's selected row, when it is an analysable layer: 'analyze THIS
  // layer' is the common intent, so it beats the remembered form's layer and
  // the first-eligible default. A chat prefill still wins since it names its
  // layer. Non-layer ids the slot also carries ('settings', a folder group)
  // validate false and change nothing.
  const stackLayerId =
    selectedLayerId &&
    layers.some((l) => l.id === selectedLayerId && isAnalysableLayer(l))
      ? selectedLayerId
      : undefined;
  // The panel is conditionally mounted, so a rail switch, Escape or breakpoint
  // crossing destroys it: restore the remembered form for this map rather than
  // lose a drawn mask and typed name. A chat handoff (prefill) takes
  // precedence. A remembered form whose source layer left the map is ignored
  // wholesale, since its byField/mask describe that layer.
  const [savedForm] = useState<SavedAnalysisForm | null>(() => {
    if (prefill || !mapId) return null;
    const remembered = useAnalysisFormStore.getState().forms[mapId];
    if (!remembered) return null;
    const sourceStillEligible = layers.some(
      (l) => l.id === remembered.layerId && isAnalysableLayer(l),
    );
    return sourceStillEligible ? remembered : null;
  });
  const initialLayerId =
    prefillLayerId ?? stackLayerId ?? savedForm?.layerId ?? firstEligibleId;
  // A stack selection that DISPLACES the remembered layer makes this mount a
  // different draft: layer-coupled fields (byField, any run the form still
  // owned) reset as if the layer select had been edited, while layer-agnostic
  // ones (operation, distance, drawn mask, typed name) still restore.
  const stackDisplacesSavedLayer =
    stackLayerId != null && !!savedForm && savedForm.layerId !== stackLayerId;
  const [layerId, setLayerId] = useState(initialLayerId);
  // The initializers DROP a remembered selection whose source or mask layer
  // left the map while the panel was closed, but the page-level preview overlay
  // drawn from it is still on screen. Detected during render, before the
  // write-through effect below overwrites the slot with the fallback form, and
  // cleared once from the effect further down. The tracked JOB deliberately
  // survives: it runs server-side and the user still needs its progress.
  const staleRestoreRef = useRef(
    (() => {
      if (prefill || !mapId) return false;
      const remembered = useAnalysisFormStore.getState().forms[mapId];
      if (!remembered) return false;
      return (
        // A stack selection displacing the remembered layer leaves an overlay
        // depicting the displaced layer's result, stale for the same reason.
        stackDisplacesSavedLayer ||
        !layers.some(
          (l) => l.id === remembered.layerId && isAnalysableLayer(l),
        ) ||
        (remembered.maskLayerId !== MASK_LAYER_NONE &&
          !layers.some((l) => l.id === remembered.maskLayerId)) ||
        // A vanished JOIN layer strands the overlay like a vanished mask layer:
        // the pairing can no longer be reproduced.
        (remembered.joinLayerId !== MASK_LAYER_NONE &&
          !layers.some((l) => l.id === remembered.joinLayerId))
      );
    })(),
  );
  const [operation, setOperation] = useState<AnalysisOperation>(
    prefill?.operation ?? savedForm?.operation ?? 'buffer',
  );
  const [distance, setDistance] = useState(
    prefill?.distanceMeters != null
      ? String(prefill.distanceMeters)
      : (savedForm?.distance ?? '500'),
  );
  // A chat handoff always carries metres, so the unit starts there regardless.
  const [distanceUnit, setDistanceUnit] = useState<BufferUnit>(
    prefill ? 'm' : (savedForm?.distanceUnit ?? 'm'),
  );
  const [mask, setMask] = useState<GeoJSON.Polygon | null>(savedForm?.mask ?? null);
  const [isDrawing, setIsDrawing] = useState(false);
  // Layer-sourced clip mask; mutually exclusive with a drawn mask.
  const [maskLayerId, setMaskLayerId] = useState(() =>
    savedForm &&
    // A mask layer can't clip itself; the stack-selected layer may BE the
    // remembered mask layer.
    savedForm.maskLayerId !== initialLayerId &&
    layers.some((l) => l.id === savedForm.maskLayerId)
      ? savedForm.maskLayerId
      : MASK_LAYER_NONE,
  );
  // The layer a spatial join counts against; MASK_LAYER_NONE doubles as the
  // shared 'no layer picked' sentinel. Restored on the same terms as
  // maskLayerId: a join layer cannot be the source layer, and one that left the
  // map falls back to the sentinel.
  const [joinLayerId, setJoinLayerId] = useState(() =>
    savedForm &&
    savedForm.joinLayerId !== initialLayerId &&
    layers.some((l) => l.id === savedForm.joinLayerId)
      ? savedForm.joinLayerId
      : MASK_LAYER_NONE,
  );
  // One transferable column, or none. The API takes a list (up to
  // MAX_SPATIAL_JOIN_FIELDS); the panel offers a single Select for the 'which
  // district is this point in' case, which needs no multi-select primitive. The
  // field names a column of the JOIN layer, so it is restorable exactly when
  // that layer was, not on the source layer's terms like byField below.
  const [joinField, setJoinField] = useState(() =>
    savedForm && joinLayerId !== MASK_LAYER_NONE
      ? savedForm.joinField
      : BY_FIELD_NONE,
  );
  const [byField, setByField] = useState(
    // A remembered group-by column belongs to the remembered layer; it must not
    // carry to a stack-selected one.
    savedForm && !stackDisplacesSavedLayer ? savedForm.byField : BY_FIELD_NONE,
  );
  // A chat handoff lands on the save form — suggest a title so its primary
  // button isn't silently disabled for want of one.
  const [outputTitle, setOutputTitle] = useState(() => {
    if (!prefill) return savedForm?.outputTitle ?? '';
    const layer = layers.find((l) => l.id === prefill.layerId);
    const base = layer?.display_name ?? layer?.dataset_name ?? '';
    // A lookup rather than a ternary chain, whose final else would label any
    // newly added operation 'Dissolve'.
    const opLabel: Record<AnalysisOperation, string> = {
      buffer: t('analysisTools.opBuffer', { defaultValue: 'Buffer' }),
      centroid: t('analysisTools.opCentroid', { defaultValue: 'Centroids' }),
      clip: t('analysisTools.opClip', { defaultValue: 'Clip' }),
      dissolve: t('analysisTools.opDissolve', { defaultValue: 'Dissolve' }),
      spatial_join: t('analysisTools.opSpatialJoin', { defaultValue: 'Spatial join' }),
      measure: t('analysisTools.opMeasure', { defaultValue: 'Measure' }),
      select_by_location: t('analysisTools.opSelectByLocation', {
        defaultValue: 'Select by location',
      }),
      intersect: t('analysisTools.opIntersect', { defaultValue: 'Intersect' }),
    };
    return [base, opLabel[prefill.operation]].filter(Boolean).join(' — ');
  });
  // Rehydrate a still-tracked materialize for THIS map so a reopened panel
  // shows the status line and completion actions instead of a disabled Create
  // button. Not for a chat prefill: that mount is a NEW draft, so an unrelated
  // tracked run stays ambient.
  const [jobId, setJobId] = useState<string | null>(() => {
    if (prefill) return null;
    // A restored draft that disowned the run (edited mid-flight, then the panel
    // closed) must not readopt it at mount, and neither must a stack selection
    // that displaced the remembered layer: the mounted form no longer matches
    // the run's parameters.
    if (savedForm?.runDisowned || stackDisplacesSavedLayer) return null;
    const tracked = useAnalysisJobStore.getState().job;
    return tracked && tracked.mapId && tracked.mapId === mapId
      ? tracked.jobId
      : null;
  });
  // The completed run's title, so 'Add to map' can say what it adds after the
  // input is cleared or edited.
  const [lastRunTitle, setLastRunTitle] = useState(() => {
    if (prefill || savedForm?.runDisowned || stackDisplacesSavedLayer) return '';
    const tracked = useAnalysisJobStore.getState().job;
    return tracked && tracked.mapId && tracked.mapId === mapId
      ? tracked.title
      : '';
  });
  // A completed run raises TWO 'Add to map' affordances (this button and the
  // watcher's toast action), so the single-use marker is the shared
  // useAnalysisAddedStore rather than a per-button flag. Keyed on the dataset
  // id, so a new run re-enables it. Scoped to the analysis affordances: adding
  // a dataset twice via other surfaces is legitimate.
  const addedDatasetIds = useAnalysisAddedStore((s) => s.addedDatasetIds);
  const pendingAddIds = useAnalysisAddedStore((s) => s.pendingAddIds);
  const markDatasetPending = useAnalysisAddedStore((s) => s.markPending);
  // A materialize can outlive the panel instance that started it (closed during
  // the POST, reopened before the response lands). The mount-time initializers
  // then see no tracked job, so a job arriving later for this map is adopted
  // here, once per job id. A job this instance started is owned by the
  // seq-guarded mutation callbacks, and re-adopting a run the user has since
  // disowned would resurrect state the superseded-input guard clears.
  const adoptedJobsRef = useRef(new Set<string>());
  // Adoption is only for an instance whose form still matches the run. Once the
  // user edits anything after a run starts, its job belongs to abandoned
  // parameters and stays ambient ('another analysis is running'). Set by
  // handleInputsChanged, reset when a new run starts (Create blesses the
  // current form), and PERSISTED through the form store so closing and
  // reopening between the edit and the POST response can't launder the
  // disowning. A chat prefill starts disowned, as does a mount whose stack
  // selection displaced the remembered layer.
  const formEditedRef = useRef(
    prefill || stackDisplacesSavedLayer ? true : (savedForm?.runDisowned ?? false),
  );
  const trackedJob = useAnalysisJobStore((s) => s.job);
  useEffect(() => {
    if (!trackedJob || !mapId || trackedJob.mapId !== mapId) return;
    if (formEditedRef.current) return;
    if (adoptedJobsRef.current.has(trackedJob.jobId)) return;
    adoptedJobsRef.current.add(trackedJob.jobId);
    setJobId(trackedJob.jobId);
    setLastRunTitle(trackedJob.title);
  }, [trackedJob, mapId]);
  const drawRef = useRef<TerraDraw | null>(null);

  // Snapshot of the form for this map, refreshed every render and written
  // through by the effect below.
  const formSnapshotRef = useRef<SavedAnalysisForm | null>(null);
  formSnapshotRef.current = {
    layerId,
    operation,
    distance,
    distanceUnit,
    mask,
    maskLayerId,
    byField,
    joinLayerId,
    joinField,
    outputTitle,
    runDisowned: formEditedRef.current,
  };
  // The snapshot belongs to the user who typed it: after a logout (the auth
  // subscription cleared the slot) this panel must stop writing, or it would
  // hand the previous user's form to the next login. Captured once at mount,
  // since after an in-place identity change the mounted values are still the
  // previous user's.
  const [formOwnerId] = useState(() => useAuthStore.getState().user?.id ?? null);
  // The responsive breakpoint swap unmounts this panel and mounts its
  // replacement in the SAME commit, and the replacement's mount-only
  // initializers read the store during render, before any unmount cleanup could
  // run. So write through at the end of every commit (nothing renders from this
  // store, so save() notifies no one). That also covers the plain unmount, so
  // there is deliberately no cleanup-time save.
  useEffect(() => {
    if (!mapId) return;
    if ((useAuthStore.getState().user?.id ?? null) !== formOwnerId) return;
    if (formSnapshotRef.current) {
      useAnalysisFormStore.getState().save(mapId, formSnapshotRef.current);
    }
  });

  // A restored drawn mask must be VISIBLE, not just set: the previous unmount
  // tore down TerraDraw and its map layers. Recreate the kept-static overlay as
  // the finish handler leaves it. Best effort: if TerraDraw rejects the
  // feature, the mask still applies without the outline. Shared by the mount
  // restore and the style.load re-add.
  const addStaticMaskOverlay = useCallback(
    (map: MaplibreMap, maskGeometry: GeoJSON.Polygon) => {
      // Held locally so the catch can reach a PARTIALLY started instance;
      // drawRef is only assigned on full success.
      let td: TerraDraw | null = null;
      try {
        td = new TerraDraw({
          adapter: new TerraDrawMapLibreGLAdapter({ map }),
          modes: [
            new TerraDrawPolygonMode({
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
        td.addFeatures([
          {
            id: randomId(),
            type: 'Feature',
            geometry: maskGeometry,
            properties: { mode: 'polygon' },
          },
        ]);
        td.setMode('static');
        drawRef.current = td;
      } catch {
        try {
          td?.stop();
        } catch {
          // stop() on a partially initialized instance may itself throw.
        }
        drawRef.current = null;
      }
    },
    [],
  );
  // The clip Draw button needs the map instance, but ref assignments don't
  // re-render. Mirror it into state from an effect (the legal place to read a
  // ref) using the same no-dep-array retry-every-commit idiom as the mask
  // effects below, which reaches the moment the lazy map exists. The
  // initializer covers a map already loaded when the panel opens.
  const [mapInstance, setMapInstance] = useState<MaplibreMap | null>(
    () => mapInstanceRef?.current ?? null,
  );
  // eslint-disable-next-line react-hooks/exhaustive-deps -- deliberately runs every commit (the ref object never changes identity, only its contents); the prev === map bailout is what stops the update chain
  useEffect(() => {
    const map = mapInstanceRef?.current ?? null;
    setMapInstance((prev) => (prev === map ? prev : map));
  });
  const restoredMaskDrawnRef = useRef(false);
  useEffect(() => {
    if (restoredMaskDrawnRef.current) return;
    const map = mapInstanceRef?.current;
    if (!mask || !map || drawRef.current) return;
    addStaticMaskOverlay(map, mask);
    // Latch AFTER the attempt, and only on success (the overlay helper assigns
    // drawRef when it fully starts and resets it to null on failure), so a
    // failed overlay is retried. Mirrors use-ephemeral-layers'
    // retry-until-attached idiom.
    if (drawRef.current) restoredMaskDrawnRef.current = true;
    // No dep array: the map arrives by ref assignment, so no dep changes, but
    // the lazy BuilderMap's load re-renders the parent. Retrying every commit
    // reaches the moment the map exists; restoredMaskDrawnRef then latches this
    // to a no-op.
  });
  // A basemap switch calls setStyle, which wipes every imperatively added
  // source/layer, TerraDraw's static overlay included (the 1.4.x adapter has no
  // style-reload handling), while `mask` and drawRef survive. Mirror
  // use-ephemeral-layers: subscribe for the lifetime of the mask and rebuild
  // the overlay on every style.load. Stopping the orphaned instance first can
  // throw over the already-wiped layers (the adapter's unregister removes them
  // unguarded), hence the try/catch. No dep array for the same reason as above;
  // the cleanup keeps exactly one live subscription.
  useEffect(() => {
    const map = mapInstanceRef?.current;
    if (!mask || !map) return;
    const readdMask = () => {
      try {
        drawRef.current?.stop();
      } catch {
        // The new style already removed the adapter's layers; stop() may
        // throw tearing down what no longer exists.
      }
      drawRef.current = null;
      addStaticMaskOverlay(map, mask);
    };
    map.on('style.load', readdMask);
    return () => {
      map.off('style.load', readdMask);
    };
  });
  // Shares its TanStack query with the page-level tracker (same key), so
  // there is exactly one 2s poll loop however many components watch the job.
  const { data: job, error: jobError } = useJobStatus(jobId);
  // Once the observed run COMPLETES, clear the mounted panel's copy of the
  // typed name so the unmount snapshot doesn't re-save the finished run's name
  // over what AnalysisJobWatcher cleared in the form store. Success only, and
  // only while the run still owns the field (nothing edited since it started):
  // a failed run created nothing, so the user likely retries under the same
  // name, and an edited field is a newer draft, even one reusing the same
  // permitted non-unique name, which is why this keys on the edit revision and
  // not title equality.
  const observedJobStatus = job?.status;
  useEffect(() => {
    if (observedJobStatus !== 'complete') return;
    if (!formEditedRef.current) setOutputTitle('');
  }, [observedJobStatus]);
  // Mirror AnalysisJobWatcher's gone path for the mounted panel: a definitive
  // 401/403/404 (retention sweep, revoked access) never yields a terminal
  // status, so the panel would poll a dead id forever and keep the old run's
  // name, re-enabling Create with it once the watcher drops the global job.
  // Transient errors keep polling.
  const jobGone =
    jobError instanceof ApiError && [401, 403, 404].includes(jobError.status);
  useEffect(() => {
    if (!jobGone) return;
    setJobId(null);
    if (!formEditedRef.current) setOutputTitle('');
  }, [jobGone]);
  // AnalysisJobWatcher clears this on any terminal status, so a tracked job
  // is by definition still in flight.
  const analysisJobRunning = useAnalysisJobStore((s) => !!s.job);

  const datasetLayers = layers.filter(isAnalysableLayer);
  const selectedLayer = datasetLayers.find((l) => l.id === layerId);
  // The layer a finished materialize produced, once it is on the map. The
  // operation input is a LAYER id, so the result must be on the stack before it
  // can be chained; the chain affordance therefore appears alongside 'Add to
  // map'.
  const resultLayer =
    job?.status === 'complete' && job.dataset_id
      ? datasetLayers.find((l) => l.dataset_id === job.dataset_id)
      : undefined;
  // Candidate clip-mask layers, filtered to polygonal ones since
  // dataset_geometry_type is already here and a point or line layer would only
  // earn a failed request.
  const maskLayerOptions = datasetLayers.filter(
    (l) =>
      l.id !== layerId &&
      POLYGONAL_GEOMETRY_TYPES.has((l.dataset_geometry_type ?? '').toUpperCase()),
  );
  const maskLayer =
    maskLayerId !== MASK_LAYER_NONE
      ? maskLayerOptions.find((l) => l.id === maskLayerId)
      : undefined;
  // select_by_location takes its geometry from the same drawn-or-layer pair as
  // clip, so the panel shares the controls.
  const usesMask = operation === 'clip' || operation === 'select_by_location';
  // Intersect shares the layer PICKER but not the draw block: a drawn polygon
  // carries no attributes to overlay, which would make it an expensive clip.
  // The API agrees: `mask` is not an intersect param, only `mask_dataset_id`.
  const usesMaskLayer = usesMask || operation === 'intersect';
  // The controls are shared; the words cannot be: 'Draw clip area' under a
  // selection names an operation the user did not pick.
  const maskCopy =
    operation === 'select_by_location'
      ? {
          draw: t('analysisTools.drawSelectionArea', {
            defaultValue: 'Draw selection area',
          }),
          areaSet: t('analysisTools.selectionAreaSet', {
            defaultValue: 'Selection area set',
          }),
          layerLabel: t('analysisTools.selectLayerLabel', {
            defaultValue: 'Or select against a layer',
          }),
          layerNone: t('analysisTools.clipLayerNone', {
            defaultValue: 'None — draw on the map',
          }),
          pointerHint: t('analysisTools.drawSelectionPointerHint', {
            defaultValue:
              'Drawing needs a pointer. To select without one, pick a polygon layer below.',
          }),
        }
      : operation === 'intersect'
        ? {
            // draw/areaSet/pointerHint are unused here: intersect renders the
            // picker below but never the draw block above it.
            draw: '',
            areaSet: '',
            pointerHint: '',
            layerLabel: t('analysisTools.overlayLayerLabel', {
              defaultValue: 'Overlay with layer',
            }),
            layerNone: t('analysisTools.overlayLayerNone', {
              defaultValue: 'Choose a layer',
            }),
          }
      : {
          draw: t('analysisTools.drawMask', { defaultValue: 'Draw clip area' }),
          areaSet: t('analysisTools.maskSet', { defaultValue: 'Clip area set' }),
          layerLabel: t('analysisTools.clipLayerLabel', {
            defaultValue: 'Or clip to a layer',
          }),
          layerNone: t('analysisTools.clipLayerNone', {
            defaultValue: 'None — draw on the map',
          }),
          pointerHint: t('analysisTools.drawMaskPointerHint', {
            defaultValue:
              'Drawing needs a pointer. To clip without one, pick a polygon layer below.',
          }),
        };
  // A join works in any direction (points in polygons, lines crossing
  // polygons), so unlike the clip mask there is no geometry-type filter, only
  // 'not the source layer'.
  const joinLayerOptions = datasetLayers.filter((l) => l.id !== layerId);
  const joinLayer =
    joinLayerId !== MASK_LAYER_NONE
      ? joinLayerOptions.find((l) => l.id === joinLayerId)
      : undefined;
  // spatial_join needs the SOURCE's columns too, not just dissolve. A
  // transferred field lands as join_<name>, so a source that already has
  // join_zone (e.g. the output of an earlier spatial join) collides with a join
  // layer's `zone`, and the server rejects Preview and Create with a 422.
  // Fetched fresh on mount and focus: a filter typed from columns that predate
  // a re-upload can keep features the map hides.
  const datasetDetail = useDataset(
    operation === 'dissolve' || operation === 'spatial_join' || selectedLayer?.filter
      ? (selectedLayer?.dataset_id ?? '')
      : '',
    FRESH_COLUMNS,
  );
  const maskFilterApplies = usesMaskLayer && !mask && !!maskLayer;
  const maskDatasetDetail = useDataset(
    maskFilterApplies && maskLayer?.filter ? maskLayer.dataset_id : '',
    FRESH_COLUMNS,
  );
  const sourceColumnNames = new Set(
    (datasetDetail.data?.column_info ?? []).map((c) => c.name),
  );
  const byFieldColumns = (datasetDetail.data?.column_info ?? [])
    .filter(
      (c) =>
        SAFE_COLUMN_RE.test(c.name) &&
        // The dissolve output already emits a generated source_count column.
        c.name !== 'source_count' &&
        // A group key needs an equality operator; json and xml have none.
        !NON_GROUPABLE_COLUMN_TYPES.has(String(c.type ?? '').toLowerCase()),
    )
    .map((c) => c.name);
  // Columns of the JOIN layer, not the source: these are what gets copied
  // across. Fetched only while a join layer is selected.
  const joinDatasetDetail = useDataset(
    operation === 'spatial_join' ? (joinLayer?.dataset_id ?? '') : '',
    FRESH_COLUMNS,
  );
  // Each layer is analysed as the map shows it: through its own filter, sent as
  // CQL2-JSON and typed from the dataset's current columns (the map's copy
  // predates any re-upload made while the builder is open). Only the layers the
  // request names count.
  const sourceCql2 = maplibreFilterToCql2(
    selectedLayer?.filter,
    datasetDetail.data?.column_info,
  );
  const maskCql2 = maskFilterApplies
    ? maplibreFilterToCql2(maskLayer?.filter, maskDatasetDetail.data?.column_info)
    : null;
  const joinCql2 =
    operation === 'spatial_join' && joinLayer
      ? maplibreFilterToCql2(joinLayer.filter, joinDatasetDetail.data?.column_info)
      : null;
  const filterUnsupported = [sourceCql2, maskCql2, joinCql2].includes('unsupported');
  // A failed or paused refetch keeps the previous columns, which may predate a
  // re-upload.
  const columnsSettled = (detail: { isSuccess: boolean; fetchStatus: string }) =>
    detail.isSuccess && detail.fetchStatus === 'idle';
  const filterColumnsPending =
    (sourceCql2 !== null && !columnsSettled(datasetDetail)) ||
    (maskCql2 !== null && !columnsSettled(maskDatasetDetail)) ||
    (joinCql2 !== null && !columnsSettled(joinDatasetDetail));
  const failedColumnQueries = (
    [
      [sourceCql2, datasetDetail],
      [maskCql2, maskDatasetDetail],
      [joinCql2, joinDatasetDetail],
    ] as const
  )
    .filter(([cql2, detail]) => cql2 !== null && detail.isError && detail.fetchStatus === 'idle')
    .map(([, detail]) => detail);
  const filterColumnsFailed = failedColumnQueries.length > 0;
  const filterColumnsLoading = filterColumnsPending && !filterColumnsFailed;
  const filterFields = {
    ...cql2Field('filter', sourceCql2),
    ...cql2Field('mask_filter', maskCql2),
    ...cql2Field('join_filter', joinCql2),
  };
  // A filter edited in the layer panel changes what a preview or a run means.
  const filterKey = JSON.stringify([sourceCql2, maskCql2, joinCql2]);
  const joinFieldColumns = (joinDatasetDetail.data?.column_info ?? [])
    .filter((c) => {
      if (!SAFE_COLUMN_RE.test(c.name)) return false;
      // Every rejection below is about the name the field would LAND on, so all
      // of them compare the generated form. Truncate first, mirroring
      // spatial_join_output_columns: PostgreSQL truncates an identifier past 63
      // bytes with a notice rather than refusing it, so an over-long alias can
      // land on a source column that the untruncated string does not match.
      const generated = `join_${c.name}`.slice(0, MAX_IDENTIFIER_LENGTH);
      // Would overwrite the generated match count.
      if (generated === 'join_count') return false;
      // Would arrive twice: once from the source, once from the join.
      if (sourceColumnNames.has(generated)) return false;
      return true;
    })
    .map((c) => c.name);

  const stopDrawing = useCallback(() => {
    drawRef.current?.stop();
    drawRef.current = null;
    setIsDrawing(false);
  }, []);

  // Starting a draw swaps the Draw button for Cancel, which would drop focus to
  // <body>: keyboard users lose their place and the Escape-cancels-draw handler
  // never receives the keystroke. Follow the swap onto Cancel when drawing
  // starts, and back onto Draw (or Clear, when finishing replaced Draw with the
  // mask row) when it ends.
  const drawButtonRef = useRef<HTMLButtonElement | null>(null);
  const cancelDrawButtonRef = useRef<HTMLButtonElement | null>(null);
  const clearMaskButtonRef = useRef<HTMLButtonElement | null>(null);
  const wasDrawingRef = useRef(false);
  useEffect(() => {
    if (isDrawing) {
      cancelDrawButtonRef.current?.focus();
    } else if (wasDrawingRef.current) {
      (drawButtonRef.current ?? clearMaskButtonRef.current)?.focus();
    }
    wasDrawingRef.current = isDrawing;
  }, [isDrawing]);

  // A preview belongs to the inputs that produced it. Every input change bumps
  // the sequence (so an in-flight response knows it was superseded) and clears
  // the overlay and badge.
  const previewSeqRef = useRef(0);
  // The controller for the preview in flight, aborted on unmount and when a
  // newer preview supersedes it. This cancels the CLIENT half only: the preview
  // endpoint does not watch Request.is_disconnected(), so the sandbox statement
  // behind an abandoned request runs to its own timeout, holding the per-user
  // advisory lock.
  const previewAbortRef = useRef<AbortController | null>(null);
  useEffect(() => () => previewAbortRef.current?.abort(), []);
  const jobIdRef = useRef(jobId);
  jobIdRef.current = jobId;
  // An input change while the materialize POST is on the wire must reset too:
  // jobId isn't set yet, but the run (and its name) already belongs to the old
  // parameters. Assigned below the mutation.
  const materializePendingRef = useRef(false);
  // The shared slot may hold someone else's overlay (a chat query result): an
  // input change invalidates only a preview these inputs produced, one the
  // panel drew itself or the chat run_analysis handoff this panel continues.
  // Render-assigned so handleInputsChanged stays referentially stable.
  const ownsPreviewRef = useRef(false);
  ownsPreviewRef.current = previewSource === 'analysis-panel' || !!prefill;
  const handleInputsChanged = useCallback(() => {
    previewSeqRef.current += 1;
    // The sequence bump only makes the response ineligible to be drawn; the
    // mutation stays pending until the abandoned request settles, and canRun
    // gates on isPending. Without this abort the user could not start the
    // replacement preview, and the abort at the head of the next mutation would
    // never fire.
    previewAbortRef.current?.abort();
    formEditedRef.current = true;
    if (ownsPreviewRef.current) onClearPreview?.();
    // A finished run's 'Dataset created' and name must not survive an input
    // change, or one more click would create an identically-named dataset from
    // different parameters. Global job tracking is untouched (see the Create
    // button).
    if (jobIdRef.current != null || materializePendingRef.current) {
      setJobId(null);
      setOutputTitle('');
    }
  }, [onClearPreview]);
  const lastFilterKeyRef = useRef(filterKey);
  useEffect(() => {
    if (lastFilterKeyRef.current === filterKey) return;
    lastFilterKeyRef.current = filterKey;
    handleInputsChanged();
  }, [filterKey, handleInputsChanged]);

  // Switching the source layer is reachable from the Layer select and from the
  // chain affordance in the completion state, so the resets live here. Each one
  // resets a field that would otherwise outlive the layer it belonged to.
  const selectSourceLayer = (nextLayerId: string) => {
    handleInputsChanged();
    setLayerId(nextLayerId);
    // A mask layer can't clip itself.
    if (nextLayerId === maskLayerId) setMaskLayerId(MASK_LAYER_NONE);
    // A group-by column chosen for one dataset must not carry to another: it
    // may not exist there (422) or would silently group by a same-named field.
    setByField(BY_FIELD_NONE);
    // The transferred field belongs to the JOIN layer, so it survives a source
    // change intact, but whether it is usable depends on the SOURCE
    // (join_<name> must not collide with a source column). Picking `zone`
    // against a source with no join_zone and then switching to one that has it
    // would leave the menu filtering `zone` out while the state still held it,
    // and the request would earn a 422. A join layer can't join against itself
    // either, so the layer goes with the field.
    if (nextLayerId === joinLayerId) setJoinLayerId(MASK_LAYER_NONE);
    setJoinField(BY_FIELD_NONE);
  };

  // Mount-time half: see staleRestoreRef above.
  useEffect(() => {
    if (!staleRestoreRef.current) return;
    staleRestoreRef.current = false;
    // The shared ephemeral slot may meanwhile hold a NEWER result someone else
    // wrote (a chat query): only an overlay this panel drew belongs to the
    // stale form.
    if (previewSource === 'analysis-panel') onClearPreview?.();
  }, [onClearPreview, previewSource]);
  // Open-panel half: losing the selected source or mask layer while open
  // (deleted from the stack) is an input change like any other. The overlay
  // clears, a finished run's affordances reset, and the selection falls back as
  // a fresh mount would.
  const selectedLayerGone =
    layerId !== '' && !datasetLayers.some((l) => l.id === layerId);
  const maskLayerGone =
    maskLayerId !== MASK_LAYER_NONE &&
    !maskLayerOptions.some((l) => l.id === maskLayerId);
  // A vanished join layer is an input change on the same terms.
  const joinLayerGone =
    joinLayerId !== MASK_LAYER_NONE &&
    !joinLayerOptions.some((l) => l.id === joinLayerId);
  useEffect(() => {
    if (!selectedLayerGone && !maskLayerGone && !joinLayerGone) return;
    handleInputsChanged();
    if (selectedLayerGone) setLayerId(firstEligibleId);
    if (maskLayerGone) setMaskLayerId(MASK_LAYER_NONE);
    if (joinLayerGone) {
      setJoinLayerId(MASK_LAYER_NONE);
      // The field list belonged to the layer that just went away.
      setJoinField(BY_FIELD_NONE);
    }
  }, [
    selectedLayerGone,
    maskLayerGone,
    joinLayerGone,
    firstEligibleId,
    handleInputsChanged,
  ]);

  // Stop any active draw when the panel unmounts.
  useEffect(() => stopDrawing, [stopDrawing]);

  // Tell BuilderMap a draw mode owns the pointer so a vertex click doesn't open
  // the clicked feature's popup. Mirrored from isDrawing in one place because
  // the 'finish' handler drops to static mode without going through
  // stopDrawing.
  useEffect(() => {
    const { setDrawActive } = useMapDrawStore.getState();
    setDrawActive(isDrawing);
    return () => setDrawActive(false);
  }, [isDrawing]);

  const startDrawing = useCallback(() => {
    const map = mapInstanceRef?.current;
    if (!map || drawRef.current) return;
    // The preview is stale the moment drawing begins: the next line drops any
    // layer-sourced mask and cancelling leaves no mask, so a preview computed
    // against the old mask must not linger. The 'finish' handler still
    // invalidates for the drawn mask.
    handleInputsChanged();
    // Drawing replaces a layer-sourced mask.
    setMaskLayerId(MASK_LAYER_NONE);
    // Direct TerraDraw instantiation (BboxMapPicker precedent); the
    // feature-editing drawing-store is dataset-edit-specific.
    const td = new TerraDraw({
      adapter: new TerraDrawMapLibreGLAdapter({ map }),
      modes: [
        new TerraDrawPolygonMode({
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
    td.setMode('polygon');
    td.on('finish', (id: string | number) => {
      const feature = td.getSnapshotFeature(id);
      if (feature && feature.geometry.type === 'Polygon') {
        // A new mask supersedes any preview drawn without it.
        handleInputsChanged();
        setMask(feature.geometry as GeoJSON.Polygon);
        // Keep the drawn polygon visible (built-in static mode) so the user can
        // see what will be clipped. Clearing the mask stops TerraDraw, which
        // removes its layers.
        td.setMode('static');
        setIsDrawing(false);
      } else {
        td.removeFeatures([id]);
        stopDrawing();
      }
    });
    drawRef.current = td;
    setIsDrawing(true);
  }, [mapInstanceRef, stopDrawing, handleInputsChanged]);

  // The API takes metres; the input is whatever unit the user picked.
  const distanceValue = Number(distance) * BUFFER_UNIT_METERS[distanceUnit];
  // Same floor as the unit-switch clamp, so the stated maximum is attainable
  // (see maxBufferInUnit).
  const distanceMaxInUnit = maxBufferInUnit(distanceUnit);
  // Materialize requires the upload permission server-side (it creates a
  // dataset) and also `export`, since the output carries the source's
  // attributes. Hide the creation half for roles lacking either instead of
  // letting them fill the form into a guaranteed 403. Preview stays. Read
  // before the mutations so their callbacks can branch on it.
  const { can } = usePermissions();
  const canCreateDataset = can('upload') && can('export');

  const distanceValid =
    Number.isFinite(distanceValue) &&
    distanceValue > 0 &&
    distanceValue <= MAX_BUFFER_METERS;

  const previewMutation = useMutation({
    // The request carries the sequence current at click time, so a response
    // that outlived its inputs is dropped instead of drawn. `bbox` is read at
    // submit time in the onSubmit handler alongside `seq`, so mutationFn and
    // onSuccess see the same value.
    mutationFn: async ({
      seq: _seq,
      bbox,
    }: {
      seq: number;
      bbox?: [number, number, number, number];
    }) => {
      const datasetId = selectedLayer?.dataset_id;
      // Thrown messages reach the user verbatim via the onError
      // `error.message || t(...)` fallback, so this one has to be translated.
      if (!datasetId)
        throw new Error(
          t('analysisTools.noLayerSelected', { defaultValue: 'No layer selected' }),
        );
      // Belt and braces: handleInputsChanged already aborted what this preview
      // supersedes, but a caller that reaches here without one (a resubmit on
      // unchanged inputs) must not leave the old fetch pending.
      previewAbortRef.current?.abort();
      const controller = new AbortController();
      previewAbortRef.current = controller;
      return previewAnalysis(
        datasetId,
        {
          // canRun blocks dissolve from the preview path.
          operation: operation as Exclude<AnalysisOperation, 'dissolve'>,
          ...(operation === 'buffer' ? { distance_meters: distanceValue } : {}),
          ...(usesMask && mask ? { mask } : {}),
          ...(usesMaskLayer && !mask && maskLayer?.dataset_id
            ? { mask_dataset_id: maskLayer.dataset_id }
            : {}),
          ...(operation === 'spatial_join' && joinLayer?.dataset_id
            ? {
                join_dataset_id: joinLayer.dataset_id,
                ...(joinField !== BY_FIELD_NONE
                  ? { join_fields: [joinField.replace(/^col:/, '')] }
                  : {}),
              }
            : {}),
          // Scope the preview to the map's current viewport so a capped result
          // draws a spatial sample instead of the first PREVIEW_FEATURE_CAP
          // rows in ingest order. Omitted when the map ref is empty.
          ...(bbox ? { bbox } : {}),
          ...filterFields,
        },
        controller.signal,
      );
    },
    // The error path checks the sequence too: a rejection from an abandoned
    // request must not raise 'Analysis failed' over a newer preview.
    onError: (error: Error, { seq }) => {
      // A preview this panel cancelled is not a failure to report. The seq
      // guard doesn't cover the unmount abort (it aborts WITHOUT bumping the
      // sequence) and the callback still fires, so closing the panel
      // mid-preview would raise 'Analysis failed' over the builder. A timeout
      // is not caught here: safeFetch turns TimeoutError into a normalized
      // ApiError, and only a caller abort keeps this name.
      if (error.name === 'AbortError') return;
      if (seq !== previewSeqRef.current) return;
      toast.error(
        error.message ||
          t('analysisTools.previewFailed', { defaultValue: 'Analysis failed' }),
      );
    },
    onSuccess: (result, { seq, bbox: requestBbox }) => {
      if (seq !== previewSeqRef.current) return;
      if (!result.feature_count || !result.bbox) {
        // Chat surfaces clear a stale overlay on an empty result; otherwise the
        // previous preview would keep describing a result the toast says
        // doesn't exist.
        onClearPreview?.();
        toast.info(
          t('analysisTools.noResults', {
            defaultValue: 'The operation returned no features',
          }),
        );
        return;
      }
      // Which total the server sent, and what it MEANS. For 1:1 operations it
      // sends source_feature_count ('source features'). For the row-filtering
      // ones (select_by_location, intersect) the source count cannot describe
      // the output, so it sends null and the exact OUTPUT total as match_count.
      //
      // Keyed off the OPERATION, not off source_feature_count being null: null
      // also occurs when the dataset's cached feature_count snapshot is absent
      // (legacy imports, register_existing_table), and a spatial_join then has
      // a match_count of matched PAIRS, which runs larger than its output
      // because one source row can match many join rows. Inferring from null
      // would report that pair count as the output total.
      //
      // Reading `operation` after the seq guard above makes it the operation
      // that produced `result`. A new operation lands in the else branch and
      // gets the source total; that default is deliberately not automatic,
      // since what match_count means is per-operation and a new one owes this
      // list a decision.
      const filtersRows = ROW_FILTERING_OPERATIONS.includes(
        operation as (typeof ROW_FILTERING_OPERATIONS)[number],
      );
      const matchedTotal = filtersRows ? (result.match_count ?? null) : null;
      const total = matchedTotal ?? result.source_feature_count ?? null;
      const resultBbox = result.bbox as [number, number, number, number];
      // Whether `total` is viewport-scoped depends on WHICH field it came from.
      // source_feature_count is scoped whenever the request carried a bbox (the
      // service overrides the cached whole-table snapshot with a live
      // bbox-scoped count). match_count is per-operation: intersect's rides the
      // same statement as the geometry preview, so it inherits the bbox filter,
      // but select_by_location's is a SEPARATE uncapped query the bbox never
      // reaches (see AnalysisPreviewResponse.match_count), so it stays
      // unscoped.
      const matchedTotalIsScoped = operation === 'intersect' && requestBbox != null;
      const viewportScoped =
        matchedTotal != null
          ? matchedTotalIsScoped
          : total != null && requestBbox != null;
      if (result.truncated) {
        onPreviewResult?.(result.geojson, resultBbox, {
          truncated: true,
          totalCount: total ?? undefined,
          viewportScoped: viewportScoped || undefined,
          source: 'analysis-panel',
        });
      } else {
        onPreviewResult?.(result.geojson, resultBbox, { source: 'analysis-panel' });
      }
      if (result.truncated) {
        toast.info(
          matchedTotal != null
            ? t(
                // A separate string, not the same one with a different number:
                // this total is the OUTPUT row count, so 'source features'
                // would misdescribe it (for intersect one source feature can
                // produce several output pieces). Intersect's total is
                // viewport-scoped too when a bbox was sent (see
                // matchedTotalIsScoped above), so it names the extent for the
                // same reason source_feature_count's scoped branch does.
                viewportScoped
                  ? 'analysisTools.truncatedNoticeMatchedScoped'
                  : 'analysisTools.truncatedNoticeMatched',
                {
                  defaultValue: viewportScoped
                    ? 'Showing the first {{count, number}} of {{total, number}} matching features in the previewed extent'
                    : 'Showing the first {{count, number}} of {{total, number}} matching features',
                  count: result.feature_count,
                  total: matchedTotal,
                },
              )
            : total != null
            ? t(
                // A viewport-scoped total names the extent it was computed
                // against; otherwise '500 of 22,324' reads like an arbitrary
                // 500 rows although these 500 are what's on screen.
                viewportScoped
                  ? 'analysisTools.truncatedNoticeTotalScoped'
                  : 'analysisTools.truncatedNoticeTotal',
                {
                  // 'source features': the total is the source dataset's
                  // COUNT(*), which can exceed the number of rows that produce
                  // output (NULL/EMPTY geometries). Both numbers are passed
                  // raw: the locale strings group them via {{count,
                  // number}}/{{total, number}}, so count keeps driving plural
                  // selection and renders locale-grouped.
                  defaultValue: viewportScoped
                    ? 'Showing the first {{count, number}} of {{total, number}} source features in the previewed extent'
                    : 'Showing the first {{count, number}} of {{total, number}} source features',
                  count: result.feature_count,
                  total,
                },
              )
            : t('analysisTools.truncatedNotice', {
                defaultValue: 'Preview capped at {{count, number}} features',
                count: result.feature_count,
              }),
          // A capped preview is what materialize is for, so name it instead of
          // leaving the user to infer it. Omitted for viewers, who have no
          // Create dataset button to follow it to.
          canCreateDataset
            ? {
                description: t('analysisTools.truncatedCreateHint', {
                  defaultValue:
                    'Use Create dataset to run the operation over every feature.',
                }),
              }
            : undefined,
        );
      }
    },
  });

  const materializeMutation = useMutation({
    mutationFn: async ({ seq: _seq }: { seq: number }) => {
      // Create blesses the current form as this run's form; edits from here on
      // disown the run again.
      formEditedRef.current = false;
      const datasetId = selectedLayer?.dataset_id;
      // Thrown messages reach the user verbatim via the onError
      // `error.message || t(...)` fallback, so this one has to be translated.
      if (!datasetId)
        throw new Error(
          t('analysisTools.noLayerSelected', { defaultValue: 'No layer selected' }),
        );
      const title = outputTitle.trim();
      const result = await materializeAnalysis(datasetId, {
        operation,
        title,
        ...(operation === 'buffer' ? { distance_meters: distanceValue } : {}),
        ...(usesMask && mask ? { mask } : {}),
        ...(usesMaskLayer && !mask && maskLayer?.dataset_id
          ? { mask_dataset_id: maskLayer.dataset_id }
          : {}),
        ...(operation === 'dissolve' && byField !== BY_FIELD_NONE
          ? { by_field: byField.replace(/^col:/, '') }
          : {}),
        ...(operation === 'spatial_join' && joinLayer?.dataset_id
          ? {
              join_dataset_id: joinLayer.dataset_id,
              ...(joinField !== BY_FIELD_NONE
                ? { join_fields: [joinField.replace(/^col:/, '')] }
                : {}),
            }
          : {}),
        ...filterFields,
      });
      // Mark the job as this instance's own BEFORE the store learns about it,
      // so the adoption effect doesn't treat it as foreign and bypass the seq
      // guard below.
      adoptedJobsRef.current.add(result.job_id);
      // Notify the page from inside the mutationFn, NOT onSuccess: TanStack
      // suppresses observer callbacks once the component unmounts, and
      // page-level tracking exists to survive an unmount while the request is
      // in flight.
      onAnalysisJobChange?.(result.job_id, title);
      return { ...result, title };
    },
    // A response whose inputs were superseded must not resurrect the panel's
    // run state. Global tracking (onAnalysisJobChange above) is deliberately
    // unguarded: the job IS running either way.
    onSuccess: (result, { seq }) => {
      if (seq !== previewSeqRef.current) return;
      setJobId(result.job_id);
      setLastRunTitle(result.title);
    },
    onError: (error: Error) => {
      toast.error(
        error.message ||
          t('analysisTools.previewFailed', { defaultValue: 'Analysis failed' }),
      );
    },
  });
  materializePendingRef.current = materializeMutation.isPending;

  const paramsValid =
    (operation !== 'buffer' || distanceValid) &&
    (!usesMask || !!mask || !!maskLayer) &&
    // Layer only, so there is no drawn fallback to fall back to.
    (operation !== 'intersect' || !!maskLayer) &&
    // A join with nothing to join against is not a runnable form —
    // reflect it here rather than letting the click earn a 422.
    (operation !== 'spatial_join' || !!joinLayer) &&
    // The transferred field must still be one the picker would offer. Clearing
    // it on a source change handles the usual way it goes stale; this handles
    // the rest, since the field and its rule depend on two different layers.
    // Submission is gated on the state agreeing with the menu rather than on
    // enumerating how they can disagree.
    (operation !== 'spatial_join' ||
      joinField === BY_FIELD_NONE ||
      joinFieldColumns.includes(joinField.replace(/^col:/, '')));
  const canRun =
    !!selectedLayer?.dataset_id &&
    !previewMutation.isPending &&
    operation !== 'dissolve' &&
    paramsValid &&
    !filterUnsupported &&
    !filterColumnsPending;
  const canSave =
    !!selectedLayer?.dataset_id &&
    !materializeMutation.isPending &&
    // The API allows one active analysis job per user; reflect that instead of
    // letting the click earn a 429.
    !analysisJobRunning &&
    paramsValid &&
    !filterUnsupported &&
    !filterColumnsPending &&
    outputTitle.trim().length > 0;
  // A validation reason lives in this STATIC hint (pointed at via
  // aria-describedby), because the role='status' region below explains only the
  // job case; putting it in the polite live region would narrate every
  // keystroke.
  const saveBlockedReason = !outputTitle.trim()
    ? ('name' as const)
    : !paramsValid
      ? ('params' as const)
      : filterUnsupported
        ? ('filter' as const)
        : filterColumnsFailed
          ? ('filterColumns' as const)
          : filterColumnsLoading
            ? ('filterColumnsLoading' as const)
            : null;

  if (datasetLayers.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
        {t('analysisTools.noLayers', {
          defaultValue: 'Add a vector dataset layer to use analysis tools. Raster layers are not supported.',
        })}
      </div>
    );
  }

  return (
    // A <form> so Enter in any field runs Preview. Every non-submit button
    // below carries an explicit type="button" so it doesn't trigger this
    // instead.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- container-level Escape shortcut for keystrokes bubbling from the panel's own interactive children (cancels a pending draw, BuilderRail precedent); the form itself stays non-interactive
    <form
      className="flex h-full flex-col gap-3 overflow-y-auto p-3.5"
      data-testid="analysis-panel"
      // The panel renders its own range message; native constraint bubbles on
      // the number input would double up with it.
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        if (canRun) {
          // Read the viewport at submit time, the same instant `seq` is read; a
          // ref that hasn't mounted just means no bbox goes out. The typeof
          // guard covers a caller-supplied ref whose current value isn't a real
          // MaplibreMap (a partial test double, an early-lifecycle stub), which
          // must also degrade to no bbox rather than throw out of a submit
          // handler.
          const map = mapInstanceRef?.current;
          const bounds = typeof map?.getBounds === 'function' ? map.getBounds() : undefined;
          const bbox = bounds ? viewportPreviewBbox(bounds) : undefined;
          previewMutation.mutate({ seq: previewSeqRef.current, bbox });
        }
      }}
      onKeyDown={(e) => {
        // Escape while a clip-mask draw is pending cancels the DRAW, not the
        // panel: BuilderRail's container Escape handler guards on
        // !e.defaultPrevented, so this preventDefault is what keeps the whole
        // Analysis panel (and the in-progress mask) from being torn down.
        if (e.key === 'Escape' && isDrawing) {
          e.preventDefault();
          stopDrawing();
        }
      }}
    >
      <div className="space-y-1.5">
        <Label className="text-xs" htmlFor="analysis-layer">
          {t('analysisTools.layerLabel', { defaultValue: 'Layer' })}
        </Label>
        <Select value={layerId} onValueChange={selectSourceLayer}>
          <SelectTrigger id="analysis-layer" className="w-full">
            <SelectValue
              placeholder={t('analysisTools.layerPlaceholder', {
                defaultValue: 'Select a layer',
              })}
            />
          </SelectTrigger>
          <SelectContent>
            {datasetLayers.map((l) => (
              <SelectItem key={l.id} value={l.id}>
                {l.display_name ?? l.dataset_name ?? l.id}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {sourceCql2 !== null && sourceCql2 !== 'unsupported' && (
          <p className="text-xs text-muted-foreground">
            {t('analysisTools.layerFilterApplied', {
              defaultValue: "Analysis uses only the features this layer's filter shows.",
            })}
          </p>
        )}
        {filterUnsupported && (
          <p id="analysis-filter-unsupported" className="text-xs text-destructive">
            {t('analysisTools.layerFilterUnsupported', {
              defaultValue:
                "A layer's filter uses an expression analysis can't apply. Simplify it in the layer's filter settings, or remove it.",
            })}
          </p>
        )}
        {filterColumnsFailed && (
          <div className="flex items-center gap-2">
            <p id="analysis-filter-columns-failed" className="text-xs text-destructive">
              {t('analysisTools.layerFilterColumnsFailed', {
                defaultValue:
                  "Couldn't load a filtered layer's columns, so its filter can't be checked yet.",
              })}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="shrink-0"
              onClick={() => failedColumnQueries.forEach((query) => void query.refetch())}
            >
              {t('analysisTools.layerFilterColumnsRetry', { defaultValue: 'Try again' })}
            </Button>
          </div>
        )}
        {filterColumnsLoading && (
          <p id="analysis-filter-columns-loading" className="text-xs text-muted-foreground">
            {t('analysisTools.layerFilterColumnsLoading', {
              defaultValue: "Checking the filtered layer's columns…",
            })}
          </p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs" htmlFor="analysis-operation">
          {t('analysisTools.operationLabel', { defaultValue: 'Operation' })}
        </Label>
        <Select
          value={operation}
          onValueChange={(v) => {
            handleInputsChanged();
            const next = v as AnalysisOperation;
            if (next !== 'clip' && next !== 'select_by_location') {
              // Leaving clip mode must drop the retained mask: the static-mode
              // TerraDraw layers would otherwise stay visible under operations
              // that ignore them. Clip and select_by_location both use the
              // mask, so switching between them keeps the drawn area.
              setMask(null);
              stopDrawing();
            }
            setOperation(next);
          }}
        >
          <SelectTrigger id="analysis-operation" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="buffer">
              {t('analysisTools.opBuffer', { defaultValue: 'Buffer' })}
            </SelectItem>
            <SelectItem value="centroid">
              {t('analysisTools.opCentroid', { defaultValue: 'Centroids' })}
            </SelectItem>
            <SelectItem value="clip">
              {t('analysisTools.opClip', { defaultValue: 'Clip' })}
            </SelectItem>
            <SelectItem value="spatial_join">
              {t('analysisTools.opSpatialJoin', { defaultValue: 'Spatial join' })}
            </SelectItem>
            <SelectItem value="measure">
              {t('analysisTools.opMeasure', { defaultValue: 'Measure' })}
            </SelectItem>
            <SelectItem value="select_by_location">
              {t('analysisTools.opSelectByLocation', {
                defaultValue: 'Select by location',
              })}
            </SelectItem>
            <SelectItem value="intersect">
              {t('analysisTools.opIntersect', { defaultValue: 'Intersect' })}
            </SelectItem>
            {/* Dissolve has no preview, and the materialize block is hidden
                without the upload permission, so a viewer picking it would get
                a form with no actions and a hint naming a button they cannot
                see. */}
            {canCreateDataset && (
              <SelectItem value="dissolve">
                {t('analysisTools.opDissolve', { defaultValue: 'Dissolve' })}
              </SelectItem>
            )}
          </SelectContent>
        </Select>
        {operation === 'dissolve' && (
          <p className="text-xs text-muted-foreground">
            {t('analysisTools.dissolveHint', {
              defaultValue:
                'Dissolve merges features into one geometry per group; only the group field is carried over. Run it with Create dataset',
            })}
          </p>
        )}
      </div>

      {operation === 'intersect' && (
        <p className="text-xs text-muted-foreground">
          {t('analysisTools.intersectHint', {
            defaultValue:
              'Cuts new features where the two layers overlap, one per overlapping pair, carrying columns from both. Use Measure afterwards for overlap area.',
          })}
        </p>
      )}

      {operation === 'select_by_location' && (
        <p className="text-xs text-muted-foreground">
          {t('analysisTools.selectByLocationHint', {
            defaultValue:
              'Keeps the features that touch the area, whole and unchanged. Use Create dataset to save the list, then export it.',
          })}
        </p>
      )}

      {operation === 'measure' && (
        <p className="text-xs text-muted-foreground">
          {t('analysisTools.measureHint', {
            defaultValue:
              'Adds area_sqm and length_m to every feature, measured on the globe. Polygons get an area and lines a length; the other reads 0.',
          })}
        </p>
      )}

      {operation === 'spatial_join' && (
        <>
          <div className="space-y-1.5">
            <Label className="text-xs" htmlFor="analysis-join-layer">
              {t('analysisTools.joinLayerLabel', { defaultValue: 'Join with layer' })}
            </Label>
            <Select
              value={joinLayerId}
              onValueChange={(v) => {
                handleInputsChanged();
                setJoinLayerId(v);
                // The column list comes from the join layer, so a remembered
                // field cannot survive changing which layer that is.
                setJoinField(BY_FIELD_NONE);
              }}
            >
              <SelectTrigger id="analysis-join-layer" className="w-full">
                <SelectValue
                  placeholder={t('analysisTools.joinLayerPlaceholder', {
                    defaultValue: 'Choose a layer',
                  })}
                />
              </SelectTrigger>
              <SelectContent>
                {joinLayerOptions.map((l) => (
                  <SelectItem key={l.id} value={l.id}>
                    {l.display_name ?? l.dataset_name ?? l.id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {t('analysisTools.spatialJoinHint', {
                defaultValue:
                  'Each feature gains a join_count of the features it intersects. Overlaps count every match but still produce one row.',
              })}
            </p>
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs" htmlFor="analysis-join-field">
              {t('analysisTools.joinFieldLabel', {
                defaultValue: 'Copy a field across (optional)',
              })}
            </Label>
            <Select
              value={joinField}
              onValueChange={(v) => {
                handleInputsChanged();
                setJoinField(v);
              }}
              disabled={!joinLayer}
            >
              <SelectTrigger id="analysis-join-field" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={BY_FIELD_NONE}>
                  {t('analysisTools.joinFieldNone', {
                    defaultValue: 'Count only',
                  })}
                </SelectItem>
                {joinFieldColumns.map((name) => (
                  // Same 'col:' prefix as the dissolve picker: a real column
                  // named '__none__' must not collide with the sentinel.
                  <SelectItem key={name} value={`col:${name}`}>
                    {name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </>
      )}

      {operation === 'dissolve' && (
        <div className="space-y-1.5">
          <Label className="text-xs" htmlFor="analysis-by-field">
            {t('analysisTools.byFieldLabel', {
              defaultValue: 'Group by field (optional)',
            })}
          </Label>
          <Select
            value={byField}
            onValueChange={(v) => {
              handleInputsChanged();
              setByField(v);
            }}
          >
            <SelectTrigger id="analysis-by-field" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={BY_FIELD_NONE}>
                {t('analysisTools.byFieldNone', {
                  defaultValue: 'No grouping — merge everything',
                })}
              </SelectItem>
              {byFieldColumns.map((name) => (
                // 'col:' prefix keeps a real column named
                // '__none__' from colliding with the no-grouping sentinel.
                <SelectItem key={name} value={`col:${name}`}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {operation === 'buffer' && (
        <div className="space-y-1.5">
          <Label className="text-xs" htmlFor="analysis-distance">
            {t('analysisTools.distanceLabel', { defaultValue: 'Distance' })}
          </Label>
          <div className="flex gap-2">
            <Input
              id="analysis-distance"
              type="number"
              min={0}
              max={distanceMaxInUnit}
              step={distanceUnit === 'm' ? 50 : 'any'}
              value={distance}
              onChange={(e) => {
                handleInputsChanged();
                setDistance(e.target.value);
              }}
              aria-invalid={!distanceValid || undefined}
              aria-describedby={distanceValid ? undefined : 'analysis-distance-error'}
              className="flex-1"
            />
            <Select
              value={distanceUnit}
              onValueChange={(v) => {
                handleInputsChanged();
                const next = v as BufferUnit;
                // Keep the physical distance, not the number: '100 m' switched
                // to miles must not silently mean '100 miles'.
                setDistance(convertDistanceBetweenUnits(distance, distanceUnit, next));
                setDistanceUnit(next);
              }}
            >
              <SelectTrigger
                className="w-24"
                aria-label={t('analysisTools.distanceUnitLabel', {
                  defaultValue: 'Distance unit',
                })}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="m">
                  {t('analysisTools.unitMeters', { defaultValue: 'meters' })}
                </SelectItem>
                <SelectItem value="km">
                  {t('analysisTools.unitKilometers', { defaultValue: 'kilometers' })}
                </SelectItem>
                <SelectItem value="ft">
                  {t('analysisTools.unitFeet', { defaultValue: 'feet' })}
                </SelectItem>
                <SelectItem value="mi">
                  {t('analysisTools.unitMiles', { defaultValue: 'miles' })}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          {/* An out-of-range distance disables Preview and Create dataset, so
              say why: aria-invalid alone tells a screen reader the field is
              invalid but not the accepted range. */}
          {!distanceValid && (
            <p
              id="analysis-distance-error"
              role="alert"
              className="text-xs text-destructive"
            >
              {t('analysisTools.distanceOutOfRange', {
                defaultValue:
                  'Enter a distance greater than 0 and no more than {{max}} {{unit}}.',
                max: distanceMaxInUnit.toLocaleString(i18n.language, {
                  maximumFractionDigits: 2,
                }),
                unit: t(`analysisTools.unit${UNIT_KEY[distanceUnit]}`, {
                  defaultValue: distanceUnit,
                }),
              })}
            </p>
          )}
        </div>
      )}

      {usesMask && maskLayer == null && (
        <div className="space-y-1.5">
          {/* No htmlFor: a <label for> pointing at a button OVERRIDES the
              button's own text in the accessible-name computation, so Cancel
              and Clear would both be announced as "Draw clip area". The buttons
              below are self-labeling. */}
          <Label className="text-xs">{maskCopy.draw}</Label>
          {isDrawing ? (
            <div className="space-y-1.5">
              <p className="text-xs text-muted-foreground">
                {t('analysisTools.drawingHint', {
                  defaultValue: 'Draw on the map — double-click to finish',
                })}
              </p>
              <Button
                ref={cancelDrawButtonRef}
                type="button"
                variant="outline"
                size="sm"
                onClick={stopDrawing}
              >
                {t('analysisTools.cancelDrawing', { defaultValue: 'Cancel' })}
              </Button>
            </div>
          ) : mask ? (
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">
                {maskCopy.areaSet}
              </span>
              <Button
                ref={clearMaskButtonRef}
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  handleInputsChanged();
                  setMask(null);
                  // Also removes the kept-visible drawn polygon (TerraDraw
                  // owns its own map layers; stop() tears them down).
                  stopDrawing();
                }}
              >
                {t('analysisTools.clearMask', { defaultValue: 'Clear' })}
              </Button>
            </div>
          ) : (
            <div className="space-y-1.5">
              <Button
                ref={drawButtonRef}
                type="button"
                variant="outline"
                size="sm"
                onClick={startDrawing}
                disabled={!mapInstance}
              >
                {maskCopy.draw}
              </Button>
              {/* Drawing is pointer-only. Name the keyboard-reachable
                  alternative instead of leaving it to be discovered. */}
              <p className="text-xs text-muted-foreground">
                {maskCopy.pointerHint}
              </p>
            </div>
          )}
        </div>
      )}

      {usesMaskLayer && (
        <div className="space-y-1.5">
          <Label className="text-xs" htmlFor="analysis-mask-layer">
            {maskCopy.layerLabel}
          </Label>
          <Select
            value={maskLayerId}
            onValueChange={(v) => {
              handleInputsChanged();
              setMaskLayerId(v);
              if (v !== MASK_LAYER_NONE) {
                // A layer mask replaces a drawn one.
                setMask(null);
                stopDrawing();
              }
            }}
          >
            <SelectTrigger id="analysis-mask-layer" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={MASK_LAYER_NONE}>{maskCopy.layerNone}</SelectItem>
              {/* Say why the list is empty instead of showing a
                  dropdown with a lone "None" entry. */}
              {maskLayerOptions.length === 0 && (
                <SelectItem value="__no_polygon_layers__" disabled>
                  {t('analysisTools.clipLayerEmpty', {
                    defaultValue: 'No polygon layers on this map',
                  })}
                </SelectItem>
              )}
              {maskLayerOptions.map((l) => (
                <SelectItem key={l.id} value={l.id}>
                  {l.display_name ?? l.dataset_name ?? l.id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      <div className="mt-auto flex flex-col gap-2 pt-1">
        {operation !== 'dissolve' && (
          <Button
            type="submit"
            aria-busy={previewMutation.isPending || undefined}
            aria-describedby={
              filterUnsupported
                ? 'analysis-filter-unsupported'
                : filterColumnsFailed
                  ? 'analysis-filter-columns-failed'
                  : filterColumnsLoading
                    ? 'analysis-filter-columns-loading'
                    : undefined
            }
            disabled={!canRun}
          >
            {previewMutation.isPending
              ? t('analysisTools.running', { defaultValue: 'Running…' })
              : t('analysisTools.run', { defaultValue: 'Preview' })}
          </Button>
        )}
        {hasPreview && (
          <Button type="button" variant="outline" onClick={onClearPreview}>
            {t('analysisTools.clearPreview', { defaultValue: 'Clear preview' })}
          </Button>
        )}

        {/* Hidden without the upload permission — the
            gating mirrors DatasetSearchPanel's import CTA. */}
        {canCreateDataset && (
          <div className="space-y-1.5 border-t pt-3">
            <Label className="text-xs" htmlFor="analysis-output-title">
              {t('analysisTools.outputTitleLabel', {
                defaultValue: 'New dataset name',
              })}
            </Label>
            <Input
              id="analysis-output-title"
              value={outputTitle}
              // A name typed while a run is pending is the NEXT draft's: it
              // disowns the running job's claim on this field (so completion
              // won't clear it) without touching the preview or run status.
              onChange={(e) => {
                formEditedRef.current = true;
                setOutputTitle(e.target.value);
              }}
              // Matches the server's bound, so an over-long title is
              // stopped at the keystroke instead of after clicking Create.
              maxLength={500}
              placeholder={t('analysisTools.outputTitlePlaceholder', {
                defaultValue: 'e.g. Parcels buffered 500 m',
              })}
            />
            <Button
              type="button"
              variant="secondary"
              className="w-full"
              aria-busy={materializeMutation.isPending || undefined}
              // The validation hint below says WHY this is disabled; the
              // job cases are narrated by the status region instead.
              aria-describedby={
                saveBlockedReason === 'filter'
                  ? 'analysis-filter-unsupported'
                  : saveBlockedReason === 'filterColumns'
                    ? 'analysis-filter-columns-failed'
                    : saveBlockedReason === 'filterColumnsLoading'
                      ? 'analysis-filter-columns-loading'
                      : saveBlockedReason
                    ? 'analysis-save-hint'
                    : undefined
              }
              onClick={() => {
                // Reset only this panel's local status line. Clearing the
                // GLOBAL tracking would orphan a job that is still running (the
                // server then 429s the replacement) and lose its completion
                // notification; the mutation replaces the tracked job on
                // success instead.
                setJobId(null);
                materializeMutation.mutate({ seq: previewSeqRef.current });
              }}
              disabled={!canSave}
            >
              {materializeMutation.isPending
                ? t('analysisTools.saving', { defaultValue: 'Creating…' })
                : t('analysisTools.saveButton', { defaultValue: 'Create dataset' })}
            </Button>
            {/* Static hint, deliberately NOT in the role="status" region —
                a polite live region would narrate it on every keystroke. */}
            {(saveBlockedReason === 'name' || saveBlockedReason === 'params') && (
              <p id="analysis-save-hint" className="text-xs text-muted-foreground">
                {saveBlockedReason === 'name'
                  ? t('analysisTools.saveHintNeedsName', {
                      defaultValue:
                        'Enter a name for the new dataset to enable Create dataset.',
                    })
                  : t('analysisTools.saveHintNeedsParams', {
                      defaultValue:
                        'Complete the operation settings above to enable Create dataset.',
                    })}
              </p>
            )}
            {/* One PERSISTENT status region, mounted empty with the form: a
                live region that mounts already populated is not announced, so
                every message arrives as a mutation inside an existing region.
                The one-job-per-user cap disables the button, so the "another
                analysis" branch says so instead of leaving a disabled primary
                control unexplained (covers a job started before a reload or
                from another panel). */}
            <p className="text-xs text-muted-foreground" role="status">
              {/* "Another analysis" means a FOREIGN job only. The panel's own
                  run passes through two tracked-but-not-yet-observed gaps
                  (mutationFn onAnalysisJobChange to onSuccess setJobId, and
                  setJobId to the first poll response) during which the store
                  holds OUR job while `job` is still empty; announcing then
                  would be a false warning, and guarding on isPending alone
                  would leave the second gap open. */}
              {analysisJobRunning &&
              !job &&
              jobId == null &&
              !materializeMutation.isPending
                ? t('analysisTools.anotherJobRunning', {
                    defaultValue:
                      'Another analysis is still running — wait for it to finish.',
                  })
                : job
                  ? // Reuse the watcher's jobFailedDetail template instead of
                    // concatenating the raw server error onto a translated prefix.
                    job.status === 'failed'
                    ? // The coded reason is not worth showing; the plain line
                      // below already says it failed.
                      job.error_message &&
                      job.error_message !== INTERNAL_FAILURE_REASON
                      ? t('analysisTools.jobFailedDetail', {
                          defaultValue: 'Analysis job failed: {{message}}',
                          message: fixedFailureReason(job.error_code) ?? job.error_message,
                        })
                      : t('analysisTools.jobFailed', {
                          defaultValue: 'Analysis job failed',
                        })
                    : job.status === 'complete'
                      ? t('analysisTools.jobComplete', { defaultValue: 'Dataset created' })
                      : // A cancelled run is a reachable terminal status; without
                        // its own branch it would fall through to the current_step
                        // copy and sit on 'Saving the dataset…'. `job` is this
                        // panel's own query state, so it outlives the watcher's
                        // store clear.
                        job.status === 'cancelled'
                        ? (fixedFailureReason(job.error_code) ??
                            t('analysisTools.jobCancelled', {
                              defaultValue: 'Analysis run cancelled',
                            }))
                        : job.current_step === 'registering'
                        ? t('analysisTools.jobSaving', {
                            defaultValue: 'Saving the dataset…',
                          })
                        : job.current_step === 'queued'
                          ? t('analysisTools.jobQueued', {
                              defaultValue: 'Queued — waiting for a worker…',
                            })
                          : t('analysisTools.jobRunning', {
                              defaultValue: 'Creating dataset…',
                            })
                  : null}
            </p>
            {job?.status === 'complete' && !!job.dataset_id && layerActions && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-full"
                // Completion raises this button AND the watcher's toast action;
                // both share one single-use guard: pending while the add
                // mutation is in flight (re-armed if it fails), confirmed once
                // it succeeds.
                disabled={
                  addedDatasetIds.includes(job.dataset_id) ||
                  pendingAddIds.includes(job.dataset_id)
                }
                onClick={() => {
                  if (!job.dataset_id) return;
                  if (
                    addedDatasetIds.includes(job.dataset_id) ||
                    pendingAddIds.includes(job.dataset_id)
                  ) {
                    return;
                  }
                  markDatasetPending(job.dataset_id);
                  layerActions.onAddDataset(job.dataset_id);
                }}
              >
                {/* Name the dataset this adds — after a rail
                    round-trip or reload the field above may no longer say. */}
                {addedDatasetIds.includes(job.dataset_id)
                  ? t('analysisTools.addedToMap', { defaultValue: 'Added to map' })
                  : lastRunTitle
                    ? t('analysisTools.addToMapNamed', {
                        defaultValue: 'Add "{{name}}" to map',
                        name: lastRunTitle,
                      })
                    : t('analysisTools.addToMap', { defaultValue: 'Add to map' })}
              </Button>
            )}
            {/* Chain a second operation onto the result without leaving the
                panel.

                The target is the MATERIALIZED dataset's layer, and only ever
                that. An ephemeral preview is not an operation input: making an
                explicitly ephemeral result addressable is a new concept every
                surface that can hold one would have to honour (the preview
                stack row, select-by-location, the shared overlay slot chat also
                writes to), whereas chaining on the materialized half needs no
                new concept. */}
            {resultLayer && resultLayer.id !== layerId && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-full"
                // Goes through the same reset path as the Layer select: a
                // source change clears the finished run's status line and name
                // (handleInputsChanged) and the completion block collapses to a
                // fresh form.
                onClick={() => selectSourceLayer(resultLayer.id)}
              >
                {t('analysisTools.chainOnResult', {
                  defaultValue: 'Run another operation on this result',
                })}
              </Button>
            )}
          </div>
        )}
      </div>
    </form>
  );
}
