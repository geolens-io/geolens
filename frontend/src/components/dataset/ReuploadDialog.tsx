import { useState, useEffect, useCallback, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useDropzone } from 'react-dropzone';
import { useQueryClient } from '@tanstack/react-query';
import {
  useReuploadDataset,
  useReuploadPreview,
  useReuploadServicePreview,
  useReuploadCommit,
} from '@/hooks/use-dataset';
import { useJobStatus, useUploadConfig } from '@/hooks/use-ingest';
import { buildAcceptMap } from '@/lib/file-utils';
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
import { Globe, Loader2, CheckCircle2, AlertCircle, Upload } from 'lucide-react';
import { toast } from 'sonner';
import { probeService } from '@/api/ingest';
import { ApiError } from '@/api/client';
import { reuploadPresigned } from '@/api/datasets';
import { getGeometryTypeLabel } from '@/i18n/labels';
import type {
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
  | 'uploading'
  | 'previewing'
  | 'preview'
  | 'committing'
  | 'tracking'
  | 'complete'
  | 'error';


const AUTH_ERROR_HINTS = [
  '401',
  '403',
  'unauthorized',
  'forbidden',
  'token',
  'auth',
];

interface ReuploadDialogProps {
  dataset: DatasetResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function humanizeLayerName(layer: LayerInfo): string {
  if (layer.title) return layer.title;
  return layer.name.replace(/_/g, ' ');
}

function findPreferredLayer(probeResult: ProbeResponse): LayerInfo | null {
  if (probeResult.layers.length === 0) {
    return null;
  }
  if (probeResult.selected_layer_id == null) {
    return probeResult.layers[0];
  }
  return (
    probeResult.layers.find(
      (layer) =>
        layer.layer_id === probeResult.selected_layer_id ||
        layer.name === String(probeResult.selected_layer_id),
    ) ?? probeResult.layers[0]
  );
}

function isLikelyProtectedServiceFailure(message: string): boolean {
  const normalized = message.toLowerCase();
  return AUTH_ERROR_HINTS.some((hint) => normalized.includes(hint));
}

export function ReuploadDialog({
  dataset,
  open,
  onOpenChange,
}: ReuploadDialogProps) {
  const { t } = useTranslation('dataset');
  const [step, setStep] = useState<ReuploadStep>('source-select');
  const [sourceType, setSourceType] = useState<ReuploadSourceType | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [preview, setPreview] = useState<ReuploadPreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [serviceUrl, setServiceUrl] = useState(dataset.source_url ?? '');
  const [serviceToken, setServiceToken] = useState('');
  const [probeResult, setProbeResult] = useState<ProbeResponse | null>(null);
  const [selectedLayer, setSelectedLayer] = useState<LayerInfo | null>(null);

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
    setPreview(null);
    setError(null);
    setSelectedFile(null);
    setServiceUrl(dataset.source_url ?? '');
    setServiceToken('');
    setProbeResult(null);
    setSelectedLayer(null);
  }, [dataset.source_url]);

  // Only poll when tracking
  const trackingJobId = step === 'tracking' ? jobId : null;
  const { data: jobData } = useJobStatus(trackingJobId);

  // Watch job status for completion
  useEffect(() => {
    if (step !== 'tracking' || !jobData) return;

    if (jobData.status === 'complete') {
      queryClient.invalidateQueries({ queryKey: ['dataset', dataset.id] });
      queryClient.invalidateQueries({
        queryKey: ['dataset-versions', dataset.id],
      });
      queryClient.invalidateQueries({ queryKey: ['datasets'] });
      queryClient.invalidateQueries({ queryKey: ['search'] });
      setStep('complete');
      toast.success(t('reupload.toastSuccess'));
    } else if (jobData.status === 'failed') {
      const message = jobData.error_message ?? t('reupload.jobFailed');
      setError(
        sourceType === 'service_url'
          ? appendRetryGuidance(message)
          : message,
      );
      setStep('error');
    }
  }, [step, jobData, dataset.id, queryClient, sourceType, appendRetryGuidance, t]);

  const handleSelectSource = useCallback((nextSource: ReuploadSourceType) => {
    setSourceType(nextSource);
    setError(null);
    setPreview(null);
    setJobId(null);
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
        const previewResult = await previewMutation.mutateAsync({
          datasetId: dataset.id,
          jobId: uploadResult.job_id,
        });
        setPreview(previewResult);
        setStep('preview');
      } catch (err) {
        setError(
          err instanceof Error ? err.message : t('reupload.uploadFailed'),
        );
        setStep('error');
      }
    },
    [dataset.id, uploadMutation, previewMutation, uploadConfig?.presigned_uploads, t],
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
    [dataset.id, probeResult, servicePreviewMutation, serviceToken, t, appendRetryGuidance],
  );

  const handleConfirm = useCallback(async () => {
    if (!jobId) return;
    setStep('committing');
    try {
      const token = sourceType === 'service_url' && serviceToken.trim()
        ? serviceToken.trim()
        : undefined;
      await commitMutation.mutateAsync({
        datasetId: dataset.id,
        jobId,
        token,
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
    }
  }, [dataset.id, jobId, sourceType, serviceToken, commitMutation, appendRetryGuidance, t]);

  const handleRetry = useCallback(() => {
    setError(null);
    setPreview(null);
    setJobId(null);
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

  const reuploadAccept = uploadConfig?.allowed_extensions
    ? buildAcceptMap(uploadConfig.allowed_extensions.split(',').map(e => e.trim()).filter(Boolean))
    : undefined;

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
    uploading: t('reupload.descriptions.uploading'),
    previewing: t('reupload.service.previewing', {
      defaultValue: 'Preparing re-upload preview...',
    }),
    preview: t('reupload.descriptions.preview'),
    committing: t('reupload.descriptions.committing'),
    tracking: t('reupload.descriptions.tracking'),
    complete: t('reupload.descriptions.complete'),
    error: t('reupload.descriptions.error'),
  };

  const activeSourceLabel = sourceType === 'service_url'
    ? t('reupload.sourceSelector.service', { defaultValue: 'Service URL' })
    : t('reupload.sourceSelector.file', { defaultValue: 'File' });

  const previewSourceLabel = sourceType === 'service_url'
    ? t('reupload.service.layerLabel', { defaultValue: 'Layer:' })
    : t('reupload.file');

  const previewSourceValue = sourceType === 'service_url'
    ? (selectedLayer ? humanizeLayerName(selectedLayer) : (preview?.layer_name ?? t('common:unknown')))
    : selectedFile?.name;

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
              {t('reupload.sourceSelector.helpText', {
                defaultValue: 'Select whether to re-upload from a local file or a service URL.',
              })}
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => handleSelectSource('file')}
              >
                <Upload className="mr-2 h-4 w-4" />
                {t('reupload.sourceSelector.file', { defaultValue: 'File' })}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => handleSelectSource('service_url')}
              >
                <Globe className="mr-2 h-4 w-4" />
                {t('reupload.sourceSelector.service', { defaultValue: 'Service URL' })}
              </Button>
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
              <p className="mt-1 text-xs text-muted-foreground">
                {t('reupload.acceptedFormats')}
              </p>
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
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <DialogFooter>
                <Button type="button" variant="outline" onClick={resetState}>
                  {t('common:back')}
                </Button>
                <Button type="submit" disabled={!serviceUrl.trim()}>
                  <Globe className="mr-2 h-4 w-4" />
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
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('reupload.service.columns.name', { defaultValue: 'Name' })}</TableHead>
                      <TableHead>{t('reupload.service.columns.geometry', { defaultValue: 'Geometry' })}</TableHead>
                      <TableHead>{t('reupload.service.columns.featureCount', { defaultValue: 'Features' })}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {probeResult.layers.map((layer) => (
                      <TableRow
                        key={`${layer.name}-${String(layer.layer_id)}`}
                        className={cn(
                          'cursor-pointer',
                          selectedLayer?.name === layer.name && 'bg-accent',
                        )}
                        onClick={() => setSelectedLayer(layer)}
                      >
                        <TableCell className="max-w-[300px] truncate">{humanizeLayerName(layer)}</TableCell>
                        <TableCell>
                          {layer.geometry_type ? getGeometryTypeLabel(t, layer.geometry_type) : '-'}
                        </TableCell>
                        <TableCell>
                          {layer.feature_count !== null
                            ? layer.feature_count.toLocaleString()
                            : '-'}
                        </TableCell>
                      </TableRow>
                    ))}
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

        {step === 'preview' && preview && (
          <div className="space-y-4">
            <p className="text-sm">
              {previewSourceLabel}{' '}
              <span className="font-medium">{previewSourceValue}</span>
            </p>
            <SchemaDiffView schemaDiff={preview.schema_diff} />
            {hasWarning && (
              <p className="text-sm text-warning">
                {t('reupload.warningSchemaChanges')}
              </p>
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
              {t('reupload.processingMessage')}
            </p>
            <p className="text-xs text-muted-foreground">
              {t('reupload.trackingBackground')}
            </p>
          </div>
        )}

        {step === 'complete' && (
          <div className="flex flex-col items-center justify-center gap-3 py-8">
            <CheckCircle2 className="h-10 w-10 text-success" />
            <p className="text-sm font-medium">{t('reupload.completeTitle')}</p>
            <p className="text-xs text-muted-foreground">
              {t('reupload.completeMessage')}
            </p>
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
              <Button variant="outline" onClick={handleRetry}>
                {t('reupload.tryAgain')}
              </Button>
              <Button onClick={() => handleOpenChange(false)}>{t('common:close')}</Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
