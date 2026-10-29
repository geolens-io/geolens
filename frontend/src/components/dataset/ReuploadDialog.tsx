import { useState, useEffect, useCallback, useMemo, useRef, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useDropzone } from 'react-dropzone';
import { useQueryClient } from '@tanstack/react-query';
import {
  useReuploadDataset,
  useReuploadPreview,
  useReuploadServicePreview,
  useReuploadCommit,
} from '@/components/dataset/hooks/use-dataset';
import { useJobStatus, useUploadConfig } from '@/components/import/hooks/use-ingest';
import { useRefreshSearchWhenQuicklookLands } from '@/components/dataset/hooks/use-quicklook-settled';
import { queryKeys } from '@/lib/query-keys';
import { buildAcceptMap, deriveFormatBadges } from '@/lib/file-utils';
import { describeFailureReason, fixedFailureReason } from '@/lib/failure-reason';
import { SchemaDiffView } from './SchemaDiffView';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { recordTypeCapabilities } from '@/lib/record-types';
import { Globe, Loader2, CheckCircle2, AlertCircle, AlertTriangle, Upload } from 'lucide-react';
import { toast } from 'sonner';
import { probeService } from '@/api/ingest';
import { ApiError } from '@/api/client';
import { reuploadPresigned, getDataset, getDatasetRefreshRuns } from '@/api/datasets';
import { getGeometryTypeLabel } from '@/i18n/labels';
import { formatNumber } from '@/lib/format';
import type {
  DatasetOrigin,
  DatasetResponse,
  ReuploadPreviewResponse,
  ReuploadSourceType,
  ProbeResponse,
  LayerInfo,
} from '@/types/api';

type ReuploadStep =
  | 'source-select'
  | 'file-select'
  | 'service-connect'
  | 'probing'
  | 'layer-select'
  // File-path layer-select step (distinct from service 'layer-select')
  | 'selecting-file-layer'
  | 'uploading'
  | 'previewing'
  | 'preview'
  | 'committing'
  | 'tracking'
  | 'complete'
  | 'held'
  | 'error';


const AUTH_ERROR_HINTS = [
  '401',
  '403',
  'unauthorized',
  'forbidden',
  'token',
  'auth',
];

// VRT datasets never reach this dialog (DatasetPage keeps them on the
// regenerate flow) and no reupload source produces a .vrt, so it stays
// excluded from every reupload context as a defensive floor.
const VRT_EXTENSION = '.vrt';
// A .3tz holds only a 3D Tiles tileset and a .laz only a point cloud, which no
// reupload can replace.
const KIND_ONLY_EXTENSIONS = new Set(['.3tz', '.laz']);
// Raster reupload accepts only raster source formats; vector/table reupload
// accepts everything the backend allows except raster/VRT formats (rasters go
// through the branch below, VRTs through the regenerate flow).
const RASTER_REUPLOAD_EXTENSIONS = new Set(['.tif', '.tiff']);

interface ReuploadDialogProps {
  dataset: DatasetResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called once a raster replacement job completes, so the caller can remount
   * its hero map: the raster tile URL is a fixed per-dataset route, so nothing
   * else tells MapLibre's already-added raster source to reload. */
  onReplaceComplete?: () => void;
}

function humanizeLayerName(layer: LayerInfo): string {
  if (layer.title) return layer.title;
  return layer.name.replace(/_/g, ' ');
}

function findPreferredLayer(probeResult: ProbeResponse): LayerInfo | null {
  const layers = probeResult.layers.filter((layer) => layer.importable !== false);
  if (layers.length === 0) {
    return null;
  }
  if (probeResult.selected_layer_id == null) {
    return layers[0];
  }
  return (
    layers.find(
      (layer) =>
        layer.layer_id === probeResult.selected_layer_id ||
        layer.name === String(probeResult.selected_layer_id),
    ) ?? layers[0]
  );
}

function isLikelyProtectedServiceFailure(message: string): boolean {
  const normalized = message.toLowerCase();
  return AUTH_ERROR_HINTS.some((hint) => normalized.includes(hint));
}

/** The commit door's expected-origin refusal, read off the raw `detail`
 *  ApiError carries in `body` rather than the translated message: the copy is
 *  locale-dependent, the code is not. */
function isOriginChangedError(err: unknown): boolean {
  if (!(err instanceof ApiError) || err.status !== 409) return false;
  const body = err.body;
  if (typeof body !== 'object' || body === null) return false;
  return (body as { code?: unknown }).code === 'origin_changed';
}

