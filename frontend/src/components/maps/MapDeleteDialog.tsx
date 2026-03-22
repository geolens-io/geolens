import { useTranslation, Trans } from 'react-i18next';
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

interface MapDeleteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mapName: string;
  onConfirm: () => void;
  isDeleting: boolean;
}

export function MapDeleteDialog({
  open,
  onOpenChange,
  mapName,
  onConfirm,
  isDeleting,
}: MapDeleteDialogProps) {
  const { t } = useTranslation('builder');

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t('mapDelete.title')}</AlertDialogTitle>
          <AlertDialogDescription>
            <Trans i18nKey="mapDelete.description" t={t} values={{ mapName }} components={{ 1: <strong /> }} />
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isDeleting}>{t('common:cancel')}</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            disabled={isDeleting}
            variant="destructive"
          >
            {isDeleting ? t('mapDelete.deleting') : t('common:delete')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
