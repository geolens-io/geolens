import { type FormEvent, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { useAuth } from '@/hooks/use-auth';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PasswordInput } from '@/components/ui/password-input';
import { Label } from '@/components/ui/label';
import { removeSessionStorage } from '@/lib/storage';

/**
 * Login form for username + password authentication.
 *
 * On success, stores the JWT in `useAuthStore` and navigates to the original
 * destination (from `location.state.from`) or the catalog home. Renders inside
 * the right-hand sign-in panel next to the optional OAuth provider buttons;
 * both code paths feed the same auth store. Handles password visibility
 * toggling and inline error display.
 */
export function LoginForm() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation('auth');

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      await login(username, password);
      const from = (location.state as { from?: string } | null)?.from;
      // The root route is the canonical search workspace.
      const target = from && from.startsWith('/') ? from : '/';
      // Keep storage cleanup exception-safe after authentication so it cannot
      // turn a successful login into an inline error before navigation.
      removeSessionStorage('geolens-login-redirect');
      navigate(target, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : t('loginFailed'));
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex w-full flex-col gap-3.5">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="username" className="text-xs">
          {t('username')}
        </Label>
        {/* On a server error, mark both credentials invalid and associate the error. */}
        <Input
          id="username"
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder={t('usernamePlaceholder')}
          required
          autoComplete="username"
          className="h-10"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? 'login-error' : undefined}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="password" className="text-xs">
          {t('password')}
        </Label>
        <PasswordInput
          id="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder={t('enterPassword')}
          required
          autoComplete="current-password"
          className="h-10"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? 'login-error' : undefined}
        />
      </div>
      {error && (
        <p id="login-error" role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Button
        type="submit"
        disabled={loading || !username.trim() || !password}
        className="h-[42px] w-full font-semibold"
      >
        {loading && <Loader2 className="size-4 animate-spin" />}
        {loading ? t('signingIn') : t('signIn')}
      </Button>
      <p className="text-xs leading-relaxed text-muted-foreground">
        {t('supportHint')}
      </p>
    </form>
  );
}
