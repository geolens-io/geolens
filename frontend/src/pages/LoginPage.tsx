import { memo, useEffect, useCallback, useRef, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ArrowRight, Layers, Search, Upload } from 'lucide-react';
import { LoadingState } from '@/components/layout/LoadingState';
import { AppFooter } from '@/components/layout/AppFooter';
import { toast } from 'sonner';
import { useAuthStore } from '@/stores/auth-store';
import { getAuthConfig } from '@/api/auth';
import { queryKeys } from '@/lib/query-keys';
import { GeoLensLogo } from '@/components/GeoLensLogo';
import { LoginForm } from '@/components/auth/LoginForm';
import { OAuthButtons } from '@/components/auth/OAuthButtons';
import { Button } from '@/components/ui/button';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useBranding } from '@/hooks/use-settings';
import { useEdition } from '@/hooks/use-edition';
import { isSafeHttpUrl } from '@/lib/safe-http-url';
import { postSignInPath } from '@/lib/post-sign-in-path';
import { writeSessionStorage } from '@/lib/storage';
import {
  GLOBE_VIEW,
  landDotsPath,
  meridianPath,
  parallelPath,
  restLongitude,
} from '@/lib/login-globe';
import type { Translator } from '@/i18n/translator';

function getOAuthErrorMessage(error: string, t: Translator): string {
  if (error.includes('invalid_grant')) {
    return t('oauthErrors.invalidGrant');
  }
  if (error.includes('access_denied')) {
    return t('oauthErrors.accessDenied');
  }
  // SSO reports a rejected email domain through this callback error.
  if (error.includes('domain_not_allowed')) {
    return t('oauthErrors.domainNotAllowed');
  }
  // The identity is valid but cannot create an account while registration is disabled.
  if (error.includes('registration_disabled')) {
    return t('oauthErrors.registrationDisabled');
  }
  if (error.includes('account_not_linkable')) {
    return t('oauthErrors.accountNotLinkable');
  }
  if (error.includes('account_inactive')) {
    return t('oauthErrors.accountInactive');
  }
  return t('oauthErrors.generic', { error });
}

/** Session-scoped key that suppresses the landing-first redirect.
 *  Written by the "Browse Catalog" button; cleared when the tab closes. */
const GUEST_BROWSE_KEY = 'gl-guest-browse';

const GLOBE_MERIDIANS = Array.from({ length: 12 }, (_, i) => i * 30);
const GLOBE_PARALLELS = [-60, -30, 0, 30, 60];
const PARALLEL_PATHS = GLOBE_PARALLELS.map(parallelPath);

// The globe turns this far, eastward like the Earth, before it comes to rest.
const SETTLE_DEGREES = 40;
// Motion that starts by itself has to end within five seconds (WCAG 2.2.2).
const SETTLE_MS = 2400;

/** Decorative globe behind the brand panel. It faces the visitor's part of the
 *  world, worked out from the browser's UTC offset, turns once into that pose,
 *  and stays still for anyone who asked their system for less motion or whose
 *  screen hides the panel. */
