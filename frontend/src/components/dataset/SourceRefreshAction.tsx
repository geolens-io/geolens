import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { useRefreshDataset } from '@/components/dataset/hooks/use-dataset';
import { datasetOrigin } from '@/components/dataset/OriginBadge';
import { useDrawingStore } from '@/stores/drawing-store';
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
import type { DatasetRefreshWatch } from '@/components/dataset/hooks/use-dataset';

// fix(#1285 codex round 1): refresh-door origins. router_refresh.py dispatches
// by origin kind and routes everything it does not name through
// _resolve_service_origin(), which refuses with 409 refresh_not_applicable —
// so `upload` and `created` are NOT refreshable even though they have a
// resolvable origin. This is the one place that fact is encoded; DetailPanel
// imports it rather than gating on origin presence alone.
//
// feat(#1266): `stac` joins them. Its strategy re-reads the item document the
// asset was published in and follows the asset if the publisher moved it. One
// caveat this set cannot express: a STAC binding whose item identity cannot be
// verified — recorded before item ids were stored, on a catalog whose item
// URLs carry none — is refused by the door with 409 origin_unavailable. That
// is a per-dataset fact rather than a per-kind one, so it stays a refusal the
// error-map renders rather than a hidden control; a user who cannot refresh
// that dataset is told why and what to do about it.
export const REFRESHABLE_ORIGINS: ReadonlySet<DatasetOrigin> = new Set([
  'service',
  'postgis',
  'stac',
]);

interface SourceRefreshActionProps {
  dataset: DatasetResponse;
  /**
   * fix(#1285 codex round 4): the "sources" tab this control lives in is a
   * Radix TabsContent, which unmounts on tab switch — so any state tracking
   * a dispatched run (and the poll watching it) has to live somewhere that
   * survives that unmount, or a refresh that finishes while the user is on
   * another tab never gets its caches invalidated. Owned by the dataset page
   * via useDatasetRefreshWatch and handed down; this component only reports
   * a successful dispatch through `watch.trackDispatchedRun` and reads
   * `latestRun`/`isBusy` back, rather than polling or tracking on its own.
   */
  watch: DatasetRefreshWatch;
}

/**
 * "Refresh from source" trigger for the Source panel (#1285).
 *
 * Owns its own dialog, token field, and mutation, so a caller only has to
 * decide WHETHER to render it (DetailPanel gates on canEdit plus
 * REFRESHABLE_ORIGINS above) and supply the page-level `watch`. The taxonomy
 * of 409/503/400/422 refusals from the refresh door is rendered through the
 * shared error-map (`err.message`), which already maps each backend code to
 * a distinct, actionable sentence rather than a single generic failure toast
 * — see `frontend/src/lib/error-map.ts`.
 */
export function SourceRefreshAction({ dataset, watch }: SourceRefreshActionProps) {
  const { t } = useTranslation('dataset');
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState('');
  const [error, setError] = useState<string | null>(null);
  const refreshMutation = useRefreshDataset();
  // fix(#1285 codex round 3): _dispatch_postgis_refresh() (router_refresh.py)
  // rejects ANY nonempty token with 422 credential_not_applicable — a
  // registered table needs no service credential, and there is nothing else
  // in REFRESHABLE_ORIGINS to authenticate to. Recomputed here rather than
  // threaded in as a prop so this component stays self-contained; it is the
  // same derivation DetailPanel uses for the REFRESHABLE_ORIGINS gate.
  const origin = dataset.origin ?? datasetOrigin(dataset);
  const supportsToken = origin === 'service';
  const { isBusy } = watch;

  // fix(#1285 codex round 6, widened on completion): DatasetMap stays
  // mounted above DetailPanel regardless of which tab is active, so a
  // feature the user selected survives a switch to the Source tab — and the
  // hazard does not require an in-progress EDIT. The selection alone keeps
  // the pre-refresh GID and properties live: handleDeleteFeature acts on a
  // merely-selected feature immediately (no dirtiness involved), and a
  // later handleSaveEdit would too. Either can submit a stale GID against a
  // table a refresh already replaced — overwriting a freshly refreshed row,
  // or the wrong row entirely if GIDs were reassigned. So this blocks on
  // SELECTION presence, not edit dirtiness; scoped to THIS dataset via
  // targetDatasetId so a stale selection left over from a different
  // dataset's map can't false-positive block a refresh here.
  const selectedFeature = useDrawingStore((s) => s.selectedFeature);
  const targetDatasetId = useDrawingStore((s) => s.targetDatasetId);
  const hasSelectedFeature = targetDatasetId === dataset.id && selectedFeature !== null;

  const isDisabled = isBusy || hasSelectedFeature;

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
      // Reported to the page-level watch rather than a local ref — this call
      // is safe even if the user has already switched away from the Source
      // tab (and this component has unmounted) by the time the 202 arrives,
      // because `watch` is owned by the still-mounted page.
      watch.trackDispatchedRun(result.run_id);
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
          disabled={isDisabled}
          onClick={() => setOpen(true)}
        >
          <RefreshCw className="me-2 h-4 w-4" />
          {t('sourcePanel.refresh.action')}
        </Button>
        {isBusy ? (
          <p className="text-xs text-muted-foreground">{t('sourcePanel.refresh.busyHint')}</p>
        ) : hasSelectedFeature ? (
          <p className="text-xs text-muted-foreground">
            {t('sourcePanel.refresh.featureEditBlockedHint')}
          </p>
        ) : null}
      </div>

      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('sourcePanel.refresh.dialogTitle')}</DialogTitle>
            <DialogDescription>{t('sourcePanel.refresh.dialogDescription')}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {supportsToken && (
              <div className="space-y-2">
                <Label htmlFor="source-refresh-token">{t('sourcePanel.refresh.tokenLabel')}</Label>
                <Input
                  id="source-refresh-token"
                  type="password"
                  // fix(#1746): autoComplete="off" alone does not stop Chrome
                  // from offering a saved password on a password-type field —
                  // this is a request-only service token, so opt out of every
                  // password manager explicitly.
                  autoComplete="new-password"
                  data-1p-ignore
                  data-lpignore="true"
                  data-bwignore
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                  placeholder={t('sourcePanel.refresh.tokenPlaceholder')}
                  disabled={refreshMutation.isPending}
                />
                <p className="text-xs text-muted-foreground">{t('sourcePanel.refresh.tokenHint')}</p>
              </div>
            )}

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
