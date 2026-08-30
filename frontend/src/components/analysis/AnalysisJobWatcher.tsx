import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { queryKeys } from '@/lib/query-keys';
import { ApiError } from '@/api/client';
import { useJobStatus } from '@/components/import/hooks/use-ingest';
import { useAnalysisFormStore } from '@/stores/analysis-form-store';
import {
  analysisAddToMap,
  useAnalysisAddedStore,
  useAnalysisJobStore,
  type TrackedAnalysisJob,
} from '@/stores/analysis-job-store';

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
      titleRetiredRef.current.add(job.jobId);
      void clearJobIfCurrent(job.jobId);
      return;
    }
    // Only a terminal status stops tracking — deliberately no client-side
    // staleness rule (fix(#682 review)). An elapsed-time guess is wrong in both
    // directions: too short and a legitimately long job loses its completion
    // notification entirely, too long and the save guard outlives the API's own
    // cap. fix(#691): the server holds the materialize slot on a heartbeat
    // lease, and the job-status route this component polls auto-fails an
    // analysis job whose lease expired — so a hard-killed worker surfaces
    // here as status 'failed' within the lease window, this watcher clears,
    // and the Analysis panel's Create button re-enables at the same moment
    // the server would admit a new materialize. The client still needs no
    // staleness rule of its own; it mirrors the server's verdict.
    // fix(#1677): 'cancelled' is terminal too. The cancel control made it a
    // reachable outcome for every job type, and `useJobStatus` already stops
    // polling on it — but this watcher did not clear, so a cancelled analysis
    // job stayed tracked in a PERSISTED store forever, surviving reloads, and
    // the Analysis panel's Create button (gated on `!!s.job`) never
    // re-enabled short of logging out or clearing site data.
    if (status !== 'complete' && status !== 'failed' && status !== 'cancelled')
      return;

    // Once per job per tab. The clear used to be synchronous, so a re-run
    // simply fell out at `if (!job)`; now the claim is awaited, and any render
    // in between re-enters — including the one the claim's own store write
    // causes, and the one a fresh `t` identity causes on every render. This
    // also subsumes StrictMode's double invoke, which is why the effect needs
    // no cleanup-based guard.
    if (handledRef.current.has(job.jobId)) return;
    handledRef.current.add(job.jobId);

    // fix(#1008 codex P2): the cache invalidation is deliberately NOT behind
    // the claim below. Every document owns its own QueryClient and the app
    // disables refetch-on-window-focus, so gating this would leave every tab
    // but the winner showing a catalog that omits the dataset just created.
    // Reporting is what must happen once; refreshing must happen everywhere.
    if (status === 'complete') {
      refreshedRef.current.add(job.jobId);
      queryClient.invalidateQueries({ queryKey: queryKeys.datasets.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.search.all });
    }

    // feat(#1008): with two builders open, both tabs poll this job and both
    // reach here. Exactly one may report it — the claim is a written, durable
    // arbiter rather than a timing accident, so it also holds for a tab that
    // reloads after another already reported.
    const tracked = job;
    void claimCompletion(tracked.jobId, status).then((claimed) => {
      if (claimed) {
        // Stable id so a re-run (StrictMode's double invoke) replaces the toast
        // instead of stacking a second one. That collapses duplicates WITHIN a
        // tab only — each tab has its own toaster, which is why the claim above
        // is what makes it one across tabs.
        const toastId = `analysis-job-${job.jobId}`;
        if (status === 'complete') {
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
        } else if (status === 'cancelled') {
          // fix(#1677): not an error — somebody asked for this. It still
          // deserves a notification, because the cancel can arrive from
          // another tab, or from the dataset's owner or an admin cancelling
          // a run this user started, and the panel is about to re-enable
          // with no other explanation of why the run stopped.
          toast.info(
            job.title
              ? t('analysisTools.jobCancelledNamed', {
                  defaultValue: '“{{title}}” was cancelled',
                  title: job.title,
                })
              : t('analysisTools.jobCancelled', {
                  defaultValue: 'Analysis run cancelled',
                }),
            { id: toastId },
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
      }
      // fix(#793 review): the remembered form title belongs to a finished run —
      // restoring it on the panel's next mount would re-enable Create with the
      // old name and invite an identically-named duplicate. Success only: a
      // failed run created nothing, and the user most likely retries it under
      // the same name.
      //
      // Outside the claim: a tab that lost still has to stop offering the
      // finished run's name and re-enable its own Create button.
      // Settled either way: a failed run KEEPS its name for the retry, which
      // is a decision, not an omission — the departure handler below must not
      // second-guess it. fix(#1677): a cancelled run keeps it for the same
      // reason — nothing was created, and re-running under the same name is
      // the likely next step.
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
    t,
  ]);

  // fix(#1008 codex P2): the clear propagates, so a tab that was throttled
  // through the terminal poll simply watches its tracked job go away. The
  // effect above then returns at `if (!job)` and it never runs the cleanup
  // that is document-local: its own QueryClient (focus refetching is off, so
  // nothing else refreshes it) and its own remembered form title.
  //
  // The two halves have DIFFERENT keys, which is what earlier passes kept
  // getting wrong by handling them together.
  //
  // Refreshing is keyed on the CLAIM and is not job-specific: one
  // invalidation re-reads the whole catalog, so a tab suspended across
  // several runs needs exactly one, for whichever claim it can see.
  //
  // Retiring the remembered title is keyed on the DEPARTURE of the run this
  // tab was showing, because that title is what its form would reopen with.
  // It deliberately does not wait for a claim: the claim and the clear are
  // separate persisted writes and arrive in either order, and a job swept by
  // the retention sweep (401/403/404) departs with no claim at all. Keeping a
  // finished run's name invites an accidental duplicate, so an unexplained
  // departure retires it — the same reading the `gone` branch above already
  // takes in whichever tab observes the sweep itself. A claim that says the
  // run FAILED is the one case that keeps the name, for the retry.
  useEffect(() => {
    const previous = lastSeenRef.current;
    lastSeenRef.current = job;
    if (
      previous &&
      previous.jobId !== job?.jobId &&
      !titleRetiredRef.current.has(previous.jobId)
    ) {
      // At most one: the store tracks a single run, so an older departed job
      // has already been superseded here.
      pendingCleanupRef.current = previous;
    }

    if (completedAt && !refreshedRef.current.has(completedAt.jobId)) {
      refreshedRef.current.add(completedAt.jobId);
      // fix(#1008 codex P2): deliberately NOT gated on the status. A tab
      // suspended while one run succeeded and a later one failed resumes to
      // the failed claim only, and gating here would leave it a catalog
      // missing the first run's dataset with nothing to correct it. A refetch
      // after a failure costs one request; a permanently stale catalog does
      // not correct itself.
      queryClient.invalidateQueries({ queryKey: queryKeys.datasets.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.search.all });
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
