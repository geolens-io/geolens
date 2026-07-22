import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { onSessionExpired } from '@/api/client';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

// fix(#628): routes whose anonymous view is a complete experience — when the
// session dies here we downgrade silently (the auth-store logout triggers the
// wireAuthCacheReset cache clear, so active queries refetch anonymously)
// instead of prompting. Detail pages (/datasets/:id, /maps/:id) are excluded:
// whether they work anonymously depends on the resource's visibility, so they
// keep the prompt; a public resource still recovers after dismissal via the
// same anonymous refetch.
const ANON_EXACT = new Set(['/', '/collections', '/maps', '/login', '/register', '/verify-email']);
const ANON_PREFIXES = ['/m/', '/oauth/'];

function isAnonymousCapable(pathname: string): boolean {
  return ANON_EXACT.has(pathname) || ANON_PREFIXES.some((p) => pathname.startsWith(p));
}

/**
 * fix(#628): global last-resort session-expiry surface. The fetch core calls
 * the onSessionExpired handler exactly once when a request 401s and the
 * follow-up refresh is also dead; this host shows a single dismissable
 * "signed out" dialog whose sign-in action returns to the current route
 * (same `from` contract as ProtectedRoute/LoginPage, including the
 * sessionStorage key the OAuth callback reads).
 */
export function SessionExpiredDialog() {
  const { t } = useTranslation('auth');
  const location = useLocation();
  const navigate = useNavigate();
  // The route to return to after sign-in; non-null means the dialog is open.
  const [from, setFrom] = useState<string | null>(null);

  // Ref, not closure: the handler is registered once and must read the route
  // at event time, not the route captured when the effect ran.
  const locationRef = useRef(location);
  locationRef.current = location;

  useEffect(
    () =>
      onSessionExpired(() => {
        const { pathname, search } = locationRef.current;
        if (isAnonymousCapable(pathname)) return;
        setFrom(pathname + search);
      }),
    [],
  );

  // A protected route bounces to /login on its own the moment the store is
  // cleared (ProtectedRoute) — the prompt over the login form is noise.
  useEffect(() => {
    if (from && (location.pathname === '/login' || location.pathname === '/register')) {
      setFrom(null);
    }
  }, [from, location.pathname]);

  const signIn = () => {
    if (from) sessionStorage.setItem('geolens-login-redirect', from);
    navigate('/login', { state: { from } });
    setFrom(null);
  };

  return (
    <Dialog open={from !== null} onOpenChange={(open) => !open && setFrom(null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('sessionExpired.title')}</DialogTitle>
          <DialogDescription>{t('sessionExpired.body')}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setFrom(null)}>
            {t('sessionExpired.dismiss')}
          </Button>
          <Button onClick={signIn}>{t('sessionExpired.signIn')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
