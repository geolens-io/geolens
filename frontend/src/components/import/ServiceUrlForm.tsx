import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
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
import { LayerPicker } from './LayerPicker';
import { ImportPreview } from './ImportPreview';
import { ImportMetadataForm } from './ImportMetadataForm';
import { JobProgress } from './JobProgress';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Card, CardContent } from '@/components/ui/card';
import { Globe } from 'lucide-react';

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

  // Loading states
  if (step === 'probing') {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-6">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <span className="text-sm text-muted-foreground">{t('serviceUrl.connecting')}</span>
        </CardContent>
      </Card>
    );
  }

  if (step === 'previewing') {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-6">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <span className="text-sm text-muted-foreground">{t('serviceUrl.loadingPreview')}</span>
        </CardContent>
      </Card>
    );
  }

  // Layer selection
  if (step === 'layer-select' && probeResult) {
    return (
      <LayerPicker
        probeResult={probeResult}
        onSelect={handleLayerSelect}
        onBack={() => {
          setStep('idle');
          setError(null);
        }}
        error={error}
      />
    );
  }

  // Review and commit
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

  // Job tracking
  if (step === 'tracking' && jobId) {
    return <JobProgress jobId={jobId} onReset={reset} />;
  }

  // Idle -- URL input form
  return (
    <Card>
      <CardContent className="pt-6">
        <form onSubmit={handleConnect} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="service-url">{t('serviceUrl.label')}</Label>
            <Input
              id="service-url"
              type="url"
              placeholder={t('serviceUrl.placeholder')}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              {t('serviceUrl.helpText')}
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="access-token">{t('serviceUrl.tokenLabel')}</Label>
            <Input
              id="access-token"
              type="password"
              placeholder={t('serviceUrl.tokenPlaceholder')}
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              {t('serviceUrl.tokenHelpText')}
            </p>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" disabled={!url.trim()}>
            <Globe className="me-2 h-4 w-4" />
            {t('serviceUrl.connect')}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
