import { useTranslation } from 'react-i18next';
import { useDeleteUser } from '@/hooks/use-admin';
import type { UserResponse } from '@/types/api';
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

interface UserDeleteDialogProps {
  user: UserResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function UserDeleteDialog({ user, open, onOpenChange }: UserDeleteDialogProps) {
  const { t } = useTranslation('admin');
  const deleteUser = useDeleteUser();

  async function handleDelete() {
    try {
      await deleteUser.mutateAsync(user.id);
      onOpenChange(false);
    } catch {
      // error displayed inline -- keep dialog open
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t('userDelete.title')}</AlertDialogTitle>
          <AlertDialogDescription>
            {t('userDelete.description', { username: user.username })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        {deleteUser.error && (
          <p className="text-sm text-destructive">
            {deleteUser.error instanceof Error ? deleteUser.error.message : t('userDelete.error')}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel>{t('common:cancel')}</AlertDialogCancel>
          <AlertDialogAction
            onClick={handleDelete}
            disabled={deleteUser.isPending}
            variant="destructive"
          >
            {deleteUser.isPending ? t('userDelete.deleting') : t('common:delete')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
