/**
 * SAML provider admin API client.
 *
 * SAML providers live in the same `catalog.oauth_providers` table as OAuth
 * providers and are CRUDed through the same admin endpoints
 * (`/settings/oauth-providers/...`). This module provides typed wrappers plus
 * the SAML-specific metadata fetch.
 *
 * The CRUD wrappers call `apiFetch` directly against those endpoints. The update
 * wrapper resolves to HTTP PUT (`@router.put` in settings/router.py, not PATCH).
 *
 * `idp_certificate` is write-only at rest (Fernet-encrypted) and omitted from
 * `OAuthProviderResponse`; clients never read it back. The other SAML fields
 * (idp_entity_id, idp_sso_url, sp_entity_id) are returned by list/detail.
 */

import { apiFetch } from './client';
import { translateApiErrorDetail } from '@/lib/error-map';
import type { OAuthProviderConfig } from './settings';

// SAML reuses the OAuth provider table; this is a typed extension that
// narrows `provider_type` to 'saml' and adds the 3 readable SAML fields.
export interface SamlProviderConfig extends Omit<OAuthProviderConfig, 'provider_type'> {
  provider_type: 'saml';
  idp_entity_id: string | null;
  idp_sso_url: string | null;
  sp_entity_id: string | null;
  // idp_certificate is write-only (encrypted at rest, never returned)
}

export interface SamlProviderCreateData {
  slug: string;
  display_name: string;
  provider_type: 'saml';
  default_role?: string;
  group_claim?: string | null;
  group_role_mapping?: Record<string, string> | null;
  idp_entity_id: string;
  idp_sso_url: string;
  idp_certificate: string;     // PEM, write-only
  sp_entity_id: string;
  enabled?: boolean;
}

export type SamlProviderUpdateData = Partial<SamlProviderCreateData>;

/**
 * Loose shape returned by `/settings/oauth-providers/` when SAML providers are
 * present (only with the enterprise overlay; community returns only
 * `'google' | 'microsoft' | 'oidc'` rows). The wire shape before narrowing to
 * `SamlProviderConfig`.
 */
type AnyProviderConfig = Omit<OAuthProviderConfig, 'provider_type'> & {
  provider_type: string;
  idp_entity_id?: string | null;
  idp_sso_url?: string | null;
  sp_entity_id?: string | null;
};

/**
 * List SAML providers by reusing the OAuth provider list endpoint and filtering
 * client-side by `provider_type === 'saml'`. The trailing slash on
 * `/settings/oauth-providers/` is mandatory (FastAPI 307 redirect).
 */
export async function listSamlProviders(): Promise<SamlProviderConfig[]> {
  // Loose shape so SAML-only fields (absent from OAuthProviderConfig) can be read.
  const all = await apiFetch<AnyProviderConfig[]>('/settings/oauth-providers/');
  return all
    .filter((p) => p.provider_type === 'saml')
    .map((p) => ({
      ...p,
      provider_type: 'saml' as const,
      idp_entity_id: p.idp_entity_id ?? null,
      idp_sso_url: p.idp_sso_url ?? null,
      sp_entity_id: p.sp_entity_id ?? null,
    }));
}

// CRUD goes through the same endpoints as OAuth, but these call `apiFetch`
// directly: the OAuth-typed wrappers in settings.ts narrow `provider_type` and
// require `client_id` / `client_secret`, which excludes the SAML shape. The
// wire shape is identical (see auth/oauth/schemas.py).
export async function createSamlProvider(
  data: SamlProviderCreateData,
): Promise<SamlProviderConfig> {
  return apiFetch<SamlProviderConfig>('/settings/oauth-providers/', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateSamlProvider(
  id: string,
  data: SamlProviderUpdateData,
): Promise<SamlProviderConfig> {
  return apiFetch<SamlProviderConfig>(`/settings/oauth-providers/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteSamlProvider(id: string): Promise<void> {
  return apiFetch<void>(`/settings/oauth-providers/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

/**
 * Fetch the SP metadata XML for a SAML provider. Doesn't use `apiFetch`: the
 * response is `application/samlmetadata+xml`, not JSON. Returns the raw XML
 * string for download/inspection.
 */
export async function fetchSamlMetadata(slug: string): Promise<string> {
  const response = await fetch(`/api/auth/saml/${encodeURIComponent(slug)}/metadata`);
  if (!response.ok) {
    let detail: unknown;
    try {
      const body = await response.json();
      detail = body.detail;
    } catch { /* not JSON */ }
    throw new Error(translateApiErrorDetail(detail, response.status));
  }
  return response.text();
}
