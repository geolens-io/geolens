import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { useUpdateUser } from '@/hooks/use-admin';
import { userStatusColors } from '@/lib/status-colors';
import type { UserResponse } from '@/types/api';
import { Badge } from '@/components/ui/badge';
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
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import { ApiKeySection } from './ApiKeySection';
import { RoleSelect } from './RoleSelect';

interface UserEditDialogProps {
  user: UserResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function UserEditDialog({ user, open, onOpenChange }: UserEditDialogProps) {
  const { t } = useTranslation('admin');
  const [email, setEmail] = useState(user.email ?? '');
  const [role, setRole] = useState(user.roles[0] ?? 'viewer');
  const [isActive, setIsActive] = useState(user.is_active);

  const updateUser = useUpdateUser();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    // Only send changed fields
    const data: { email?: string; role?: string; is_active?: boolean } = {};
    if (email !== (user.email ?? '')) data.email = email;
    if (role !== (user.roles[0] ?? 'viewer')) data.role = role;
    if (isActive !== user.is_active) data.is_active = isActive;

    if (Object.keys(data).length === 0) {
      onOpenChange(false);
      return;
    }

    try {
      await updateUser.mutateAsync({ userId: user.id, data });
      onOpenChange(false);
    } catch {
      // error displayed inline
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('userEdit.title')}</DialogTitle>
          <DialogDescription>{t('userEdit.description', { username: user.username })}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label>{t('userEdit.labels.username')}</Label>
            <p className="text-sm text-muted-foreground">{user.username}</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="edit-email">{t('userEdit.labels.email')}</Label>
            <Input
              id="edit-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t('userEdit.placeholder.email')}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="edit-role">{t('userEdit.labels.role')}</Label>
            <RoleSelect id="edit-role" value={role} onChange={setRole} />
          </div>
          <div className="space-y-2">
            <Label>{t('userEdit.labels.status')}</Label>
            <div>
              <Badge variant="outline" className={userStatusColors[user.status] ?? 'bg-muted text-muted-foreground border-border'}>
                {user.status === 'pending' ? t('users.status.pending') : t('users.status.active')}
              </Badge>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <Label htmlFor="edit-active">{t('userEdit.labels.active')}</Label>
            <Switch
              id="edit-active"
              checked={isActive}
              onCheckedChange={setIsActive}
            />
          </div>
          {updateUser.error && (
            <p className="text-sm text-destructive">
              {updateUser.error instanceof Error ? updateUser.error.message : t('userEdit.error')}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" type="button" onClick={() => onOpenChange(false)}>
              {t('common:cancel')}
            </Button>
            <Button type="submit" disabled={updateUser.isPending}>
              {updateUser.isPending && <Loader2 className="size-4 animate-spin" />}
              {updateUser.isPending ? t('userEdit.saving') : t('common:save')}
            </Button>
          </DialogFooter>
        </form>
        <Separator className="my-4" />
        <ApiKeySection userId={user.id} />
      </DialogContent>
    </Dialog>
  );
}
