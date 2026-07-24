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
import { useJobStatus } from '@/components/import/hooks/use-ingest';
import type { LayerActions } from '@/components/builder/ChatPanel';
import type { AnalysisOperation, MapLayerResponse } from '@/types/api';

const MAX_BUFFER_METERS = 100_000;

interface AnalysisPanelProps {
  layers: MapLayerResponse[];
  mapInstanceRef?: React.RefObject<MaplibreMap | null>;
  onPreviewResult?: (
    geojson: GeoJSON.FeatureCollection,
    bbox: [number, number, number, number],
  ) => void;
  onClearPreview?: () => void;
  hasPreview?: boolean;
  layerActions?: LayerActions;
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
}: AnalysisPanelProps) {
  const { t } = useTranslation('builder');
  const firstEligibleId =
    layers.find((l) => !!l.dataset_id && !l.is_dem)?.id ?? '';
  const [layerId, setLayerId] = useState(firstEligibleId);
  const [operation, setOperation] = useState<AnalysisOperation>('buffer');
  const [distance, setDistance] = useState('500');
  const [mask, setMask] = useState<GeoJSON.Polygon | null>(null);
  const [isDrawing, setIsDrawing] = useState(false);
  const [outputTitle, setOutputTitle] = useState('');
  const [jobId, setJobId] = useState<string | null>(null);
  const drawRef = useRef<TerraDraw | null>(null);
  const job = useJobStatus(jobId).data;

  const datasetLayers = layers.filter((l) => !!l.dataset_id && !l.is_dem);
  const selectedLayer = datasetLayers.find((l) => l.id === layerId);

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
      }
      td.removeFeatures([id]);
      stopDrawing();
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
      });
    },
    onSuccess: (result) => {
      if (!result.feature_count || !result.bbox) {
        toast.info(
          t('analysisTools.noResults', {
            defaultValue: 'The operation returned no features',
          }),
        );
        return;
      }
      onPreviewResult?.(
        result.geojson,
        result.bbox as [number, number, number, number],
      );
      if (result.truncated) {
        toast.info(
          t('analysisTools.truncatedNotice', {
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
      return materializeAnalysis(datasetId, {
        operation,
        title: outputTitle.trim(),
        ...(operation === 'buffer' ? { distance_meters: distanceValue } : {}),
        ...(operation === 'clip' && mask ? { mask } : {}),
      });
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
    (operation !== 'clip' || !!mask);
  const canRun =
    !!selectedLayer?.dataset_id &&
    !previewMutation.isPending &&
    operation !== 'dissolve' &&
    paramsValid;
  const canSave =
    !!selectedLayer?.dataset_id &&
    !materializeMutation.isPending &&
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
        <Select value={layerId} onValueChange={setLayerId}>
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
          onValueChange={(v) => setOperation(v as AnalysisOperation)}
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
                'Dissolve merges all features into one geometry; run it with Create dataset',
            })}
          </p>
        )}
      </div>

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

      {operation === 'clip' && (
        <div className="space-y-1.5">
          <Label className="text-xs">
            {t('analysisTools.drawMask', { defaultValue: 'Draw clip area' })}
          </Label>
          {isDrawing ? (
            <div className="space-y-1.5">
              <p className="text-xs text-muted-foreground">
                {t('analysisTools.drawingHint', {
                  defaultValue: 'Draw on the map — double-click to finish',
                })}
              </p>
              <Button variant="outline" size="sm" onClick={stopDrawing}>
                {t('analysisTools.cancelDrawing', { defaultValue: 'Cancel' })}
              </Button>
            </div>
          ) : mask ? (
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">
                {t('analysisTools.maskSet', { defaultValue: 'Clip area set' })}
              </span>
              <Button variant="ghost" size="sm" onClick={() => setMask(null)}>
                {t('analysisTools.clearMask', { defaultValue: 'Clear' })}
              </Button>
            </div>
          ) : (
            <Button
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
                  : t('analysisTools.jobRunning', { defaultValue: 'Creating dataset…' })}
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
