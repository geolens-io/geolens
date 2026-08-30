import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
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

const MAX_BUFFER_METERS = 100_000;
// shadcn Select items can't carry an empty value — sentinels for "none".
const BY_FIELD_NONE = '__none__';
const MASK_LAYER_NONE = '__none__';
// ux(#698): mirrors _POLYGONAL_TYPES in
// backend/app/modules/catalog/datasets/api/router_analysis.py — the server
// rejects any other mask dataset with a 422.
const POLYGONAL_GEOMETRY_TYPES = new Set(['POLYGON', 'MULTIPOLYGON']);
// fix(#1097 review): mirrors _ROW_FILTERING_OPERATIONS in
// backend/app/modules/catalog/datasets/domain/service_analysis.py. These drop
// or multiply source rows, so the source's feature count says nothing about
// the output and the server sends null for it. They are also the operations
// whose match_count IS the output total, which is what this list selects for.
// spatial_join is absent on purpose: it reports match_count too, but as a
// count of matched pairs beside a result that keeps every source row.
const ROW_FILTERING_OPERATIONS = ['clip', 'select_by_location', 'intersect'] as const;
// fix(#1097 review): a column the server will refuse must not be offered.
//
// These mirror router_analysis.py. _SAFE_COLUMN_RE gates any column named as a
// group key or a transferred field, so `Área`, `2020_pop` and `:id` are all
// rejected there — GDAL launders only case, `-` and `#`, so ingested tables
// hold names like those routinely (see _list_carry_columns on why they are
// still CARRIED; being carried and being nameable in a request are different
// questions). _NON_GROUPABLE_TYPES rejects json and xml as group keys.
//
// The picker filtered exactly one of these before: dissolve dropped
// `source_count`. Everything else was offered and then refused on submit, so
// the only way to learn a field was unusable was to run the operation. Both
// pickers share the rule now rather than the join picker learning it alone —
// the finding named the join picker, but the gap is in what the pickers know
// about the server's rules, and dissolve had the same hole.
const SAFE_COLUMN_RE = /^[a-zA-Z_][a-zA-Z0-9_]*$/;
// Mirrors MAX_IDENTIFIER_LENGTH in backend/app/platform/analysis_sql.py:
// PostgreSQL's NAMEDATALEN - 1. Safe as a character count here because
// SAFE_COLUMN_RE above has already restricted these names to ASCII.
const MAX_IDENTIFIER_LENGTH = 63;
const NON_GROUPABLE_COLUMN_TYPES = new Set(['json', 'xml']);
// ux(#686): buffer distances are metres on the wire; the picker converts so a
// user thinking in feet or miles doesn't have to.
const BUFFER_UNIT_METERS = { m: 1, km: 1000, ft: 0.3048, mi: 1609.344 } as const;
type BufferUnit = keyof typeof BUFFER_UNIT_METERS;
// fix(#773 follow-up): the cap expressed in a display unit, floored to two
// decimals so the STATED maximum is itself a legal value. Rounding to nearest
// overstated it — 100 000 m in feet displayed as 328,083.99 ft, which
// converts back to 100 000.0005 m, over the cap, making the panel's own
// stated maximum unattainable. Flooring keeps it attainable in every unit
// (100 000 m and 100 km are exact; feet and miles floor slightly short).
const maxBufferInUnit = (unit: BufferUnit): number =>
  Math.floor((MAX_BUFFER_METERS / BUFFER_UNIT_METERS[unit]) * 100) / 100;
