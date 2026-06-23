import { type FormEvent, useState } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { registerUser } from '@/api/auth';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PasswordInput } from '@/components/ui/password-input';
import { Label } from '@/components/ui/label';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { GEOLENS_PRIVACY_URL } from '@/lib/external-links';

interface RegisterFormProps {
  onSuccess: (
    email: string,
    nextStep?: 'verify_email' | 'await_approval',
  ) => void;
}

export function RegisterForm({ onSuccess }: RegisterFormProps) {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { t } = useTranslation('auth');

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const result = await registerUser({ username, email, password });
      onSuccess(email, result.next_step);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('registrationFailed'));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle className="text-xl">{t('createAccount')}</CardTitle>
        <CardDescription>
          {t('registerForAccount')}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {/* #305: on a server error mark the credential fields invalid + describe by the error */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="username" className="text-[12.5px]">{t('username')}</Label>
            <Input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder={t('chooseUsername')}
              required
              minLength={3}
              autoComplete="username"
              className="h-10"
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? 'register-error' : undefined}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="email" className="text-[12.5px]">{t('email')}</Label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t('enterEmail')}
              required
              autoComplete="email"
              className="h-10"
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? 'register-error' : undefined}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="password" className="text-[12.5px]">{t('password')}</Label>
            <PasswordInput
              id="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t('choosePassword')}
              required
              minLength={8}
              autoComplete="new-password"
              className="h-10"
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? 'register-error' : undefined}
            />
            <p className="text-xs text-muted-foreground">{t('passwordRequirement')}</p>
          </div>
          {error && (
            <p id="register-error" className="text-destructive text-sm" role="alert">{error}</p>
          )}
          <Button type="submit" disabled={loading || !username.trim() || !email.trim() || !password} className="h-[42px] w-full font-semibold">
            {loading && <Loader2 className="size-4 animate-spin" />}
            {loading ? t('creatingAccount') : t('createAccount')}
          </Button>
          <p className="text-center text-sm text-muted-foreground">
            {t('alreadyHaveAccount')}{' '}
            <Link to="/login" className="text-primary underline hover:text-primary/80">
              {t('signIn')}
            </Link>
          </p>
          <p className="text-center text-xs text-muted-foreground">
            {t('consentNote')}{' '}
            <a
              href={GEOLENS_PRIVACY_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-foreground"
            >
              {t('privacyPolicy')}
            </a>
            {t('consentNoteSuffix')}
          </p>
        </form>
      </CardContent>
    </Card>
  );
}
