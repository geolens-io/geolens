import { useEffect, useCallback, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router';
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
import { GEOLENS_PRIVACY_URL } from '@/lib/external-links';

function getOAuthErrorMessage(error: string, t: (key: string, opts?: Record<string, string>) => string): string {
  if (error.includes('invalid_grant')) {
    return t('oauthErrors.invalidGrant');
  }
  if (error.includes('access_denied')) {
    return t('oauthErrors.accessDenied');
  }
  // DOMAIN-03 (Phase 1236): SSO callback redirects here with error=domain_not_allowed
  // when the user's email domain is not in the allowed_email_domains list.
  if (error.includes('domain_not_allowed')) {
    return t('oauthErrors.domainNotAllowed');
  }
  return t('oauthErrors.generic', { error });
}

/** Session-scoped key that suppresses the landing-first redirect.
 *  Written by the "Browse Catalog" button; cleared when the tab closes. */
const GUEST_BROWSE_KEY = 'gl-guest-browse';

export function LoginPage() {
  const { t } = useTranslation('auth');
  useDocumentTitle(t('common:pageTitle.login'));
  const token = useAuthStore((s) => s.token);
  const location = useLocation();
  const navigate = useNavigate();
  const oauthError = (location.state as { oauthError?: string } | null)?.oauthError;
  // Break-glass: in SSO-only mode the password form is hidden by default, but a
  // manage_settings admin can still authenticate with a password server-side.
  // Keep that path reachable from the UI (e.g. during an SSO outage) behind an
  // explicit disclosure so the clean SSO-only default is preserved.
  const [showBreakGlass, setShowBreakGlass] = useState(false);

  useEffect(() => {
    if (oauthError) {
      toast.error(getOAuthErrorMessage(oauthError, t));
      window.history.replaceState({}, '', '/login');
    }
  }, [oauthError, t]);

  const { data: config, isLoading: configLoading, isError: configError } = useQuery({
    queryKey: queryKeys.authConfig.config,
    queryFn: getAuthConfig,
    staleTime: 5 * 60 * 1000,
  });

  // FRONT-02 (Phase 1223): guest-browse escape hatch.
  // Sets the sessionStorage marker so LandingFirstGuard does not bounce the
  // visitor back to /login for the rest of the browser session.
  const handleBrowseCatalog = useCallback(() => {
    sessionStorage.setItem(GUEST_BROWSE_KEY, 'true');
    navigate('/');
  }, [navigate]);

  if (token) {
    const from = (location.state as { from?: string } | null)?.from;
    // CLEAN-N4: search workspace is "/" after landing page removal.
    const target = from && from.startsWith('/') ? from : '/';
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
          {configError && <div className="text-sm text-destructive">{t('authConfig.loadFailed')}</div>}
          {/* SSO-03 (Phase 1236 Plan 02): hide the password form (no flash) when
              password_login_enabled is explicitly false. The config is already
              resolved before we reach this render path (configLoading shows Loader2
              above). Treat absent field (older servers) as true for back-compat. */}
          {config?.password_login_enabled !== false ? (
            <LoginForm />
          ) : showBreakGlass ? (
            <div className="flex w-full flex-col items-center gap-2">
              <LoginForm />
              <Button
                variant="link"
                className="h-auto p-0 text-xs text-muted-foreground"
                onClick={() => setShowBreakGlass(false)}
              >
                {t('ssoOnly.hidePasswordSignIn')}
              </Button>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-1">
              <p className="max-w-sm text-center text-sm text-muted-foreground">
                {t('ssoOnly.signInWithProvider')}
              </p>
              {/* Admin break-glass: reveal the password form so a manage_settings
                  admin can sign in if SSO is unavailable (server enforces the gate). */}
              <Button
                variant="link"
                className="h-auto p-0 text-xs text-muted-foreground"
                onClick={() => setShowBreakGlass(true)}
              >
                {t('ssoOnly.adminPasswordSignIn')}
              </Button>
            </div>
          )}
          <OAuthButtons />
          <p className="max-w-sm text-center text-xs text-muted-foreground">
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
          <p className="max-w-sm text-center text-sm text-muted-foreground">
            {t('browseCatalogHelper', {
              defaultValue: 'No account needed to browse the public catalog.',
            })}{' '}
            {/* FRONT-02: sets gl-guest-browse to suppress the landing-first
                redirect for the rest of the session before navigating to /. */}
            <Button
              variant="link"
              className="h-auto p-0 align-baseline text-sm"
              onClick={handleBrowseCatalog}
            >
              {t('browseCatalog', {
                defaultValue: 'Browse Catalog',
              })}
            </Button>
          </p>
          {/* SIGNUP-06 (Phase 1231): show signup link when allow_signup is true;
              fall back to registration_enabled for older server versions that
              don't yet expose allow_signup. Google SSO (OAuthButtons) is
              intentionally outside this gate (SIGNUP-02). */}
          {(config?.allow_signup === true || (config?.allow_signup === undefined && config?.registration_enabled === true)) ? (
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
