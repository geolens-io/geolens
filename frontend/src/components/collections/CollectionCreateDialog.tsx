import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { useCreateCollection } from '@/hooks/use-collections';
import { queryKeys } from '@/lib/query-keys';
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

interface CollectionCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CollectionCreateDialog({ open, onOpenChange }: CollectionCreateDialogProps) {
  const { t } = useTranslation('collections');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const createCollection = useCreateCollection();
  const qc = useQueryClient();

  useEffect(() => {
    if (open) {
      setName('');
      setDescription('');
      createCollection.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await createCollection.mutateAsync({
        name: name.trim(),
        description: description.trim() || null,
      });
      // Invalidate + refetch all collection queries so the list updates
      // before the dialog closes. Use predicate to match any key starting
      // with 'collections' since prefix matching may not catch parameterized keys.
      await qc.invalidateQueries({
        predicate: (query) =>
          Array.isArray(query.queryKey) && query.queryKey[0] === 'collections',
      });
      onOpenChange(false);
      toast.success(t('toasts.created'));
    } catch {
      // error displayed inline
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('createDialog.title')}</DialogTitle>
          <DialogDescription>
            {t('createDialog.description')}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="collection-name">{t('createDialog.nameLabel')}</Label>
            <Input
              id="collection-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('createDialog.namePlaceholder')}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="collection-description">{t('createDialog.descriptionLabel')}</Label>
            <textarea
              id="collection-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder={t('createDialog.descriptionPlaceholder')}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          {createCollection.error && (
            <p className="text-sm text-destructive">
              {createCollection.error instanceof Error
                ? createCollection.error.message
                : t('createDialog.errorFallback')}
            </p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('common:cancel')}
            </Button>
            <Button
              type="submit"
              disabled={createCollection.isPending || !name.trim()}
            >
              {createCollection.isPending && <Loader2 className="size-4 animate-spin" />}
              {createCollection.isPending ? t('createDialog.creating') : t('common:create')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
