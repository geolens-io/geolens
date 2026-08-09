import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { Loader2, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { useDatasetRefreshRuns, useRefreshDataset } from '@/components/dataset/hooks/use-dataset';
import { queryKeys } from '@/lib/query-keys';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import type { DatasetOrigin, DatasetResponse } from '@/types/api';

// fix(#1285 codex round 1): refresh-door origins. router_refresh.py routes
// every non-postgis request through _resolve_service_origin(), which
// refuses everything except `service` with 409 refresh_not_applicable — so
// `upload`/`created`/`stac` are NOT refreshable today even though they have
// a resolvable origin. This is the one place that fact is encoded; DetailPanel
// imports it rather than gating on origin presence alone. #1266 (STAC refresh
// strategy) adds 'stac' when it lands — check before widening this set.
export const REFRESHABLE_ORIGINS: ReadonlySet<DatasetOrigin> = new Set(['service', 'postgis']);

function isRunActive(status: string | undefined): boolean {
  return status === 'pending' || status === 'running';
}

interface SourceRefreshActionProps {
  dataset: DatasetResponse;
}

/**
 * "Refresh from source" trigger for the Source panel (#1285).
 *
 * Self-contained: owns its own dialog, token field, and mutation, so a
 * caller only has to decide WHETHER to render it (DetailPanel gates on
 * canEdit plus REFRESHABLE_ORIGINS above) and never touches the token
 * itself. The taxonomy of 409/503/400/422 refusals from the refresh door is
 * rendered through the shared error-map (`err.message`), which already maps
 * each backend code to a distinct, actionable sentence rather than a single
 * generic failure toast — see `frontend/src/lib/error-map.ts`.
 */
export function SourceRefreshAction({ dataset }: SourceRefreshActionProps) {
  const { t } = useTranslation('dataset');
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState('');
  const [error, setError] = useState<string | null>(null);
  const refreshMutation = useRefreshDataset();
  // Limit 1: only interested in whether the most recent run is still active,
  // so the trigger can be disabled ahead of a 409 dataset_busy rather than
  // only reacting to one after the click. Self-polls while active (see
  // useDatasetRefreshRuns), so this also picks up a terminal transition
  // without a manual refresh.
  const { data: runsData } = useDatasetRefreshRuns(dataset.id, { limit: 1 });
  const latestRun = runsData?.runs[0];
  const latestRunId = latestRun?.id;
  const latestRunStatus = latestRun?.status;
  const isBusy = isRunActive(latestRunStatus);

  // fix(#1285 codex round 1, corrected round 2): the dispatch-time
  // invalidation in useRefreshDataset fires before the worker has done
  // anything (the run is still "pending"), so freshness/health/
  // last_refreshed_at only actually change once OUR dispatched run leaves
  // pending/running. Round 1 caught that transition by comparing successive
  // polls, but a fast strategy (postgis remeasurement can finish in ~1s)
  // can already be terminal on the FIRST poll after dispatch — no "active"
  // sample is ever observed, so a transition-based check never fires.
  // Tracking the specific run_id from the 202 response instead: invalidate
  // the first time THAT run is observed terminal, regardless of whether it
  // was ever seen active. `invalidatedRunIdRef` makes it fire once per run.
  const dispatchedRunIdRef = useRef<string | null>(null);
  const invalidatedRunIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (!latestRunId || latestRunId !== dispatchedRunIdRef.current) return;
    if (isRunActive(latestRunStatus)) return;
    if (invalidatedRunIdRef.current === latestRunId) return;
    invalidatedRunIdRef.current = latestRunId;
    queryClient.invalidateQueries({ queryKey: queryKeys.datasets.detail(dataset.id) });
  }, [latestRunId, latestRunStatus, dataset.id, queryClient]);

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) {
      // Cleared on cancel/close too: a dismissed dialog must not leave a
      // typed token sitting in this component's state any longer than the
      // confirm path does.
      setToken('');
      setError(null);
    }
  };

  const handleConfirm = async () => {
    setError(null);
    const submittedToken = token.trim() || undefined;
    // Cleared before the request settles. Once handed to mutateAsync the
    // token lives only in the in-flight request body; this component never
    // reconstructs it from state again, on either the success or error path.
    setToken('');
    try {
      const result = await refreshMutation.mutateAsync({
        datasetId: dataset.id,
        token: submittedToken,
      });
      dispatchedRunIdRef.current = result.run_id;
      setOpen(false);
      toast.success(t('sourcePanel.refresh.toastAccepted', { runId: result.run_id }));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('sourcePanel.refresh.errors.unknown'));
    }
  };

  return (
    <>
      <div className="flex flex-col items-end gap-1">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={isBusy}
          onClick={() => setOpen(true)}
        >
          <RefreshCw className="me-2 h-4 w-4" />
          {t('sourcePanel.refresh.action')}
        </Button>
        {isBusy && (
          <p className="text-xs text-muted-foreground">{t('sourcePanel.refresh.busyHint')}</p>
        )}
      </div>

      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('sourcePanel.refresh.dialogTitle')}</DialogTitle>
            <DialogDescription>{t('sourcePanel.refresh.dialogDescription')}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="source-refresh-token">{t('sourcePanel.refresh.tokenLabel')}</Label>
              <Input
                id="source-refresh-token"
                type="password"
                autoComplete="off"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                placeholder={t('sourcePanel.refresh.tokenPlaceholder')}
                disabled={refreshMutation.isPending}
              />
              <p className="text-xs text-muted-foreground">{t('sourcePanel.refresh.tokenHint')}</p>
            </div>

            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
              disabled={refreshMutation.isPending}
            >
              {t('common:cancel')}
            </Button>
            <Button type="button" onClick={() => void handleConfirm()} disabled={refreshMutation.isPending}>
              {refreshMutation.isPending && <Loader2 className="me-2 h-4 w-4 animate-spin" />}
              {t('sourcePanel.refresh.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
