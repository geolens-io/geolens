import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '@/stores/auth-store';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { exchangeSignInCode } from '@/api/auth';
import { completeSignIn, type IssuedSession } from '@/lib/sign-in';
import { postSignInPath } from '@/lib/post-sign-in-path';
import { readSessionStorage, removeSessionStorage } from '@/lib/storage';
import { Loader2 } from 'lucide-react';

export function OAuthCallbackPage() {
  const { t } = useTranslation('auth');
  useDocumentTitle(t('common:pageTitle.signingIn'));
  const navigate = useNavigate();
  const processedRef = useRef(false);
  const mountedRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (processedRef.current) return;
    processedRef.current = true;

    // Read tokens from URL fragment (not query params) to avoid server log exposure
    const hash = window.location.hash.replace(/^#/, '');
    const params = new URLSearchParams(hash || window.location.search);

    const error = params.get('error');
    if (error) {
      window.history.replaceState({}, '', '/oauth/callback');
      navigate('/login', { replace: true, state: { oauthError: decodeURIComponent(error) } });
      return;
    }

    const code = params.get('code');
    const token = params.get('token');
    const refreshToken = params.get('refresh_token');
    const expiresIn = params.get('expires_in');
    // An API from before the code exchange set the cookie on its redirect
    // and sends no refresh token; accepted while versions can differ.
    const legacyCookieMode = params.get('auth_mode') === 'cookie';

    // Clean URL immediately (remove fragment with the code or tokens)
    window.history.replaceState({}, '', '/oauth/callback');

    // A same-origin deployment sends a one-time code, exchanged for the
    // session cookie under the cross-tab cookie lock. A cross-origin one
    // cannot use that cookie and sends the tokens themselves.
    let issued: Promise<IssuedSession>;
    if (code) {
      issued = exchangeSignInCode(code);
    } else if (token && expiresIn && (refreshToken || legacyCookieMode)) {
      issued = Promise.resolve({
        access_token: token,
        refresh_token: refreshToken,
        expires_in: parseInt(expiresIn, 10),
      });
    } else {
      // An incomplete fragment is not evidence that credentials were rejected.
      // Avoid /auth/logout/ here because it revokes every session for the user.
      useAuthStore.getState().logout();
      navigate('/login', { replace: true });
      return;
    }

    issued
      .then((session) => completeSignIn(session))
      .then((outcome) => {
        // The user may have navigated away while the profile loaded.
        if (!mountedRef.current) return;
        if (outcome === 'superseded') {
          // The login page forwards a tab that is still signed in.
          navigate('/login', { replace: true });
          return;
        }
        // Denied storage must not turn a valid SSO round-trip into a failed
        // session. Without a stored redirect, land on the root route.
        const redirect = readSessionStorage('geolens-login-redirect');
        removeSessionStorage('geolens-login-redirect');
        navigate(postSignInPath(redirect), { replace: true });
      })
      .catch(() => {
        if (mountedRef.current) navigate('/login', { replace: true });
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
