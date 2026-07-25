import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { queryKeys } from '@/lib/query-keys';
import { ApiError } from '@/api/client';
import { useJobStatus } from '@/components/import/hooks/use-ingest';
import { analysisAddToMap, useAnalysisJobStore } from '@/stores/analysis-job-store';

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
    // Only a terminal status stops tracking — deliberately no client-side
    // staleness rule (fix(#682 review)). An elapsed-time guess is wrong in both
    // directions: too short and a legitimately long job loses its completion
    // notification entirely, too long and the save guard outlives the API's own
    // cap. The endpoint applies the same rule (pending or running blocks), so
    // the two never disagree. A dead worker is resolved by the platform's job
    // timeout rather than guessed at here.
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
