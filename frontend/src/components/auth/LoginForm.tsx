import { type FormEvent, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { useAuth } from '@/hooks/use-auth';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PasswordInput } from '@/components/ui/password-input';
import { Label } from '@/components/ui/label';
import { removeSessionStorage } from '@/lib/storage';
import { postSignInPath } from '@/lib/post-sign-in-path';

/**
 * Login form for username + password authentication.
 *
 * On success, stores the JWT in `useAuthStore` and navigates to the original
 * destination (from `location.state.from`) or the catalog home. Renders inside
 * the right-hand sign-in panel next to the optional OAuth provider buttons;
 * both code paths feed the same auth store. Handles password visibility
 * toggling and inline error display. The contact-an-administrator hint shows
 * only while sign-up is closed, since the page offers its own sign-up link
 * otherwise.
 */
export function LoginForm({ signupOpen = false }: { signupOpen?: boolean }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation('auth');
  const mountedRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // Read the fields themselves: autofill can fill them before React's state sees it.
    const form = new FormData(e.currentTarget);
    const typedUsername = String(form.get('username') ?? '');
    const typedPassword = String(form.get('password') ?? '');
    if (!typedUsername.trim()) {
      document.getElementById('username')?.focus();
      return;
    }
    // Controlled inputs re-render from state, so adopt what was read or a
    // failed attempt would blank an autofilled form.
    setUsername(typedUsername);
    setPassword(typedPassword);
    setError(null);
    setLoading(true);

    try {
      await login(typedUsername, typedPassword);
      const from = (location.state as { from?: string } | null)?.from;
      // The root route is the canonical search workspace.
      const target = postSignInPath(from);
      // Keep storage cleanup exception-safe after authentication so it cannot
      // turn a successful login into an inline error before navigation.
      removeSessionStorage('geolens-login-redirect');
      // The login page already forwards a signed-in tab, and the user may have
      // moved on while the profile loaded.
      if (mountedRef.current) navigate(target, { replace: true });
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
          name="username"
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
          name="password"
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
      {/* Stays enabled while a field is empty: the browser then points at the
          missing field, and a filled-in look from autofill is never a dead button. */}
      <Button type="submit" disabled={loading} className="h-[42px] w-full font-semibold">
        {loading && <Loader2 className="size-4 animate-spin" />}
        {loading ? t('signingIn') : t('signIn')}
      </Button>
      {!signupOpen && (
        <p className="text-xs leading-relaxed text-muted-foreground">
          {t('supportHint')}
        </p>
      )}
    </form>
  );
}
