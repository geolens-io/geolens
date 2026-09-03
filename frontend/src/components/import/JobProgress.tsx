import { useEffect, useRef } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useJobStatus, useRetryJob, useCancelJob } from '@/components/import/hooks/use-ingest';
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
          {t('jobProgress.connect')}
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
  const { t } = useTranslation('import');
  const colors = jobStatusColors[status];
  const label = (() => {
    switch (status) {
      case 'pending': return t('jobProgress.status.pending');
      case 'running': return t('jobProgress.status.running');
      case 'complete': return t('jobProgress.status.complete');
      case 'failed': return t('jobProgress.status.failed');
      case 'cancelled': return t('jobProgress.status.cancelled');
      case 'fanned_out': return t('jobProgress.status.fannedOut');
      default: return t('jobProgress.status.unknown', { status });
    }
  })();
  if (!colors) {
    return <Badge variant="secondary">{label}</Badge>;
  }
  return (
    <Badge variant="outline" className={colors}>
      {label}
    </Badge>
  );
}

export function JobProgress({ jobId, onReset, isRasterEntry = false }: JobProgressProps) {
  const { t } = useTranslation('import');
  const { data: job, isLoading, isError, error } = useJobStatus(jobId);
  const retryMutation = useRetryJob();
  const cancelMutation = useCancelJob();
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

  // fix(#1778): a failing GET /jobs/{id} (401/403/404, or a retry-exhausted
  // 5xx) used to leave `job` undefined forever, so this fell into the
  // isLoading/!job branch and rendered an indefinite "Loading status…"
  // spinner. Give it its own terminal render, same as the failed-job branch
  // below, so the user sees a real message and onReset instead.
  if (isError && !job) {
    const msg = error instanceof ApiError ? error.message : t('jobProgress.statusError');
    return (
      <Card>
        <CardContent className="space-y-3 py-6">
          <p className="text-sm text-destructive">{msg}</p>
          <Button variant="outline" onClick={onReset}>
            {t('jobProgress.startOver')}
          </Button>
        </CardContent>
      </Card>
    );
  }

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

  // fix(#1778): the backend already grants cancel to the job's creator
  // (#1709) — this is the only client caller that reaches it from an import
  // surface. One-click, matching the admin job list and the refresh-run
  // history's cancel (feat #1677): no confirm dialog, a toast on rejection.
  const handleCancel = () => {
    cancelMutation.mutate(jobId, {
      onError: () => toast.error(t('jobProgress.cancelFailed')),
    });
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
          <div className="flex items-center gap-2">
            {job.source_filename && (
              <span className="text-sm text-muted-foreground">{job.source_filename}</span>
            )}
            {isPolling && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleCancel}
                disabled={cancelMutation.isPending}
              >
                {cancelMutation.isPending ? t('jobProgress.cancelling') : t('jobProgress.cancel')}
              </Button>
            )}
          </div>
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
            {job.retry_reason && (
              <p className="text-sm text-muted-foreground">{job.retry_reason}</p>
            )}
            <div className="flex items-center gap-2">
              {job.can_retry !== false && (
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
              )}
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

        {/* fix(review #1800 P2): the new Cancel button (#1778) drives a job
            to `cancelled`, but the terminal blocks below only covered
            `complete` and `failed` — a cancelled job rendered no action at
            all. That strands any consumer with no OTHER escape hatch of its
            own; ServiceUrlForm and VrtCreatorForm render bare <JobProgress>
            with nothing else, unlike UrlImportForm's own terminal-status
            "Import another" button. */}
        {job.status === 'cancelled' && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">{t('jobProgress.cancelledMessage')}</p>
            <Button variant="outline" onClick={onReset}>
              {t('jobProgress.startOver')}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
