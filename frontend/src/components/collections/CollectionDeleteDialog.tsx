import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import { useDeleteCollection } from '@/components/collections/hooks/use-collections';
import type { CollectionResponse } from '@/types/api';
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

interface CollectionDeleteDialogProps {
  collection: CollectionResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CollectionDeleteDialog({ collection, open, onOpenChange }: CollectionDeleteDialogProps) {
  const { t } = useTranslation('collections');
  const [confirmName, setConfirmName] = useState('');
  const deleteCollection = useDeleteCollection();
  const navigate = useNavigate();

  useEffect(() => {
    if (open) {
      setConfirmName('');
      deleteCollection.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const isConfirmed = confirmName === collection.name;

  async function handleDelete() {
    try {
      await deleteCollection.mutateAsync(collection.id);
      onOpenChange(false);
      toast.success(t('toasts.deleted'));
      navigate('/collections');
    } catch {
      // error displayed inline -- keep dialog open
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t('deleteDialog.title')}</AlertDialogTitle>
          <AlertDialogDescription>
            {t('deleteDialog.description', { name: collection.name })}
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-2">
          <p className="text-sm font-medium">{t('deleteDialog.confirmPrompt')}</p>
          <Input
            value={confirmName}
            onChange={(e) => setConfirmName(e.target.value)}
            placeholder={collection.name}
          />
        </div>

        {deleteCollection.error && (
          <p className="text-sm text-destructive">
            {deleteCollection.error instanceof Error
              ? deleteCollection.error.message
              : t('deleteDialog.errorFallback')}
          </p>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel>{t('common:cancel')}</AlertDialogCancel>
          <AlertDialogAction
            onClick={handleDelete}
            disabled={!isConfirmed || deleteCollection.isPending}
            variant="destructive"
          >
            {deleteCollection.isPending ? t('deleteDialog.deleting') : t('deleteDialog.deleteButton')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
