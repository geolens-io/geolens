import { useEffect, useCallback, useRef, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ArrowRight, Layers, Search, Upload } from 'lucide-react';
import { LoadingState } from '@/components/layout/LoadingState';
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

const GLOBE = { W: 1600, H: 800, cx: 1050, cy: 400, R: 340 } as const;
const GLOBE_TILT = (23.4 * Math.PI) / 180; // Earth's axial tilt

/** Lat/long lattice on the unit sphere (denser near the equator) that the
 *  rotating dot-globe is drawn from. Static, so build it once at module load. */
const GLOBE_DOTS: { lat: number; lon: number }[] = [];
for (let lat = -72; lat <= 72; lat += 18) {
  const ringR = Math.cos((lat * Math.PI) / 180);
  const count = Math.max(6, Math.round(20 * ringR));
  for (let j = 0; j < count; j++) GLOBE_DOTS.push({ lat, lon: (360 / count) * j });
}

const GLOBE_MERIDIANS = Array.from({ length: 12 }, (_, i) => i * 30); // longitudes (deg)
const GLOBE_PARALLELS = [-60, -30, 0, 30, 60]; // latitudes (deg)

/** Orthographic projection of a sphere point (lat/lon, radians) onto the panel,
 *  with the polar axis tilted by GLOBE_TILT in the screen plane (Earth-like).
 *  `near` = the point is on the hemisphere facing the viewer. */
function projectGlobePoint(lat: number, lon: number, cosT: number, sinT: number) {
  const cosLat = Math.cos(lat);
  const ox = cosLat * Math.cos(lon); // screen-x before tilt
  const oz = Math.sin(lat); // pole (screen-y before tilt)
  const depth = cosLat * Math.sin(lon); // + = near hemisphere
  return {
    x: GLOBE.cx + (ox * cosT - oz * sinT) * GLOBE.R,
    y: GLOBE.cy - (ox * sinT + oz * cosT) * GLOBE.R,
    near: depth >= 0,
  };
}

/** Build an SVG path for the near-hemisphere portion of a sampled great/small
 *  circle — pen lifts whenever the line passes behind the globe. */
function nearArcPath(samples: [number, number][], cosT: number, sinT: number) {
  let d = '';
  let penDown = false;
  for (const [lat, lon] of samples) {
    const p = projectGlobePoint(lat, lon, cosT, sinT);
    if (p.near) {
      d += `${penDown ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`;
      penDown = true;
    } else {
      penDown = false;
    }
  }
  return d;
}

/** Decorative dot-globe behind the brand panel scrim — a slowly rotating Earth.
 *  Purely cartographic flavor: no MapLibre instance, no interactivity. Dots,
 *  graticule and limb all use the theme `foreground`/`--map-*` tokens so the
 *  backdrop tracks light/dark mode and the overlaid brand text stays legible.
 *
 *  Everything spins about a 23.4°-tilted polar axis (orthographic projection,
 *  near hemisphere only): meridians + surface dots rotate per frame while
 *  parallels are spin-invariant, so the graticule + dots visibly stream across
 *  the face like a turning globe. Honors prefers-reduced-motion — those users
 *  get a fixed earth-like pose.
 *  ponytail: a tiny rAF + analytic projection beats pulling in a 3D lib for a
 *  decorative backdrop; one-line motion gate, no dependency. */
