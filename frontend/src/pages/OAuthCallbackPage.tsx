import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '@/stores/auth-store';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { getMe, logoutSession } from '@/api/auth';
import { readSessionStorage, removeSessionStorage } from '@/lib/storage';
import { Loader2 } from 'lucide-react';

export function OAuthCallbackPage() {
  const { t } = useTranslation('auth');
  useDocumentTitle(t('common:pageTitle.signingIn')); // fix(#438): UX-09
  const navigate = useNavigate();
  const processedRef = useRef(false);

  useEffect(() => {
    if (processedRef.current) return;
    processedRef.current = true;

    // Read tokens from URL fragment (not query params) to avoid server log exposure
    const hash = window.location.hash.replace(/^#/, '');
    const params = new URLSearchParams(hash || window.location.search);

    // Check for error param first (OAuth callback failure)
    const error = params.get('error');
    if (error) {
      window.history.replaceState({}, '', '/oauth/callback');
      navigate('/login', { replace: true, state: { oauthError: decodeURIComponent(error) } });
      return;
    }

    const token = params.get('token');
    const refreshToken = params.get('refresh_token');
    const expiresIn = params.get('expires_in');
    // fix(#1302): with auth_mode=cookie the backend delivered the refresh token
    // as an httpOnly cookie on the redirect, so the fragment carries no
    // refresh_token to require. The fragment is readable by any script on this
    // page, which made it the same exfiltration surface as localStorage.
    const cookieMode = params.get('auth_mode') === 'cookie';

    // Clean URL immediately (remove fragment with tokens)
    window.history.replaceState({}, '', '/oauth/callback');

    if (!token || !expiresIn || (!refreshToken && !cookieMode)) {
      // fix(#1446): a truncated or malformed fragment still arrived on a
      // response that installed the cookies, so bailing out here without
      // revoking leaves a live credential behind a UI reporting failure. The
      // freshly-set CSRF cookie authenticates it; there is no bearer token to
      // send. Unconditional — on the legacy fragment path there is no cookie,
      // so the call simply 401s and costs nothing.
      void logoutSession().catch(() => {});
      useAuthStore.getState().logout();
      navigate('/login', { replace: true });
      return;
    }

    // Set token temporarily so getMe() can authenticate
    useAuthStore.setState({ token });

    getMe()
      .then((user) => {
        useAuthStore.getState().setAuth(token, refreshToken ?? null, parseInt(expiresIn, 10), user);
        // fix(#1527): a bare access here threw into the sibling .catch()
        // below, which revokes the session and bounces to /login — so a
        // storage-denied context ended a perfectly good SSO round-trip signed
        // out. No stored redirect just means landing on "/".
        const redirect = readSessionStorage('geolens-login-redirect');
        removeSessionStorage('geolens-login-redirect');
        const target = redirect && redirect.startsWith('/') ? redirect : '/';
        navigate(target, { replace: true });
      })
      .catch(() => {
        // fix(#1446): the backend already installed the refresh cookie before
        // redirecting here, so clearing the store alone would strand a
        // replayable credential the UI claims is gone. logoutSession captures
        // the temporary bearer token synchronously, so dispatching it here
        // sends a fully-formed request before the store is cleared below.
        void logoutSession().catch(() => {});
        useAuthStore.getState().logout();
        navigate('/login', { replace: true });
      });
  }, [navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="flex flex-col items-center gap-3 text-muted-foreground">
        <Loader2 className="size-8 animate-spin" />
        <p className="text-sm">{t('oauthCallback.completingSignIn')}</p>
      </div>
    </div>
  );
}
