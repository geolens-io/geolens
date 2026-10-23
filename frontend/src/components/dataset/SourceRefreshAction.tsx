import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { ApiError } from '@/api/client';
import { useRefreshDataset } from '@/components/dataset/hooks/use-dataset';
import { datasetOrigin } from '@/components/dataset/OriginBadge';
import {
  ArcgisCredentialBlock,
  isExpired,
  type ArcgisCredentialBlockHandle,
} from '@/components/dataset/ArcgisCredentialBlock';
import { ServiceCredentialBlock } from '@/components/dataset/ServiceCredentialBlock';
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
import type { DatasetOrigin, DatasetResponse, ServiceAuthRequest } from '@/types/api';
import type { DatasetRefreshWatch } from '@/components/dataset/hooks/use-dataset';
import type { BlockedRunToAccept } from '@/components/dataset/SourcePanel';

// Refresh-door origins. router_refresh.py dispatches by origin kind and routes
// everything it does not name through _resolve_service_origin(), which refuses
// with 409 refresh_not_applicable, so `upload` and `created` are NOT
// refreshable even though they have a resolvable origin. DetailPanel imports
// this set rather than gating on origin presence alone.
//
// `stac` is included: its strategy re-reads the item document the asset was
// published in and follows the asset if the publisher moved it. A STAC binding
// whose item identity can't be verified (recorded before item ids were
// stored, on a catalog whose item URLs carry none) is refused by the door with
// 409 origin_unavailable. That is per-dataset, not per-kind, so it stays a
// refusal the error-map renders rather than a hidden control.
export const REFRESHABLE_ORIGINS: ReadonlySet<DatasetOrigin> = new Set([
  'service',
  'postgis',
  'stac',
]);

interface SourceRefreshActionProps {
  dataset: DatasetResponse;
  /**
   * The "sources" tab this control lives in is a Radix TabsContent, which
   * unmounts on tab switch, so state tracking a dispatched run (and the poll
   * watching it) must survive that unmount, or a refresh that finishes on
   * another tab never gets its caches invalidated. Owned by the dataset page
   * via useDatasetRefreshWatch; this component only reports a dispatch
   * through `watch.trackDispatchedRun` and reads `latestRun`/`isBusy`.
   */
  watch: DatasetRefreshWatch;
  /** False renders only the dialog, for accepting a held-back file replacement. */
  showTrigger?: boolean;
  acceptBlockedRun?: BlockedRunToAccept;
  onAcceptHandled?: () => void;
}

/**
 * "Refresh from source" trigger for the Source panel.
 *
 * Owns its dialog, token field and mutation, so a caller only decides WHETHER
 * to render it (DetailPanel gates on canEdit plus REFRESHABLE_ORIGINS above)
 * and supplies the page-level `watch`. The 409/503/400/422 refusals from the
 * refresh door are rendered through the shared error-map (`err.message`),
 * which maps each backend code to a distinct, actionable sentence.
 */