// ux(#773): switching the unit converts the displayed number so the PHYSICAL
// distance is preserved — "100 m" becomes "0.1 km", not a silent 1000×
// reinterpretation. Rounded to 6 significant digits to trim float tails
// (0.3 km → 300 m, not 300.00000000000006) while staying far finer than any
// map-distance precision the buffer endpoint cares about.
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
  // fix(#773 follow-up): a legal value must stay legal across a unit switch.
  // 100 000 m rounded to 6 digits became 328 084 ft, which the panel then
  // flagged invalid against its own cap. Round DOWN to the cap in the target
  // unit instead of letting the significant-digit rounding step over it.
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
 * fix(#727 codex P2): `map.getBounds()` is MONOTONIC and UNWRAPPED — MapLibre
 * takes min/max over the four raw corner longitudes, so an antimeridian-
 * straddling viewport or a pan through extra world copies (`renderWorldCopies`
 * is on by default) returns values like `[179.5, …, 182, …]` or even
 * `[899.5, …, 902, …]` (documented against a different consumer in
 * `terrain-coverage.ts`'s module comment). `geom_4326` always stores
 * longitudes in the standard `[-180, 180]` range, so handing those raw values
 * to `ST_MakeEnvelope` silently misses real on-screen data — sending a bbox
 * that is WRONG is worse than sending none, because it looks scoped and
 * isn't. Rather than build antimeridian-splitting support this preview's
 * single-envelope backend predicate does not have, degrade to "no bbox" (this
 * panel's pre-#727 behaviour) for the two cases that cannot be represented as
 * one increasing envelope: a full-world viewport, and a genuinely
 * seam-crossing one.
 *
 * fix(#727 codex P3 round 4): west and east are normalized TOGETHER, not
 * independently — west is wrapped once, and east is reconstructed by adding
 * back the raw width, never wrapped on its own. 180 and -180 are the same
 * meridian, so wrapping each end independently let a viewport starting
 * exactly at the seam (e.g. [180, 190], a real 10°-wide box equivalent to
 * [-180, -170]) keep its west edge at +180 while its east edge wrapped to
 * -170, manufacturing a false crossing out of a box that never had one.
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
  // Reject a decreasing raw pair and a span at or past a full turn. MapLibre's
  // own getBounds() is always monotonic (rawEast >= rawWest is guaranteed),
  // so a decreasing pair is outside this function's contract — degrade the
  // same way as every other unrepresentable case. A >=360 span covers every
  // longitude at this latitude band; there is nothing left for a bbox to
  // restrict.
  if (!(rawEast >= rawWest) || rawEast - rawWest >= 360) return undefined;
  // Already representable byte-identically, no wrapping needed — the
  // overwhelming common case, and skipping the arithmetic below avoids
  // introducing float noise (`-74.1` round-tripped through `% 360` lands a
  // ULP off) on every ordinary viewport just to handle a rare wrapped one.
  if (rawWest >= -180 && rawEast <= 180) return [rawWest, south, rawEast, north];
  // fix(#727 codex P3 round 4): wrap WEST only, then reconstruct east by
  // adding back the raw (already validated non-negative, < 360) width —
  // never wrap east independently. 180 and -180 are the SAME meridian, so a
  // viewport starting exactly at the seam (e.g. [180, 190]) used to keep west
  // at +180 (already "in range" by the old inclusive check) while wrapping
  // east down to -170, manufacturing a false crossing out of a box
  // ([-180, -170]) that never had one. Deriving east from west's normalized
  // value instead of wrapping it separately makes the two ends agree on
  // which representation of the seam they are using.
  const west = (((rawWest + 180) % 360) + 360) % 360 - 180;
  const east = west + (rawEast - rawWest);
  // A normalized east past +180 means the box genuinely straddles the seam —
  // not representable as one non-crossing envelope.
  return east > 180 ? undefined : [west, south, east, north];
}

interface AnalysisPanelProps {
  layers: MapLayerResponse[];
  /** fix(#757)/fix(#760): keys the remembered form and the rehydrated job to
   *  the map they belong to. */
  mapId?: string;
  /** ux(#772): the layer currently selected in the builder's stack. When it is
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
  /** fix(#793 review): who drew the current ephemeral overlay. The
   *  stale-restore cleanup only clears the panel's own previews — never a
   *  chat result sharing the slot. */
  previewSource?: 'analysis-panel';
  layerActions?: LayerActions;
  /** feat(#675): initial form values handed off from a chat run_analysis
   *  preview ("Save as dataset"). Applied on mount only — BuilderRail keys the
   *  panel on the handoff so a new one remounts it. */
  prefill?: EphemeralAnalysisHandoff;
  /** Notifies the app-level watcher of materialize-job changes so
   *  completion/failure still reports after this panel unmounts. The title
   *  rides along so a notification arriving minutes later has context. */
  onAnalysisJobChange?: (jobId: string | null, title?: string) => void;
}

/**
 * M4 analysis tools rail panel: pick a dataset layer, run a parameterized
 * PostGIS operation (buffer/centroid/clip) and preview the result as an
 * ephemeral GeoJSON overlay via the existing use-ephemeral-layers pipeline.
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
  // feat(#675): a handoff layer that has since left the map (or lost its
  // dataset) falls back to the default selection instead of an empty select.
  const prefillLayerId =
    prefill && layers.some((l) => l.id === prefill.layerId && isAnalysableLayer(l))
      ? prefill.layerId
      : undefined;
  // ux(#772): the stack's selected row, when it is an analysable layer —
  // "analyze THIS layer" is the common intent behind opening the panel, so it
  // beats the remembered form's layer and the first-eligible default. A chat
  // prefill still wins: it names its own layer explicitly. Non-layer ids the
  // selection slot also carries ('settings', a folder group) validate false
  // here and change nothing.
  const stackLayerId =
    selectedLayerId &&
    layers.some((l) => l.id === selectedLayerId && isAnalysableLayer(l))
      ? selectedLayerId
      : undefined;
  // fix(#757): the panel is conditionally mounted, so a rail switch, Escape,
  // or a breakpoint crossing destroys it — restore the remembered form for
  // this map instead of losing a drawn mask and a typed name to a stray
  // click. A chat handoff (prefill) takes precedence; a remembered form
  // whose source layer has left the map is ignored wholesale rather than
  // restored piecemeal (its byField/mask describe that layer).
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
  // ux(#772): a stack selection that DISPLACES the remembered layer makes this
  // mount a different draft. The layer-coupled remembered fields (byField, any
  // run the form still owned) reset exactly as if the layer select had been
  // edited — fix(#680)/fix(#793) semantics — while the layer-agnostic ones
  // (operation, distance, drawn mask, typed name) still restore.
  const stackDisplacesSavedLayer =
    stackLayerId != null && !!savedForm && savedForm.layerId !== stackLayerId;
  const [layerId, setLayerId] = useState(initialLayerId);
  // fix(#793 review): the initializers here deliberately DROP a remembered
  // selection whose source or mask layer left the map while the panel was
  // closed — but the page-level preview overlay drawn from that selection is
  // still on screen, depicting a layer that no longer exists. Detected during
  // render, before the write-through effect below overwrites the slot with
  // the fallback form; cleared once, from the effect further down. The
  // tracked JOB, if any, deliberately survives: it runs server-side and
  // fix(#760) wants it visible.
  const staleRestoreRef = useRef(
    (() => {
      if (prefill || !mapId) return false;
      const remembered = useAnalysisFormStore.getState().forms[mapId];
      if (!remembered) return false;
      return (
        // ux(#772): a stack selection displacing the remembered layer leaves
        // any panel-drawn overlay depicting the displaced layer's result —
        // stale for the same reason a vanished layer's would be.
        stackDisplacesSavedLayer ||
        !layers.some(
          (l) => l.id === remembered.layerId && isAnalysableLayer(l),
        ) ||
        (remembered.maskLayerId !== MASK_LAYER_NONE &&
          !layers.some((l) => l.id === remembered.maskLayerId)) ||
        // fix(#1097 review): a vanished JOIN layer strands the overlay for the
        // same reason a vanished mask layer does — the drawn result depicts a
        // pairing that can no longer be reproduced.
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
    // ux(#772): a mask layer can't clip itself — the stack-selected layer may
    // BE the remembered mask layer (mirrors the layer select's own guard).
    savedForm.maskLayerId !== initialLayerId &&
    layers.some((l) => l.id === savedForm.maskLayerId)
      ? savedForm.maskLayerId
      : MASK_LAYER_NONE,
  );
  // feat(#953): the layer a spatial join counts against. MASK_LAYER_NONE is
  // reused as the shared "no layer picked" sentinel rather than a second
  // identically-valued constant.
  // fix(#1097 review): restored from the snapshot on the same terms as
  // maskLayerId — a join layer cannot be the source layer, and a remembered
  // layer that has since left the map falls back to the sentinel.
  const [joinLayerId, setJoinLayerId] = useState(() =>
    savedForm &&
    savedForm.joinLayerId !== initialLayerId &&
    layers.some((l) => l.id === savedForm.joinLayerId)
      ? savedForm.joinLayerId
      : MASK_LAYER_NONE,
  );
  // One transferable column, or none. The API takes a list and the backend
  // handles up to MAX_SPATIAL_JOIN_FIELDS; the panel offers a single Select
  // because that is the "which district is this point in" case, and it needs
  // no multi-select primitive that does not exist here yet.
  // fix(#1097 review): the field names a column of the JOIN layer, so it is
  // restorable exactly when that layer was — not on the source layer's terms
  // like byField below. If the join layer fell back to the sentinel above,
  // a remembered column of it means nothing.
  const [joinField, setJoinField] = useState(() =>
    savedForm && joinLayerId !== MASK_LAYER_NONE
      ? savedForm.joinField
      : BY_FIELD_NONE,
  );
  const [byField, setByField] = useState(
    // ux(#772)/fix(#680) parity: a remembered group-by column belongs to the
    // remembered layer — it must not carry to a stack-selected one.
    savedForm && !stackDisplacesSavedLayer ? savedForm.byField : BY_FIELD_NONE,
  );
  // A chat handoff lands on the save form — suggest a title so its primary
  // button isn't silently disabled for want of one.
  const [outputTitle, setOutputTitle] = useState(() => {
    if (!prefill) return savedForm?.outputTitle ?? '';
    const layer = layers.find((l) => l.id === prefill.layerId);
    const base = layer?.display_name ?? layer?.dataset_name ?? '';
    // feat(#953): a lookup, not a ternary chain. The chain's final else read
    // "Dissolve", so every operation added after it was silently labelled
    // Dissolve in the suggested title until someone extended the chain too.
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
  // fix(#760): rehydrate a still-tracked materialize for THIS map so a
  // reopened (or reloaded) panel shows the status line and completion
  // actions instead of a silently disabled Create button. NOT for a chat
  // prefill (fix(#793 review)): that mount is a NEW draft — an unrelated
  // tracked run stays ambient rather than surfacing its status and
  // completion actions over the handed-off form.
  const [jobId, setJobId] = useState<string | null>(() => {
    if (prefill) return null;
    // fix(#793 review): a restored draft that disowned the run (edited
    // mid-flight, then the panel closed) must not readopt it at mount — the
    // run stays ambient, exactly as the adoption effect below decides.
    // ux(#772): a stack selection displacing the remembered layer disowns the
    // run the same way — the mounted form no longer matches its parameters.
    if (savedForm?.runDisowned || stackDisplacesSavedLayer) return null;
    const tracked = useAnalysisJobStore.getState().job;
    return tracked && tracked.mapId && tracked.mapId === mapId
      ? tracked.jobId
      : null;
  });
  // fix(#764): the completed run's title, so "Add to map" can say what it
  // adds even after the input field is cleared or edited.
  const [lastRunTitle, setLastRunTitle] = useState(() => {
    if (prefill || savedForm?.runDisowned || stackDisplacesSavedLayer) return '';
    const tracked = useAnalysisJobStore.getState().job;
    return tracked && tracked.mapId && tracked.mapId === mapId
      ? tracked.title
      : '';
  });
  // A completed run raises TWO "Add to map" affordances (this button and the
  // watcher's toast action). fix(#833): the single-use marker is the SHARED
  // useAnalysisAddedStore — a per-affordance flag deduped each button against
  // itself but not against the other, so clicking the toast action and then
  // this button added the layer twice. Keyed on the dataset id, so a NEW
  // run's completion re-enables it. Scoped to the analysis affordances only:
  // adding a dataset twice via other surfaces is legitimate, so no global
  // idempotency in onAddDataset.
  const addedDatasetIds = useAnalysisAddedStore((s) => s.addedDatasetIds);
  const pendingAddIds = useAnalysisAddedStore((s) => s.pendingAddIds);
  const markDatasetPending = useAnalysisAddedStore((s) => s.markPending);
  // fix(#793 review): a materialize can outlive the panel instance that
  // started it — closed during the POST, reopened before the response lands.
  // The mount-time initializers above see no tracked job yet, so a job that
  // arrives in the store later for this map is adopted here. Once per job id:
  // a job this instance itself started is owned by the seq-guarded mutation
  // callbacks, and re-adopting a run the user has since disowned (inputs
  // changed mid-flight) would resurrect exactly the state fix(#758) clears.
  const adoptedJobsRef = useRef(new Set<string>());
  // fix(#793 review): adoption is only for an instance whose form still
  // matches the run. Once the user edits ANYTHING after a run starts, a job
  // from that run belongs to abandoned parameters and must stay ambient
  // ("another analysis is running") — exactly what the seq guard would have
  // decided in the originating instance. Set by handleInputsChanged below,
  // reset when a new run starts (Create blesses the current form), and
  // PERSISTED through the form store so closing and reopening the panel
  // between the edit and the POST response cannot launder the disowning.
  // A chat prefill starts disowned outright (fix(#793 review)): it is a new
  // draft, so no pre-existing run may be adopted or clear its suggested
  // title on completion. ux(#772): so does a mount whose stack selection
  // displaced the remembered layer — the run's blessed form is known to
  // differ from what this mount shows.
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

  // fix(#757): remember the form for this map across unmounts. The snapshot
  // ref is refreshed every render; the cleanup writes it back exactly once,
  // when the panel actually unmounts.
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
  // fix(#793 review): the snapshot belongs to the user who typed it —
  // after a logout (the auth subscription just cleared the slot) this panel
  // must stop writing, or it would hand the previous user's form to the next
  // login. Captured once at mount: after an in-place identity change the
  // mounted values are still the previous user's, so staying silent is the
  // correct side of the line.
  const [formOwnerId] = useState(() => useAuthStore.getState().user?.id ?? null);
  // fix(#793 review): the responsive breakpoint swap unmounts this panel
  // and mounts its replacement in the SAME React commit, and the
  // replacement's mount-only initializers read the store DURING render —
  // before any unmount cleanup of ours could run. So the store must already
  // be current at the end of every commit: write through each time (nothing
  // renders from this store, so save() notifies no one). This also covers
  // the plain unmount, which is why there is deliberately no cleanup-time
  // save.
  useEffect(() => {
    if (!mapId) return;
    if ((useAuthStore.getState().user?.id ?? null) !== formOwnerId) return;
    if (formSnapshotRef.current) {
      useAnalysisFormStore.getState().save(mapId, formSnapshotRef.current);
    }
  });

  // fix(#793 review): a restored drawn mask must be VISIBLE, not just
  // set — the previous unmount tore down TerraDraw and its map layers, so
  // the panel said "Clip area set" over an empty map. Recreate the
  // kept-static overlay exactly as the finish handler leaves it. Best
  // effort: if TerraDraw rejects the feature, the mask still applies (the
  // pre-fix behavior), just without the outline. Shared by the mount
  // restore below and the fix(#775) style.load re-add.
  const addStaticMaskOverlay = useCallback(
    (map: MaplibreMap, maskGeometry: GeoJSON.Polygon) => {
      // fix(#793 review): held locally so the catch can reach a PARTIALLY
      // started instance — drawRef is only assigned on full success, so
      // stopping drawRef there stopped nothing while the failed instance kept
      // its map layers and handlers attached.
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
            id: crypto.randomUUID(),
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
  // fix(#787 item 10): the clip Draw button gated on `mapInstanceRef.current`
  // read during render. Ref assignments don't re-render, so the button could
  // stay dead until an unrelated state change happened to re-render the panel.
  // Mirror the instance into state from an effect — the legal place to read a
  // ref — using the same no-dep-array, retry-every-commit idiom as the mask
  // effects below, which is what reaches the moment the lazy map exists. The
  // initializer covers the common case (map already loaded when the panel
  // opens) so a mount does not spend an extra commit settling this.
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
    // Latch AFTER the attempt, and only on success (the overlay helper
    // assigns drawRef when it fully starts, and resets it to null on
    // failure) — latching before the attempt made a failed overlay
    // permanent: the mask applied but never became visible, with no retry.
    // Mirrors use-ephemeral-layers' retry-until-attached idiom.
    if (drawRef.current) restoredMaskDrawnRef.current = true;
    // No dep array (fix(#793 review)): the map arrives by REF assignment —
    // no dep ever changes — but the lazy BuilderMap's load re-renders the
    // parent, so retrying every commit reaches the moment the map exists;
    // restoredMaskDrawnRef then latches this to a no-op.
  });
  // fix(#775): a basemap switch calls setStyle, which wipes every
  // imperatively added source/layer — TerraDraw's static overlay included
  // (the 1.4.x adapter has no style-reload handling) — while `mask` and
  // drawRef survive, so the panel claimed "Clip area set" over a map with no
  // visible mask and no re-add path. Mirror use-ephemeral-layers' fix(#394)
  // pattern: subscribe for the lifetime of the mask and rebuild the overlay
  // on every style.load. Stopping the orphaned instance first can throw over
  // the already-wiped layers (the adapter's unregister removes them
  // unguarded), hence the try/catch. No dep array for the same
  // ref-assignment reason as above; the cleanup keeps exactly one live
  // subscription and drops it when the mask clears or the panel unmounts.
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
  // fix(#793 review): once the observed run COMPLETES, the typed name
  // has served its purpose — clearing the mounted panel's copy keeps the
  // unmount snapshot from re-saving the finished run's name over the value
  // AnalysisJobWatcher just cleared in the form store. Success only, and
  // only while the run still owns the field (nothing edited since it
  // started): a failed run created nothing (the user most likely retries
  // under the same name), and an edited field is a newer draft — even one
  // that deliberately reuses the same permitted, non-unique name, which is
  // why this keys on the edit revision and NOT on title equality. The
  // completed-state UI is unaffected: "Dataset created" and the named
  // "Add to map" read job state and lastRunTitle, not the field.
  const observedJobStatus = job?.status;
  useEffect(() => {
    if (observedJobStatus !== 'complete') return;
    if (!formEditedRef.current) setOutputTitle('');
  }, [observedJobStatus]);
  // fix(#793 review): mirror AnalysisJobWatcher's gone path for the
  // MOUNTED panel — a definitive 401/403/404 (retention sweep, revoked
  // access) never yields the terminal status the effect above keys on, so
  // without this the panel polls a dead id forever and keeps the old run's
  // name in the field, re-enabling Create with it once the watcher drops the
  // global job. Transient errors keep polling, exactly as fix(#682) requires.
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
  // feat(#790): the layer a finished materialize produced, once it is on the
  // map. The operation input is a LAYER id (the select below resolves it to
  // dataset_id), so the result has to be on the stack before it can be
  // chained — which is why the affordance appears alongside "Add to map"
  // rather than replacing it.
  const resultLayer =
    job?.status === 'complete' && job.dataset_id
      ? datasetLayers.find((l) => l.dataset_id === job.dataset_id)
      : undefined;
  // Candidate clip-mask layers. ux(#698): filtered to polygonal layers rather
  // than deferring to the server's 422 — dataset_geometry_type is already here,
  // so offering a point or line layer only buys the user a failed request.
  const maskLayerOptions = datasetLayers.filter(
    (l) =>
      l.id !== layerId &&
      POLYGONAL_GEOMETRY_TYPES.has((l.dataset_geometry_type ?? '').toUpperCase()),
  );
  const maskLayer =
    maskLayerId !== MASK_LAYER_NONE
      ? maskLayerOptions.find((l) => l.id === maskLayerId)
      : undefined;
  // feat(#955): select_by_location takes its geometry from the same drawn-or-
  // layer pair clip does, and the API takes it in the same two fields, so the
  // panel shares the controls rather than growing a second spelling of them.
  const usesMask = operation === 'clip' || operation === 'select_by_location';
  // feat(#956): intersect shares the layer PICKER but not the draw block — a
  // drawn polygon carries no attributes to overlay with, which would make it an
  // expensive clip. The API reflects that too: `mask` is not an intersect
  // param, only `mask_dataset_id`.
  const usesMaskLayer = usesMask || operation === 'intersect';
  // The controls are shared; the words cannot be. "Draw clip area" under a
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
  // feat(#953): a join works in every direction — points in polygons, polygons
  // over polygons, lines crossing polygons — so unlike the clip mask above
  // there is no geometry-type filter, only "not the source layer".
  const joinLayerOptions = datasetLayers.filter((l) => l.id !== layerId);
  const joinLayer =
    joinLayerId !== MASK_LAYER_NONE
      ? joinLayerOptions.find((l) => l.id === joinLayerId)
      : undefined;
  // fix(#1097 review): spatial_join needs the SOURCE's columns too, not just
  // dissolve. A transferred field lands as join_<name>, so a source that
  // already has join_zone — routinely, because it is the output of an earlier
  // spatial join — collides with a join layer's `zone`, and the server rejects
  // both Preview and Create with a 422 the picker gave no warning of.
  const datasetDetail = useDataset(
    operation === 'dissolve' || operation === 'spatial_join'
      ? (selectedLayer?.dataset_id ?? '')
      : '',
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
  // Columns of the JOIN layer, not the source — these are what gets copied
  // across. Fetched only while a join layer is actually selected.
  const joinDatasetDetail = useDataset(
    operation === 'spatial_join' ? (joinLayer?.dataset_id ?? '') : '',
  );
  const joinFieldColumns = (joinDatasetDetail.data?.column_info ?? [])
    .filter((c) => {
      if (!SAFE_COLUMN_RE.test(c.name)) return false;
      // Every rejection below is about the name the field would LAND on, not
      // the name it has, so all of them compare the generated form. That is
      // what keeps them true if the prefix or the generated set changes.
      //
      // fix(#1097 review): truncated first, mirroring
      // spatial_join_output_columns. PostgreSQL truncates an identifier past
      // 63 bytes with a notice rather than refusing it, so the name the
      // comparisons below need is the truncated one — an over-long alias can
      // land on a source column that the untruncated string does not match,
      // and the picker would offer a field the server then rejects.
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

  // Starting a draw swaps the Draw button for Cancel, which dropped focus to
  // <body> — keyboard users lost their place, and the Escape-cancels-draw
  // handler below never received the keystroke. Follow the swap in both
  // directions: onto Cancel when drawing starts, back onto Draw (or Clear,
  // when finishing the polygon replaced Draw with the mask row) when it ends.
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

  // fix(#758): a preview belongs to the inputs that produced it. Every input
  // change bumps the sequence (so an in-flight response knows it has been
  // superseded) and clears the overlay + badge outright.
  const previewSeqRef = useRef(0);
  // fix(#787 item 3): closing the panel mid-preview suppressed the result
  // callbacks but left the request running. The controller for the preview in
  // flight, aborted on unmount and when a newer preview supersedes it.
  // Scope: this cancels the CLIENT half. The preview endpoint does not watch
  // Request.is_disconnected(), so the sandbox statement behind an abandoned
  // request still runs to its own timeout, holding the per-user advisory lock
  // until then. Server-side cancellation on disconnect is a backend change,
  // not this batch's.
  const previewAbortRef = useRef<AbortController | null>(null);
  useEffect(() => () => previewAbortRef.current?.abort(), []);
  const jobIdRef = useRef(jobId);
  jobIdRef.current = jobId;
  // fix(#793 review): an input change while the materialize POST is still on the
  // wire must reset too — jobId isn't set yet, but the run (and its name)
  // already belongs to the old parameters. Assigned below the mutation.
  const materializePendingRef = useRef(false);
  // fix(#793 review): the shared slot may hold someone else's overlay (a
  // chat query result) — an input change invalidates only a preview these
  // inputs produced: one the panel drew itself, or the chat run_analysis
  // handoff this panel was opened to continue. Render-assigned so
  // handleInputsChanged stays referentially stable.
  const ownsPreviewRef = useRef(false);
  ownsPreviewRef.current = previewSource === 'analysis-panel' || !!prefill;
  const handleInputsChanged = useCallback(() => {
    previewSeqRef.current += 1;
    // fix(#787 item 3): the sequence bump only makes the response ineligible
    // to be drawn; the mutation stays pending until the abandoned request
    // settles. canRun gates on isPending, so without this abort the user
    // cannot start the replacement preview they just changed the inputs for,
    // and the abort at the head of the next mutation therefore never fires.
    previewAbortRef.current?.abort();
    formEditedRef.current = true;
    if (ownsPreviewRef.current) onClearPreview?.();
    // fix(#764): a finished run's "Dataset created" + name must not survive
    // an input change — one more click would create an identically-named
    // dataset from different parameters. Global job tracking is untouched
    // (see the #682 note on the Create button).
    if (jobIdRef.current != null || materializePendingRef.current) {
      setJobId(null);
      setOutputTitle('');
    }
  }, [onClearPreview]);

  // feat(#790): switching the source layer is now reachable from two places —
  // the Layer select below and the chain affordance in the completion state —
  // so the resets live here rather than being spelled twice. A second copy
  // would drift: every one of these lines is a fix for a field that outlived
  // the layer it belonged to (#680, #1097).
  const selectSourceLayer = (nextLayerId: string) => {
    handleInputsChanged();
    setLayerId(nextLayerId);
    // A mask layer can't clip itself.
    if (nextLayerId === maskLayerId) setMaskLayerId(MASK_LAYER_NONE);
    // fix(#680): a group-by column chosen for one dataset must not carry to
    // another — it may not exist there (422 from the API) or silently group by
    // a same-named field.
    setByField(BY_FIELD_NONE);
    // fix(#1097 review): the transferred field is the same problem and was
    // left out of this reset. It belongs to the JOIN layer, so it survives a
    // source change intact — but whether it is usable depends on the SOURCE,
    // since join_<name> has to not collide with a source column. Picking
    // `zone` against a source with no join_zone and then switching to one that
    // has it left the menu filtering `zone` out while the state still held it,
    // and the request still went (and earned a 422). A join layer can't join
    // against itself either, so the layer goes with the field.
    if (nextLayerId === joinLayerId) setJoinLayerId(MASK_LAYER_NONE);
    setJoinField(BY_FIELD_NONE);
  };

  // fix(#793 review), mount half: see staleRestoreRef above.
  useEffect(() => {
    if (!staleRestoreRef.current) return;
    staleRestoreRef.current = false;
    // fix(#793 review): the shared ephemeral slot may meanwhile hold a
    // NEWER result someone else wrote (a chat query) — only an overlay this
    // panel itself drew belongs to the stale form and goes with it.
    if (previewSource === 'analysis-panel') onClearPreview?.();
  }, [onClearPreview, previewSource]);
  // fix(#793 review), mounted half: losing the selected source or mask
  // layer while the panel is open (deleted from the stack) is an input
  // change like any other — the overlay clears, a finished run's affordances
  // reset, and the selection falls back exactly as a fresh mount would.
  const selectedLayerGone =
    layerId !== '' && !datasetLayers.some((l) => l.id === layerId);
  const maskLayerGone =
    maskLayerId !== MASK_LAYER_NONE &&
    !maskLayerOptions.some((l) => l.id === maskLayerId);
  // feat(#953): a vanished join layer is an input change on the same terms.
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

  // fix(#726): tell BuilderMap a draw mode owns the pointer, so a vertex click
  // stops falling through and opening the clicked feature's popup. Mirrored
  // from isDrawing in one place rather than set alongside each transition —
  // the 'finish' handler drops to static mode without going through
  // stopDrawing, so per-call-site updates would drift.
  useEffect(() => {
    const { setDrawActive } = useMapDrawStore.getState();
    setDrawActive(isDrawing);
    return () => setDrawActive(false);
  }, [isDrawing]);

  const startDrawing = useCallback(() => {
    const map = mapInstanceRef?.current;
    if (!map || drawRef.current) return;
    // fix(#793 review): the preview is stale the moment drawing begins —
    // the next line drops any layer-sourced mask, and cancelling the draw
    // leaves no mask at all, so a preview computed against the old mask must
    // not linger. The 'finish' handler still invalidates for the drawn mask.
    handleInputsChanged();
    // Drawing replaces a layer-sourced mask.
    setMaskLayerId(MASK_LAYER_NONE);
    // Direct TerraDraw instantiation (BboxMapPicker precedent) — the feature
    // editing drawing-store is dataset-edit-specific and not reused here.
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
        // fix(#758): a new mask supersedes any preview drawn without it.
        handleInputsChanged();
        setMask(feature.geometry as GeoJSON.Polygon);
        // Keep the drawn polygon visible (built-in static mode) so the user
        // can see what will be clipped — removing it left the mask invisible
        // with only a "Clip area set" note as evidence. Clearing the mask
        // stops TerraDraw, which removes its layers.
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
  // fix(#773 follow-up): same floor as the unit-switch clamp, so the stated
  // maximum is attainable — see maxBufferInUnit.
  const distanceMaxInUnit = maxBufferInUnit(distanceUnit);
  // fix(#700 review): materialize requires the upload permission server-side
  // (it creates a dataset); hide the creation half for viewer roles instead
  // of letting them fill the form into a guaranteed 403. Preview stays.
  // Read before the mutations so their callbacks can branch on it too.
  // The endpoint also requires `export` (the output carries the source's
  // attributes, matching the download endpoints), so the gate mirrors both —
  // an upload-only role must not fill the form into a guaranteed 403.
  const { can } = usePermissions();
  const canCreateDataset = can('upload') && can('export');

  const distanceValid =
    Number.isFinite(distanceValue) &&
    distanceValue > 0 &&
    distanceValue <= MAX_BUFFER_METERS;

  const previewMutation = useMutation({
    // fix(#758): the request carries the sequence current at click time, so
    // a response that outlived its inputs (layer/operation/distance/mask
    // changed while it was in flight) is dropped instead of drawn.
    // fix(#727): `bbox` rides along too — read at submit time in the onSubmit
    // handler below, alongside `seq`, so mutationFn and onSuccess see the
    // exact same value rather than each reading `mapInstanceRef.current`
    // independently at two different instants.
    mutationFn: async ({
      seq: _seq,
      bbox,
    }: {
      seq: number;
      bbox?: [number, number, number, number];
    }) => {
      const datasetId = selectedLayer?.dataset_id;
      // ux(#698): thrown messages reach the user verbatim via the onError
      // `error.message || t(...)` fallback, so this one has to be translated.
      if (!datasetId)
        throw new Error(
          t('analysisTools.noLayerSelected', { defaultValue: 'No layer selected' }),
        );
      // Belt and braces: handleInputsChanged already aborted whatever this
      // preview supersedes, but a caller that reaches here without one (a
      // resubmit on unchanged inputs) must not leave the old fetch pending.
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
          // fix(#727): scope the preview to the map's current viewport so a
          // capped result draws a spatial sample instead of the first
          // PREVIEW_FEATURE_CAP rows in ingest order. Omitted (not sent as
          // undefined) when the map ref is empty, matching every other
          // mapInstanceRef guard in this panel.
          ...(bbox ? { bbox } : {}),
        },
        controller.signal,
      );
    },
    // fix(#793 review): the error path checks the sequence too — a
    // rejection from a request whose inputs were already abandoned must not
    // raise "Analysis failed" over a newer, possibly successful preview.
    onError: (error: Error, { seq }) => {
      // fix(#787 item 3): a preview this panel cancelled is not a failure to
      // report. The seq guard alone does not cover the unmount abort, which
      // aborts WITHOUT bumping the sequence, and the callback still fires
      // (the rejection outlives the commit that unsubscribed the observer) —
      // so closing the panel mid-preview raised "Analysis failed" over the
      // builder. A timeout is not caught here: safeFetch turns TimeoutError
      // into a normalized ApiError, and only a caller abort keeps this name.
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
        // fix(#676) parity: chat surfaces clear a stale overlay on an empty
        // result; without this the previous preview kept describing a result
        // the toast says doesn't exist.
        onClearPreview?.();
        toast.info(
          t('analysisTools.noResults', {
            defaultValue: 'The operation returned no features',
          }),
        );
        return;
      }
      // fix(#1097 review): which total the server sent, and what it MEANS.
      // For 1:1 operations it sends source_feature_count and the notice says
      // "source features". For the row-filtering ones (select_by_location,
      // intersect) the source count cannot describe the output, so it sends
      // null there and the exact OUTPUT total as match_count instead — which
      // this read used to discard, leaving the user the generic cap message
      // despite the server having paid for an exact count.
      //
      // fix(#1097 review): keyed off the OPERATION, not off source_feature_count
      // being null. Null has two causes, and only one of them means "read
      // match_count instead": the operation filters rows, or the dataset's
      // cached feature_count snapshot is simply absent (legacy imports,
      // register_existing_table). A spatial_join on a dataset with no snapshot
      // hits the second, and its match_count is a count of matched PAIRS — one
      // source row can match many join rows, so it runs LARGER than the output,
      // which for a 1:1 join is the source row count. Inferring from null
      // reported and stored that pair count as the output total.
      //
      // Reading `operation` after the seq guard above is what makes this the
      // operation that produced `result`: any input change bumps the sequence,
      // so a response that outlived its inputs has already returned.
      //
      // A ninth operation lands in the else branch and gets the source total.
      // That is the safe default and it is deliberately not automatic: what
      // match_count MEANS is per-operation, so a new one owes this list a
      // decision rather than inheriting a guess.
      const filtersRows = ROW_FILTERING_OPERATIONS.includes(
        operation as (typeof ROW_FILTERING_OPERATIONS)[number],
      );
      const matchedTotal = filtersRows ? (result.match_count ?? null) : null;
      const total = matchedTotal ?? result.source_feature_count ?? null;
      const resultBbox = result.bbox as [number, number, number, number];
      // fix(#727 codex round 3): whether `total` is viewport-scoped depends
      // on WHICH field it came from. source_feature_count is scoped whenever
      // the request carried a bbox (the service overrides the cached
      // whole-table snapshot with a live bbox-scoped count). match_count is
      // per-operation: intersect's rides the SAME statement the geometry
      // preview runs, so it inherits that statement's bbox filter too (fix(
      // #727 codex round 2) threaded bbox into render_intersect_preview) —
      // but select_by_location's match_count is a SEPARATE uncapped query
      // the request's bbox never reaches (see AnalysisPreviewResponse.
      // match_count's docs), so it stays unscoped even though its preview
      // rows are viewport-limited too.
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
                // fix(#1097 review): a separate string, not the same one with
                // a different number. This total is the OUTPUT row count, so
                // calling it "source features" would misdescribe it — for
                // intersect it is not even a count of source rows, since one
                // source feature can produce several output pieces.
                //
                // fix(#727 codex round 3): intersect's matched total is
                // viewport-scoped too when a bbox was sent (see
                // matchedTotalIsScoped above) — naming the extent here for
                // the SAME reason source_feature_count's scoped branch does.
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
                // fix(#727): a viewport-scoped total names the extent it was
                // computed against — without that, "500 of 22,324" reads
                // exactly like the pre-fix arbitrary-500-rows case even
                // though these 500 really are what's on screen.
                viewportScoped
                  ? 'analysisTools.truncatedNoticeTotalScoped'
                  : 'analysisTools.truncatedNoticeTotal',
                {
                  // fix(#680 review): "source features" — the total is the
                  // source dataset's COUNT(*), which can exceed the number of
                  // rows that produce output (NULL/EMPTY geometries).
                  // fix(#788): both numbers passed raw — the locale strings
                  // group them via {{count, number}}/{{total, number}}, so count
                  // keeps driving plural selection AND renders locale-grouped.
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
          // ux(#686): a capped preview is exactly what materialize is for, so
          // name it here instead of leaving the user to infer it. Omitted for
          // viewers, who have no Create dataset button to follow it to.
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
      // fix(#793 review): Create blesses the current form as this run's form
      // — edits from here on disown the run again.
      formEditedRef.current = false;
      const datasetId = selectedLayer?.dataset_id;
      // ux(#698): thrown messages reach the user verbatim via the onError
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
      });
      // fix(#793 review): mark the job as this instance's own BEFORE the
      // store learns about it — the adoption effect must not treat it as a
      // foreign job and bypass the seq guard below.
      adoptedJobsRef.current.add(result.job_id);
      // Notify the page from inside the mutationFn, NOT onSuccess: TanStack
      // suppresses observer callbacks once the component unmounts, and the
      // whole point of page-level tracking is surviving an unmount while the
      // request is in flight.
      onAnalysisJobChange?.(result.job_id, title);
      return { ...result, title };
    },
    // fix(#758)/fix(#764): a response whose inputs were superseded must not
    // resurrect the panel's run state. Global tracking (onAnalysisJobChange
    // above) is deliberately unguarded — the job IS running either way.
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
    // feat(#956): layer only, so there is no drawn fallback to fall back to.
    (operation !== 'intersect' || !!maskLayer) &&
    // feat(#953): a join with nothing to join against is not a runnable form —
    // reflect it here rather than letting the click earn a 422.
    (operation !== 'spatial_join' || !!joinLayer) &&
    // fix(#1097 review): and the transferred field has to still be one the
    // picker would offer. Clearing it when the source changes handles the way
    // it went stale in practice; this handles the rest, because the field and
    // the rule that validates it depend on two different layers and either can
    // move underneath it. Submission is gated on the state agreeing with the
    // menu rather than on enumerating the ways they can disagree.
    (operation !== 'spatial_join' ||
      joinField === BY_FIELD_NONE ||
      joinFieldColumns.includes(joinField.replace(/^col:/, '')));
  const canRun =
    !!selectedLayer?.dataset_id &&
    !previewMutation.isPending &&
    operation !== 'dissolve' &&
    paramsValid;
  const canSave =
    !!selectedLayer?.dataset_id &&
    !materializeMutation.isPending &&
    // The API allows one active analysis job per user; reflect that instead of
    // letting the click earn a 429.
    !analysisJobRunning &&
    paramsValid &&
    outputTitle.trim().length > 0;
  // Create dataset went disabled with no reason: the role="status" region
  // below explains only the job case. A validation reason lives in this
  // STATIC hint instead (pointed at via aria-describedby) — putting it in
  // the polite live region would narrate every keystroke.
  const saveBlockedReason = !outputTitle.trim()
    ? ('name' as const)
    : !paramsValid
      ? ('params' as const)
      : null;

  if (datasetLayers.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
        {t('analysisTools.noLayers', {
          defaultValue: 'Add a dataset layer to use analysis tools',
        })}
      </div>
    );
  }

  return (
    // A <form> so Enter in any field runs Preview — the panel had no submit
    // path at all. Every non-submit button below carries an explicit
    // type="button" so it doesn't trigger this instead.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- container-level Escape shortcut for keystrokes bubbling from the panel's own interactive children (cancels a pending draw, BuilderRail precedent); the form itself stays non-interactive
    <form
      className="flex h-full flex-col gap-3 overflow-y-auto p-3.5"
      data-testid="analysis-panel"
      // The panel renders its own range message (#723); native constraint
      // bubbles on the number input would double up with it.
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        if (canRun) {
          // fix(#727): read the viewport at submit time, the same instant
          // `seq` is read — the mask-draw button above guards
          // `mapInstanceRef?.current` the same way, and a ref that hasn't
          // mounted yet just means no bbox goes out, matching this panel's
          // pre-#727 (whole-dataset) preview behaviour. The typeof guard is
          // the same idea one step further: a caller-supplied ref whose
          // current value exists but is not a real MaplibreMap (a partial
          // test double, an early-lifecycle stub) must degrade to "no bbox"
          // too, not throw out of a form submit handler.
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
              // fix(#680): leaving clip mode must drop the retained mask —
              // the static-mode TerraDraw layers otherwise stay visible on
              // the map under operations that ignore them. feat(#955): clip
              // and select_by_location both use the mask, so switching
              // BETWEEN them keeps the drawn area instead of making the user
              // redraw the same polygon.
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
            {/* fix(#779): dissolve has no preview by design, and the whole
                materialize block is hidden without the upload permission — a
                viewer picking it got a form with no actions and a hint
                naming a button they cannot see. Don't offer the dead end. */}
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
                  // Same 'col:' prefix as the dissolve picker, for the same
                  // reason: a real column named '__none__' must not collide
                  // with the sentinel.
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
                // fix(#680 review): 'col:' prefix keeps a real column named
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
                // ux(#773): keep the physical distance, not the number —
                // without this, "100 m" switched to miles silently meant
                // "100 miles".
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
          {/* ux(#723): an out-of-range distance disabled both Preview and
              Create dataset with nothing said. aria-invalid alone is not a
              message — it marks the field for a screen reader without telling
              anyone, sighted or not, what the accepted range is. */}
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
          {/* fix(#754): no htmlFor here — a <label for> pointed at a button
              OVERRIDES the button's own text in the accessible-name
              computation, so Cancel and Clear were both announced as "Draw
              clip area". The buttons below are self-labeling. */}
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
              {/* ux(#686): drawing is pointer-only. Name the keyboard-reachable
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
              {/* fix(#779): say why the list is empty instead of showing a
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
          // The form's submit button — Enter in any field previews too.
          <Button
            type="submit"
            aria-busy={previewMutation.isPending || undefined}
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

        {/* fix(#700 review): hidden without the upload permission — the
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
              // fix(#793 review): a name typed while a run is pending is the
              // NEXT draft's — it disowns the running job's claim on this
              // field (so its completion won't clear it) without touching
              // the preview or the run status.
              onChange={(e) => {
                formEditedRef.current = true;
                setOutputTitle(e.target.value);
              }}
              // ux(#698): matches the server's bound, so an over-long title is
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
              aria-describedby={saveBlockedReason ? 'analysis-save-hint' : undefined}
              onClick={() => {
                // fix(#682 review): reset only this panel's local status line.
                // Clearing the GLOBAL tracking here would orphan a job that is
                // still running (the server then 429s the replacement), losing
                // the original job's completion notification for good — the
                // mutation replaces the tracked job on success instead.
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
            {saveBlockedReason && (
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
            {/* fix(#784): one PERSISTENT status region, mounted empty with the
                form — a live region that mounts already populated is not
                announced, so the previous conditionally-rendered <p>s kept the
                first message ("Creating dataset…") silent for AT. Every
                message now arrives as a mutation inside an existing region.
                fix(#760): the one-job-per-user cap disables the button — the
                "another analysis" branch says so instead of leaving a disabled
                primary control unexplained (covers a job started before a
                reload or from another panel). */}
            <p className="text-xs text-muted-foreground" role="status">
              {/* "Another analysis" means a FOREIGN job only. The panel's own
                  run passes through two tracked-but-not-yet-observed gaps —
                  mutationFn (onAnalysisJobChange) → onSuccess (setJobId), and
                  setJobId → the first poll response — during which the store
                  holds OUR job while `job` is still empty; announcing then
                  was a false warning. Guarding on isPending alone would still
                  leave the second gap open. */}
              {analysisJobRunning &&
              !job &&
              jobId == null &&
              !materializeMutation.isPending
                ? t('analysisTools.anotherJobRunning', {
                    defaultValue:
                      'Another analysis is still running — wait for it to finish.',
                  })
                : job
                  ? // ux(#698): reuse the watcher's jobFailedDetail template
                    // rather than concatenating the raw server error onto a
                    // translated prefix, which left half the sentence untranslated.
                    job.status === 'failed'
                    ? job.error_message
                      ? t('analysisTools.jobFailedDetail', {
                          defaultValue: 'Analysis job failed: {{message}}',
                          message: job.error_message,
                        })
                      : t('analysisTools.jobFailed', {
                          defaultValue: 'Analysis job failed',
                        })
                    : job.status === 'complete'
                      ? t('analysisTools.jobComplete', { defaultValue: 'Dataset created' })
                      : // fix(#1677): cancel made this a reachable terminal
                        // status. Without its own branch a cancelled run fell
                        // through to the current_step copy below and sat on
                        // "Saving the dataset…" — `job` is this panel's own
                        // query state, so it outlives the watcher's store
                        // clear rather than disappearing with it.
                        job.status === 'cancelled'
                        ? t('analysisTools.jobCancelled', {
                            defaultValue: 'Analysis run cancelled',
                          })
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
                // Completion raises this button AND the watcher's toast
                // action. fix(#833): both share one single-use guard —
                // pending while the add mutation is in flight (re-armed if
                // it fails), confirmed once it succeeds.
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
                {/* fix(#764): name the dataset this adds — after a rail
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
            {/* feat(#790): chain a second operation onto the result without
                leaving the panel. Before this, running one was materialize →
                wait → Add to map → scroll back up and hunt the new layer out
                of the source picker.

                The target is the MATERIALIZED dataset's layer, and only ever
                that. An ephemeral preview is NOT an operation input and is not
                going to become one: making an explicitly ephemeral result
                addressable is a new concept the builder would have to honour
                on every surface that can hold one (the preview stack row in
                #1009, select-by-location in #955, the shared overlay slot the
                chat also writes to), whereas chaining on the materialized half
                needs no new concepts and covers the workflow complaint that
                motivated the request. Decided on #790 — read that thread
                before proposing preview-as-input again. */}
            {resultLayer && resultLayer.id !== layerId && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-full"
                // Goes through the same reset path as the Layer select: this
                // is a source change, so the finished run's status line and
                // its name clear with it (handleInputsChanged), and the
                // completion block collapses back to a fresh form.
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