function BrandMapBackdrop() {
  const { W, H, cx, cy, R } = GLOBE;
  const cosT = Math.cos(GLOBE_TILT);
  const sinT = Math.sin(GLOBE_TILT);
  const dotsRef = useRef<SVGGElement>(null);
  const meridiansRef = useRef<SVGGElement>(null);

  // Parallels are invariant under polar-axis spin → build their arcs once.
  const parallelPaths = GLOBE_PARALLELS.map((latDeg) => {
    const lat = (latDeg * Math.PI) / 180;
    const samples: [number, number][] = [];
    for (let lon = 0; lon <= 360; lon += 6) samples.push([lat, (lon * Math.PI) / 180]);
    return nearArcPath(samples, cosT, sinT);
  });

  useEffect(() => {
    const dots = dotsRef.current?.querySelectorAll('circle');
    const meridians = meridiansRef.current?.querySelectorAll('path');
    const render = (spin: number) => {
      dots?.forEach((el, idx) => {
        const { lat, lon } = GLOBE_DOTS[idx];
        const p = projectGlobePoint((lat * Math.PI) / 180, (lon * Math.PI) / 180 + spin, cosT, sinT);
        el.setAttribute('cx', p.x.toFixed(1));
        el.setAttribute('cy', p.y.toFixed(1));
        el.setAttribute('r', p.near ? '2.4' : '1.4');
        el.setAttribute('opacity', p.near ? '0.34' : '0.1');
      });
      meridians?.forEach((el, idx) => {
        const lon0 = (GLOBE_MERIDIANS[idx] * Math.PI) / 180 + spin;
        const samples: [number, number][] = [];
        for (let lat = -90; lat <= 90; lat += 6) samples.push([(lat * Math.PI) / 180, lon0]);
        el.setAttribute('d', nearArcPath(samples, cosT, sinT));
      });
    };
    // matchMedia is absent under jsdom; optional-chain so tests don't crash.
    const reduceMq = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    // The brand panel is `hidden` below 880px — don't burn rAF when it isn't shown.
    const wideMq = window.matchMedia?.('(min-width: 880px)');
    const omega = (2 * Math.PI) / 120_000; // ~120s per revolution
    let start = 0; // seeded from the first rAF timestamp (avoids impure performance.now)
    let raf = 0;
    const tick = (now: number) => {
      if (start === 0) start = now;
      render(omega * (now - start));
      raf = requestAnimationFrame(tick);
    };
    const canAnimate = () =>
      typeof window.requestAnimationFrame === 'function' &&
      !reduceMq?.matches &&
      (wideMq?.matches ?? true);
    const sync = () => {
      if (canAnimate()) {
        if (!raf) {
          start = 0;
          raf = requestAnimationFrame(tick);
        }
      } else {
        if (raf) {
          cancelAnimationFrame(raf);
          raf = 0;
        }
        render(0.7); // fixed earth-like pose while hidden / reduced-motion
      }
    };
    sync();
    wideMq?.addEventListener?.('change', sync);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      wideMq?.removeEventListener?.('change', sync);
    };
  }, [cosT, sinT]);

  // Faint full-bleed graticule for texture behind the globe.
  const vGrat: number[] = [];
  for (let x = 130; x < W; x += 130) vGrat.push(x);
  const hGrat: number[] = [];
  for (let y = 90; y < H; y += 110) hGrat.push(y);

  return (
    <svg
      className="absolute inset-0 size-full"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      <rect width={W} height={H} className="fill-map-paper" />
      <g className="fill-none stroke-map-street" strokeOpacity={0.16} strokeWidth={0.6}>
        {vGrat.map((x) => (
          <line key={`v${x}`} x1={x} y1={0} x2={x} y2={H} />
        ))}
        {hGrat.map((y) => (
          <line key={`h${y}`} x1={0} y1={y} x2={W} y2={y} />
        ))}
      </g>
      {/* Sphere silhouette — a circle under any rotation/tilt (orthographic). */}
      <circle cx={cx} cy={cy} r={R} className="fill-none stroke-foreground" strokeOpacity={0.18} strokeWidth={1.2} />
      {/* Graticule: spin-invariant parallels + per-frame meridians (near side). */}
      <g className="fill-none stroke-foreground" strokeOpacity={0.15} strokeWidth={1}>
        {parallelPaths.map((d, i) => (
          <path key={`par${i}`} d={d} />
        ))}
      </g>
      <g ref={meridiansRef} className="fill-none stroke-foreground" strokeOpacity={0.15} strokeWidth={1}>
        {GLOBE_MERIDIANS.map((_, i) => (
          <path key={`mer${i}`} />
        ))}
      </g>
      <g ref={dotsRef} className="fill-foreground">
        {GLOBE_DOTS.map((_, i) => (
          <circle key={i} r={2} cx={cx} cy={cy} />
        ))}
      </g>
    </svg>
  );
}

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
        {/* fix(#438): UX-16 — LoadingState carries role="status" + aria-live. */}
        <LoadingState />
      </div>
    );
  }

  // SSO-only login mode (#268): treat absent password_login_enabled (older
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
    <main className="grid min-h-screen grid-cols-1 min-[880px]:grid-cols-[1.05fr_0.95fr]">
      {/* ───────── LEFT — brand / map panel (hidden ≤880px) ───────── */}
      <section className="relative hidden overflow-hidden border-e border-border bg-map-paper px-14 py-12 min-[880px]:flex min-[880px]:flex-col min-[880px]:justify-between">
        <BrandMapBackdrop />
        {/* Paper scrim keeps the left-aligned text legible over the map. */}
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-map-paper/90 via-map-paper/70 to-map-paper/30" />

        <div className="relative z-10 flex h-full flex-col">
          {/* Top — logo lockup + eyebrow */}
          <div>
            <Link
              to="/"
              className="inline-flex text-foreground transition-colors hover:text-primary focus-visible:rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              <GeoLensLogo size="lg" />
            </Link>
            <p className="eyebrow mt-2.5">
              {t('geospatialDataCatalog')}
            </p>
          </div>

          {/* Middle — hero (optically centered) */}
          <div className="my-auto max-w-[460px] py-8">
            <h1 className="text-pretty text-4xl font-semibold leading-[1.08] tracking-[-0.025em] text-foreground">
              {t('loginHero')}
            </h1>
            <p className="mt-4 max-w-[400px] text-base leading-[1.55] text-muted-foreground">
              {t('loginHeroSub')}
            </p>

            <div className="mt-8 flex flex-col gap-3.5">
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
          <div className="flex items-center justify-between font-mono text-2xs tracking-[0.04em] text-muted-foreground">
            <span>{instanceHost}</span>
            <span>40.7128°N · 74.0060°W</span>
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
          {/* Mobile-only level-1 heading: the desktop brand panel's <h1> is
              display:none below 880px, so screen-reader heading nav has no h1
              on mobile without this. Hidden on desktop to keep a single h1. */}
          <h1 className="sr-only min-[880px]:hidden">{t('signIn')}</h1>
          {/* Form head */}
          <div className="mb-5">
            <h2 className="text-xl font-semibold tracking-[-0.01em] text-foreground">
              {t('signIn')}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">{t('welcomeBack')}</p>
          </div>

          {configError && (
            <p className="mb-4 text-sm text-destructive">{t('authConfig.loadFailed')}</p>
          )}

          {/* SSO-only login mode (#268): hide the password form (no flash) when
              password_login_enabled is explicitly false. Config is already
              resolved here (configLoading shows the LoadingState above). Treat an
              absent field (older servers) and a config error as true. */}
          {showPasswordForm ? (
            <>
              <LoginForm />
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

          {/* Adaptive OAuth: 0 → renders nothing; 1 → labeled; 2-3 → icon row.
              The divider only belongs above the buttons when a password form
              sits above it. */}
          <div className="mt-5">
            <OAuthButtons showDivider={showPasswordForm} />
          </div>

          {/* Legal */}
          <p className="mt-5 text-center text-mini leading-relaxed text-muted-foreground">
            {t('consentNote')}{' '}
            <a
              href={GEOLENS_PRIVACY_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="underline decoration-border underline-offset-2 hover:text-foreground"
            >
              {t('privacyPolicy')}
            </a>
            {t('consentNoteSuffix')}
          </p>

          {/* Signup gate (#266): show when allow_signup is true;
              fall back to registration_enabled for older servers. */}
          {showSignup && (
            <p className="mt-3 text-center text-sm text-muted-foreground">
              {t('needAccount')}{' '}
              <Link to="/register" className="text-primary underline hover:text-primary/80">
                {t('createOne')}
              </Link>
            </p>
          )}

          {/* Browse block — second, deliberate browse path at the end of the form. */}
          <div className="mt-[18px] border-t border-border pt-[18px] text-center">
            <p className="mb-2.5 text-xs text-muted-foreground">
              {t('browseCatalogHelper')}
            </p>
            {/* FRONT-02: sets gl-guest-browse to suppress the landing-first
                redirect for the rest of the session before navigating to /. */}
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
  );
}
