import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ApiError } from '@/api/client';
import { useRestorePreviousVersion } from '@/components/dataset/hooks/use-dataset';
import { Input } from '@/components/ui/input';
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

const REFUSAL_CODES = [
  'dataset_busy',
  'previous_version_changed',
  'no_previous_version',
  'restore_not_applicable',
] as const;

function refusalCode(error: unknown): (typeof REFUSAL_CODES)[number] | null {
  if (!(error instanceof ApiError)) return null;
  const code = (error.body as { code?: unknown } | undefined)?.code;
  return REFUSAL_CODES.find((c) => c === code) ?? null;
}

interface RestoreVersionDialogProps {
  datasetId: string;
  datasetTitle: string;
  versionNumber: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called with the queued run's id so the page watcher sees it settle. */
  onQueued?: (runId: string) => void;
}

export function RestoreVersionDialog({
  datasetId,
  datasetTitle,
  versionNumber,
  open,
  onOpenChange,
  onQueued,
}: RestoreVersionDialogProps) {
  const { t } = useTranslation('dataset');
  const [confirmName, setConfirmName] = useState('');
  const restore = useRestorePreviousVersion();

  useEffect(() => {
    if (open) {
      setConfirmName('');
      restore.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset() identity is stable; reopen is the only trigger we want
  }, [open]);

  async function handleRestore() {
    try {
      const result = await restore.mutateAsync({ datasetId, versionNumber });
      onQueued?.(result.run_id);
      toast.success(t('restoreDialog.queued', { number: versionNumber }));
      onOpenChange(false);
    } catch {
      // error displayed inline -- keep dialog open
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t('restoreDialog.title', { number: versionNumber })}</AlertDialogTitle>
          <AlertDialogDescription>{t('restoreDialog.description', { number: versionNumber })}</AlertDialogDescription>
        </AlertDialogHeader>

        <ul className="list-disc ps-5 text-sm space-y-1">
          <li>{t('restoreDialog.consequenceEdits', { number: versionNumber })}</li>
          <li>{t('restoreDialog.consequenceMosaics')}</li>
        </ul>

        <div className="space-y-2">
          <p id="dataset-restore-confirm-prompt" className="text-sm font-medium">
            {t('restoreDialog.confirmPrompt')}
          </p>
          <Input
            value={confirmName}
            onChange={(e) => setConfirmName(e.target.value)}
            placeholder={datasetTitle}
            aria-labelledby="dataset-restore-confirm-prompt"
          />
        </div>

        {restore.error && (
          <p className="text-sm text-destructive">
            {refusalCode(restore.error)
              ? t(`restoreDialog.refusal.${refusalCode(restore.error)}`)
              : restore.error instanceof Error
                ? restore.error.message
                : t('restoreDialog.failed')}
          </p>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel>{t('common:cancel')}</AlertDialogCancel>
          <AlertDialogAction
            onClick={(e) => {
              e.preventDefault();
              handleRestore();
            }}
            disabled={confirmName !== datasetTitle || restore.isPending}
            variant="destructive"
          >
            {restore.isPending ? t('restoreDialog.restoring') : t('restoreDialog.restore')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
