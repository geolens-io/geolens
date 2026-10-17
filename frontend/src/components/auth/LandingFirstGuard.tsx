/**
 * Root-route guard for the landing-first flag.
 *
 * Renders <SearchPage/> in every case EXCEPT:
 *   flag ON  AND  no auth token  AND  no guest-browse session marker
 *   → <Navigate to="/login" replace/>
 *
 * This keeps the index route public: datasets/:id, collections,
 * maps, etc. are NOT affected — only the "/" index route uses this guard.
 *
 * The guest-browse marker ("gl-guest-browse") is written to sessionStorage
 * by the "Browse Catalog" link on LoginPage.  It is checked here so that
 * visitors who explicitly chose to browse anonymously are NOT bounced back
 * to /login on every navigation to "/".
 */
import { lazy } from 'react';
import { Navigate } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth-store';
import { getAuthConfig } from '@/api/auth';
import { queryKeys } from '@/lib/query-keys';
import { readSessionStorage } from '@/lib/storage';

// Lazy so SearchPage's ~163KB subtree (FilterPanel, color-ramps, etc.) stays
// out of the entry chunk for every route. RootLayout's <Suspense> already
// wraps the route Outlet, so no new boundary is needed here.
const SearchPage = lazy(() => import('@/pages/SearchPage').then((m) => ({ default: m.SearchPage })));

const GUEST_BROWSE_KEY = 'gl-guest-browse';

export function LandingFirstGuard() {
  const token = useAuthStore((s) => s.token);

  const { data: config } = useQuery({
    queryKey: queryKeys.authConfig.config,
    queryFn: getAuthConfig,
    staleTime: 5 * 60 * 1000,
  });

  const landingFirst = config?.landing_first ?? false;
  // This read happens during render, so an exception here is a blank
  // page, not a lost preference. A `typeof sessionStorage !== 'undefined'`
  // guard would not prevent one: the property exists in every context that
  // matters, and it is READING it that throws — SecurityError in a frame with
  // an opaque origin, and in some private-browsing modes.
  const guestBrowse = readSessionStorage(GUEST_BROWSE_KEY) === 'true';

  // Redirect ONLY when: flag ON + unauthenticated + no guest-browse marker
  if (landingFirst && !token && !guestBrowse) {
    return <Navigate to="/login" replace />;
  }

  return <SearchPage />;
}