const BrandMapBackdrop = memo(function BrandMapBackdrop() {
  const { size, cx, cy, r } = GLOBE_VIEW;
  const landRef = useRef<SVGPathElement>(null);
  const meridiansRef = useRef<SVGGElement>(null);
  const [restLon] = useState(() => restLongitude(new Date().getTimezoneOffset()));
  const [settles] = useState(
    () =>
      typeof requestAnimationFrame === 'function' &&
      (globalThis.matchMedia?.('(min-width: 880px)')?.matches ?? true) &&
      !(globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false),
  );
  const firstLon = restLon + (settles ? SETTLE_DEGREES : 0);

  useEffect(() => {
    if (!settles) return;
    const meridians = meridiansRef.current?.querySelectorAll('path');
    const start = performance.now();
    let frame = requestAnimationFrame(function draw(now) {
      // The first frame's timestamp can be a little earlier than `start`.
      const t = Math.min(1, Math.max(0, now - start) / SETTLE_MS);
      const centerLon = restLon + SETTLE_DEGREES * (1 - t) ** 3;
      landRef.current?.setAttribute('d', landDotsPath(centerLon));
      meridians?.forEach((el, i) => el.setAttribute('d', meridianPath(GLOBE_MERIDIANS[i], centerLon)));
      if (t < 1) frame = requestAnimationFrame(draw);
    });
    return () => cancelAnimationFrame(frame);
  }, [settles, restLon]);

  const grid: number[] = [];
  for (let v = 80; v < size; v += 80) grid.push(v);

  return (
    <svg
      className="absolute inset-0 size-full"
      viewBox={`0 0 ${size} ${size}`}
      preserveAspectRatio="xMaxYMid slice"
      aria-hidden="true"
    >
      <rect width={size} height={size} className="fill-map-paper" />
      <g className="fill-none stroke-map-street" strokeOpacity={0.16} strokeWidth={0.6}>
        {grid.map((v) => (
          <line key={`v${v}`} x1={v} y1={0} x2={v} y2={size} />
        ))}
        {grid.map((v) => (
          <line key={`h${v}`} x1={0} y1={v} x2={size} y2={v} />
        ))}
      </g>
      <circle cx={cx} cy={cy} r={r} className="fill-none stroke-foreground" strokeOpacity={0.18} strokeWidth={1.2} />
      <g className="fill-none stroke-foreground" strokeOpacity={0.1} strokeWidth={0.8}>
        {PARALLEL_PATHS.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>
      <g ref={meridiansRef} className="fill-none stroke-foreground" strokeOpacity={0.1} strokeWidth={0.8}>
        {GLOBE_MERIDIANS.map((lon) => (
          <path key={lon} d={meridianPath(lon, firstLon)} />
        ))}
      </g>
      <path
        ref={landRef}
        d={landDotsPath(firstLon)}
        className="fill-none stroke-foreground"
        strokeOpacity={0.34}
        strokeWidth={4.2}
        strokeLinecap="round"
      />
    </svg>
  );
});

export function LoginPage() {
  const { t } = useTranslation('auth');
  useDocumentTitle(t('common:pageTitle.login'));
  const { data: branding } = useBranding();
  const privacyUrl = branding?.privacy_url;
  // Login renders outside AppLayout, so it owns the footer visibility rule.
  // Wait for edition resolution to avoid briefly showing disabled enterprise branding.
  const { isEnterprise, isResolved: editionResolved } = useEdition();
  const showFooterBranding = editionResolved && (!isEnterprise || branding?.show_badge !== false);
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
      // Drop the consumed error from the entry, keeping the router's idx and key.
      window.history.replaceState({ ...window.history.state, usr: null }, '', '/login');
    }
  }, [oauthError, t]);

  const { data: config, isLoading: configLoading, isError: configError } = useQuery({
    queryKey: queryKeys.authConfig.config,
    queryFn: getAuthConfig,
    staleTime: 5 * 60 * 1000,
  });

  // Suppress LandingFirstGuard for this browser session before opening the catalog.
  const handleBrowseCatalog = useCallback(() => {
    // Denied storage must not disable the anonymous navigation action.
    writeSessionStorage(GUEST_BROWSE_KEY, 'true');
    navigate('/');
  }, [navigate]);

  if (token) {
    const from = (location.state as { from?: string } | null)?.from;
    return <Navigate to={postSignInPath(from)} replace />;
  }

  // In SSO-only mode, treat absent password_login_enabled (older
  // servers) and a config fetch error (fail-open) as "password login allowed".
  const passwordLoginEnabled = config?.password_login_enabled !== false;
  const showPasswordForm = passwordLoginEnabled || showBreakGlass;
  const showSignup =
    config?.allow_signup === true ||
    (config?.allow_signup === undefined && config?.registration_enabled === true);
  const instanceHost = typeof window !== 'undefined' ? window.location.host : '';

  const features = [
    { Icon: Search, title: t('loginFeatures.searchTitle'), desc: t('loginFeatures.searchDesc') },
    { Icon: Layers, title: t('loginFeatures.buildTitle'), desc: t('loginFeatures.buildDesc') },
    { Icon: Upload, title: t('loginFeatures.importTitle'), desc: t('loginFeatures.importDesc') },
  ];

  return (
    <div className="flex min-h-screen flex-col">
    <main className="grid flex-1 grid-cols-1 min-[880px]:grid-cols-[1.05fr_0.95fr]">
      {/* ───────── LEFT — brand / map panel (hidden ≤880px) ───────── */}
      <section className="relative hidden overflow-hidden border-e border-border bg-map-paper px-14 py-8 lg:py-12 min-[880px]:flex min-[880px]:flex-col min-[880px]:justify-between">
        <BrandMapBackdrop />
        {/* Paper scrim keeps the left-aligned text legible over the map. */}
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-map-paper/95 via-map-paper/85 to-map-paper/70 xl:from-map-paper/90 xl:via-map-paper/70 xl:to-map-paper/30" />

        <div className="relative z-10 flex h-full flex-col">
          {/* Top — logo lockup + eyebrow */}
          <div>
            {/* Use the guest-browse escape so the logo works when landing-first is enabled. */}
            <button
              type="button"
              onClick={handleBrowseCatalog}
              className="inline-flex text-foreground transition-colors hover:text-primary focus-visible:rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              <GeoLensLogo size="lg" />
            </button>
            <p className="eyebrow mt-2.5">
              {t('geospatialDataCatalog')}
            </p>
          </div>

          {/* Middle — hero (optically centered) */}
          <div className="my-auto max-w-[460px] py-4 lg:py-6">
            <h1 className="text-pretty text-[1.75rem] font-semibold leading-[1.1] lg:text-4xl lg:leading-[1.08] tracking-[-0.025em] text-foreground">
              {t('loginHero')}
            </h1>
            <p className="mt-3 max-w-[400px] text-sm leading-[1.5] lg:mt-4 lg:text-base lg:leading-[1.55] text-muted-foreground">
              {t('loginHeroSub')}
            </p>

            <div className="mt-5 flex flex-col gap-3 lg:mt-8 lg:gap-3.5">
              {features.map(({ Icon, title, desc }) => (
                <div key={title} className="flex items-start gap-3">
                  <span className="flex size-[30px] shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Icon className="size-[15px]" />
                  </span>
                  <span className="text-sm">
                    <span className="block font-semibold text-foreground">{title}</span>
                    <span className="leading-[1.45] text-muted-foreground">{desc}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Bottom — instance footer */}
          <div className="flex items-center font-mono text-2xs tracking-[0.04em] text-muted-foreground">
            <span>{instanceHost}</span>
          </div>
        </div>
      </section>

      {/* ───────── RIGHT — sign-in form panel ───────── */}
      <section className="relative flex flex-col items-center justify-center bg-background px-10 py-12">
        {/* Persistent top-right browse link — the immediate escape hatch. */}
        <Button
          variant="ghost"
          className="absolute end-[14px] top-[14px] h-auto gap-1.5 px-3 py-1.5 text-xs font-medium text-muted-foreground min-[880px]:end-[26px] min-[880px]:top-[22px]"
          onClick={handleBrowseCatalog}
        >
          {t('browseCatalogCta')}
          <ArrowRight className="size-3.5 text-primary rtl-mirror" />
        </Button>

        <div className="w-full max-w-[360px]">
          {/* Mobile needs its own branding and level-one heading because the
              desktop brand panel and its heading are hidden below 880px. */}
          <div className="mb-6 flex flex-col items-center gap-2 text-center min-[880px]:hidden">
            <GeoLensLogo size="md" />
            <h1 className="text-pretty text-lg font-semibold leading-snug tracking-[-0.01em] text-foreground">
              {t('loginHero')}
            </h1>
          </div>
          {/* Form head */}
          <div className="mb-5">
            <h2 className="text-xl font-semibold tracking-[-0.01em] text-foreground">
              {t('signIn')}
            </h2>
            {!configLoading && showPasswordForm && (
              <p className="mt-1 text-sm text-muted-foreground">{t('signInHint')}</p>
            )}
          </div>

          {/* Only the form waits for the sign-in settings. The rest of the page
              is the same either way, so it shows at once. */}
          {configLoading ? (
            <LoadingState className="py-10" message={t('common:loading')} />
          ) : (
            <>
              {configError && (
                <p role="alert" className="mb-4 text-sm text-destructive">{t('authConfig.loadFailed')}</p>
              )}

              {/* Config is resolved here, so the SSO-only password form hides
                  without a flash when password_login_enabled is explicitly false. */}
              {showPasswordForm ? (
                <>
                  <LoginForm signupOpen={showSignup} />
                  {!passwordLoginEnabled && (
                    <Button
                      variant="link"
                      className="mt-2 h-auto p-0 text-xs text-muted-foreground"
                      onClick={() => setShowBreakGlass(false)}
                    >
                      {t('ssoOnly.hidePasswordSignIn')}
                    </Button>
                  )}
                </>
              ) : (
                <div className="flex flex-col items-center gap-1 text-center">
                  <p className="text-sm text-muted-foreground">{t('ssoOnly.signInWithProvider')}</p>
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

              {/* Adaptive OAuth: 0 → nothing; 1 → labeled; 2-3 → icon row. The
                  divider shows only when a password form sits above. */}
              <div className="mt-5">
                <OAuthButtons showDivider={showPasswordForm} />
              </div>

              {/* Legal */}
              {isSafeHttpUrl(privacyUrl) && (
                <p className="mt-5 text-center text-mini leading-relaxed text-muted-foreground">
                  {t('consentNote')}{' '}
                  <a
                    href={privacyUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline decoration-border underline-offset-2 hover:text-foreground"
                  >
                    {t('privacyPolicy')}
                  </a>
                  {t('consentNoteSuffix')}
                </p>
              )}

              {/* showSignup falls back to registration_enabled on older servers. */}
              {showSignup && (
                <p className="mt-3 text-center text-sm text-muted-foreground">
                  {t('needAccount')}{' '}
                  <Link to="/register" className="text-primary underline hover:text-primary/80">
                    {t('createOne')}
                  </Link>
                </p>
              )}

            </>
          )}

          {/* Browse block — second, deliberate browse path at the end of the form. */}
          <div className="mt-[18px] border-t border-border pt-[18px] text-center">
            <p className="mb-2.5 text-xs text-muted-foreground">
              {t('browseCatalogHelper')}
            </p>
            {/* Sets gl-guest-browse to suppress the landing-first redirect for
                the session before navigating to /. */}
            <Button
              variant="outline"
              className="h-10 w-full gap-1.5 font-semibold"
              onClick={handleBrowseCatalog}
            >
              {t('browseCatalogCta')}
              <ArrowRight className="size-3.5 text-primary rtl-mirror" />
            </Button>
          </div>
        </div>
      </section>
    </main>
    <AppFooter showBranding={showFooterBranding} />
    </div>
  );
}
