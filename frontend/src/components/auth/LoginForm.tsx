import { type FormEvent, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, Loader2 } from 'lucide-react';
import { useAuth } from '@/hooks/use-auth';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

export function LoginForm() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
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
      const target = from && from.startsWith('/') ? from : '/search';
      sessionStorage.removeItem('geolens-login-redirect');
      navigate(target, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : t('loginFailed'));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="w-full max-w-sm border-border/70 shadow-lg shadow-black/5">
      <CardHeader>
        <CardTitle className="text-xl">{t('signIn')}</CardTitle>
        <CardDescription>
          {t('enterCredentials')}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="username">{t('username')}</Label>
            <Input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder={t('enterUsername')}
              required
              autoComplete="username"
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="password">{t('password')}</Label>
            <div className="relative">
              <Input
                id="password"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t('enterPassword')}
                required
                autoComplete="current-password"
                className="pe-11"
              />
              <button
                type="button"
                onClick={() => setShowPassword((visible) => !visible)}
                className="absolute inset-y-0 right-0 flex items-center px-3 text-muted-foreground transition-colors hover:text-foreground"
                aria-label={
                  showPassword
                    ? t('hidePassword', { defaultValue: 'Hide password' })
                    : t('showPassword', { defaultValue: 'Show password' })
                }
              >
                {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
          </div>
          {error && (
            <p role="alert" className="text-destructive text-sm">{error}</p>
          )}
          <Button
            type="submit"
            disabled={loading || !username.trim() || !password}
            className="w-full"
          >
            {loading && <Loader2 className="size-4 animate-spin" />}
            {loading ? t('signingIn') : t('signIn')}
          </Button>
          <p className="text-xs text-muted-foreground">
            {t('supportHint', {
              defaultValue: 'Need access or a password reset? Contact a GeoLens administrator.',
            })}
          </p>
        </form>
      </CardContent>
    </Card>
  );
}
