import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '@/stores/auth-store';
import { getMe } from '@/api/auth';
import { Loader2 } from 'lucide-react';

export function OAuthCallbackPage() {
  const { t } = useTranslation('auth');
  const navigate = useNavigate();
  const processedRef = useRef(false);

  useEffect(() => {
    if (processedRef.current) return;
    processedRef.current = true;

    const params = new URLSearchParams(window.location.search);

    // Check for error param first (OAuth callback failure)
    const error = params.get('error');
    if (error) {
      navigate('/login', { replace: true, state: { oauthError: decodeURIComponent(error) } });
      return;
    }

    const token = params.get('token');
    const refreshToken = params.get('refresh_token');
    const expiresIn = params.get('expires_in');

    // Clean URL immediately
    window.history.replaceState({}, '', '/oauth/callback');

    if (!token || !refreshToken || !expiresIn) {
      navigate('/login', { replace: true });
      return;
    }

    // Set token temporarily so getMe() can authenticate
    useAuthStore.setState({ token });

    getMe()
      .then((user) => {
        useAuthStore.getState().setAuth(token, refreshToken, parseInt(expiresIn, 10), user);
        const redirect = sessionStorage.getItem('geolens-login-redirect');
        sessionStorage.removeItem('geolens-login-redirect');
        const target = redirect && redirect.startsWith('/') ? redirect : '/';
        navigate(target, { replace: true });
      })
      .catch(() => {
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
