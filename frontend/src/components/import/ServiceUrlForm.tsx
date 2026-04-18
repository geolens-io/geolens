import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Globe, Check } from 'lucide-react';
import { cn } from '@/lib/utils';
import { ApiError } from '@/api/client';
import { probeService, previewServiceLayer, commitImport } from '@/api/ingest';
import type {
  ProbeResponse,
  LayerInfo,
  ServicePreviewResponse,
  ServicePreviewRequest,
  CommitImportRequest,
  FilePreviewResponse,
} from '@/types/api';
import { ImportPreview } from './ImportPreview';
import { ImportMetadataForm } from './ImportMetadataForm';
import { JobProgress } from './JobProgress';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { TypeTag } from './TypeTag';

type ServiceStep =
  | 'idle'
  | 'probing'
  | 'layer-select'
  | 'previewing'
  | 'review'
  | 'committing'
  | 'tracking';

export function ServiceUrlForm() {
  const { t } = useTranslation('import');
  const [step, setStep] = useState<ServiceStep>('idle');
  const [url, setUrl] = useState('');
  const [token, setToken] = useState('');
  const [probeResult, setProbeResult] = useState<ProbeResponse | null>(null);
  const [previewData, setPreviewData] = useState<ServicePreviewResponse | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setStep('idle');
    setUrl('');
    setToken('');
    setProbeResult(null);
    setPreviewData(null);
    setJobId(null);
    setError(null);
  };

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) return;

    setStep('probing');
    setError(null);

    try {
      const result = await probeService(trimmed, token || undefined);
      setProbeResult(result);
      setStep('layer-select');
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t('serviceUrl.connectFailed');
      setError(msg);
      setStep('idle');
      toast.error(msg);
    }
  };

  const handleLayerSelect = async (layer: LayerInfo) => {
    if (!probeResult) return;

    setStep('previewing');
    setError(null);

    const request: ServicePreviewRequest = {
      url: probeResult.url,
      service_type: probeResult.service_type,
      layer_name: layer.name,
      layer_title: layer.title,
      layer_id: layer.layer_id,
      token: token || undefined,
      object_id_field: layer.object_id_field,
    };

    try {
      const result = await previewServiceLayer(request);
      setPreviewData(result);
      setStep('review');
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const body = err.body as { code?: string; existing_dataset_id?: string; existing_title?: string } | undefined;
        if (body?.code === 'duplicate_source' && body.existing_dataset_id) {
          const title = body.existing_title ?? 'Unknown dataset';
          const msg = `Already registered: "${title}"`;
          setError(msg);
          setStep('layer-select');
          toast.error(msg, {
            action: {
              label: 'View existing',
              onClick: () => { window.location.href = `/datasets/${body.existing_dataset_id}`; },
            },
          });
          return;
        }
      }
      const msg = err instanceof ApiError ? err.message : t('serviceUrl.previewFailed');
      setError(msg);
      setStep('layer-select');
      toast.error(msg);
    }
  };

  const handleCommit = async (metadata: CommitImportRequest) => {
    if (!previewData) return;

    setStep('committing');

    try {
      await commitImport(previewData.job_id, { ...metadata, ...(token && { token }) });
      setJobId(previewData.job_id);
      setStep('tracking');
      toast.success(t('serviceUrl.importStarted'));
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t('serviceUrl.commitFailed');
      setError(msg);
      setStep('review');
      toast.error(msg);
    }
  };

  // ── Loading states ──
  if (step === 'probing' || step === 'previewing') {
    const loadingLabel = step === 'probing' ? t('serviceUrl.connecting') : t('serviceUrl.loadingPreview');
    return (
      <div className="flex items-center gap-3 rounded-xl border border-border bg-card px-5 py-8 justify-center">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span className="text-sm text-muted-foreground">{loadingLabel}</span>
      </div>
    );
  }

  // ── Layer selection with probe result ──
  if (step === 'layer-select' && probeResult) {
    return (
      <div className="space-y-5">
        {/* Probe input — detected state */}
        <div className="rounded-xl border border-border bg-card p-5">
          <label className="mb-2.5 block font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            {t('serviceUrl.detectedLabel', { defaultValue: 'Service URL — detected' })}
          </label>
          <div className="flex items-stretch overflow-hidden rounded-lg border-[1.5px] border-success bg-surface-0">
            <span className="flex items-center gap-1.5 border-r border-border bg-success/10 px-3.5 font-mono text-[11px] font-semibold uppercase tracking-wider text-success">
              <Check className="size-3.5" />
              {probeResult.service_type}
            </span>
            <input
              type="text"
              readOnly
              value={probeResult.url}
              className="flex-1 bg-transparent px-3.5 py-2.5 font-mono text-[13.5px] text-foreground outline-none"
            />
            <button
              onClick={reset}
              className="border-l border-border bg-surface-2 px-4 text-[13px] font-medium text-muted-foreground hover:bg-surface-3 hover:text-foreground"
            >
              {t('serviceUrl.clear', { defaultValue: 'Clear' })}
            </button>
          </div>
        </div>

        {/* Service info + layer cards */}
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <div className="flex items-center gap-3.5 border-b border-border px-5 py-3.5">
            <span className="rounded-md bg-type-vrt-bg px-2.5 py-0.5 font-mono text-[11px] font-semibold uppercase tracking-wider text-type-vrt">
              {probeResult.service_type}
            </span>
            <div className="flex-1">
              <h3 className="text-[15px] font-medium tracking-tight">
                {probeResult.url}
              </h3>
              <p className="font-mono text-[11px] text-muted-foreground tracking-wide">
                {t('serviceUrl.layersAvailable', { count: probeResult.layers.length, defaultValue: `${probeResult.layers.length} layers available` })}
              </p>
            </div>
          </div>

          <div className="grid gap-2 p-2 sm:grid-cols-2">
            {probeResult.layers.length === 0 && (
              <p className="col-span-2 px-3 py-4 text-center text-sm text-muted-foreground">
                {t('serviceUrl.noLayers', { defaultValue: 'No layers were found in this service.' })}
              </p>
            )}
            {probeResult.layers.map((layer) => {
              const isVector = layer.geometry_type && !layer.geometry_type.toLowerCase().includes('raster');
              return (
                <button
                  key={layer.name}
                  onClick={() => handleLayerSelect(layer)}
                  className={cn(
                    'flex items-center gap-2.5 rounded-lg border border-border p-2.5 text-left transition-colors',
                    'hover:bg-surface-2',
                  )}
                >
                  <TypeTag kind={isVector ? 'vector' : 'raster'} size="sm" />
                  <div className="flex-1 min-w-0">
                    <p className="truncate text-[12.5px] font-medium tracking-tight">
                      {layer.title || layer.name}
                    </p>
                    <p className="truncate font-mono text-[10.5px] text-muted-foreground tracking-wide mt-0.5">
                      {layer.name}
                      {layer.geometry_type && ` · ${layer.geometry_type}`}
                    </p>
                  </div>
                </button>
              );
            })}
          </div>

          {error && (
            <p className="border-t border-border px-5 py-3 text-sm text-destructive">{error}</p>
          )}
        </div>
      </div>
    );
  }

  // ── Review and commit ──
  if ((step === 'review' || step === 'committing') && previewData) {
    return (
      <div className="space-y-4">
        <ImportPreview preview={previewData as FilePreviewResponse} />
        {error && <p className="text-sm text-destructive">{error}</p>}
        <ImportMetadataForm
          defaultName={previewData.source_filename ?? previewData.layer_name}
          detectedCrs={previewData.crs}
          onCommit={handleCommit}
          isCommitting={step === 'committing'}
        />
        <Button variant="outline" onClick={reset}>
          {t('serviceUrl.startOver')}
        </Button>
      </div>
    );
  }

  // ── Job tracking ──
  if (step === 'tracking' && jobId) {
    return <JobProgress jobId={jobId} onReset={reset} />;
  }

  // ── Idle — URL input form ──
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <form onSubmit={handleConnect} className="space-y-5">
        <div>
          <label className="mb-2.5 block font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            {t('serviceUrl.label', { defaultValue: 'Service URL — we\'ll auto-detect the type' })}
          </label>
          <div className="flex items-stretch overflow-hidden rounded-lg border-[1.5px] border-border bg-surface-0 transition-colors focus-within:border-primary">
            <span className="flex items-center gap-1.5 border-r border-border bg-surface-2 px-3.5 font-mono text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
              <Globe className="size-3.5" />
              URL
            </span>
            <input
              type="url"
              placeholder={t('serviceUrl.placeholder')}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="flex-1 bg-transparent px-3.5 py-2.5 font-mono text-[13.5px] text-foreground outline-none placeholder:text-muted-foreground/50"
            />
            <button
              type="submit"
              disabled={!url.trim()}
              className="bg-primary px-4 text-[13px] font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
            >
              {t('serviceUrl.probe', { defaultValue: 'Probe →' })}
            </button>
          </div>
          <div className="mt-2.5 flex flex-wrap gap-4 text-xs text-muted-foreground">
            <span>
              {t('serviceUrl.supported', { defaultValue: 'Supported:' })}{' '}
              <code className="rounded bg-surface-2 px-1.5 py-px font-mono text-[11px] text-muted-foreground">WFS</code>{' '}
              <code className="rounded bg-surface-2 px-1.5 py-px font-mono text-[11px] text-muted-foreground">ArcGIS FeatureServer</code>{' '}
              <code className="rounded bg-surface-2 px-1.5 py-px font-mono text-[11px] text-muted-foreground">OGC API Features</code>
            </span>
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="access-token" className="text-xs text-muted-foreground">
            {t('serviceUrl.tokenLabel')}
          </Label>
          <Input
            id="access-token"
            type="password"
            placeholder={t('serviceUrl.tokenPlaceholder')}
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="font-mono text-sm"
          />
          <p className="text-xs text-muted-foreground">{t('serviceUrl.tokenHelpText')}</p>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}
      </form>
    </div>
  );
}
