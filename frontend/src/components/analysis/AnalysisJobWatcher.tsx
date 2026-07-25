import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { queryKeys } from '@/lib/query-keys';
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
  const { data, isError } = useJobStatus(job?.jobId ?? null);
  const status = data?.status;

  useEffect(() => {
    if (!job) return;
    if (isError) {
      // Unreadable job (pruned by the retention sweep, or signed out) —
      // nothing to report, and keeping it would poll forever.
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
      toast.error(
        `${t('analysisTools.jobFailed', { defaultValue: 'Analysis job failed' })}${message ? `: ${message}` : ''}`,
        { id: toastId, duration: Infinity },
      );
    }
    setJob(null);
  }, [job, status, isError, data, queryClient, navigate, setJob, t]);

  return null;
}