export function SourceRefreshAction({
  dataset,
  watch,
  showTrigger = true,
  acceptBlockedRun,
  onAcceptHandled,
}: SourceRefreshActionProps) {
  const { t } = useTranslation('dataset');
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState('');
  const [error, setError] = useState<string | null>(null);
  // The non-ArcGIS credential, built by ServiceCredentialBlock. `token` above
  // stays the ArcGIS-only field; the two are mutually exclusive on the wire
  // (reject_service_auth_conflict), as `isArcgisOrigin` below picks one block.
  const [serviceAuth, setServiceAuth] = useState<ServiceAuthRequest | undefined>(undefined);
  // Set on a 422 `service_token_required` refusal so the dialog stays open and
  // reveals a credential block keyed to the token field above, instead of a
  // generic inline error.
  const [serviceTokenRequired, setServiceTokenRequired] = useState(false);
  // Read synchronously in handleConfirm before `token` is trusted: the belt
  // effect inside ArcgisCredentialBlock may not have run yet (see the check).
  const credentialBlockRef = useRef<ArcgisCredentialBlockHandle>(null);
  const refreshMutation = useRefreshDataset();
  // _dispatch_postgis_refresh() (router_refresh.py) rejects ANY nonempty token
  // with 422 credential_not_applicable: a registered table needs no service
  // credential. Recomputed here rather than passed as a prop to stay
  // self-contained; DetailPanel derives the same for the REFRESHABLE_ORIGINS gate.
  const origin = dataset.origin ?? datasetOrigin(dataset);
  // A STAC origin takes the credential path: its refresh re-reads the catalog
  // over HTTP, so it takes the same four-way choice as WFS and OGC API
  // Features. A registered table takes none, and publishing a kept upload
  // contacts no source.
  const acceptingUpload = Boolean(acceptBlockedRun?.upload);
  const supportsToken = !acceptingUpload && (origin === 'service' || origin === 'stac');
  // The two service families that can hit this refusal read differently: ArcGIS
  // was asked a probe question and lost, so it gets the full sign-in taxonomy;
  // WFS and OGC API Features were refused outright with no probe, so they keep
  // the plain token field and are told the refusal was unconditional.
  const isArcgisOrigin = dataset.source_format === 'arcgis_featureserver';
  const { isBusy } = watch;
  const acceptBlockedRunId = acceptBlockedRun?.id;

  // DatasetMap stays mounted above DetailPanel whichever tab is active, so a
  // selected feature survives a switch to the Source tab, and the hazard needs
  // no in-progress EDIT: handleDeleteFeature acts on a merely-selected feature
  // immediately, and a later handleSaveEdit would too. Either can submit a
  // stale GID against a table a refresh already replaced, overwriting a freshly
  // refreshed row or the wrong one if GIDs were reassigned. So this blocks on
  // SELECTION presence, not edit dirtiness, scoped to THIS dataset via
  // targetDatasetId so a stale selection from another dataset's map can't
  // block a refresh here.
  const selectedFeature = useDrawingStore((s) => s.selectedFeature);
  const targetDatasetId = useDrawingStore((s) => s.targetDatasetId);
  const hasSelectedFeature = targetDatasetId === dataset.id && selectedFeature !== null;

  const isDisabled = isBusy || hasSelectedFeature;

  useEffect(() => {
    if (!acceptBlockedRunId) return;
    if (isBusy || hasSelectedFeature) {
      onAcceptHandled?.();
      return;
    }
    setOpen(true);
  }, [acceptBlockedRunId, hasSelectedFeature, isBusy, onAcceptHandled]);

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) {
      onAcceptHandled?.();
      // Cleared on cancel/close too: a dismissed dialog must not leave a
      // typed token sitting in this component's state any longer than the
      // confirm path does.
      setToken('');
      setError(null);
      setServiceTokenRequired(false);
      // The non-ArcGIS credential's block state resets for free (Radix Dialog
      // unmounts DialogContent on close); this clears the PARENT's copy, which
      // does not unmount with the child.
      setServiceAuth(undefined);
    }
  };

  const handleConfirm = async () => {
    if (isBusy || hasSelectedFeature) {
      handleOpenChange(false);
      return;
    }
    setError(null);
    // Recheck expiry synchronously before `token` (below) is trusted.
    // ArcgisCredentialBlock's belt effect and scheduled expiry timer are both
    // suspended by a backgrounded tab or system sleep, so if the user returns
    // and clicks immediately, neither has necessarily run and `token` can hold
    // a dead credential. Uses the same `isExpired` they call.
    if (
      isArcgisOrigin &&
      credentialBlockRef.current &&
      isExpired(credentialBlockRef.current.getExpiresAt(), Date.now())
    ) {
      setToken('');
      credentialBlockRef.current.markExpired();
      return;
    }
    const submittedToken = token.trim() || undefined;
    const submittedAuth = serviceAuth;
    // `token` is cleared before the request settles because
    // ArcgisCredentialBlock's "Signed in" display is DERIVED from this prop, so
    // clearing it blanks that display too.
    //
    // `serviceAuth` does NOT get the same treatment. ServiceCredentialBlock is
    // uncontrolled for its username/password/header fields: it only calls
    // `onAuthChange` when ITS state changes and has no prop to resync if the
    // parent clears `serviceAuth`. Clearing it here would leave the block
    // showing a filled-in credential (a 422 keeps the dialog open) while
    // `serviceAuth` was undefined, so a same-click retry silently sent
    // `auth: undefined`. It is retained until the request succeeds (cleared
    // there, and on cancel or close via `handleOpenChange`) so a retry resends
    // what the block still displays.
    setToken('');
    try {
      const result = await refreshMutation.mutateAsync({
        datasetId: dataset.id,
        token: supportsToken && isArcgisOrigin ? submittedToken : undefined,
        auth: supportsToken && !isArcgisOrigin ? submittedAuth : undefined,
        acceptBlockedRunId,
        ...(acceptBlockedRun?.verificationPolicy
          ? { verificationPolicy: acceptBlockedRun.verificationPolicy }
          : {}),
      });
      // Reported to the page-level watch rather than a local ref, so this is
      // safe even if the user has switched away from the Source tab (unmounting
      // this component) by the time the 202 arrives: `watch` lives on the page.
      watch.trackDispatchedRun(result.run_id);
      setServiceAuth(undefined);
      setOpen(false);
      onAcceptHandled?.();
      toast.success(t(
        acceptingUpload ? 'sourcePanel.refresh.uploadToastAccepted' : 'sourcePanel.refresh.toastAccepted',
        { runId: result.run_id },
      ));
    } catch (err) {
      // A 422 `service_token_required` gets its own inline credential block
      // rather than the generic error paragraph. The body carries only a stable
      // code plus an English diagnostic aimed at an API client, which must never
      // reach the DOM; this component's own copy explains the refusal.
      if (err instanceof ApiError && err.status === 422) {
        const body = err.body as { code?: string } | undefined;
        if (body?.code === 'service_token_required') {
          setServiceTokenRequired(true);
          return;
        }
        // The shared copy points at a URL field this dialog doesn't have.
        if (body?.code === 'credential_over_http') {
          setError(t('common:errors.credentialOverHttpRefresh'));
          return;
        }
      }
      setError(err instanceof Error ? err.message : t('sourcePanel.refresh.errors.unknown'));
    }
  };

  return (
    <>
      {showTrigger && (
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
      )}

      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t(acceptingUpload
                ? 'sourcePanel.refresh.uploadReviewDialogTitle'
                : acceptBlockedRunId
                  ? 'sourcePanel.refresh.reviewDialogTitle'
                  : 'sourcePanel.refresh.dialogTitle')}
            </DialogTitle>
            <DialogDescription>
              {t(acceptingUpload
                ? 'sourcePanel.refresh.uploadReviewDialogDescription'
                : acceptBlockedRunId
                  ? 'sourcePanel.refresh.reviewDialogDescription'
                  : 'sourcePanel.refresh.dialogDescription')}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {supportsToken && serviceTokenRequired && isArcgisOrigin && (
              <div className="space-y-2">
                <p className="text-sm text-foreground">
                  {t('sourcePanel.refresh.credential.requiredTitle')}
                </p>
                <ArcgisCredentialBlock
                  ref={credentialBlockRef}
                  token={token}
                  onTokenChange={setToken}
                  disabled={refreshMutation.isPending}
                />
              </div>
            )}

            {supportsToken && !(serviceTokenRequired && isArcgisOrigin) && isArcgisOrigin && (
              <div className="space-y-2">
                <Label htmlFor="source-refresh-token">{t('sourcePanel.refresh.tokenLabel')}</Label>
                <Input
                  id="source-refresh-token"
                  type="password"
                  // autoComplete="off" alone doesn't stop Chrome offering a saved
                  // password on a password-type field; this is a request-only
                  // service token, so opt out of every password manager.
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

            {/* WFS and OGC API Features now get the same
                four-way credential choice the import wizard offers, in
                place of the bearer-only field above. */}
            {supportsToken && !isArcgisOrigin && (
              <div className="space-y-2">
                {serviceTokenRequired && (
                  <p className="text-sm text-foreground">
                    {t('sourcePanel.refresh.credential.wfs.intro')}
                  </p>
                )}
                <ServiceCredentialBlock
                  onAuthChange={setServiceAuth}
                  disabled={refreshMutation.isPending}
                />
                {serviceTokenRequired && (
                  <p className="text-xs text-muted-foreground">
                    {/* The way out differs by origin — a STAC
                        dataset has no Re-Upload dialog, it is re-imported
                        from the catalog. */}
                    {t(
                      origin === 'stac'
                        ? 'sourcePanel.refresh.credential.stac.escapeHatch'
                        : 'sourcePanel.refresh.credential.wfs.escapeHatch',
                    )}
                  </p>
                )}
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
              {t(acceptingUpload ? 'sourcePanel.refresh.uploadConfirm' : 'sourcePanel.refresh.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
