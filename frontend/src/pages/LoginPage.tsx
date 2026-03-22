import { useEffect } from 'react';
import { Link, Navigate, useLocation } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Database, Globe2, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';
import { useAuthStore } from '@/stores/auth-store';
import { getAuthConfig } from '@/api/auth';
import { GeoLensLogo } from '@/components/GeoLensLogo';
import { LoginForm } from '@/components/auth/LoginForm';
import { OAuthButtons } from '@/components/auth/OAuthButtons';
import { useDocumentTitle } from '@/hooks/use-document-title';

function getOAuthErrorMessage(error: string, t: (key: string, opts?: Record<string, string>) => string): string {
  if (error.includes('invalid_grant')) {
    return t('oauthErrors.invalidGrant');
  }
  if (error.includes('access_denied')) {
    return t('oauthErrors.accessDenied');
  }
  return t('oauthErrors.generic', { error });
}

export function LoginPage() {
  const { t } = useTranslation('auth');
  useDocumentTitle('Login');
  const token = useAuthStore((s) => s.token);
  const location = useLocation();
  const oauthError = (location.state as { oauthError?: string } | null)?.oauthError;

  useEffect(() => {
    if (oauthError) {
      toast.error(getOAuthErrorMessage(oauthError, t));
      window.history.replaceState({}, '', '/login');
    }
  }, [oauthError]);

  const { data: config } = useQuery({
    queryKey: ['auth', 'config'],
    queryFn: getAuthConfig,
    staleTime: 5 * 60 * 1000,
  });

  if (token) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_hsl(var(--primary)/0.12),_transparent_38%),linear-gradient(180deg,_hsl(var(--background)),_hsl(var(--muted)/0.2))] px-4 py-10">
      <div className="mx-auto grid min-h-[calc(100vh-5rem)] max-w-5xl gap-8 lg:grid-cols-[1.1fr_0.9fr] lg:items-center">
        <section className="flex flex-col justify-center text-center lg:text-left">
          <GeoLensLogo size="lg" className="justify-center lg:justify-start" />
          <p className="mt-2 text-sm text-muted-foreground">
            {t('geospatialDataCatalog')}
          </p>
          <h1 className="mt-6 text-3xl font-semibold tracking-tight sm:text-4xl">
            {t('loginHeadline', {
              defaultValue: 'Search, assess, and share spatial data without extra ceremony.',
            })}
          </h1>
          <p className="mt-4 max-w-xl text-sm text-muted-foreground sm:text-base">
            {t('loginSubheadline', {
              defaultValue: 'Sign in to work with the catalog, inspect dataset quality, and move directly into maps and exports.',
            })}
          </p>

          <div className="mt-8 grid gap-3 sm:grid-cols-3">
            <div className="rounded-2xl border bg-background/80 p-4 text-left shadow-sm backdrop-blur">
              <Database className="size-4 text-primary" />
              <p className="mt-3 text-sm font-medium">
                {t('loginHighlights.catalog', { defaultValue: 'Catalog-first workflow' })}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {t('loginHighlights.catalogCopy', {
                  defaultValue: 'Find datasets quickly with search, filters, and saved views.',
                })}
              </p>
            </div>
            <div className="rounded-2xl border bg-background/80 p-4 text-left shadow-sm backdrop-blur">
              <Globe2 className="size-4 text-primary" />
              <p className="mt-3 text-sm font-medium">
                {t('loginHighlights.preview', { defaultValue: 'Spatial context built in' })}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {t('loginHighlights.previewCopy', {
                  defaultValue: 'Preview extents, metadata, and quality before opening detail pages.',
                })}
              </p>
            </div>
            <div className="rounded-2xl border bg-background/80 p-4 text-left shadow-sm backdrop-blur">
              <ShieldCheck className="size-4 text-primary" />
              <p className="mt-3 text-sm font-medium">
                {t('loginHighlights.access', { defaultValue: 'Secure by default' })}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {t('loginHighlights.accessCopy', {
                  defaultValue: 'Use your account or organization sign-in to access the catalog.',
                })}
              </p>
            </div>
          </div>
        </section>

        <div className="flex flex-col items-center gap-4 lg:items-stretch">
          <LoginForm />
          <OAuthButtons />
          {config?.registration_enabled === true && (
            <p className="text-center text-sm text-muted-foreground">
              {t('needAccount')}{' '}
              <Link to="/register" className="text-primary underline hover:text-primary/80">
                {t('createOne')}
              </Link>
            </p>
          )}
          {config?.registration_enabled === false && (
            <p className="text-center text-sm text-muted-foreground">
              {t('contactAdministrator', {
                defaultValue: 'Need an account? Contact an administrator for access.',
              })}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
