import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { useResetUserPassword } from '@/hooks/use-admin';
import { useAuthStore } from '@/stores/auth-store';
import type { UserResponse } from '@/types/api';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { PasswordInput } from '@/components/ui/password-input';
import { Label } from '@/components/ui/label';

interface UserResetPasswordDialogProps {
  user: UserResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * feat(#1715): the administrator half of "Contact a GeoLens administrator for a
 * password reset", which the login page has always said and nothing could do.
 *
 * One field, no generated value and no clipboard copy: the administrator picks
 * the credential and hands it over out of band, which keeps the value out of
 * every surface that would otherwise hold it (the clipboard, a rendered
 * one-time panel, a screenshot). The state is dropped on close and on success.
 */
export function UserResetPasswordDialog({ user, open, onOpenChange }: UserResetPasswordDialogProps) {
  const { t } = useTranslation('admin');
  const currentUserId = useAuthStore((state) => state.user?.id);
  const [password, setPassword] = useState('');

  const resetPassword = useResetUserPassword();
  const isSelf = user.id === currentUserId;

  useEffect(() => {
    if (open) setPassword('');
  }, [open]);

  // fix(#1715 codex r1 P2): a close while the request is in flight would unmount
  // the dialog without stopping the reset, so the password would change and the
  // account's credentials be revoked with the UI showing nothing at all. Every
  // dismissal route (Cancel, the X, Escape, the overlay) goes through here, so
  // refusing the close covers all of them.
  //
  // The request is deliberately NOT aborted. Aborting the fetch would not undo
  // a commit the backend may already have made, so it would swap a confusing
  // outcome for an unknowable one; blocking until it resolves is what keeps the
  // dialog's report of what happened true.
  function handleOpenChange(next: boolean) {
    if (resetPassword.isPending && !next) return;
    onOpenChange(next);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await resetPassword.mutateAsync({ userId: user.id, password });
      setPassword('');
      // Not handleOpenChange: isPending can still read true in this tick, and
      // the guard above would swallow the close it is meant to allow.
      onOpenChange(false);
      if (isSelf) {
        // fix(#1715 codex r1 P2): the reset revoked this very session, so the
        // persisted token is already dead. Without this the UI keeps rendering
        // as signed in until some later request happens to 401, contradicting
        // the warning this dialog just showed. logout() drops the token and
        // ProtectedRoute redirects; the query cache is cleared by the identity
        // subscription in wireAuthCacheReset.
        useAuthStore.getState().logout();
      }
    } catch {
      // error displayed inline and as a toast from the mutation
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="sm:max-w-md"
        // Belt and braces with handleOpenChange: these stop the dismiss gesture
        // at the primitive, so a pending reset cannot even begin to close.
        showCloseButton={!resetPassword.isPending}
        onEscapeKeyDown={(event) => { if (resetPassword.isPending) event.preventDefault(); }}
        onPointerDownOutside={(event) => { if (resetPassword.isPending) event.preventDefault(); }}
        onInteractOutside={(event) => { if (resetPassword.isPending) event.preventDefault(); }}
      >
        <DialogHeader>
          <DialogTitle>{t('users.resetPasswordDialog.title')}</DialogTitle>
          <DialogDescription>
            {t('users.resetPasswordDialog.description', { username: user.username })}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="reset-password">{t('users.resetPasswordDialog.passwordLabel')}</Label>
            <PasswordInput
              id="reset-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              // The client floor stays at the schema's fast-fail minimum, not
              // the policy's 12: PASSWORD_MIN_LENGTH is configurable, and an
              // instance that lowered it must not have valid values blocked
              // here. The placeholder states the default the API describes.
              minLength={8}
              placeholder={t('users.resetPasswordDialog.passwordPlaceholder')}
              // fix(#1746): autoComplete="off" alone does not stop Chrome from
              // offering a saved password on a password-type field. This value
              // belongs to someone else's account, so opt out of every password
              // manager explicitly rather than let one file it under this admin.
              autoComplete="new-password"
              data-1p-ignore
              data-lpignore="true"
              data-bwignore
              disabled={resetPassword.isPending}
            />
            <p className="text-xs text-muted-foreground">{t('users.resetPasswordDialog.hint')}</p>
            {isSelf && (
              <p className="text-xs text-muted-foreground">
                {t('users.resetPasswordDialog.selfWarning')}
              </p>
            )}
          </div>
          {resetPassword.error && (
            <p className="text-sm text-destructive">
              {resetPassword.error instanceof Error
                ? resetPassword.error.message
                : t('users.resetPasswordDialog.error')}
            </p>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              type="button"
              onClick={() => onOpenChange(false)}
              disabled={resetPassword.isPending}
            >
              {t('common:cancel')}
            </Button>
            <Button type="submit" disabled={resetPassword.isPending}>
              {resetPassword.isPending && <Loader2 className="size-4 animate-spin" />}
              {resetPassword.isPending
                ? t('users.resetPasswordDialog.resetting')
                : t('users.resetPasswordDialog.submit')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
