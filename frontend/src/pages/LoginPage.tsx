import { useEffect } from 'react';
import { Link, Navigate, useLocation } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Bookmark, Loader2, Map, Upload } from 'lucide-react';
import { toast } from 'sonner';
import { useAuthStore } from '@/stores/auth-store';
import { getAuthConfig } from '@/api/auth';
import { queryKeys } from '@/lib/query-keys';
import { GeoLensLogo } from '@/components/GeoLensLogo';
import { LoginForm } from '@/components/auth/LoginForm';
import { OAuthButtons } from '@/components/auth/OAuthButtons';
import { Button } from '@/components/ui/button';
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
  useDocumentTitle(t('common:pageTitle.login'));
  const token = useAuthStore((s) => s.token);
  const location = useLocation();
  const oauthError = (location.state as { oauthError?: string } | null)?.oauthError;

  useEffect(() => {
    if (oauthError) {
      toast.error(getOAuthErrorMessage(oauthError, t));
      window.history.replaceState({}, '', '/login');
    }
  }, [oauthError, t]);

  const { data: config, isLoading: configLoading } = useQuery({
    queryKey: queryKeys.authConfig.config,
    queryFn: getAuthConfig,
    staleTime: 5 * 60 * 1000,
  });
  if (token) {
    const from = (location.state as { from?: string } | null)?.from;
    const target = from && from.startsWith('/') ? from : '/search';
    return <Navigate to={target} replace />;
  }

  if (configLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_hsl(var(--primary)/0.12),_transparent_38%),linear-gradient(180deg,_hsl(var(--background)),_hsl(var(--muted)/0.2))] px-4 py-10">
      <div className="mx-auto grid min-h-[calc(100vh-5rem)] max-w-5xl gap-8 lg:grid-cols-[1.1fr_0.9fr] lg:items-center">
        <section className="flex flex-col justify-center text-center lg:text-start">
          <Link
            to="/"
            className="inline-flex justify-center text-foreground transition-colors hover:text-primary lg:justify-start"
          >
            <GeoLensLogo size="lg" className="justify-center lg:justify-start" />
          </Link>
          <p className="mt-2 text-sm text-muted-foreground">
            {t('geospatialDataCatalog')}
          </p>
          <h1 className="mt-6 text-3xl font-bold tracking-tight">
            {t('loginHeadline', {
              defaultValue: 'Access your geospatial workspace.',
            })}
          </h1>
          <p className="mt-4 max-w-xl text-sm text-muted-foreground sm:text-base">
            {t('loginSubheadline', {
              defaultValue: 'Sign in to save searches, build maps, and work with the catalog in one place.',
            })}
          </p>

          <div className="mt-8 grid gap-4 sm:grid-cols-3">
            <div className="rounded-2xl border bg-background/80 p-4 text-start shadow-sm backdrop-blur">
              <Bookmark className="size-4 text-primary" />
              <p className="mt-3 text-sm font-medium">
                {t('loginHighlights.searches', { defaultValue: 'Save searches' })}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {t('loginHighlights.searchesCopy', {
                  defaultValue: 'Keep the views and filters you come back to.',
                })}
              </p>
            </div>
            <div className="rounded-2xl border bg-background/80 p-4 text-start shadow-sm backdrop-blur">
              <Map className="size-4 text-primary" />
              <p className="mt-3 text-sm font-medium">
                {t('loginHighlights.maps', { defaultValue: 'Build maps' })}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {t('loginHighlights.mapsCopy', {
                  defaultValue: 'Turn catalog data into styled, shareable maps.',
                })}
              </p>
            </div>
            <div className="rounded-2xl border bg-background/80 p-4 text-start shadow-sm backdrop-blur">
              <Upload className="size-4 text-primary" />
              <p className="mt-3 text-sm font-medium">
                {t('loginHighlights.imports', { defaultValue: 'Import data' })}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {t('loginHighlights.importsCopy', {
                  defaultValue: 'Upload new datasets and keep your workspace current.',
                })}
              </p>
            </div>
          </div>
        </section>

        <div className="flex flex-col items-center gap-4 lg:items-stretch">
          <LoginForm />
          <OAuthButtons />
          <p className="max-w-sm text-center text-sm text-muted-foreground">
            {t('browseCatalogHelper', {
              defaultValue: 'No account needed to browse the public catalog.',
            })}{' '}
            <Button asChild variant="link" className="h-auto p-0 align-baseline text-sm">
              <Link to="/search">
                {t('browseCatalog', {
                  defaultValue: 'Browse Catalog',
                })}
              </Link>
            </Button>
          </p>
          {config?.registration_enabled === true ? (
            <p className="text-center text-sm text-muted-foreground">
              {t('needAccount')}{' '}
              <Link to="/register" className="text-primary underline hover:text-primary/80">
                {t('createOne')}
              </Link>
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
