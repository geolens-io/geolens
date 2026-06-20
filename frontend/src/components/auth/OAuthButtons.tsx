import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { getOAuthProviders } from '@/api/auth';
import { queryKeys } from '@/lib/query-keys';
import { Button } from '@/components/ui/button';
import { API_BASE } from '@/lib/constants';

function ProviderIcon({ providerType }: { providerType: string }) {
  if (providerType === 'google') {
    return (
      <svg className="size-4" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
          fill="#4285F4"
        />
        <path
          d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
          fill="#34A853"
        />
        <path
          d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18A10.96 10.96 0 0 0 1 12c0 1.77.42 3.45 1.18 4.93l3.66-2.84z"
          fill="#FBBC05"
        />
        <path
          d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
          fill="#EA4335"
        />
      </svg>
    );
  }

  if (providerType === 'microsoft') {
    return (
      <svg className="size-4" viewBox="0 0 21 21" aria-hidden="true">
        <rect x="1" y="1" width="9" height="9" fill="#F25022" />
        <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
        <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
        <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
      </svg>
    );
  }

  if (providerType === 'github') {
    return (
      <svg className="size-4" viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
        <path d="M12 0C5.37 0 0 5.37 0 12c0 5.3 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61-.546-1.385-1.335-1.755-1.335-1.755-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 21.795 24 17.295 24 12c0-6.63-5.37-12-12-12z" />
      </svg>
    );
  }

  // Generic OIDC icon
  return (
    <svg className="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
      <polyline points="10 17 15 12 10 7" />
      <line x1="15" y1="12" x2="3" y2="12" />
    </svg>
  );
}

function getButtonLabel(
  t: (key: string, options?: Record<string, unknown>) => string,
  provider: { display_name: string; provider_type: string },
) {
  const providerLabel =
    provider.provider_type === 'google'
      ? t('oauth.providers.google')
      : provider.provider_type === 'microsoft'
        ? t('oauth.providers.microsoft')
        : provider.provider_type === 'github'
          ? t('oauth.providers.github')
          : provider.display_name;

  return t('oauth.signInWith', { provider: providerLabel });
}

export function OAuthButtons() {
  const { t } = useTranslation('auth');
  const { data: providers, isLoading, isError } = useQuery({
    queryKey: queryKeys.authConfig.oauthProviders,
    queryFn: getOAuthProviders,
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
  });

  if (isError) {
    return <p className="text-xs text-muted-foreground">{t('oauth.unavailable')}</p>;
  }

  if (isLoading || !providers || providers.length === 0) return null;

  return (
    <div className="w-full max-w-sm space-y-4">
      <div className="relative">
        <div className="absolute inset-0 flex items-center">
          <span className="w-full border-t" />
        </div>
        <div className="relative flex justify-center text-xs uppercase">
          <span className="bg-background px-2 text-muted-foreground">
            {t('oauth.divider')}
          </span>
        </div>
      </div>
      <div className="flex flex-col gap-2">
        {providers.map((provider) => (
          <Button
            key={provider.slug}
            variant="outline"
            className="w-full"
            onClick={() => {
              window.location.href = `${API_BASE}/auth/oauth/${provider.slug}/login`;
            }}
          >
            <ProviderIcon providerType={provider.provider_type} />
            {getButtonLabel(t, provider)}
          </Button>
        ))}
      </div>
      <p className="text-center text-xs text-muted-foreground">
        {t('oauth.helper', {
          defaultValue: 'Single sign-on is available when your organization has configured it.',
        })}
      </p>
    </div>
  );
}
