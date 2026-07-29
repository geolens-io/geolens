import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { queryKeys } from '@/lib/query-keys';
import { ApiError } from '@/api/client';
import { useJobStatus } from '@/components/import/hooks/use-ingest';
import { useAnalysisFormStore } from '@/stores/analysis-form-store';
import { analysisAddToMap, useAnalysisAddedStore, useAnalysisJobStore } from '@/stores/analysis-job-store';

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
      // report, and keeping it would poll forever. The run may well have
      // completed before the sweep, so drop its remembered title too
      // (#793 review): restoring it would re-enable Create with the finished
      // run's name.
      useAnalysisFormStore.getState().clearTitleForMap(job.mapId);
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
      // Sonner dismisses a toast when its action is clicked, but the exit
      // animation leaves a window for a second click — and the panel's own
      // "Add to map" button is a second affordance for the same add.
      // fix(#833): the single-use guard is the SHARED useAnalysisAddedStore
      // (it used to be a local flag per affordance, so toast + panel button
      // together added the layer twice); the add itself stays repeatable
      // elsewhere (adding a dataset twice is legitimate).
      toast.success(
        job.title
          ? t('analysisTools.jobCompleteNamed', {
              defaultValue: '“{{title}}” is ready',
              title: job.title,
            })
          : t('analysisTools.jobComplete', { defaultValue: 'Dataset created' }),
        {
          id: toastId,
          // fix(#725): the default bottom-right placement lands exactly on
          // the rail panel's own "Add to map" button, and with an infinite
          // duration the overlap is permanent, leaving the button visible
          // but unclickable. When a builder for this map is mounted, raise
          // the notification top-center, clear of the right rail; everywhere
          // else the default corner stays.
          position: canAddToMap ? ('top-center' as const) : undefined,
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
                    const added = useAnalysisAddedStore.getState();
                    if (
                      added.addedDatasetIds.includes(datasetId) ||
                      added.pendingAddIds.includes(datasetId)
                    ) {
                      return;
                    }
                    added.markPending(datasetId);
                    analysisAddToMap.current(datasetId);
                  } else {
                    // View-dataset path: navigation is idempotent, no guard.
                    navigate(`/datasets/${datasetId}`);
                  }
                },
              }
            : undefined,
        },
      );
      // The backend persists a collision note (e.g. the output was renamed
      // to avoid clobbering an existing dataset) in warning_message; surface
      // it beside the success toast, mirroring the upload path's
      // JobProgress warning. Raw message, same as JobProgress — it is
      // operator-facing server prose with no client-side template.
      if (data?.warning_message) {
        toast.warning(data.warning_message, {
          id: `${toastId}-warning`,
          duration: Infinity,
        });
      }
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
        {
          id: toastId,
          duration: Infinity,
          // Mirror the success branch's recovery action: the failure toast
          // dead-ended with no way back to the run. Opening the map lands on
          // the Analysis panel's remembered form — the failed run's name is
          // deliberately kept there for the retry.
          action: job.mapId
            ? {
                label: t('analysisTools.openMap', { defaultValue: 'Open map' }),
                onClick: () => navigate(`/maps/${job.mapId}`),
              }
            : undefined,
        },
      );
    }
    // fix(#793 review): the remembered form title belongs to a finished run —
    // restoring it on the panel's next mount would re-enable Create with the
    // old name and invite an identically-named duplicate. Success only: a
    // failed run created nothing, and the user most likely retries it under
    // the same name.
    if (status === 'complete') {
      useAnalysisFormStore.getState().clearTitleForMap(job.mapId);
    }
    setJob(null);
  }, [job, status, gone, data, queryClient, navigate, setJob, t]);

  return null;
}