export function ReuploadDialog({
  dataset,
  open,
  onOpenChange,
  onReplaceComplete,
}: ReuploadDialogProps) {
  const { t } = useTranslation('dataset');
  // Raster datasets take the upload -> commit shortcut below and get
  // raster-specific copy in the preview/tracking steps.
  const isRaster = dataset.record_type === 'raster_dataset';
  const [step, setStep] = useState<ReuploadStep>('source-select');
  // The completed replacement matched the live data, so nothing was published.
  const [dataUnchanged, setDataUnchanged] = useState(false);
  const [sourceType, setSourceType] = useState<ReuploadSourceType | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  // The dataset's origin as of when this replacement was staged, captured beside
  // the job id and sent with the commit. Between staging and confirmation a
  // service or STAC re-upload can bind this dataset to a remote source; the
  // queued swap would rebind it to `upload` and sever that binding, so the
  // server refuses the commit when the origin it reads is no longer this one.
  const [stagedOriginKind, setStagedOriginKind] = useState<DatasetOrigin | null>(null);
  // Gate "Try Again" on a landed post-refusal refetch (see
  // handleConfirm's catch block), not just the refusal itself.
  const [isRefreshingOrigin, setIsRefreshingOrigin] = useState(false);
  const [originRefreshFailed, setOriginRefreshFailed] = useState(false);
  // Stale-completion guard for the refetch above — see
  // handleConfirm and resetState.
  const refreshGenerationRef = useRef(0);
  const [preview, setPreview] = useState<ReuploadPreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [serviceUrl, setServiceUrl] = useState(dataset.source_url ?? '');
  const [serviceToken, setServiceToken] = useState('');
  const [probeResult, setProbeResult] = useState<ProbeResponse | null>(null);
  const [selectedLayer, setSelectedLayer] = useState<LayerInfo | null>(null);
  const [allLayers, setAllLayers] = useState<NonNullable<ReuploadPreviewResponse['all_layers']>>([]);
  const [previousSourceLayer, setPreviousSourceLayer] = useState<string | null>(null);
  const [selectedFileLayer, setSelectedFileLayer] = useState<string | null>(null);

  const uploadMutation = useReuploadDataset();
  const previewMutation = useReuploadPreview();
  const servicePreviewMutation = useReuploadServicePreview();
  const commitMutation = useReuploadCommit();
  const { data: uploadConfig } = useUploadConfig();
  const queryClient = useQueryClient();

  const appendRetryGuidance = useCallback(
    (message: string) => {
      const guidance = t('reupload.service.retryNeedsToken', {
        defaultValue: 'If this source requires authentication, restart re-upload with a fresh access token.',
      });
      return message.includes(guidance) ? message : `${message} ${guidance}`;
    },
    [t],
  );

  const resetState = useCallback(() => {
    setStep('source-select');
    setSourceType(null);
    setJobId(null);
    setStagedOriginKind(null);
    setIsRefreshingOrigin(false);
    setOriginRefreshFailed(false);
    // Orphans any refetch still in flight from before this reset (e.g. the
    // dialog was closed mid-refetch).
    refreshGenerationRef.current += 1;
    setPreview(null);
    setDataUnchanged(false);
    setError(null);
    setSelectedFile(null);
    setServiceUrl(dataset.source_url ?? '');
    setServiceToken('');
    setProbeResult(null);
    setSelectedLayer(null);
    setAllLayers([]);
    setPreviousSourceLayer(null);
    setSelectedFileLayer(null);
  }, [dataset.source_url]);

  const trackingJobId = step === 'tracking' ? jobId : null;
  const { data: jobData } = useJobStatus(trackingJobId);
  const [quicklookJobId, setQuicklookJobId] = useState<string | null>(null);
  useRefreshSearchWhenQuicklookLands(quicklookJobId);

  useEffect(() => {
    if (step !== 'tracking' || !jobData) return;

    // The run ended too, possibly blocked for review, and run history is not polled.
    if (['complete', 'failed', 'cancelled'].includes(jobData.status)) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.datasets.refreshRunsPrefix(dataset.id),
      });
    }

    if (jobData.status === 'complete') {
      if (jobData.quicklook_pending) setQuicklookJobId(jobId);
      // The await below leaves this continuation in flight across a render
      // where `step`/`jobId` can change under it: closing the dialog
      // (resetState) or starting a second reupload before the first's
      // invalidation settles must not let this stale run apply its 'complete'
      // transition. `cancelled` is flipped by the effect cleanup, which fires on
      // any dependency change (including step leaving 'tracking').
      let cancelled = false;
      // invalidateQueries only SCHEDULES a refetch, so firing onReplaceComplete
      // without waiting raced the remount against the in-flight dataset-detail
      // refetch: a replacement with a different extent could remount using the
      // OLD bbox (DatasetMap fits the new one only on an explicit zoom-to-extent,
      // never on prop change). Await the detail refetch first so the remount
      // reads fresh bbox/tile_url/updated_at off the query cache.
      void (async () => {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: queryKeys.datasets.detail(dataset.id) }),
          queryClient.invalidateQueries({
            queryKey: queryKeys.datasets.versionsPrefix(dataset.id),
          }),
          queryClient.invalidateQueries({ queryKey: queryKeys.datasets.all }),
          queryClient.invalidateQueries({ queryKey: queryKeys.search.all }),
        ]);
        let unchanged = false;
        try {
          const history = await queryClient.fetchQuery({
            queryKey: queryKeys.datasets.refreshRuns(dataset.id, 0, 10),
            queryFn: () => getDatasetRefreshRuns(dataset.id, { skip: 0, limit: 10 }),
          });
          unchanged = history.runs.some(
            (run) => run.ingest_job_id === jobId && run.verification?.data_unchanged === true,
          );
        } catch {
          // Without the run the ordinary completion message stands.
        }
        if (cancelled) return;
        setDataUnchanged(unchanged);
        // A raster's tile URL is a fixed per-dataset route, not versioned by
        // content, so invalidating the dataset query alone leaves the hero map's
        // MapLibre raster source serving the old tiles until something remounts
        // it. Vector tiles are cache-busted through `tileVersion`
        // (dataset.updated_at), which this invalidation already refreshes.
        if (isRaster) {
          onReplaceComplete?.();
        }
        setStep('complete');
        toast.success(t(unchanged ? 'reupload.toastUnchanged' : 'reupload.toastSuccess'));
      })();
      return () => {
        cancelled = true;
      };
    } else if (jobData.status === 'failed') {
      const reason = jobData.error_message;
      const message = reason
        ? describeFailureReason(reason, t('reupload.jobFailed'), jobData.error_code)
        : t('reupload.jobFailed');
      if (jobData.error_code === 'review_required') {
        // A hold waits on a person's decision; retrying here would not change it.
        setError(message);
        setStep('held');
        return;
      }
      setError(
        sourceType === 'service_url'
          ? appendRetryGuidance(message)
          : message,
      );
      setStep('error');
    } else if (jobData.status === 'cancelled') {
      // Cancel is a reachable terminal status. Without this branch the dialog
      // would sit on the tracking spinner forever, since polling has stopped.
      // No retry guidance: a deliberate cancel and a sweep-abandoned upload both
      // just start over.
      setError(fixedFailureReason(jobData.error_code) ?? t('reupload.jobCancelled'));
      setStep('error');
    }
  }, [step, jobId, jobData, dataset.id, queryClient, sourceType, isRaster, onReplaceComplete, appendRetryGuidance, t]);

  const handleSelectSource = useCallback((nextSource: ReuploadSourceType) => {
    setSourceType(nextSource);
    setError(null);
    setPreview(null);
    setJobId(null);
    setStagedOriginKind(null);
    setProbeResult(null);
    setSelectedLayer(null);
    if (nextSource === 'file') {
      setSelectedFile(null);
      setStep('file-select');
      return;
    }
    setStep('service-connect');
  }, []);

  const handleUpload = useCallback(
    async (file: File) => {
      setSourceType('file');
      setSelectedFile(file);
      setError(null);
      setStep('uploading');
      try {
        let uploadResult: { job_id: string };
        if (uploadConfig?.presigned_uploads) {
          uploadResult = await reuploadPresigned(dataset.id, file);
        } else {
          uploadResult = await uploadMutation.mutateAsync({
            datasetId: dataset.id,
            file,
          });
        }
        setJobId(uploadResult.job_id);
        setStagedOriginKind(dataset.origin ?? null);

        // Raster has no schema-preview step: the preview endpoint returns 400 for
        // raster by design (nothing for ogrinfo to diff a COG against). Skip to
        // the confirm gate.
        if (isRaster) {
          setStep('preview');
          return;
        }

        const previewResult = await previewMutation.mutateAsync({
          datasetId: dataset.id,
          jobId: uploadResult.job_id,
        });

        // Show the selecting-file-layer step when the file has >1 layers
        // (multi-layer GPKG) or previous_source_layer is set but missing from
        // the new file's layers (even 1-layer files surface the mismatch so
        // users confirm). Otherwise skip it.
        const layers = previewResult.all_layers ?? [];
        const prevLayer = previewResult.previous_source_layer ?? null;
        const prevLayerMissing = prevLayer !== null && !layers.some((l) => l.name === prevLayer);
        const needsLayerSelect = layers.length > 1 || (layers.length >= 1 && prevLayerMissing);
        if (needsLayerSelect) {
          setAllLayers(layers);
          setPreviousSourceLayer(prevLayer);
          // Default to previous source_layer if it appears in the new file.
          // If absent (mismatch case), set to null — user MUST explicitly select.
          const isPresent = prevLayer !== null && layers.some((l) => l.name === prevLayer);
          setSelectedFileLayer(isPresent ? prevLayer : null);
          setStep('selecting-file-layer');
        } else {
          setPreview(previewResult);
          setStep('preview');
        }
      } catch (err) {
        setError(
          err instanceof Error ? err.message : t('reupload.uploadFailed'),
        );
        setStep('error');
      }
    },
    [dataset.id, dataset.origin, isRaster, uploadMutation, previewMutation, uploadConfig?.presigned_uploads, t],
  );

  const handleServiceConnect = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const trimmedUrl = serviceUrl.trim();
      if (!trimmedUrl) {
        return;
      }

      setSourceType('service_url');
      setError(null);
      setProbeResult(null);
      setSelectedLayer(null);
      setStep('probing');

      try {
        const token = serviceToken.trim() || undefined;
        const result = await probeService(trimmedUrl, token);
        setProbeResult(result);
        setSelectedLayer(findPreferredLayer(result));
        setStep('layer-select');
      } catch (err) {
        const message = err instanceof ApiError
          ? err.message
          : t('reupload.service.connectFailed', {
            defaultValue: 'Failed to connect to service.',
          });
        setError(
          isLikelyProtectedServiceFailure(message)
            ? appendRetryGuidance(message)
            : message,
        );
        setStep('service-connect');
      }
    },
    [serviceToken, serviceUrl, t, appendRetryGuidance],
  );

  const handleLayerPreview = useCallback(
    async (layer: LayerInfo) => {
      if (!probeResult) {
        return;
      }
      setError(null);
      setSelectedLayer(layer);
      setStep('previewing');

      try {
        const token = serviceToken.trim() || undefined;
        const previewResult = await servicePreviewMutation.mutateAsync({
          datasetId: dataset.id,
          request: {
            url: probeResult.url,
            service_type: probeResult.service_type,
            layer_name: layer.name,
            layer_title: layer.title,
            layer_id: layer.layer_id,
            token,
            object_id_field: layer.object_id_field,
          },
        });
        setJobId(previewResult.job_id);
        setStagedOriginKind(dataset.origin ?? null);
        setPreview(previewResult);
        setStep('preview');
      } catch (err) {
        const message = err instanceof ApiError
          ? err.message
          : t('reupload.service.previewFailed', {
            defaultValue: 'Failed to preview selected layer.',
          });
        setError(
          isLikelyProtectedServiceFailure(message)
            ? appendRetryGuidance(message)
            : message,
        );
        setStep('layer-select');
      }
    },
    [dataset.id, dataset.origin, probeResult, servicePreviewMutation, serviceToken, t, appendRetryGuidance],
  );

  // File-path layer selection; mirrors handleLayerPreview (service path) on the
  // file-path state machine.
  const handleFileLayerPreview = useCallback(
    async (layerName: string) => {
      if (!jobId) {
        // jobId must be set by handleUpload before this step is reachable
        throw new Error('No job ID available for file layer preview');
      }
      setError(null);
      setSelectedFileLayer(layerName);
      setStep('previewing');
      try {
        const previewResult = await previewMutation.mutateAsync({
          datasetId: dataset.id,
          jobId,
          layerName,
        });
        setPreview(previewResult);
        setStep('preview');
      } catch (err) {
        const message = err instanceof Error
          ? err.message
          : t('reupload.uploadFailed');
        setError(message);
        setStep('selecting-file-layer');
      }
    },
    [dataset.id, jobId, previewMutation, t],
  );

  const handleConfirm = useCallback(async () => {
    if (!jobId) return;
    setStep('committing');
    try {
      const token = sourceType === 'service_url' && serviceToken.trim()
        ? serviceToken.trim()
        : undefined;
      // Pass selectedFileLayer so commit persists the user-chosen layer
      await commitMutation.mutateAsync({
        datasetId: dataset.id,
        jobId,
        token,
        ...(selectedFileLayer !== null ? { layerName: selectedFileLayer } : {}),
        // The origin as of staging, not as of now: `dataset` is a live query
        // result, so reading it here would re-read the very change this
        // condition exists to catch and always agree with the server.
        expectedOriginKind: stagedOriginKind,
        // The changes this dialog showed, acknowledged by confirming.
        reviewFingerprint: preview?.review_fingerprint,
      });
      setStep('tracking');
    } catch (err) {
      const message = err instanceof Error ? err.message : t('reupload.commitFailed');
      setError(
        sourceType === 'service_url'
          ? appendRetryGuidance(message)
          : message,
      );
      setStep('error');

      // dataset.origin is stale; wait for a landed fetch
      // (fetchQuery, not refetchQueries, which resolves early when paused)
      // before re-enabling retry.
      if (isOriginChangedError(err)) {
        const generation = ++refreshGenerationRef.current;
        setIsRefreshingOrigin(true);
        try {
          // fetchQuery dedupes onto an
          // already in-flight fetch for this key (e.g. a window-focus
          // refetch) instead of running ours, so cancel it first.
          await queryClient.cancelQueries({ queryKey: queryKeys.datasets.detail(dataset.id) });
          await queryClient.fetchQuery({
            queryKey: queryKeys.datasets.detail(dataset.id),
            queryFn: () => getDataset(dataset.id),
            staleTime: 0,
          });
        } catch {
          // A reset (dialog closed) or a newer attempt
          // bumped the generation — this completion is orphaned, ignore it.
          if (generation === refreshGenerationRef.current) {
            setOriginRefreshFailed(true);
            setError(
              t('reupload.originRefreshFailed', {
                defaultValue:
                  "Could not refresh the dataset's info after this conflict. Reload the page and try again.",
              }),
            );
          }
        } finally {
          if (generation === refreshGenerationRef.current) {
            setIsRefreshingOrigin(false);
          }
        }
      }
    }
  }, [dataset.id, jobId, stagedOriginKind, sourceType, preview, serviceToken, selectedFileLayer, commitMutation, queryClient, appendRetryGuidance, t]);

  const handleRetry = useCallback(() => {
    setError(null);
    setPreview(null);
    setJobId(null);
    setStagedOriginKind(null);
    // Reset for a second origin_changed round in this session.
    setIsRefreshingOrigin(false);
    setOriginRefreshFailed(false);
    if (sourceType === 'service_url') {
      setProbeResult(null);
      setSelectedLayer(null);
      setServiceToken('');
      setStep('service-connect');
      return;
    }
    if (sourceType === 'file') {
      setSelectedFile(null);
      setStep('file-select');
      return;
    }
    resetState();
  }, [resetState, sourceType]);

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen) {
        resetState();
      }
      onOpenChange(nextOpen);
    },
    [onOpenChange, resetState],
  );

  const reuploadExtensions = useMemo(
    () => uploadConfig?.allowed_extensions
      ?.split(',')
      .map((extension) => extension.trim())
      .filter((extension) => {
        if (!extension) return false;
        const normalized = extension.toLowerCase();
        if (normalized === VRT_EXTENSION || KIND_ONLY_EXTENSIONS.has(normalized)) return false;
        // Raster reupload offers only raster formats; every other reupload
        // (vector/table) offers everything except raster/VRT.
        const isRasterExtension = RASTER_REUPLOAD_EXTENSIONS.has(normalized);
        return isRaster ? isRasterExtension : !isRasterExtension;
      }),
    [uploadConfig?.allowed_extensions, isRaster],
  );
  const reuploadAccept = useMemo(
    () => reuploadExtensions ? buildAcceptMap(reuploadExtensions) : undefined,
    [reuploadExtensions],
  );
  const reuploadBadges = useMemo(
    () => reuploadExtensions ? deriveFormatBadges(reuploadExtensions) : [],
    [reuploadExtensions],
  );

  const { getRootProps, getInputProps, isDragActive, isDragReject } =
    useDropzone({
      accept: reuploadAccept,
      maxFiles: 1,
      multiple: false,
      disabled: step !== 'file-select',
      onDrop: (accepted) => {
        if (accepted.length > 0) {
          void handleUpload(accepted[0]);
        }
      },
    });

  const hasWarning =
    preview &&
    (preview.schema_diff.columns_removed.length > 0 ||
      preview.schema_diff.type_changes.length > 0);

  // Advisory banner — derived client-side, distinct from hasWarning
  const schemaChangeCount =
    (preview?.schema_diff.columns_added.length ?? 0) +
    (preview?.schema_diff.columns_removed.length ?? 0);
  const hasSchemaChange = schemaChangeCount > 0;

  const descriptions: Record<ReuploadStep, string> = {
    'source-select': t('reupload.descriptions.sourceSelect', {
      defaultValue: 'Choose a source for this re-upload.',
    }),
    'file-select': t('reupload.descriptions.select'),
    'service-connect': t('reupload.descriptions.serviceConnect', {
      defaultValue: 'Connect to a service and choose a layer.',
    }),
    probing: t('reupload.service.connecting', {
      defaultValue: 'Connecting to service...',
    }),
    'layer-select': t('reupload.descriptions.layerSelect', {
      defaultValue: 'Choose the service layer to preview.',
    }),
    'selecting-file-layer': t('reupload.descriptions.fileLayerSelect', {
      defaultValue: 'Choose the layer from this multi-layer file.',
    }),
    uploading: t('reupload.descriptions.uploading'),
    previewing: t('reupload.service.previewing', {
      defaultValue: 'Preparing re-upload preview...',
    }),
    // Raster has no schema diff to review, so the preview/tracking copy
    // describes the COG conversion instead.
    preview: isRaster
      ? t('reupload.raster.previewDescription', {
        defaultValue: 'Confirm to replace the raster.',
      })
      : t('reupload.descriptions.preview'),
    committing: t('reupload.descriptions.committing'),
    tracking: isRaster
      ? t('reupload.raster.trackingDescription', {
        defaultValue: 'Converting to Cloud Optimized GeoTIFF. This can take several minutes.',
      })
      : t('reupload.descriptions.tracking'),
    complete: dataUnchanged
      ? t('reupload.descriptions.unchanged')
      : t('reupload.descriptions.complete'),
    held: t('reupload.descriptions.held'),
    error: t('reupload.descriptions.error'),
  };

  const activeSourceLabel = sourceType === 'service_url'
    ? t('reupload.sourceSelector.service', { defaultValue: 'Service URL' })
    : t('reupload.sourceSelector.file', { defaultValue: 'File' });

  const previewSourceLabel = sourceType === 'service_url'
    ? t('reupload.service.layerLabel', { defaultValue: 'Layer:' })
    : selectedFileLayer !== null
      ? t('reupload.service.layerLabel', { defaultValue: 'Layer:' })
      : t('reupload.file');

  const previewSourceValue = sourceType === 'service_url'
    ? (selectedLayer ? humanizeLayerName(selectedLayer) : (preview?.layer_name ?? t('common:unknown')))
    : selectedFileLayer !== null
      ? selectedFileLayer
      : selectedFile?.name;

  if (!isRaster && !recordTypeCapabilities(dataset.record_type).featureTable) return null;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('reupload.title')}</DialogTitle>
          <DialogDescription>{descriptions[step]}</DialogDescription>
        </DialogHeader>

        {step === 'source-select' && (
          <div className="space-y-4" data-testid="reupload-source-selector">
            <p className="text-sm text-muted-foreground">
              {/* Raster has no service path — nothing
                  fetches a GeoTIFF from a feature service, and the backend
                  refuses a raster service-preview outright — so raster
                  never sees the Service URL option below. */}
              {isRaster
                ? t('reupload.raster.sourceSelectHelpText', {
                  defaultValue: 'Select a replacement raster file.',
                })
                : t('reupload.sourceSelector.helpText', {
                  defaultValue: 'Select whether to re-upload from a local file or a service URL.',
                })}
            </p>
            <div className={cn('grid gap-2', !isRaster && 'sm:grid-cols-2')}>
              <Button
                type="button"
                variant="outline"
                onClick={() => handleSelectSource('file')}
              >
                <Upload className="me-2 h-4 w-4" />
                {t('reupload.sourceSelector.file', { defaultValue: 'File' })}
              </Button>
              {!isRaster && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => handleSelectSource('service_url')}
                >
                  <Globe className="me-2 h-4 w-4" />
                  {t('reupload.sourceSelector.service', { defaultValue: 'Service URL' })}
                </Button>
              )}
            </div>
          </div>
        )}

        {step === 'file-select' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">
                {t('reupload.sourceSelector.active', {
                  source: activeSourceLabel,
                  defaultValue: 'Source: {{source}}',
                })}
              </p>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={resetState}
              >
                {t('common:back')}
              </Button>
            </div>
            <div
              {...getRootProps({ 'data-testid': 'reupload-file-dropzone' })}
              className={cn(
                'flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 text-center transition-colors',
                isDragReject && 'border-destructive bg-destructive/5',
                isDragActive &&
                  !isDragReject &&
                  'border-primary bg-primary/5',
                !isDragActive &&
                  !isDragReject &&
                  'border-muted-foreground/25 hover:border-muted-foreground/50',
              )}
            >
              <input {...getInputProps()} />
              <Upload className="mb-3 h-10 w-10 text-muted-foreground" />
              <p className="text-sm font-medium">
                {t('reupload.dropzone')}
              </p>
              {reuploadBadges.length > 0 && (
                <div className="mt-2 flex flex-wrap justify-center gap-1">
                  {reuploadBadges.map((ext) => (
                    <span
                      key={ext}
                      className="inline-flex items-center rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground"
                    >
                      {ext}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {step === 'service-connect' && (
          <div className="space-y-4">
            <p className="text-xs text-muted-foreground">
              {t('reupload.sourceSelector.active', {
                source: activeSourceLabel,
                defaultValue: 'Source: {{source}}',
              })}
            </p>
            <form onSubmit={handleServiceConnect} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="reupload-service-url">
                  {t('reupload.service.urlLabel', { defaultValue: 'Service URL' })}
                </Label>
                <Input
                  id="reupload-service-url"
                  type="url"
                  placeholder={t('reupload.service.urlPlaceholder', {
                    defaultValue: 'https://example.com/wfs',
                  })}
                  value={serviceUrl}
                  onChange={(event) => setServiceUrl(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="reupload-service-token">
                  {t('reupload.service.tokenLabel', { defaultValue: 'Access Token (optional)' })}
                </Label>
                <Input
                  id="reupload-service-token"
                  type="password"
                  placeholder={t('reupload.service.tokenPlaceholder', {
                    defaultValue: 'Bearer token or API key',
                  })}
                  value={serviceToken}
                  onChange={(event) => setServiceToken(event.target.value)}
                  // Request-only service token, not a login credential: opt out
                  // of password managers explicitly.
                  autoComplete="new-password"
                  data-1p-ignore
                  data-lpignore="true"
                  data-bwignore
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <DialogFooter>
                <Button type="button" variant="outline" onClick={resetState}>
                  {t('common:back')}
                </Button>
                <Button type="submit" disabled={!serviceUrl.trim()}>
                  <Globe className="me-2 h-4 w-4" />
                  {t('reupload.service.connect', { defaultValue: 'Connect' })}
                </Button>
              </DialogFooter>
            </form>
          </div>
        )}

        {step === 'probing' && (
          <div className="flex flex-col items-center justify-center gap-3 py-8">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              {t('reupload.service.connecting', {
                defaultValue: 'Connecting to service...',
              })}
            </p>
          </div>
        )}

        {step === 'layer-select' && probeResult && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">
                {t('reupload.service.layerStep', { defaultValue: 'Select a layer' })}
              </p>
              <Badge variant="secondary">{probeResult.service_type}</Badge>
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}

            {probeResult.layers.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t('reupload.service.emptyState', {
                  defaultValue: 'No layers were found for this service.',
                })}
              </p>
            ) : (
              <div className="max-h-64 overflow-y-auto rounded-md border">
                <Table aria-label={t('reupload.service.tableLabel', { defaultValue: 'Service layers' })}>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('reupload.service.columns.name', { defaultValue: 'Name' })}</TableHead>
                      <TableHead>{t('reupload.service.columns.geometry', { defaultValue: 'Geometry' })}</TableHead>
                      <TableHead>{t('reupload.service.columns.featureCount', { defaultValue: 'Features' })}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {probeResult.layers.map((layer) => {
                      const unsupported = layer.importable === false;
                      return (
                      <TableRow
                        key={`${layer.name}-${String(layer.layer_id)}`}
                        aria-disabled={unsupported || undefined}
                        className={cn(
                          unsupported ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
                          selectedLayer?.name === layer.name && 'bg-accent',
                        )}
                        onClick={unsupported ? undefined : () => setSelectedLayer(layer)}
                      >
                        <TableCell className="max-w-[300px] truncate">
                          {humanizeLayerName(layer)}
                          {unsupported && (
                            <span className="block truncate text-2xs text-muted-foreground">
                              {t('reupload.service.unsupportedLayerType', {
                                type: layer.source_layer_type ?? layer.layer_type,
                              })}
                            </span>
                          )}
                        </TableCell>
                        <TableCell>
                          {layer.geometry_type ? getGeometryTypeLabel(t, layer.geometry_type) : '-'}
                        </TableCell>
                        <TableCell>
                          {layer.feature_count !== null
                            ? formatNumber(layer.feature_count)
                            : '-'}
                        </TableCell>
                      </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setError(null);
                  setSelectedLayer(null);
                  setStep('service-connect');
                }}
              >
                {t('common:back')}
              </Button>
              <Button
                onClick={() => selectedLayer && void handleLayerPreview(selectedLayer)}
                disabled={selectedLayer === null}
              >
                {t('reupload.service.previewLayer', { defaultValue: 'Preview Layer' })}
              </Button>
            </DialogFooter>
          </div>
        )}

        {/* File-path layer-select step for multi-layer GPKG files */}
        {step === 'selecting-file-layer' && (
          <div className="space-y-4" data-testid="reupload-file-layer-select">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">
                {t('reupload.fileLayer.layerStep', { defaultValue: 'Select a layer' })}
              </p>
            </div>
            {/* Warn when previous source_layer is not in the new file's layers */}
            {previousSourceLayer && !allLayers.find((l) => l.name === previousSourceLayer) && (
              <p className="rounded-md border border-warning/50 bg-warning/10 p-3 text-sm text-warning">
                {t('reupload.fileLayer.missingLayerWarning', {
                  layer: previousSourceLayer,
                  defaultValue: `Original layer '{{layer}}' is not present in the new file. Pick a replacement to continue.`,
                })}
              </p>
            )}
            {error && <p className="text-sm text-destructive">{error}</p>}
            <div className="max-h-64 overflow-y-auto rounded-md border">
              <Table aria-label={t('reupload.fileLayer.tableLabel', { defaultValue: 'File layers' })}>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('reupload.service.columns.name', { defaultValue: 'Name' })}</TableHead>
                    <TableHead>{t('reupload.service.columns.geometry', { defaultValue: 'Geometry' })}</TableHead>
                    <TableHead>{t('reupload.service.columns.featureCount', { defaultValue: 'Features' })}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {allLayers.map((layer) => (
                    <TableRow
                      key={layer.name}
                      className={cn(
                        'cursor-pointer',
                        selectedFileLayer === layer.name && 'bg-accent',
                      )}
                      onClick={() => setSelectedFileLayer(layer.name)}
                    >
                      <TableCell className="max-w-[300px] truncate">{layer.name}</TableCell>
                      <TableCell>-</TableCell>
                      <TableCell>
                        {layer.feature_count !== null ? formatNumber(layer.feature_count) : '—'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setError(null);
                  setSelectedFileLayer(null);
                  setAllLayers([]);
                  setPreviousSourceLayer(null);
                  setStep('file-select');
                }}
              >
                {t('common:back')}
              </Button>
              <Button
                onClick={() => selectedFileLayer && void handleFileLayerPreview(selectedFileLayer)}
                disabled={selectedFileLayer === null}
              >
                {t('reupload.fileLayer.previewLayer', { defaultValue: 'Preview Layer' })}
              </Button>
            </DialogFooter>
          </div>
        )}

        {(step === 'uploading' || step === 'previewing') && (
          <div className="flex flex-col items-center justify-center gap-3 py-8">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              {step === 'uploading'
                ? t('reupload.uploadingMessage')
                : t('reupload.service.previewing', {
                  defaultValue: 'Preparing re-upload preview...',
                })}
            </p>
          </div>
        )}

        {/* Raster has no preview payload to render (schema-preview is
            skipped in handleUpload above), so this step renders on isRaster
            alone rather than waiting for `preview`. */}
        {step === 'preview' && (preview || isRaster) && (
          <div className="space-y-4">
            {/* File-path multi-layer shows File + Layer lines; single-layer or service shows one line */}
            {sourceType === 'file' && selectedFileLayer !== null ? (
              <>
                <p className="text-sm">
                  {t('reupload.file')}{' '}
                  <span className="font-medium">{selectedFile?.name}</span>
                </p>
                <p className="text-sm">
                  {t('reupload.service.layerLabel', { defaultValue: 'Layer:' })}{' '}
                  <span className="font-medium">{selectedFileLayer}</span>
                </p>
              </>
            ) : (
              <p className="text-sm">
                {previewSourceLabel}{' '}
                <span className="font-medium">{previewSourceValue}</span>
              </p>
            )}
            {isRaster ? (
              <p
                className="rounded-md border border-muted-foreground/20 bg-muted/40 p-3 text-sm text-muted-foreground"
                data-testid="raster-preview-note"
              >
                {t('reupload.raster.previewNote', {
                  defaultValue: 'Raster re-uploads skip schema comparison. Confirming starts a Cloud Optimized GeoTIFF conversion, which can take several minutes.',
                })}
              </p>
            ) : preview && (
              <>
                {/* Schema-change advisory banner (informational, distinct from hasWarning) */}
                {hasSchemaChange && (
                  <div
                    className="rounded-md border border-warning/30 bg-warning/10 p-3 text-sm"
                    data-testid="schema-change-advisory"
                  >
                    {t('reupload.schemaChangeAdvisory', {
                      added: preview.schema_diff.columns_added.length,
                      removed: preview.schema_diff.columns_removed.length,
                    })}
                  </div>
                )}
                <SchemaDiffView schemaDiff={preview.schema_diff} />
                {(preview.review_reasons?.length ?? 0) > 0 && (
                  <ul
                    className="space-y-1 rounded-md border border-warning/30 bg-warning/10 p-3 text-sm"
                    aria-label={t('reupload.reviewReasonsLabel')}
                  >
                    {preview.review_reasons?.map((reason) => (
                      <li key={reason}>{t(`sourcePanel.refresh.history.reason.${reason}`)}</li>
                    ))}
                  </ul>
                )}
                {hasWarning && (
                  <p className="text-sm text-warning">
                    {t('reupload.warningSchemaChanges')}
                  </p>
                )}
              </>
            )}
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => handleOpenChange(false)}
              >
                {t('common:cancel')}
              </Button>
              <Button onClick={() => void handleConfirm()}>
                {t('reupload.confirmReupload')}
              </Button>
            </DialogFooter>
          </div>
        )}

        {step === 'committing' && (
          <div className="flex flex-col items-center justify-center gap-3 py-8">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              {t('reupload.committingMessage')}
            </p>
          </div>
        )}

        {step === 'tracking' && (
          <div className="flex flex-col items-center justify-center gap-3 py-8">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              {/* COG conversion runs on the raster queue and takes
                  minutes, not the seconds a vector reupload takes. */}
              {isRaster
                ? t('reupload.raster.processingMessage', {
                  defaultValue: 'Converting to Cloud Optimized GeoTIFF...',
                })
                : t('reupload.processingMessage')}
            </p>
            <p className="text-xs text-muted-foreground">
              {/* Job tracking (useJobStatus polling)
                  stops once the dialog closes and steps away from
                  'tracking', so this must not promise closing is safe. */}
              {isRaster
                ? t('reupload.raster.trackingBackground', {
                  defaultValue: 'This can take a few minutes. Keep this dialog open until the conversion finishes.',
                })
                : t('reupload.trackingBackground')}
            </p>
          </div>
        )}

        {step === 'complete' && (
          <div className="flex flex-col items-center justify-center gap-3 py-8">
            <CheckCircle2 className="h-10 w-10 text-success" />
            <p className="text-sm font-medium">
              {t(dataUnchanged ? 'reupload.unchangedTitle' : 'reupload.completeTitle')}
            </p>
            <p className="text-xs text-muted-foreground">
              {t(dataUnchanged ? 'reupload.unchangedMessage' : 'reupload.completeMessage')}
            </p>
            <DialogFooter className="w-full">
              <Button onClick={() => handleOpenChange(false)}>{t('common:close')}</Button>
            </DialogFooter>
          </div>
        )}

        {step === 'held' && (
          <div className="flex flex-col items-center justify-center gap-3 py-8" data-testid="reupload-held">
            <AlertTriangle className="h-10 w-10 text-warning" />
            <p className="text-sm font-medium">{error}</p>
            <DialogFooter className="w-full">
              <Button onClick={() => handleOpenChange(false)}>{t('common:close')}</Button>
            </DialogFooter>
          </div>
        )}

        {step === 'error' && (
          <div className="flex flex-col items-center justify-center gap-3 py-8">
            <AlertCircle className="h-10 w-10 text-destructive" />
            <p className="text-sm font-medium text-destructive">
              {error ?? t('reupload.errorFallback')}
            </p>
            <DialogFooter className="w-full">
              {/* Disabled while the origin refetch is pending,
                  and permanently if it fails. */}
              <Button
                variant="outline"
                onClick={handleRetry}
                disabled={isRefreshingOrigin || originRefreshFailed}
                data-testid="reupload-try-again"
              >
                {isRefreshingOrigin
                  ? t('reupload.refreshingOrigin', { defaultValue: 'Refreshing...' })
                  : t('reupload.tryAgain')}
              </Button>
              <Button onClick={() => handleOpenChange(false)}>{t('common:close')}</Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
