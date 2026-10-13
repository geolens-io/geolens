import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Loader2, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';
import { rememberThisBrowser } from '@/api/auth';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { GeoLensLogo } from '@/components/GeoLensLogo';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

/**
 * Landing page for an operator's trust link. Opening it changes nothing, so a
 * link preview can't use the link up; the button redeems it.
 */
export function TrustBrowserPage() {
  const { t } = useTranslation('auth');
  useDocumentTitle(t('common:pageTitle.trustBrowser'));
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get('token');
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRemember() {
    if (!token) return;
    setWorking(true);
    setError(null);
    try {
      await rememberThisBrowser(token);
      toast.success(t('trustBrowser.success'));
      navigate('/login', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : t('trustBrowser.failed'));
    } finally {
      setWorking(false);
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 bg-background px-4">
      <div className="text-center">
        <h1 className="sr-only">{t('trustBrowser.title')}</h1>
        <GeoLensLogo size="lg" className="justify-center" />
      </div>
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center">
          <ShieldCheck className="text-primary mb-2 h-10 w-10" />
          <CardTitle level={2} className="text-xl">{t('trustBrowser.title')}</CardTitle>
          <CardDescription>
            {token ? t('trustBrowser.description') : t('trustBrowser.missingToken')}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
          {token && (
            <Button type="button" onClick={handleRemember} disabled={working}>
              {working ? (
                <>
                  <Loader2 className="me-2 h-4 w-4 animate-spin" />
                  {t('trustBrowser.working')}
                </>
              ) : (
                t('trustBrowser.button')
              )}
            </Button>
          )}
          <div className="flex justify-center">
            <Link to="/login" className="text-primary text-sm underline hover:text-primary/80">
              {t('backToSignIn')}
            </Link>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}
