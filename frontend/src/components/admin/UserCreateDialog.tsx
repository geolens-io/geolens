import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { useCreateUser } from '@/hooks/use-admin';
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
import { RoleSelect } from './RoleSelect';

interface UserCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function UserCreateDialog({ open, onOpenChange }: UserCreateDialogProps) {
  const { t } = useTranslation('admin');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('viewer');

  const createUser = useCreateUser();

  // Reset form state when dialog opens
  useEffect(() => {
    if (open) {
      setUsername('');
      setEmail('');
      setPassword('');
      setRole('viewer');
    }
  }, [open]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await createUser.mutateAsync({
        username,
        password,
        email: email || undefined,
        role,
      });
      onOpenChange(false);
    } catch {
      // error displayed inline
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('userCreate.title')}</DialogTitle>
          <DialogDescription>{t('userCreate.description')}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="create-username">{t('userCreate.labels.username')}</Label>
            <Input
              id="create-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={3}
              placeholder={t('userCreate.placeholders.username')}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="create-email">{t('userCreate.labels.email')}</Label>
            <Input
              id="create-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder={t('userCreate.placeholders.email')}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="create-password">{t('userCreate.labels.password')}</Label>
            <Input
              id="create-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              placeholder={t('userCreate.placeholders.password')}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="create-role">{t('userCreate.labels.role')}</Label>
            <RoleSelect id="create-role" value={role} onChange={setRole} />
          </div>
          {createUser.error && (
            <p className="text-sm text-destructive">
              {createUser.error instanceof Error ? createUser.error.message : t('userCreate.error')}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" type="button" onClick={() => onOpenChange(false)}>
              {t('common:cancel')}
            </Button>
            <Button type="submit" disabled={createUser.isPending}>
              {createUser.isPending && <Loader2 className="size-4 animate-spin" />}
              {createUser.isPending ? t('userCreate.creating') : t('common:create')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
