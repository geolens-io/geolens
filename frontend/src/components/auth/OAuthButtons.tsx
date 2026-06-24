import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { getOAuthProviders } from '@/api/auth';
import { queryKeys } from '@/lib/query-keys';
import { Button } from '@/components/ui/button';
import { API_BASE } from '@/lib/constants';
import { cn } from '@/lib/utils';

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

// Provider types that render a recognizable branded mark. Only these are safe
// to show as icon-only — generic OIDC/SAML providers share one fallback icon, so
// in a multi-provider setup they'd be visually indistinguishable without a label.
const BRANDED_PROVIDER_TYPES = new Set(['google', 'microsoft', 'github']);

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

export function OAuthButtons({ showDivider = true }: { showDivider?: boolean } = {}) {
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

  // Adaptive layout (per design handoff):
  //   0 providers        → render nothing (no block, no divider, no SSO note)
  //   1 provider         → single full-width labeled button
  //   2-3, all branded   → equal-width row of icon-only buttons (label on aria-label/title)
  //   2-3, any generic   → stacked labeled buttons so generic providers stay distinguishable
  if (isLoading || !providers || providers.length === 0) return null;

  const count = providers.length;
  // Icon-only is only safe when every provider has a *distinct, branded* icon —
  // otherwise (generic providers, or two of the same branded type) the buttons
  // are visually indistinguishable, so fall back to stacked labeled buttons.
  const providerTypes = providers.map((p) => p.provider_type);
  const compact =
    count >= 2 &&
    providerTypes.every((type) => BRANDED_PROVIDER_TYPES.has(type)) &&
    new Set(providerTypes).size === count;

  return (
    <div className="w-full space-y-4">
      {/* The "or continue with" divider only makes sense as an alternative to a
          password form above it. In SSO-only mode there is no form, so the caller
          passes showDivider={false} and the buttons are the primary path. */}
      {showDivider && (
        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <span className="w-full border-t opacity-60" />
          </div>
          <div className="relative flex justify-center">
            <span className="bg-background px-3 font-mono text-[10.5px] uppercase tracking-[0.1em] text-muted-foreground">
              {t('oauth.divider')}
            </span>
          </div>
        </div>
      )}
      <div
        className={cn(
          'grid gap-2',
          compact ? (count === 3 ? 'grid-cols-3' : 'grid-cols-2') : 'grid-cols-1',
        )}
      >
        {providers.map((provider) => {
          const label = getButtonLabel(t, provider);
          return (
            <Button
              key={provider.slug}
              variant="outline"
              className="h-10 w-full"
              title={compact ? label : undefined}
              aria-label={compact ? label : undefined}
              onClick={() => {
                window.location.href = `${API_BASE}/auth/oauth/${provider.slug}/login`;
              }}
            >
              <ProviderIcon providerType={provider.provider_type} />
              {!compact && <span>{label}</span>}
            </Button>
          );
        })}
      </div>
    </div>
  );
}
