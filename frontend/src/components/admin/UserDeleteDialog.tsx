import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useDeleteUser } from '@/hooks/use-admin';
import type { UserResponse } from '@/types/api';
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

interface UserDeleteDialogProps {
  user: UserResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function UserDeleteDialog({ user, open, onOpenChange }: UserDeleteDialogProps) {
  const { t } = useTranslation('admin');
  const deleteUser = useDeleteUser();
  // fix(#438): UX-04 — deleting a user is the most destructive delete in the
  // app (irreversible, removes their data), yet it was a plain confirm while
  // dataset and collection deletes require typing the name. Match that guard.
  const [confirmName, setConfirmName] = useState('');

  useEffect(() => {
    if (open) {
      setConfirmName('');
      deleteUser.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset() identity is stable; reopen is the only trigger we want
  }, [open]);

  const isConfirmed = confirmName === user.username;

  async function handleDelete() {
    if (!isConfirmed) return;
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

        <div className="space-y-2">
          <p id="user-delete-confirm-prompt" className="text-sm font-medium">
            {t('userDelete.confirmPrompt', { username: user.username })}
          </p>
          <Input
            value={confirmName}
            onChange={(e) => setConfirmName(e.target.value)}
            placeholder={user.username}
            aria-labelledby="user-delete-confirm-prompt"
            autoComplete="off"
          />
        </div>

        {deleteUser.error && (
          <p className="text-sm text-destructive">
            {deleteUser.error instanceof Error ? deleteUser.error.message : t('userDelete.error')}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel>{t('common:cancel')}</AlertDialogCancel>
          <AlertDialogAction
            onClick={handleDelete}
            disabled={!isConfirmed || deleteUser.isPending}
            variant="destructive"
          >
            {deleteUser.isPending ? t('userDelete.deleting') : t('common:delete')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
