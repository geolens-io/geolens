import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { useUpdateCollection } from '@/components/collections/hooks/use-collections';
import type { CollectionResponse, CollectionUpdateRequest } from '@/types/api';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

interface CollectionEditDialogProps {
  collection: CollectionResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CollectionEditDialog({ collection, open, onOpenChange }: CollectionEditDialogProps) {
  const { t } = useTranslation('collections');
  const [name, setName] = useState(collection.name);
  const [description, setDescription] = useState(collection.description ?? '');
  const updateCollection = useUpdateCollection();

  useEffect(() => {
    if (open) {
      setName(collection.name);
      setDescription(collection.description ?? '');
      updateCollection.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, collection.name, collection.description]);

  const hasChanges =
    name !== collection.name ||
    description !== (collection.description ?? '');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    const data: CollectionUpdateRequest = {};
    if (name !== collection.name) data.name = name.trim();
    if (description !== (collection.description ?? '')) {
      data.description = description.trim() || null;
    }

    if (Object.keys(data).length === 0) {
      onOpenChange(false);
      return;
    }

    try {
      await updateCollection.mutateAsync({ id: collection.id, data });
      onOpenChange(false);
      toast.success(t('toasts.updated'));
    } catch {
      // error displayed inline
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('editDialog.title')}</DialogTitle>
          <DialogDescription>
            {t('editDialog.description')}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="edit-collection-name">{t('editDialog.nameLabel')}</Label>
            <Input
              id="edit-collection-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="edit-collection-description">{t('editDialog.descriptionLabel')}</Label>
            <textarea
              id="edit-collection-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          {updateCollection.error && (
            <p className="text-sm text-destructive">
              {updateCollection.error instanceof Error
                ? updateCollection.error.message
                : t('editDialog.errorFallback')}
            </p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('common:cancel')}
            </Button>
            <Button
              type="submit"
              disabled={updateCollection.isPending || !hasChanges || !name.trim()}
            >
              {updateCollection.isPending && <Loader2 className="size-4 animate-spin" />}
              {updateCollection.isPending ? t('editDialog.saving') : t('common:save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
