import type { OAuthProviderConfig } from '@/api/settings';

const DOMAIN_LABEL = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/;

/** Mirrors the backend's `is_domain_pattern_valid` so a bad chip is refused before the batch 422s. */
export function isValidDomainPattern(pattern: string): boolean {
  const normalized = pattern.trim().toLowerCase();
  if (!normalized || /\s/.test(normalized)) return false;
  const rest = normalized.startsWith('*.') ? normalized.slice(2) : normalized;
  if (rest.includes('*')) return false;
  const labels = rest.split('.');
  return labels.length >= 2 && labels.every((label) => DOMAIN_LABEL.test(label));
}

const MULTITENANT_MICROSOFT = /microsoftonline\.com\/(common|organizations|consumers)\//;

function acceptsAnyAccount(provider: OAuthProviderConfig): boolean {
  if (provider.provider_type === 'google' || provider.provider_type === 'github') return true;
  return (
    provider.provider_type === 'microsoft' &&
    MULTITENANT_MICROSOFT.test(provider.discovery_url ?? '')
  );
}

/** True when anyone holding an account at an enabled public IdP could create an active account. */
export function hasOpenSignupRisk(
  registrationEnabled: boolean,
  domains: readonly string[],
  providers: readonly OAuthProviderConfig[],
): boolean {
  return (
    registrationEnabled &&
    domains.length === 0 &&
    providers.some((provider) => provider.enabled && acceptsAnyAccount(provider))
  );
}
