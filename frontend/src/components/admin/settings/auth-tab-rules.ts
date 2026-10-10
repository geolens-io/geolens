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

// Any Azure cloud host counts, and the authority segment is case-insensitive.
const MULTITENANT_MICROSOFT = /^https?:\/\/[^/]+\/(common|organizations|consumers)\//i;

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

export interface SignUpState {
  registration_enabled: boolean;
  password_login_enabled: boolean;
  email_verification_required: boolean;
  registration_default_role: string;
}

/** Reads the sign-up settings, falling back to the backend defaults for a key the backend doesn't send. */
export function readSignUpState(read: (key: string) => unknown): SignUpState {
  return {
    registration_enabled: read('registration_enabled') === true,
    password_login_enabled: read('password_login_enabled') !== false,
    email_verification_required: read('email_verification_required') !== false,
    registration_default_role: String(read('registration_default_role') ?? 'viewer'),
  };
}

/**
 * True when a stranger can create an active administrator account without an
 * administrator approving it: through an enabled SSO or SAML provider whose
 * default role is admin, or a password sign-up that activates by verifying its email.
 */
export function isAdminSignUpOpen(
  state: SignUpState,
  providers: readonly OAuthProviderConfig[],
  smtpConfigured: boolean,
): boolean {
  if (!state.registration_enabled) return false;
  if (providers.some((provider) => provider.enabled && provider.default_role === 'admin')) return true;
  return (
    state.password_login_enabled &&
    state.email_verification_required &&
    smtpConfigured &&
    state.registration_default_role === 'admin'
  );
}
