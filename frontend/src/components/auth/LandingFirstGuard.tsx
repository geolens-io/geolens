/**
 * FRONT-01/FRONT-02 (Phase 1223): Root-route guard for the landing-first flag.
 *
 * Renders <SearchPage/> in every case EXCEPT:
 *   flag ON  AND  no auth token  AND  no guest-browse session marker
 *   → <Navigate to="/login" replace/>
 *
 * This keeps the index route public (FRONT-03): datasets/:id, collections,
 * maps, etc. are NOT affected — only the "/" index route uses this guard.
 *
 * The guest-browse marker ("gl-guest-browse") is written to sessionStorage
 * by the "Browse Catalog" link on LoginPage.  It is checked here so that
 * visitors who explicitly chose to browse anonymously are NOT bounced back
 * to /login on every navigation to "/".
 */
import { Navigate } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth-store';
import { getAuthConfig } from '@/api/auth';
import { queryKeys } from '@/lib/query-keys';
import { SearchPage } from '@/pages/SearchPage';

const GUEST_BROWSE_KEY = 'gl-guest-browse';

export function LandingFirstGuard() {
  const token = useAuthStore((s) => s.token);

  const { data: config } = useQuery({
    queryKey: queryKeys.authConfig.config,
    queryFn: getAuthConfig,
    staleTime: 5 * 60 * 1000,
  });

  const landingFirst = config?.landing_first ?? false;
  const guestBrowse =
    typeof sessionStorage !== 'undefined'
      ? sessionStorage.getItem(GUEST_BROWSE_KEY) === 'true'
      : false;

  // Redirect ONLY when: flag ON + unauthenticated + no guest-browse marker
  if (landingFirst && !token && !guestBrowse) {
    return <Navigate to="/login" replace />;
  }

  return <SearchPage />;
}
