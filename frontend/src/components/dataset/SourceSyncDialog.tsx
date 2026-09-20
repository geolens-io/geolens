import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { ApiError } from '@/api/client';
import type { SyncAutomation, SyncCadence, SyncSource } from '@/api/dataset-sync';
import {
  useCreateDatasetSync,
  useCreateSyncCredential,
  useReplaceSyncCredential,
  useSyncCredentials,
  useUpdateDatasetSync,
} from '@/components/dataset/hooks/use-dataset-sync';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

type CredentialChoice = 'public' | 'new' | string;

interface SourceSyncDialogProps {
  datasetId: string;
  source: SyncSource;
  automation: SyncAutomation | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRevisionConflict: () => void;
}

function cadenceFromAutomation(automation: SyncAutomation | null): SyncCadence {
  return automation?.cadence ?? { kind: 'daily', hour: 2, minute: 0 };
}

function apiErrorCode(error: unknown): string | undefined {
  if (!(error instanceof ApiError) || !error.body || typeof error.body !== 'object') return undefined;
  const body = error.body as { code?: unknown };
  return typeof body.code === 'string' ? body.code : undefined;
}

export function SourceSyncDialog({
  datasetId,
  source,
  automation,
  open,
  onOpenChange,
  onRevisionConflict,
}: SourceSyncDialogProps) {
  const { t } = useTranslation('dataset');
  const credentials = useSyncCredentials(datasetId, open);
  const createAutomation = useCreateDatasetSync();
  const updateAutomation = useUpdateDatasetSync();
  const createCredential = useCreateSyncCredential();
  const replaceCredential = useReplaceSyncCredential();
  const [cadence, setCadence] = useState<SyncCadence>(() => cadenceFromAutomation(automation));
  const [credentialChoice, setCredentialChoice] = useState<CredentialChoice>('public');
  const [credentialName, setCredentialName] = useState('');
  const [token, setToken] = useState('');
  const [replaceToken, setReplaceToken] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setToken('');
      setError(null);
      return;
    }
    setCadence(cadenceFromAutomation(automation));
    setCredentialChoice(automation?.credential?.id ?? 'public');
    setCredentialName(automation?.credential?.display_name ?? '');
    setReplaceToken(false);
  }, [automation, open]);

  const pending = createAutomation.isPending
    || updateAutomation.isPending
    || createCredential.isPending
    || replaceCredential.isPending;
  const isNewCredential = credentialChoice === 'new';
  const selectedCredential = credentials.data?.find((item) => item.id === credentialChoice);

  const updateCadence = (nextKind: SyncCadence['kind']) => {
    setCadence((current) => {
      if (nextKind === 'hourly') return { kind: 'hourly', minute: current.minute };
      if (nextKind === 'daily') return { kind: 'daily', hour: current.kind === 'hourly' ? 2 : current.hour, minute: current.minute };
      return {
        kind: 'weekly',
        weekday: current.kind === 'weekly' ? current.weekday : 0,
        hour: current.kind === 'hourly' ? 2 : current.hour,
        minute: current.minute,
      };
    });
  };

  const updateMinute = (value: string) => setCadence((current) => ({ ...current, minute: Number(value) }));
  const updateHour = (value: string) => {
    if (cadence.kind !== 'hourly') setCadence({ ...cadence, hour: Number(value) });
  };
  const updateWeekday = (value: string) => {
    if (cadence.kind === 'weekly') setCadence({ ...cadence, weekday: Number(value) });
  };

  async function handleSubmit() {
    setError(null);
    if (isNewCredential && (!credentialName.trim() || !token.trim())) {
      setError(t('sourcePanel.sync.form.credentialRequired'));
      return;
    }
    if (replaceToken && !token.trim()) {
      setError(t('sourcePanel.sync.form.tokenRequired'));
      return;
    }
    if (!Number.isInteger(cadence.minute) || cadence.minute < 0 || cadence.minute > 59
      || (cadence.kind !== 'hourly' && (!Number.isInteger(cadence.hour) || cadence.hour < 0 || cadence.hour > 23))
      || (cadence.kind === 'weekly' && (!Number.isInteger(cadence.weekday) || cadence.weekday < 0 || cadence.weekday > 6))) {
      setError(t('sourcePanel.sync.form.invalidTime'));
      return;
    }

    try {
      let credentialId: string | null | undefined = credentialChoice === 'public' ? null : credentialChoice;
      const clearCredential = Boolean(automation?.credential && credentialChoice === 'public');
      if (isNewCredential) {
        const created = await createCredential.mutateAsync({
          connector_name: 'arcgis_feature_server',
          allowed_origin: new URL(source.service_url).origin,
          display_name: credentialName.trim(),
          token: token.trim(),
        });
        credentialId = created.id;
      } else if (replaceToken && selectedCredential) {
        await replaceCredential.mutateAsync({ credentialId: selectedCredential.id, request: { token: token.trim() } });
      }

      if (automation) {
        await updateAutomation.mutateAsync({
          datasetId,
          request: {
            revision: automation.revision,
            cadence,
            ...(clearCredential ? { clear_credential: true } : credentialId ? { credential_id: credentialId } : {}),
          },
        });
      } else {
        await createAutomation.mutateAsync({
          datasetId,
          request: { source, cadence, ...(credentialId ? { credential_id: credentialId } : {}) },
        });
      }
      setToken('');
      onOpenChange(false);
    } catch (caught) {
      if (apiErrorCode(caught) === 'revision_conflict') onRevisionConflict();
      setError(apiErrorCode(caught) === 'revision_conflict'
        ? t('sourcePanel.sync.errors.revisionConflict')
        : t('sourcePanel.sync.errors.saveFailed'));
    } finally {
      setToken('');
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{automation ? t('sourcePanel.sync.editTitle') : t('sourcePanel.sync.setupTitle')}</DialogTitle>
          <DialogDescription>{t('sourcePanel.sync.dialogDescription')}</DialogDescription>
          <p className="text-sm text-muted-foreground">{t('sourcePanel.sync.verificationHelp')}</p>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <section aria-labelledby="sync-replacement-warning-title" className="rounded-md border border-warning/30 bg-warning/5 p-3 text-sm">
            <p id="sync-replacement-warning-title" className="font-medium">{t('sourcePanel.sync.replacementWarningTitle')}</p>
            <p className="mt-1">{t('sourcePanel.sync.replacementWarning')}</p>
          </section>
          <div className="flex flex-col gap-2">
            <Label htmlFor="sync-cadence">{t('sourcePanel.sync.form.cadence')}</Label>
            <Select value={cadence.kind} onValueChange={(value) => updateCadence(value as SyncCadence['kind'])}>
              <SelectTrigger id="sync-cadence" aria-label={t('sourcePanel.sync.form.cadence')} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="hourly">{t('sourcePanel.sync.cadence.hourly')}</SelectItem>
                  <SelectItem value="daily">{t('sourcePanel.sync.cadence.daily')}</SelectItem>
                  <SelectItem value="weekly">{t('sourcePanel.sync.cadence.weekly')}</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            {cadence.kind === 'weekly' && (
              <div className="flex flex-col gap-2">
                <Label htmlFor="sync-weekday">{t('sourcePanel.sync.form.weekday')}</Label>
                <Select value={String(cadence.weekday)} onValueChange={updateWeekday}>
                  <SelectTrigger id="sync-weekday" aria-label={t('sourcePanel.sync.form.weekday')} className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent><SelectGroup>{[0, 1, 2, 3, 4, 5, 6].map((day) => <SelectItem key={day} value={String(day)}>{t(`sourcePanel.sync.weekday.${day}`)}</SelectItem>)}</SelectGroup></SelectContent>
                </Select>
              </div>
            )}
            {cadence.kind !== 'hourly' && (
              <div className="flex flex-col gap-2">
                <Label htmlFor="sync-hour">{t('sourcePanel.sync.form.hour')}</Label>
                <Input id="sync-hour" type="number" min="0" max="23" value={cadence.hour} onChange={(event) => updateHour(event.target.value)} disabled={pending} />
              </div>
            )}
            <div className="flex flex-col gap-2">
              <Label htmlFor="sync-minute">{t('sourcePanel.sync.form.minute')}</Label>
              <Input id="sync-minute" type="number" min="0" max="59" value={cadence.minute} onChange={(event) => updateMinute(event.target.value)} disabled={pending} />
            </div>
          </div>
          <p className="text-xs text-foreground">{t('sourcePanel.sync.form.utc')}</p>

          <div className="flex flex-col gap-2">
            <Label htmlFor="sync-credential">{t('sourcePanel.sync.form.credential')}</Label>
            <Select value={credentialChoice} onValueChange={setCredentialChoice}>
              <SelectTrigger id="sync-credential" aria-label={t('sourcePanel.sync.form.credential')} className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="public">{t('sourcePanel.sync.form.publicSource')}</SelectItem>
                  <SelectItem value="new">{t('sourcePanel.sync.form.newCredential')}</SelectItem>
                  {credentials.data?.filter((item) => !item.revoked_at).map((credential) => (
                    <SelectItem key={credential.id} value={credential.id}>{credential.display_name}</SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            {credentials.isError && <p role="alert" className="text-sm text-destructive">{t('sourcePanel.sync.errors.credentialsUnavailable')}</p>}
          </div>

          {isNewCredential && (
            <div className="flex flex-col gap-2">
              <Label htmlFor="sync-credential-name">{t('sourcePanel.sync.form.credentialName')}</Label>
              <Input id="sync-credential-name" value={credentialName} onChange={(event) => setCredentialName(event.target.value)} disabled={pending} />
            </div>
          )}
          {(isNewCredential || replaceToken) && (
            <div className="flex flex-col gap-2">
              <Label htmlFor="sync-token">{t('sourcePanel.sync.form.token')}</Label>
              <Input id="sync-token" type="password" autoComplete="new-password" value={token} onChange={(event) => setToken(event.target.value)} disabled={pending} />
              <p className="text-xs text-muted-foreground">{t('sourcePanel.sync.form.tokenHint')}</p>
            </div>
          )}
          {selectedCredential && !isNewCredential && (
            <Button type="button" variant="outline" size="sm" onClick={() => setReplaceToken((value) => !value)} disabled={pending}>
              {replaceToken ? t('sourcePanel.sync.form.cancelReplace') : t('sourcePanel.sync.form.replaceToken')}
            </Button>
          )}
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>{t('sourcePanel.refresh.cancel')}</Button>
          <Button type="button" className="bg-foreground text-background hover:bg-foreground/90" onClick={handleSubmit} disabled={pending || credentials.isLoading}>
            {pending && <Loader2 data-icon="inline-start" className="animate-spin" />}
            {automation ? t('sourcePanel.sync.save') : t('sourcePanel.sync.createDraft')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
