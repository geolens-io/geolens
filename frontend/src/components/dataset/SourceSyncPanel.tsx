import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { ApiError } from '@/api/client';
import type { SyncAutomation, SyncCadence, SyncSource } from '@/api/dataset-sync';
import { SourceSyncDialog } from '@/components/dataset/SourceSyncDialog';
import {
  useDatasetSync,
  useDeleteDatasetSync,
  usePauseDatasetSync,
  useResumeDatasetSync,
  useRunDatasetSync,
} from '@/components/dataset/hooks/use-dataset-sync';
import { useDatasetRefreshRuns } from '@/components/dataset/hooks/use-dataset';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateTimeUtc } from '@/lib/format';
import { useEdition } from '@/hooks/use-edition';
import type { DatasetResponse } from '@/types/api';

interface SourceSyncPanelProps {
  dataset: DatasetResponse;
  canEdit: boolean;
  onRunDispatched?: (runId: string) => void;
}

function sourceFromDataset(dataset: DatasetResponse): SyncSource | null {
  if ((dataset.origin ?? null) !== 'service') return null;
  const ref = dataset.origin_ref as Record<string, unknown> | null;
  if (ref?.kind !== 'service' || ref.service_type !== 'arcgis_featureserver') return null;
  if (typeof ref.url !== 'string' || (typeof ref.layer_id !== 'string' && typeof ref.layer_id !== 'number')) return null;
  const layerId = Number(ref.layer_id);
  if (!Number.isInteger(layerId) || layerId < 0) return null;
  try {
    const sourceUrl = new URL(ref.url);
    if (sourceUrl.protocol !== 'https:' || sourceUrl.username || sourceUrl.password) return null;
    sourceUrl.search = '';
    sourceUrl.hash = '';
    return {
      connector: 'arcgis_feature_server',
      service_url: sourceUrl.toString(),
      layer_id: layerId,
    };
  } catch {
    return null;
  }
}

function cadenceLabel(cadence: SyncCadence, t: ReturnType<typeof useTranslation>['t']): string {
  const time = cadence.kind === 'hourly'
    ? `:${String(cadence.minute).padStart(2, '0')}`
    : `${String(cadence.hour).padStart(2, '0')}:${String(cadence.minute).padStart(2, '0')}`;
  if (cadence.kind === 'weekly') return t('sourcePanel.sync.cadence.weeklyAt', { weekday: t(`sourcePanel.sync.weekday.${cadence.weekday}`), time });
  return t(`sourcePanel.sync.cadence.${cadence.kind}At`, { time });
}

function statusClass(status: SyncAutomation['status']): string {
  if (status === 'enabled') return 'border-success/30 bg-success/10 text-success';
  if (status === 'paused') return 'border-warning/30 bg-warning/10 text-warning';
  return 'border-border bg-muted text-muted-foreground';
}

function errorCode(error: unknown): string | undefined {
  if (!(error instanceof ApiError) || !error.body || typeof error.body !== 'object') return undefined;
  const code = (error.body as { code?: unknown }).code;
  return typeof code === 'string' ? code : undefined;
}

const occurrenceErrorKeys: Record<string, string> = {
  admission_metadata_error: 'admissionMetadataError',
  admission_invalid: 'admissionInvalid',
  admission_failed: 'admissionFailed',
  source_changed: 'sourceChanged',
  local_edits_changed: 'localEditsChanged',
  credential_expired: 'credentialExpired',
};

function occurrenceErrorMessage(
  occurrence: NonNullable<SyncAutomation['last_occurrence']>,
  t: ReturnType<typeof useTranslation>['t'],
): string | null {
  if (occurrence.state !== 'failed' && occurrence.state !== 'expired') return null;
  const safeErrorKey = occurrence.error_code ? occurrenceErrorKeys[occurrence.error_code] : undefined;
  if (safeErrorKey) return t(`sourcePanel.sync.errors.occurrenceError.${safeErrorKey}`);
  return t(occurrence.state === 'expired'
    ? 'sourcePanel.sync.errors.occurrenceError.expired'
    : 'sourcePanel.sync.errors.occurrenceError.failed');
}

