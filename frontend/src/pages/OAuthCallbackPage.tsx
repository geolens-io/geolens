import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '@/stores/auth-store';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { getMe, logoutSession } from '@/api/auth';
import { isCredentialRejected } from '@/api/client';
import { readSessionStorage, removeSessionStorage } from '@/lib/storage';
import { Loader2 } from 'lucide-react';

export function OAuthCallbackPage() {
  const { t } = useTranslation('auth');
  useDocumentTitle(t('common:pageTitle.signingIn'));
  const navigate = useNavigate();
  const processedRef = useRef(false);

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

    const token = params.get('token');
    const refreshToken = params.get('refresh_token');
    const expiresIn = params.get('expires_in');
    // Cookie mode keeps the refresh token in an httpOnly cookie, outside
    // the script-readable fragment; no refresh_token parameter is required.
    const cookieMode = params.get('auth_mode') === 'cookie';

    // Clean URL immediately (remove fragment with tokens)
    window.history.replaceState({}, '', '/oauth/callback');

    if (!token || !expiresIn || (!refreshToken && !cookieMode)) {
      // An incomplete fragment is not evidence that credentials were rejected.
      // Avoid /auth/logout/ here because it revokes every session for the user.
      useAuthStore.getState().logout();
      navigate('/login', { replace: true });
      return;
    }

    // Set token temporarily so getMe() can authenticate
    useAuthStore.setState({ token });

    getMe()
      .then((user) => {
        useAuthStore.getState().setAuth(token, refreshToken ?? null, parseInt(expiresIn, 10), user);
        // Denied storage must not turn a valid SSO round-trip into a failed
        // session. Without a stored redirect, land on the root route.
        const redirect = readSessionStorage('geolens-login-redirect');
        removeSessionStorage('geolens-login-redirect');
        const target = redirect && redirect.startsWith('/') ? redirect : '/';
        navigate(target, { replace: true });
      })
      .catch((err: unknown) => {
        // A rejected credential must revoke the installed refresh cookie, but
        // transient failures must not revoke every session owned by the user.
        if (isCredentialRejected(err)) void logoutSession().catch(() => {});
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
