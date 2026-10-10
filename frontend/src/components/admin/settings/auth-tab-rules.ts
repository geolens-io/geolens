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
  allowed_email_domains: readonly string[];
}

/** Reads the sign-up settings, falling back to the backend defaults for a key the backend doesn't send. */
export function readSignUpState(read: (key: string) => unknown): SignUpState {
  const domains = read('allowed_email_domains');
  return {
    registration_enabled: read('registration_enabled') === true,
    password_login_enabled: read('password_login_enabled') !== false,
    email_verification_required: read('email_verification_required') !== false,
    registration_default_role: String(read('registration_default_role') ?? 'viewer'),
    allowed_email_domains: Array.isArray(domains) ? domains : [],
  };
}

/** True when an enabled provider can create accounts with the admin role, by default or through a group mapping. SAML included. */
export function providerGrantsAdmin(providers: readonly OAuthProviderConfig[]): boolean {
  return providers.some(
    (provider) =>
      provider.enabled &&
      (provider.default_role === 'admin' ||
        Object.values(provider.group_role_mapping ?? {}).includes('admin')),
  );
}

/**
 * Who can create an active administrator account without an administrator
 * approving it: 0 nobody, 1 people at the allowed email domains, 2 anyone.
 * The paths are an enabled provider that grants admin, and a password sign-up
 * with the admin role that activates by verifying its email.
 */
export function adminSignUpReach(
  state: SignUpState,
  providerGivesAdmin: boolean,
  smtpConfigured: boolean,
): 0 | 1 | 2 {
  if (!state.registration_enabled) return 0;
  const passwordPath =
    state.password_login_enabled &&
    state.email_verification_required &&
    smtpConfigured &&
    state.registration_default_role === 'admin';
  if (!providerGivesAdmin && !passwordPath) return 0;
  return state.allowed_email_domains.length > 0 ? 1 : 2;
}

/**
 * True when a save lets more people sign up as an administrator: a wider reach,
 * or a domain added to an allowlist that already limits it.
 */
export function widensAdminSignUp(
  reachNow: 0 | 1 | 2,
  reachAfter: 0 | 1 | 2,
  domainsNow: readonly string[],
  domainsAfter: readonly string[],
): boolean {
  if (reachAfter > reachNow) return true;
  if (reachNow !== 1 || reachAfter !== 1) return false;
  const normalize = (domain: string) => domain.trim().toLowerCase();
  const known = new Set(domainsNow.map(normalize));
  return domainsAfter.some((domain) => !known.has(normalize(domain)));
}

/** The settings that, with the providers and SMTP, decide who can sign up as an administrator. */
export const SIGN_UP_GATE_KEYS: ReadonlySet<string> = new Set([
  'registration_enabled',
  'password_login_enabled',
  'email_verification_required',
  'registration_default_role',
  'allowed_email_domains',
]);
