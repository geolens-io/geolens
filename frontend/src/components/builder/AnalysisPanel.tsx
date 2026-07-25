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
import { materializeAnalysis, previewAnalysis } from '@/api/analysis';
import { useDataset } from '@/components/dataset/hooks/use-dataset';
import { useJobStatus } from '@/components/import/hooks/use-ingest';
import { useAnalysisJobStore } from '@/stores/analysis-job-store';
import type { LayerActions } from '@/components/builder/ChatPanel';
import type { EphemeralAnalysisHandoff } from '@/components/builder/hooks/use-ephemeral-layers';
import type { AnalysisOperation, MapLayerResponse } from '@/types/api';

const MAX_BUFFER_METERS = 100_000;
// shadcn Select items can't carry an empty value — sentinels for "none".
const BY_FIELD_NONE = '__none__';
const MASK_LAYER_NONE = '__none__';

interface AnalysisPanelProps {
  layers: MapLayerResponse[];
  mapInstanceRef?: React.RefObject<MaplibreMap | null>;
  onPreviewResult?: (
    geojson: GeoJSON.FeatureCollection,
    bbox: [number, number, number, number],
    meta?: { truncated?: boolean; totalCount?: number },
  ) => void;
  onClearPreview?: () => void;
  hasPreview?: boolean;
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
  mapInstanceRef,
  onPreviewResult,
  onClearPreview,
  hasPreview,
  layerActions,
  prefill,
  onAnalysisJobChange,
}: AnalysisPanelProps) {
  const { t, i18n } = useTranslation('builder');
  const firstEligibleId =
    layers.find((l) => !!l.dataset_id && !l.is_dem)?.id ?? '';
  // feat(#675): a handoff layer that has since left the map (or lost its
  // dataset) falls back to the default selection instead of an empty select.
  const prefillLayerId =
    prefill && layers.some((l) => l.id === prefill.layerId && !!l.dataset_id && !l.is_dem)
      ? prefill.layerId
      : undefined;
  const [layerId, setLayerId] = useState(prefillLayerId ?? firstEligibleId);
  const [operation, setOperation] = useState<AnalysisOperation>(prefill?.operation ?? 'buffer');
  const [distance, setDistance] = useState(
    prefill?.distanceMeters != null ? String(prefill.distanceMeters) : '500',
  );
  const [mask, setMask] = useState<GeoJSON.Polygon | null>(null);
  const [isDrawing, setIsDrawing] = useState(false);
  // Layer-sourced clip mask; mutually exclusive with a drawn mask.
  const [maskLayerId, setMaskLayerId] = useState(MASK_LAYER_NONE);
  const [byField, setByField] = useState(BY_FIELD_NONE);
  // A chat handoff lands on the save form — suggest a title so its primary
  // button isn't silently disabled for want of one.
  const [outputTitle, setOutputTitle] = useState(() => {
    if (!prefill) return '';
    const layer = layers.find((l) => l.id === prefill.layerId);
    const base = layer?.display_name ?? layer?.dataset_name ?? '';
    const opLabel =
      prefill.operation === 'buffer'
        ? t('analysisTools.opBuffer', { defaultValue: 'Buffer' })
        : prefill.operation === 'centroid'
          ? t('analysisTools.opCentroid', { defaultValue: 'Centroids' })
          : prefill.operation === 'clip'
            ? t('analysisTools.opClip', { defaultValue: 'Clip' })
            : t('analysisTools.opDissolve', { defaultValue: 'Dissolve' });
    return [base, opLabel].filter(Boolean).join(' — ');
  });
  const [jobId, setJobId] = useState<string | null>(null);
  const drawRef = useRef<TerraDraw | null>(null);
  // Shares its TanStack query with the page-level tracker (same key), so
  // there is exactly one 2s poll loop however many components watch the job.
  const job = useJobStatus(jobId).data;
  // AnalysisJobWatcher clears this on any terminal status, so a tracked job
  // is by definition still in flight.
  const analysisJobRunning = useAnalysisJobStore((s) => !!s.job);

  const datasetLayers = layers.filter((l) => !!l.dataset_id && !l.is_dem);
  const selectedLayer = datasetLayers.find((l) => l.id === layerId);
  // Candidate clip-mask layers: any other dataset layer (the server rejects
  // non-polygon mask datasets with a clear 422).
  const maskLayerOptions = datasetLayers.filter((l) => l.id !== layerId);
  const maskLayer =
    maskLayerId !== MASK_LAYER_NONE
      ? maskLayerOptions.find((l) => l.id === maskLayerId)
      : undefined;
  // Only fetched while dissolve is selected (enabled gates on a non-empty id).
  const datasetDetail = useDataset(
    operation === 'dissolve' ? (selectedLayer?.dataset_id ?? '') : '',
  );
  const byFieldColumns = (datasetDetail.data?.column_info ?? [])
    .map((c) => c.name)
    // The dissolve output already emits a generated source_count column.
    .filter((name) => name !== 'source_count');

  const stopDrawing = useCallback(() => {
    drawRef.current?.stop();
    drawRef.current = null;
    setIsDrawing(false);
  }, []);

  // Stop any active draw when the panel unmounts.
  useEffect(() => stopDrawing, [stopDrawing]);

  const startDrawing = useCallback(() => {
    const map = mapInstanceRef?.current;
    if (!map || drawRef.current) return;
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
  }, [mapInstanceRef, stopDrawing]);

  const distanceValue = Number(distance);
  const distanceValid =
    Number.isFinite(distanceValue) &&
    distanceValue > 0 &&
    distanceValue <= MAX_BUFFER_METERS;

  const previewMutation = useMutation({
    mutationFn: async () => {
      const datasetId = selectedLayer?.dataset_id;
      if (!datasetId) throw new Error('No layer selected');
      return previewAnalysis(datasetId, {
        // canRun blocks dissolve from the preview path.
        operation: operation as Exclude<AnalysisOperation, 'dissolve'>,
        ...(operation === 'buffer' ? { distance_meters: distanceValue } : {}),
        ...(operation === 'clip' && mask ? { mask } : {}),
        ...(operation === 'clip' && !mask && maskLayer?.dataset_id
          ? { mask_dataset_id: maskLayer.dataset_id }
          : {}),
      });
    },
    onSuccess: (result) => {
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
      const total = result.source_feature_count;
      const bbox = result.bbox as [number, number, number, number];
      if (result.truncated) {
        onPreviewResult?.(result.geojson, bbox, {
          truncated: true,
          totalCount: total ?? undefined,
        });
      } else {
        onPreviewResult?.(result.geojson, bbox);
      }
      if (result.truncated) {
        toast.info(
          total != null
            ? t('analysisTools.truncatedNoticeTotal', {
                // fix(#680 review): "source features" — the total is the
                // source dataset's COUNT(*), which can exceed the number of
                // rows that produce output (NULL/EMPTY geometries).
                defaultValue:
                  'Showing the first {{count}} of {{total}} source features',
                count: result.feature_count,
                total: total.toLocaleString(i18n.language),
              })
            : t('analysisTools.truncatedNotice', {
                defaultValue: 'Preview capped at {{count}} features',
                count: result.feature_count,
              }),
        );
      }
    },
    onError: (error: Error) => {
      toast.error(
        error.message ||
          t('analysisTools.previewFailed', { defaultValue: 'Analysis failed' }),
      );
    },
  });

  const materializeMutation = useMutation({
    mutationFn: async () => {
      const datasetId = selectedLayer?.dataset_id;
      if (!datasetId) throw new Error('No layer selected');
      const title = outputTitle.trim();
      const result = await materializeAnalysis(datasetId, {
        operation,
        title,
        ...(operation === 'buffer' ? { distance_meters: distanceValue } : {}),
        ...(operation === 'clip' && mask ? { mask } : {}),
        ...(operation === 'clip' && !mask && maskLayer?.dataset_id
          ? { mask_dataset_id: maskLayer.dataset_id }
          : {}),
        ...(operation === 'dissolve' && byField !== BY_FIELD_NONE
          ? { by_field: byField.replace(/^col:/, '') }
          : {}),
      });
      // Notify the page from inside the mutationFn, NOT onSuccess: TanStack
      // suppresses observer callbacks once the component unmounts, and the
      // whole point of page-level tracking is surviving an unmount while the
      // request is in flight.
      onAnalysisJobChange?.(result.job_id, title);
      return result;
    },
    onSuccess: (result) => setJobId(result.job_id),
    onError: (error: Error) => {
      toast.error(
        error.message ||
          t('analysisTools.previewFailed', { defaultValue: 'Analysis failed' }),
      );
    },
  });

  const paramsValid =
    (operation !== 'buffer' || distanceValid) &&
    (operation !== 'clip' || !!mask || !!maskLayer);
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
    <div
      className="flex h-full flex-col gap-3 overflow-y-auto p-3.5"
      data-testid="analysis-panel"
    >
      <div className="space-y-1.5">
        <Label className="text-xs" htmlFor="analysis-layer">
          {t('analysisTools.layerLabel', { defaultValue: 'Layer' })}
        </Label>
        <Select
          value={layerId}
          onValueChange={(v) => {
            setLayerId(v);
            // A mask layer can't clip itself.
            if (v === maskLayerId) setMaskLayerId(MASK_LAYER_NONE);
            // fix(#680): a group-by column chosen for one dataset must not
            // carry to another — it may not exist there (422 from the API) or
            // silently group by a same-named field.
            setByField(BY_FIELD_NONE);
          }}
        >
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
            const next = v as AnalysisOperation;
            if (next !== 'clip') {
              // fix(#680): leaving clip mode must drop the retained mask —
              // the static-mode TerraDraw layers otherwise stay visible on
              // the map under operations that ignore them.
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
            <SelectItem value="dissolve">
              {t('analysisTools.opDissolve', { defaultValue: 'Dissolve' })}
            </SelectItem>
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

      {operation === 'dissolve' && (
        <div className="space-y-1.5">
          <Label className="text-xs" htmlFor="analysis-by-field">
            {t('analysisTools.byFieldLabel', {
              defaultValue: 'Group by field (optional)',
            })}
          </Label>
          <Select value={byField} onValueChange={setByField}>
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
            {t('analysisTools.distanceLabel', {
              defaultValue: 'Distance (meters)',
            })}
          </Label>
          <Input
            id="analysis-distance"
            type="number"
            min={1}
            max={MAX_BUFFER_METERS}
            step={50}
            value={distance}
            onChange={(e) => setDistance(e.target.value)}
            aria-invalid={!distanceValid || undefined}
          />
        </div>
      )}

      {operation === 'clip' && maskLayer == null && (
        <div className="space-y-1.5">
          {/* Exactly one of the three buttons below renders at a time, so
              they can share the id this label points at. */}
          <Label className="text-xs" htmlFor="analysis-clip-action">
            {t('analysisTools.drawMask', { defaultValue: 'Draw clip area' })}
          </Label>
          {isDrawing ? (
            <div className="space-y-1.5">
              <p className="text-xs text-muted-foreground">
                {t('analysisTools.drawingHint', {
                  defaultValue: 'Draw on the map — double-click to finish',
                })}
              </p>
              <Button
                id="analysis-clip-action"
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
                {t('analysisTools.maskSet', { defaultValue: 'Clip area set' })}
              </span>
              <Button
                id="analysis-clip-action"
                variant="ghost"
                size="sm"
                onClick={() => {
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
            <Button
              id="analysis-clip-action"
              variant="outline"
              size="sm"
              onClick={startDrawing}
              disabled={!mapInstanceRef?.current}
            >
              {t('analysisTools.drawMask', { defaultValue: 'Draw clip area' })}
            </Button>
          )}
        </div>
      )}

      {operation === 'clip' && (
        <div className="space-y-1.5">
          <Label className="text-xs" htmlFor="analysis-mask-layer">
            {t('analysisTools.clipLayerLabel', {
              defaultValue: 'Or clip to a layer',
            })}
          </Label>
          <Select
            value={maskLayerId}
            onValueChange={(v) => {
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
              <SelectItem value={MASK_LAYER_NONE}>
                {t('analysisTools.clipLayerNone', {
                  defaultValue: 'None — draw on the map',
                })}
              </SelectItem>
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
          <Button onClick={() => previewMutation.mutate()} disabled={!canRun}>
            {previewMutation.isPending
              ? t('analysisTools.running', { defaultValue: 'Running…' })
              : t('analysisTools.run', { defaultValue: 'Preview' })}
          </Button>
        )}
        {hasPreview && (
          <Button variant="outline" onClick={onClearPreview}>
            {t('analysisTools.clearPreview', { defaultValue: 'Clear preview' })}
          </Button>
        )}

        <div className="space-y-1.5 border-t pt-3">
          <Label className="text-xs" htmlFor="analysis-output-title">
            {t('analysisTools.outputTitleLabel', {
              defaultValue: 'New dataset name',
            })}
          </Label>
          <Input
            id="analysis-output-title"
            value={outputTitle}
            onChange={(e) => setOutputTitle(e.target.value)}
            placeholder={t('analysisTools.outputTitlePlaceholder', {
              defaultValue: 'e.g. Parcels buffered 500 m',
            })}
          />
          <Button
            variant="secondary"
            className="w-full"
            onClick={() => {
              // fix(#682 review): reset only this panel's local status line.
              // Clearing the GLOBAL tracking here would orphan a job that is
              // still running (the server then 429s the replacement), losing
              // the original job's completion notification for good — the
              // mutation replaces the tracked job on success instead.
              setJobId(null);
              materializeMutation.mutate();
            }}
            disabled={!canSave}
          >
            {materializeMutation.isPending
              ? t('analysisTools.saving', { defaultValue: 'Creating…' })
              : t('analysisTools.saveButton', { defaultValue: 'Create dataset' })}
          </Button>
          {job && (
            <p className="text-xs text-muted-foreground" role="status">
              {job.status === 'failed'
                ? `${t('analysisTools.jobFailed', { defaultValue: 'Analysis job failed' })}${job.error_message ? `: ${job.error_message}` : ''}`
                : job.status === 'complete'
                  ? t('analysisTools.jobComplete', { defaultValue: 'Dataset created' })
                  : job.current_step === 'registering'
                    ? t('analysisTools.jobSaving', {
                        defaultValue: 'Saving the dataset…',
                      })
                    : t('analysisTools.jobRunning', {
                        defaultValue: 'Creating dataset…',
                      })}
            </p>
          )}
          {job?.status === 'complete' && !!job.dataset_id && layerActions && (
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={() => job.dataset_id && layerActions.onAddDataset(job.dataset_id)}
            >
              {t('analysisTools.addToMap', { defaultValue: 'Add to map' })}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
