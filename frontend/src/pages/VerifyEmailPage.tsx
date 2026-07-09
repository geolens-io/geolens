import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Loader2, Mail } from 'lucide-react';
import { toast } from 'sonner';
import { verifyEmail, resendVerification } from '@/api/auth';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { GeoLensLogo } from '@/components/GeoLensLogo';
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

type PageState = 'loading' | 'success' | 'error';

export function VerifyEmailPage() {
  const { t } = useTranslation('auth');
  // fix(#435): UX-09 — this page is landed on directly from an email link, so it
  // is the one that most needs a real tab title.
  useDocumentTitle(t('common:pageTitle.verifyEmail'));
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get('token');

  const [pageState, setPageState] = useState<PageState>('loading');
  const [email, setEmail] = useState('');
  const [resendSent, setResendSent] = useState(false);
  const [resending, setResending] = useState(false);

  // Use a ref to guard against StrictMode double-invocations.
  const attempted = useRef(false);

  useEffect(() => {
    if (attempted.current) return;
    attempted.current = true;

    if (!token) {
      setPageState('error');
      return;
    }

    verifyEmail(token)
      .then(() => {
        setPageState('success');
        toast.success(t('verifyEmail.success'));
        // Brief pause so the toast is visible before the redirect.
        setTimeout(() => {
          navigate('/login', { replace: true });
        }, 1500);
      })
      .catch(() => {
        setPageState('error');
      });
  }, [token, navigate, t]);

  async function handleResend(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setResending(true);
    try {
      // The backend is enumeration-safe: always returns 200 regardless of
      // whether the email is registered/unverified — we always show the
      // generic confirmation (T-1231-11).
      await resendVerification(email.trim());
    } catch {
      // Swallow errors to preserve enumeration-safety on the frontend.
    } finally {
      setResending(false);
      setResendSent(true);
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 bg-background px-4">
      <div className="text-center">
        {/* sr-only level-1 heading: the state cards below use CardTitle (a plain
            <div>), so without this the page has no heading-one for SR nav. */}
        <h1 className="sr-only">{t('verifyEmail.title')}</h1>
        <GeoLensLogo size="lg" className="justify-center" />
        <p className="text-muted-foreground mt-1 text-sm">
          {t('geospatialDataCatalog')}
        </p>
      </div>

      {pageState === 'loading' && (
        <Card className="w-full max-w-sm">
          <CardHeader className="items-center text-center">
            <Loader2 className="text-muted-foreground mb-2 h-10 w-10 animate-spin" />
            <CardTitle className="text-xl">{t('verifyEmail.title')}</CardTitle>
            <CardDescription>{t('verifyEmail.verifying')}</CardDescription>
          </CardHeader>
        </Card>
      )}

      {pageState === 'success' && (
        <Card className="w-full max-w-sm">
          <CardHeader className="items-center text-center">
            <Mail className="text-primary mb-2 h-10 w-10" />
            <CardTitle className="text-xl">{t('verifyEmail.title')}</CardTitle>
            <CardDescription>{t('verifyEmail.success')}</CardDescription>
          </CardHeader>
          <CardContent className="flex justify-center">
            <Link
              to="/login"
              className="text-primary text-sm underline hover:text-primary/80"
            >
              {t('backToSignIn')}
            </Link>
          </CardContent>
        </Card>
      )}

      {pageState === 'error' && (
        <Card className="w-full max-w-sm">
          <CardHeader className="items-center text-center">
            <CardTitle className="text-destructive text-xl">
              {t('verifyEmail.invalid')}
            </CardTitle>
            <CardDescription>{t('verifyEmail.invalidDescription')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {resendSent ? (
              <p className="text-muted-foreground text-center text-sm">
                {t('verifyEmail.resendSent')}
              </p>
            ) : (
              <form onSubmit={handleResend} className="flex flex-col gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="resend-email">{t('verifyEmail.emailLabel')}</Label>
                  <Input
                    id="resend-email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder={t('enterEmail')}
                    required
                  />
                </div>
                <Button type="submit" disabled={resending}>
                  {resending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      {t('verifyEmail.resending')}
                    </>
                  ) : (
                    t('verifyEmail.resend')
                  )}
                </Button>
              </form>
            )}
            <div className="flex justify-center">
              <Link
                to="/login"
                className="text-primary text-sm underline hover:text-primary/80"
              >
                {t('backToSignIn')}
              </Link>
            </div>
          </CardContent>
        </Card>
      )}
    </main>
  );
}
