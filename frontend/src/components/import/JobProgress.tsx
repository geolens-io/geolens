import { useEffect, useRef } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useJobStatus, useRetryJob } from '@/components/import/hooks/use-ingest';
import { toast } from 'sonner';
import { Copy, Download, Link2, Map } from 'lucide-react';
import { jobStatusColors } from '@/lib/status-colors';
import { formatDateTimeSmart, formatNumber } from '@/lib/format';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { ApiError } from '@/api/client';
import { downloadCog, getCogDownloadUrl } from '@/api/datasets';
import { IngestWarningsBanner } from './IngestWarningsBanner';

interface JobProgressProps {
  jobId: string;
  onReset: () => void;
  isRasterEntry?: boolean;
}

function ConnectDropdownInline({ datasetId }: { datasetId: string }) {
  const { t } = useTranslation('import');
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          <Link2 className="me-1 size-3" />
          Connect
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem
          onClick={() => {
            navigator.clipboard.writeText(
              `${window.location.origin}${getCogDownloadUrl(datasetId)}`,
            );
            toast.success(t('jobProgress.copiedCogUrl'));
          }}
        >
          <Copy className="me-2 size-3.5" />
          {t('jobProgress.copyCogUrl')}
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => {
            navigator.clipboard.writeText(
              `${window.location.origin}/raster-tiles/${datasetId}/tiles/{z}/{x}/{y}.png`,
            );
            toast.success(t('jobProgress.copiedXyzUrl'));
          }}
        >
          <Copy className="me-2 size-3.5" />
          {t('jobProgress.copyXyzUrl')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors = jobStatusColors[status];
  if (!colors) {
    return <Badge variant="secondary">{status}</Badge>;
  }
  return (
    <Badge variant="outline" className={colors}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </Badge>
  );
}

export function JobProgress({ jobId, onReset, isRasterEntry = false }: JobProgressProps) {
  const { t } = useTranslation('import');
  const { data: job, isLoading } = useJobStatus(jobId);
  const retryMutation = useRetryJob();
  const warningShownRef = useRef(false);

  // Warn before tab close / refresh while an import is still running —
  // navigating away abandons the in-progress ingest. Mirrors the builder's
  // beforeunload guard (see use-unsaved-guard.ts). In-app navigation blocking
  // via useBlocker is intentionally NOT used here: it requires a data router
  // and the leave-warning UX for a backgroundable ingest is the tab-close case.
  const jobInProgress = job?.status === 'pending' || job?.status === 'running';
  useEffect(() => {
    if (!jobInProgress) return;
    function handleBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = '';
    }
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [jobInProgress]);

  useEffect(() => {
    warningShownRef.current = false;
  }, [jobId]);

  useEffect(() => {
    if (job?.status === 'complete' && job.warning_message && !warningShownRef.current) {
      warningShownRef.current = true;
      toast.warning(job.warning_message);
    }
  }, [job?.status, job?.warning_message]);

  if (isLoading || !job) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-6">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <span className="text-sm text-muted-foreground">{t('jobProgress.loadingStatus')}</span>
        </CardContent>
      </Card>
    );
  }

  const isPolling = job.status === 'pending' || job.status === 'running';
  const hasDeterminateProgress = isPolling && job.progress != null;

  const handleRetry = async () => {
    try {
      await retryMutation.mutateAsync(jobId);
      toast.success(t('jobProgress.retrySuccess'));
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t('jobProgress.retry');
      toast.error(t('jobProgress.retryFailed', { message: msg }));
    }
  };

  return (
    <Card>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {isPolling && (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            )}
            <StatusBadge status={job.status} />
          </div>
          {job.source_filename && (
            <span className="text-sm text-muted-foreground">{job.source_filename}</span>
          )}
        </div>

        {hasDeterminateProgress && (
          <div className="space-y-1.5">
            {/* fix(#438): A11Y-01 — expose progress semantics to assistive tech. */}
            <div
              className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2"
              role="progressbar"
              aria-valuenow={Math.round((job.progress ?? 0) * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={t('jobProgress.progressLabel', { defaultValue: 'Job progress' })}
            >
              <span
                className="block h-full rounded-full bg-primary transition-[width] duration-300"
                style={{ width: `${Math.round((job.progress ?? 0) * 100)}%` }}
              />
            </div>
            <p className="font-mono text-mini text-muted-foreground tracking-wide">
              {job.current_step &&
                t(`jobProgress.step.${job.current_step}`, {
                  defaultValue: job.current_step,
                })}
              {job.rows_processed != null && (
                <>
                  {' '}
                  · {formatNumber(job.rows_processed)}{' '}
                  {t('jobProgress.rowsSuffix', { defaultValue: 'rows' })}
                </>
              )}
            </p>
          </div>
        )}

        <div className="text-xs text-muted-foreground space-y-1">
          <p>{t('jobProgress.created')} {formatDateTimeSmart(job.created_at)}</p>
          {job.started_at && <p>{t('jobProgress.started')} {formatDateTimeSmart(job.started_at)}</p>}
          {job.completed_at && <p>{t('jobProgress.completed')} {formatDateTimeSmart(job.completed_at)}</p>}
        </div>

        {job.status === 'complete' && (
          <IngestWarningsBanner job={job} />
        )}

        {job.status === 'complete' && job.dataset_id && (
          <div className="flex flex-wrap items-center gap-2">
            <Button asChild>
              <Link to={`/datasets/${job.dataset_id}`}>{t('jobProgress.viewDataset')}</Link>
            </Button>
            {isRasterEntry && (
              <>
                <Button variant="outline" size="sm" onClick={async () => {
                  try { await downloadCog(job.dataset_id!); } catch { toast.error(t('jobProgress.cogDownloadFailed')); }
                }}>
                  <Download className="me-1 size-3" />
                  {t('jobProgress.downloadCog')}
                </Button>
                <Button variant="outline" size="sm" asChild>
                  <Link to={`/datasets/${job.dataset_id}`}>
                    <Map className="me-1 size-3" />
                    {t('jobProgress.addToMap')}
                  </Link>
                </Button>
                <ConnectDropdownInline datasetId={job.dataset_id} />
              </>
            )}
          </div>
        )}

        {job.status === 'failed' && (
          <div className="space-y-3">
            {job.error_message && (
              <p className="text-sm text-destructive">{job.error_message}</p>
            )}
            <div className="flex items-center gap-2">
              <Button
                onClick={handleRetry}
                disabled={retryMutation.isPending}
              >
                {retryMutation.isPending ? (
                  <span className="flex items-center gap-2">
                    <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
                    {t('jobProgress.retrying')}
                  </span>
                ) : (
                  t('jobProgress.retry')
                )}
              </Button>
              <Button
                variant="outline"
                onClick={onReset}
                disabled={retryMutation.isPending}
              >
                {t('jobProgress.startOver')}
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
