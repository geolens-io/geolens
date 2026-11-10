import { useTranslation } from 'react-i18next';
import { useDeleteGroup } from '@/hooks/use-admin-groups';
import type { GroupResponse } from '@/types/api';
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

interface GroupDeleteDialogProps {
  group: GroupResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function GroupDeleteDialog({ group, open, onOpenChange }: GroupDeleteDialogProps) {
  const { t } = useTranslation('admin');
  const deleteGroup = useDeleteGroup();

  async function handleDelete(e: React.MouseEvent) {
    // The action closes the dialog on click; hold it open so a failure stays visible.
    e.preventDefault();
    try {
      await deleteGroup.mutateAsync(group.id);
      onOpenChange(false);
    } catch {
      // error displayed inline -- keep dialog open
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t('groups.delete.title', { name: group.name })}</AlertDialogTitle>
          <AlertDialogDescription>
            {t('groups.delete.description', { count: group.member_count })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        {deleteGroup.error && (
          <p role="alert" className="text-sm text-destructive">
            {deleteGroup.error.message}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel>{t('common:cancel')}</AlertDialogCancel>
          <AlertDialogAction onClick={handleDelete} disabled={deleteGroup.isPending} variant="destructive">
            {deleteGroup.isPending ? t('groups.delete.deleting') : t('common:delete')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
