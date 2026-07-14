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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ApiKeySection } from './ApiKeySection';
import { RoleSelect } from './RoleSelect';
import { useAuthStore } from '@/stores/auth-store';

interface UserEditDialogProps {
  user: UserResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type AccountStatus = 'active' | 'pending' | 'suspended' | 'deactivated';

export function UserEditDialog({ user, open, onOpenChange }: UserEditDialogProps) {
  const { t } = useTranslation('admin');
  const currentUserId = useAuthStore((state) => state.user?.id);
  const isSelf = currentUserId === user.id;
  const canEditAuthority = !isSelf && user.status !== 'pending';
  const [email, setEmail] = useState(user.email ?? '');
  const [role, setRole] = useState(user.roles[0] ?? 'viewer');
  const [accountStatus, setAccountStatus] = useState<AccountStatus>(
    user.status as AccountStatus,
  );

  const updateUser = useUpdateUser();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    // Only send changed fields
    const data: {
      email?: string;
      role?: string;
      status?: 'active' | 'suspended' | 'deactivated';
    } = {};
    if (email !== (user.email ?? '')) data.email = email;
    if (canEditAuthority && role !== (user.roles[0] ?? 'viewer')) data.role = role;
    if (canEditAuthority && accountStatus !== user.status && accountStatus !== 'pending') {
      data.status = accountStatus;
    }

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
            <Label htmlFor={canEditAuthority ? 'edit-role' : undefined}>{t('userEdit.labels.role')}</Label>
            {!canEditAuthority ? (
              <p className="text-sm text-muted-foreground">{user.roles.join(', ') || '\u2014'}</p>
            ) : (
              <RoleSelect id="edit-role" value={role} onChange={setRole} />
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor={canEditAuthority ? 'edit-status' : undefined}>
              {t('userEdit.labels.status')}
            </Label>
            {!canEditAuthority ? (
              <div>
                <Badge variant="outline" className={userStatusColors[user.status]}>
                  {t(`users.status.${user.status}`)}
                </Badge>
              </div>
            ) : (
              <Select
                value={accountStatus}
                onValueChange={(value) => setAccountStatus(
                  value as Exclude<AccountStatus, 'pending'>,
                )}
              >
                <SelectTrigger id="edit-status">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">{t('users.status.active')}</SelectItem>
                  <SelectItem value="suspended">{t('users.status.suspended')}</SelectItem>
                  <SelectItem value="deactivated">{t('users.status.deactivated')}</SelectItem>
                </SelectContent>
              </Select>
            )}
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
