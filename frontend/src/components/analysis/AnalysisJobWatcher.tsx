import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { INTERNAL_FAILURE_REASON, fixedFailureReason } from '@/lib/failure-reason';
import { useNavigate } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { queryKeys } from '@/lib/query-keys';
import { ApiError } from '@/api/client';
import { useRefreshSearchWhenQuicklookLands } from '@/components/dataset/hooks/use-quicklook-settled';
import { useJobStatus } from '@/components/import/hooks/use-ingest';
import { useAnalysisFormStore } from '@/stores/analysis-form-store';
import {
  useAnalysisAddToMapStore,
  useAnalysisAddedStore,
  useAnalysisJobStore,
  type TrackedAnalysisJob,
} from '@/stores/analysis-job-store';

/** A finished run's success toast. */
interface Completion {
  toastId: string;
  message: string;
  datasetId: string | null;
  mapId: string | null;
}

/** The add handler of a mounted builder for `mapId`, or null when there's none. */
function builderAddFor(mapId: string | null) {
  const builder = useAnalysisAddToMapStore.getState();
  return builder.mapId === mapId ? builder.add : null;
}

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
  const completedAt = useAnalysisJobStore((s) => s.completedAt);
  const claimCompletion = useAnalysisJobStore((s) => s.claimCompletion);
  const clearJobIfCurrent = useAnalysisJobStore((s) => s.clearJobIfCurrent);
  // Runs whose terminal status this tab has already acted on, so the effect
  // below does not re-enter for one it is already seeing through.
  const handledRef = useRef<Set<string>>(new Set());
  // Runs this tab has already refreshed its caches for.
  const refreshedRef = useRef<Set<string>>(new Set());
  // Runs whose remembered form title this tab has already settled — retired,
  // or deliberately kept because the run failed.
  const titleRetiredRef = useRef<Set<string>>(new Set());
  // The job as of the previous render, so a departure is detectable.
  const lastSeenRef = useRef<TrackedAnalysisJob | null>(null);
  // A departed job still owed its document-local cleanup, waiting for the
  // claim that says how it ended.
  const pendingCleanupRef = useRef<TrackedAnalysisJob | null>(null);
  // Success toasts still open, by toast id, with whether each offers "Add to
  // map". Raising a closed toast's id again would bring it back, so every way
  // of closing one deletes its entry.
  const openCompletionsRef = useRef(
    new Map<string, { completion: Completion; addsToMap: boolean }>(),
  );
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  // The job reports complete before the output's thumbnail is drawn, and the
  // tracked job is cleared at completion, so the watch needs an id of its own.
  const [quicklookJobId, setQuicklookJobId] = useState<string | null>(null);
  useRefreshSearchWhenQuicklookLands(quicklookJobId);
  // Shares its query key with the Analysis panel, so both watching costs one poll.
  const { data, error } = useJobStatus(job?.jobId ?? null);
  const status = data?.status;
  // Only a definitive answer stops tracking. A transient 5xx or dropped
  // connection must not discard the job: refetchInterval keeps polling through
  // errors, and reloads and navigation are exactly when a blip is likely.
  const gone =
    error instanceof ApiError && [401, 403, 404].includes(error.status);

  // Raises a success toast, or updates an open one in place under the same id.
  // Label, placement and click all follow the builder registration, so they
  // can't disagree while the toast stays open.
  const showCompletion = useCallback(
    (completion: Completion) => {
      const { toastId, datasetId, mapId } = completion;
      const addsToMap = !!builderAddFor(mapId);
      const forget = () => openCompletionsRef.current.delete(toastId);
      openCompletionsRef.current.set(toastId, { completion, addsToMap });
      toast.success(completion.message, {
        id: toastId,
        // The default corner covers the Analysis panel's own "Add to map"
        // button, so the toast sits top-center while that builder is open.
        position: addsToMap ? ('top-center' as const) : undefined,
        // A long job lands when attention has moved on, so the default 4s is
        // easy to miss; the Toaster's closeButton dismisses it.
        duration: Infinity,
        onDismiss: forget,
        action: datasetId
          ? {
              label: addsToMap
                ? t('analysisTools.addToMap', { defaultValue: 'Add to map' })
                : t('analysisTools.viewDataset', { defaultValue: 'View dataset' }),
              onClick: () => {
                forget();
                // Read again here: Sonner shows an update a moment after the
                // registration changes.
                const add = builderAddFor(mapId);
                if (!add) {
                  navigate(`/datasets/${datasetId}`);
                  return;
                }
                // The panel's own button adds the same dataset, and the exit
                // animation leaves time for a second click, so every analysis
                // affordance shares one single-use guard.
                const added = useAnalysisAddedStore.getState();
                if (
                  added.addedDatasetIds.includes(datasetId) ||
                  added.pendingAddIds.includes(datasetId)
                ) {
                  return;
                }
                added.markPending(datasetId);
                add(datasetId);
              },
            }
          : undefined,
      });
    },
    [t, navigate],
  );

  // A builder mounting, leaving or switching maps updates the toasts it affects.
  useEffect(
    () =>
      useAnalysisAddToMapStore.subscribe(() => {
        for (const { completion, addsToMap } of openCompletionsRef.current.values()) {
          if (!!builderAddFor(completion.mapId) !== addsToMap) showCompletion(completion);
        }
      }),
    [showCompletion],
  );

  useEffect(() => {
    if (!job) return;
    if (gone) {
      // Pruned by the retention sweep, or no longer ours to read: nothing to
      // report, and keeping it would poll forever. The run may have completed
      // before the sweep, so drop its remembered title too; restoring it would
      // re-enable Create with the finished run's name.
      useAnalysisFormStore.getState().clearTitleForMap(job.mapId);
      titleRetiredRef.current.add(job.jobId);
      void clearJobIfCurrent(job.jobId);
      return;
    }
    // Only a terminal status stops tracking, with no client-side staleness
    // rule: an elapsed-time guess is wrong both ways (a long job loses its
    // notification, or the save guard outlives the API's cap). The server holds
    // the materialize slot on a heartbeat lease and the job-status route
    // auto-fails a job whose lease expired, so a hard-killed worker surfaces
    // here as 'failed', this watcher clears, and Create re-enables just as the
    // server would admit a new materialize.
    // 'cancelled' is terminal too, and useJobStatus already stops polling on
    // it. Without clearing, a cancelled job would stay tracked in a PERSISTED
    // store across reloads and Create (gated on `!!s.job`) would never
    // re-enable short of logging out or clearing site data.
    if (status !== 'complete' && status !== 'failed' && status !== 'cancelled')
      return;

    // Once per job per tab. The claim is awaited, so any render in between
    // re-enters, including the one the claim's own store write causes and the
    // one a fresh `t` identity causes. This also covers StrictMode's double
    // invoke, so the effect needs no cleanup-based guard.
    if (handledRef.current.has(job.jobId)) return;
    handledRef.current.add(job.jobId);

    // Deliberately NOT behind the claim below: every document owns its own
    // QueryClient and refetch-on-window-focus is off, so gating this would leave
    // every tab but the winner with a catalog missing the new dataset.
    // Reporting happens once; refreshing happens everywhere.
    if (status === 'complete') {
      refreshedRef.current.add(job.jobId);
      queryClient.invalidateQueries({ queryKey: queryKeys.datasets.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.search.all });
      if (data?.quicklook_pending) setQuicklookJobId(job.jobId);
    }

    // With two builders open, both tabs reach here. Exactly one may report it;
    // the claim is a durable arbiter, so it also holds for a tab that reloads
    // after another already reported.
    const tracked = job;
    void claimCompletion(tracked.jobId, status).then((claimed) => {
      if (claimed) {
        // A stable id makes a StrictMode re-run replace the toast; that dedupes
        // within a tab only, so the claim is what makes it one across tabs.
        const toastId = `analysis-job-${job.jobId}`;
        if (status === 'complete') {
          showCompletion({
            toastId,
            message: job.title
              ? t('analysisTools.jobCompleteNamed', {
                  defaultValue: '“{{title}}” is ready',
                  title: job.title,
                })
              : t('analysisTools.jobComplete', { defaultValue: 'Dataset created' }),
            datasetId: data?.dataset_id ?? null,
            mapId: job.mapId,
          });
          // warning_message carries the backend's collision note (e.g. the
          // output was renamed). Shown raw, like JobProgress: it is
          // operator-facing server prose with no client template.
          if (data?.warning_message) {
            toast.warning(data.warning_message, {
              id: `${toastId}-warning`,
              duration: Infinity,
            });
          }
        } else if (status === 'cancelled') {
          // Not an error, but it still needs a notification: the cancel can
          // come from another tab or from an owner/admin, and the panel is
          // about to re-enable with no other explanation.
          //
          // The stale sweep also settles an abandoned run as `cancelled` with
          // a code, so a coded reason takes priority over the named text.
          toast.info(
            fixedFailureReason(data?.error_code) ??
              (job.title
                ? t('analysisTools.jobCancelledNamed', {
                    defaultValue: '“{{title}}” was cancelled',
                    title: job.title,
                  })
                : t('analysisTools.jobCancelled', {
                    defaultValue: 'Analysis run cancelled',
                  })),
            { id: toastId },
          );
        } else {
          const reason = data?.error_message;
          const message =
            fixedFailureReason(data?.error_code) ??
            (reason === INTERNAL_FAILURE_REASON ? null : reason);
          // Interpolated through i18n: check:i18n:toast-strings flags toast
          // calls whose first argument opens with a quote or backtick.
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
              // Opening the map lands on the Analysis panel's remembered form,
              // which keeps the failed run's name for the retry.
              action: job.mapId
                ? {
                    label: t('analysisTools.openMap', { defaultValue: 'Open map' }),
                    onClick: () => navigate(`/maps/${job.mapId}`),
                  }
                : undefined,
            },
          );
        }
      }
      // The remembered form title belongs to a finished run: restoring it on
      // the panel's next mount would re-enable Create with the old name and
      // invite a duplicate. Success only; failed and cancelled runs created
      // nothing and are likely retried under the same name, so they keep it.
      // That is settled here, so the departure handler below must not
      // second-guess it.
      //
      // Outside the claim: a tab that lost still has to stop offering the
      // finished run's name and re-enable its own Create button.
      titleRetiredRef.current.add(tracked.jobId);
      if (status === 'complete') {
        useAnalysisFormStore.getState().clearTitleForMap(tracked.mapId);
      }
      void clearJobIfCurrent(tracked.jobId);
    });
  }, [
    job,
    status,
    gone,
    data,
    queryClient,
    navigate,
    claimCompletion,
    clearJobIfCurrent,
    showCompletion,
    t,
  ]);

  // The clear propagates, so a tab throttled through the terminal poll just
  // watches its tracked job go away; the effect above returns at `if (!job)`
  // and never runs the document-local cleanup: its own QueryClient (focus
  // refetching is off) and its own remembered form title.
  //
  // The two halves have DIFFERENT keys.
  //
  // Refreshing is keyed on the CLAIM and is not job-specific: one invalidation
  // re-reads the whole catalog, so a tab suspended across several runs needs
  // exactly one.
  //
  // Retiring the title is keyed on the DEPARTURE of the run this tab was
  // showing, because that title is what its form would reopen with. It does
  // not wait for a claim: the claim and the clear are separate persisted
  // writes that arrive in either order, and a job swept by retention
  // (401/403/404) departs with no claim at all. Keeping a finished run's name
  // invites a duplicate, so an unexplained departure retires it, as the `gone`
  // branch does. A claim saying the run FAILED is the one case that keeps it.
  useEffect(() => {
    const previous = lastSeenRef.current;
    lastSeenRef.current = job;
    if (
      previous &&
      previous.jobId !== job?.jobId &&
      !titleRetiredRef.current.has(previous.jobId)
    ) {
      // At most one: the store tracks a single run.
      pendingCleanupRef.current = previous;
    }

    if (completedAt && !refreshedRef.current.has(completedAt.jobId)) {
      refreshedRef.current.add(completedAt.jobId);
      // Deliberately NOT gated on the status: a tab suspended while one run
      // succeeded and a later one failed resumes to the failed claim only, and
      // gating would leave a catalog missing the first dataset with nothing to
      // correct it.
      queryClient.invalidateQueries({ queryKey: queryKeys.datasets.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.search.all });
      // The claim outlives the tracked job, so this covers a tab that missed
      // the terminal poll or reloaded. The watch ends at once for a thumbnail
      // that is already drawn.
      if (completedAt.status === 'complete') setQuicklookJobId(completedAt.jobId);
    }

    const pending = pendingCleanupRef.current;
    if (!pending) return;
    pendingCleanupRef.current = null;
    titleRetiredRef.current.add(pending.jobId);
    const claim = completedAt?.jobId === pending.jobId ? completedAt : null;
    if (claim?.status === 'failed') return;
    useAnalysisFormStore.getState().clearTitleForMap(pending.mapId);
  }, [job, completedAt, queryClient]);

  return null;
}
