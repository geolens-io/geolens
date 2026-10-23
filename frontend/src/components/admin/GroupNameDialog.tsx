import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { useCreateGroup, useRenameGroup } from '@/hooks/use-admin-groups';
import type { GroupResponse } from '@/types/api';
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

interface GroupNameDialogProps {
  /** The group to rename; omitted when creating one. */
  group?: GroupResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function GroupNameDialog({ group, open, onOpenChange }: GroupNameDialogProps) {
  const { t } = useTranslation('admin');
  const [name, setName] = useState(group?.name ?? '');
  const create = useCreateGroup();
  const rename = useRenameGroup();
  const mutation = group ? rename : create;
  const trimmed = name.trim();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!trimmed) return;
    try {
      if (group) await rename.mutateAsync({ groupId: group.id, name: trimmed });
      else await create.mutateAsync(trimmed);
      onOpenChange(false);
    } catch {
      // error displayed inline -- keep dialog open
    }
  }

  const errorId = 'group-name-error';
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{group ? t('groups.rename.title') : t('groups.create.title')}</DialogTitle>
          <DialogDescription>
            {group ? t('groups.rename.description', { name: group.name }) : t('groups.create.description')}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="group-name">{t('groups.nameLabel')}</Label>
            <Input
              id="group-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={255}
              autoComplete="off"
              aria-invalid={mutation.error ? true : undefined}
              aria-describedby={mutation.error ? errorId : undefined}
            />
          </div>
          {mutation.error && (
            <p id={errorId} role="alert" className="text-sm text-destructive">
              {mutation.error.message}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" type="button" onClick={() => onOpenChange(false)}>
              {t('common:cancel')}
            </Button>
            <Button type="submit" disabled={mutation.isPending || !trimmed}>
              {mutation.isPending && <Loader2 className="size-4 animate-spin" />}
              {group ? t('common:save') : t('common:create')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
