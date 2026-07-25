import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { queryKeys } from '@/lib/query-keys';
import { ApiError } from '@/api/client';
import { useJobStatus } from '@/components/import/hooks/use-ingest';
import { analysisAddToMap, useAnalysisJobStore } from '@/stores/analysis-job-store';

/** Mirrors _RUNNING_JOB_WINDOW in backend/.../api/router_analysis.py. */
const STALE_RUNNING_JOB_MS = 10 * 60 * 1000;

/**
 * Global notifier for a materialize-analysis job (renders nothing).
 *
 * Mounted in RootLayout so tracking outlives the things a long job outlives:
 * the Analysis panel closing, navigation off the builder, and a page reload
 * (the job id is persisted). It owns the completion notification and the
 * catalog cache invalidation so there is exactly one of each per job.
 */
export function AnalysisJobWatcher() {
  const { t } = useTranslation('builder');
  const job = useAnalysisJobStore((s) => s.job);
  const setJob = useAnalysisJobStore((s) => s.setJob);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  // Shares its query key with the Analysis panel, so both watching costs one poll.
  const { data, error } = useJobStatus(job?.jobId ?? null);
  const status = data?.status;
  // fix(#682 review): only a definitive answer stops tracking. A transient 5xx
  // or dropped connection must NOT discard the job — refetchInterval keeps
  // polling through errors, so tracking recovers on the next good response,
  // and the reload/navigation cases this exists for are exactly when a blip is
  // most likely.
  const gone =
    error instanceof ApiError && [401, 403, 404].includes(error.status);

  useEffect(() => {
    if (!job) return;
    if (gone) {
      // Pruned by the retention sweep, or no longer ours to read — nothing to
      // report, and keeping it would poll forever.
      setJob(null);
      return;
    }
    // fix(#682 review): stop tracking a job stuck in 'running' past the window
    // the API uses for its per-user cap. Without this the save guard outlives
    // the server's own: the materialize endpoint stops counting a job this old
    // (_RUNNING_JOB_WINDOW in router_analysis.py), but GET /jobs/{id} keeps
    // reporting 'running' until the hour-long platform reaper fails it, so the
    // Create button stayed disabled for ~50 minutes after the API would have
    // accepted a replacement. The CTAS carries a 300s statement timeout, so a
    // job still 'running' here is a dead worker, not slow work.
    //
    // Deliberately not applied to 'pending': queued work will still run, and
    // the endpoint counts pending jobs without a time bound for that reason.
    // This measures from enqueue while the server measures from actual start,
    // so a job that sat in a backlog can clear here while the endpoint still
    // counts it — that path just earns an explicit 429 instead of a dead button.
    if (
      status === 'running' &&
      Date.now() - job.enqueuedAt > STALE_RUNNING_JOB_MS
    ) {
      setJob(null);
      return;
    }
    if (status !== 'complete' && status !== 'failed') return;

    // Stable id so a re-run (StrictMode's double invoke) replaces the toast
    // instead of stacking a second one.
    const toastId = `analysis-job-${job.jobId}`;
    if (status === 'complete') {
      queryClient.invalidateQueries({ queryKey: queryKeys.datasets.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.search.all });
      const datasetId = data?.dataset_id;
      const canAddToMap =
        !!analysisAddToMap.current && analysisAddToMap.mapId === job.mapId;
      toast.success(
        job.title
          ? t('analysisTools.jobCompleteNamed', {
              defaultValue: '“{{title}}” is ready',
              title: job.title,
            })
          : t('analysisTools.jobComplete', { defaultValue: 'Dataset created' }),
        {
          id: toastId,
          // A long job lands when attention has moved on, so the default 4s
          // notification is one the user is likely to miss entirely. The
          // Toaster is configured with closeButton, so this stays until
          // acknowledged.
          duration: Infinity,
          action: datasetId
            ? {
                label: canAddToMap
                  ? t('analysisTools.addToMap', { defaultValue: 'Add to map' })
                  : t('analysisTools.viewDataset', { defaultValue: 'View dataset' }),
                onClick: () => {
                  // Re-check: the builder may have unmounted since this toast
                  // was raised.
                  if (
                    analysisAddToMap.current &&
                    analysisAddToMap.mapId === job.mapId
                  ) {
                    analysisAddToMap.current(datasetId);
                  } else {
                    navigate(`/datasets/${datasetId}`);
                  }
                },
              }
            : undefined,
        },
      );
    } else {
      const message = data?.error_message;
      // Interpolate the detail through i18n rather than concatenating onto
      // t(): check:i18n:toast-strings flags any toast call whose first
      // argument opens with a quote or backtick, template literals included.
      toast.error(
        message
          ? t('analysisTools.jobFailedDetail', {
              message,
              defaultValue: 'Analysis job failed: {{message}}',
            })
          : t('analysisTools.jobFailed', { defaultValue: 'Analysis job failed' }),
        { id: toastId, duration: Infinity },
      );
    }
    setJob(null);
  }, [job, status, gone, data, queryClient, navigate, setJob, t]);

  return null;
}