export function SourceSyncPanel({ dataset, canEdit, onRunDispatched }: SourceSyncPanelProps) {
  const { t } = useTranslation('dataset');
  const { features, isLoading: editionLoading, isResolved } = useEdition();
  const source = useMemo(() => sourceFromDataset(dataset), [dataset]);
  const hasCapability = features.includes('scheduled_sync');
  const sync = useDatasetSync(dataset.id, hasCapability && Boolean(source));
  const automation = sync.data ?? null;
  useDatasetRefreshRuns(dataset.id, { limit: 1, pollWhenScheduled: Boolean(automation) });
  const run = useRunDatasetSync();
  const pause = usePauseDatasetSync();
  const resume = useResumeDatasetSync();
  const detach = useDeleteDatasetSync();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [detachOpen, setDetachOpen] = useState(false);
  const [enableOpen, setEnableOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (sync.isError) setActionError(t('sourcePanel.sync.errors.loadFailed'));
  }, [sync.error, sync.isError, t]);

  if (editionLoading || !isResolved) {
    return <Skeleton className="h-40 w-full" aria-label={t('sourcePanel.sync.loading')} />;
  }

  if (!hasCapability) {
    return (
      <Card density="compact">
        <CardHeader><CardTitle level={2}>{t('sourcePanel.sync.title')}</CardTitle></CardHeader>
        <CardContent><p className="text-sm text-muted-foreground">{t('sourcePanel.sync.unavailable')}</p></CardContent>
      </Card>
    );
  }

  if (!source) {
    return (
      <Card density="compact">
        <CardHeader><CardTitle level={2}>{t('sourcePanel.sync.title')}</CardTitle></CardHeader>
        <CardContent><p className="text-sm text-muted-foreground">{t('sourcePanel.sync.unsupportedSource')}</p></CardContent>
      </Card>
    );
  }

  if (sync.isLoading) return <Skeleton className="h-40 w-full" aria-label={t('sourcePanel.sync.loading')} />;

  async function runNow() {
    if (!automation) return;
    setActionError(null);
    try {
      const result = await run.mutateAsync({ datasetId: dataset.id, revision: automation.revision });
      onRunDispatched?.(result.run_id);
      toast.success(t('sourcePanel.sync.runAccepted'));
    } catch (error) {
      const code = errorCode(error);
      setActionError(code === 'sync_not_eligible'
        ? t('sourcePanel.sync.errors.notEligible')
        : code === 'revision_conflict'
          ? t('sourcePanel.sync.errors.revisionConflict')
          : t('sourcePanel.sync.errors.runFailed'));
    }
  }

  async function toggleStatus() {
    if (!automation) return;
    if (automation.status !== 'enabled') {
      setEnableOpen(true);
      return;
    }
    setActionError(null);
    try {
      await pause.mutateAsync({ datasetId: dataset.id, revision: automation.revision });
      toast.success(t('sourcePanel.sync.paused'));
    } catch (error) {
      const code = errorCode(error);
      setActionError(code === 'qualification_required'
        ? t('sourcePanel.sync.errors.qualificationRequired')
        : code === 'revision_conflict'
          ? t('sourcePanel.sync.errors.revisionConflict')
          : t('sourcePanel.sync.errors.statusFailed'));
    }
  }

  async function confirmEnable() {
    if (!automation) return;
    setActionError(null);
    try {
      await resume.mutateAsync({ datasetId: dataset.id, revision: automation.revision });
      setEnableOpen(false);
      toast.success(t('sourcePanel.sync.enabled'));
    } catch (error) {
      const code = errorCode(error);
      setActionError(code === 'qualification_required'
        ? t('sourcePanel.sync.errors.qualificationRequired')
        : code === 'revision_conflict'
          ? t('sourcePanel.sync.errors.revisionConflict')
          : t('sourcePanel.sync.errors.statusFailed'));
    }
  }

  async function confirmDetach() {
    if (!automation) return;
    setActionError(null);
    try {
      await detach.mutateAsync({ datasetId: dataset.id, revision: automation.revision });
      setDetachOpen(false);
      toast.success(t('sourcePanel.sync.detached'));
    } catch (error) {
      setActionError(errorCode(error) === 'revision_conflict'
        ? t('sourcePanel.sync.errors.revisionConflict')
        : (error instanceof Error ? error.message : t('sourcePanel.sync.errors.detachFailed')));
      sync.refetch();
    }
  }

  if (!automation) {
    return (
      <>
        <Card density="compact">
          <CardHeader>
            <CardTitle level={2}>{t('sourcePanel.sync.title')}</CardTitle>
            {canEdit && <CardAction><Button size="sm" onClick={() => setDialogOpen(true)}>{t('sourcePanel.sync.setup')}</Button></CardAction>}
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{canEdit ? t('sourcePanel.sync.notConfigured') : t('sourcePanel.sync.reader')}</p>
            {actionError && <p role="alert" className="mt-3 text-sm text-destructive">{actionError}</p>}
          </CardContent>
        </Card>
        <SourceSyncDialog datasetId={dataset.id} source={source} automation={null} open={dialogOpen} onOpenChange={setDialogOpen} onRevisionConflict={() => sync.refetch()} />
      </>
    );
  }

  const actionPending = run.isPending || pause.isPending || resume.isPending || detach.isPending;
  const occurrenceError = automation.last_occurrence
    ? occurrenceErrorMessage(automation.last_occurrence, t)
    : null;
  return (
    <>
      <Card>
        <CardHeader>
          <div>
            <CardTitle level={2}>{t('sourcePanel.sync.title')}</CardTitle>
            <CardDescription>{t('sourcePanel.sync.description')}</CardDescription>
          </div>
          <CardAction><Badge variant="outline" className={statusClass(automation.status)} aria-live="polite" aria-atomic="true">{t(`sourcePanel.sync.status.${automation.status}`)}</Badge></CardAction>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <dl className="grid gap-3 sm:grid-cols-2">
            <div><dt className="text-xs text-muted-foreground">{t('sourcePanel.sync.cadenceLabel')}</dt><dd className="mt-1 text-sm font-medium">{cadenceLabel(automation.cadence, t)} UTC</dd></div>
            <div><dt className="text-xs text-muted-foreground">{t('sourcePanel.sync.nextDue')}</dt><dd className="mt-1 text-sm font-medium">{formatDateTimeUtc(automation.next_due_at)}</dd></div>
            <div><dt className="text-xs text-muted-foreground">{t('sourcePanel.sync.credential')}</dt><dd className="mt-1 text-sm font-medium">{automation.credential?.display_name ?? t('sourcePanel.sync.publicSource')}</dd></div>
            <div><dt className="text-xs text-muted-foreground">{t('sourcePanel.sync.lastRun')}</dt><dd className="mt-1 text-sm font-medium">{automation.last_occurrence ? <>{automation.last_occurrence.scheduled_for ? formatDateTimeUtc(automation.last_occurrence.scheduled_for) : t('sourcePanel.sync.verificationRun')}<span className="text-muted-foreground"> · {t(`sourcePanel.sync.occurrenceState.${automation.last_occurrence.state}`)}</span></> : t('sourcePanel.sync.noRuns')}</dd></div>
          </dl>
          {!automation.eligibility.eligible && (
            <p className="rounded-md border border-warning/30 bg-warning/5 p-3 text-sm text-warning">{automation.eligibility.reasons.map((reason) => t(`sourcePanel.sync.eligibility.${reason}`)).join(' ')}</p>
          )}
          {automation.pause_reason && <p className="text-sm text-muted-foreground">{t(`sourcePanel.sync.pauseReason.${automation.pause_reason}`)}</p>}
          {occurrenceError && <p role="alert" className="rounded-md border border-warning/30 bg-warning/5 p-3 text-sm text-warning">{occurrenceError}</p>}
          {actionError && <p role="alert" className="text-sm text-destructive">{actionError}</p>}
          {canEdit && (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => setDialogOpen(true)} disabled={actionPending}>{t('sourcePanel.sync.edit')}</Button>
              <Button size="sm" variant="outline" onClick={runNow} disabled={actionPending}>
                {run.isPending && <Loader2 data-icon="inline-start" className="animate-spin" />}{t('sourcePanel.sync.runNow')}
              </Button>
              <Button size="sm" variant="outline" onClick={toggleStatus} disabled={actionPending}>
                {(pause.isPending || resume.isPending) && <Loader2 data-icon="inline-start" className="animate-spin" />}
                {automation.status === 'enabled' ? t('sourcePanel.sync.pause') : t('sourcePanel.sync.enable')}
              </Button>
              <Button size="sm" variant="destructive" onClick={() => setDetachOpen(true)} disabled={actionPending}>{t('sourcePanel.sync.detach')}</Button>
            </div>
          )}
        </CardContent>
      </Card>
      <SourceSyncDialog datasetId={dataset.id} source={source} automation={automation} open={dialogOpen} onOpenChange={setDialogOpen} onRevisionConflict={() => sync.refetch()} />
      <AlertDialog open={detachOpen} onOpenChange={setDetachOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('sourcePanel.sync.detachTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('sourcePanel.sync.detachDescription')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={detach.isPending}>{t('sourcePanel.refresh.cancel')}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" disabled={detach.isPending} onClick={confirmDetach}>{t('sourcePanel.sync.detach')}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog open={enableOpen} onOpenChange={setEnableOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('sourcePanel.sync.enableTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('sourcePanel.sync.enableDescription')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={resume.isPending}>{t('sourcePanel.refresh.cancel')}</AlertDialogCancel>
            <AlertDialogAction disabled={resume.isPending} onClick={confirmEnable}>
              {resume.isPending && <Loader2 data-icon="inline-start" className="animate-spin" />}{t('sourcePanel.sync.enable')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
