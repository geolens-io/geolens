/**
 * SAML provider admin API client.
 *
 * SAML providers are persisted in the same `catalog.oauth_providers` table as
 * OAuth providers (Phase 217 D-01) and are CRUDed through the SAME admin
 * endpoints as OAuth providers (`/settings/oauth-providers/...`). This module
 * provides typed wrappers + the SAML-specific metadata fetch.
 *
 * The CRUD wrappers are re-exports of the OAuth wrappers in `./settings`,
 * aliased with SAML-prefixed names for call-site clarity. Do NOT duplicate the
 * fetch logic — every change to `/settings/oauth-providers/` semantics must be
 * made in one place (`./settings`).
 *
 * The update wrapper resolves to HTTP PUT (verified at
 * backend/app/modules/settings/router.py:399 — `@router.put`, NOT `@router.patch`).
 *
 * `idp_certificate` is write-only at rest (Fernet-encrypted) and is omitted
 * from `OAuthProviderResponse` server-side; clients should never expect to read
 * it back. The other 3 SAML fields (idp_entity_id, idp_sso_url, sp_entity_id)
 * ARE returned by the list/detail endpoints.
 */

import { apiFetch } from './client';
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
 * present (only when the enterprise overlay is loaded — community returns only
 * `'google' | 'microsoft' | 'oidc'` rows). Used as the wire shape before we
 * narrow to `SamlProviderConfig` for SAML rows.
 */
type AnyProviderConfig = Omit<OAuthProviderConfig, 'provider_type'> & {
  provider_type: string;
  idp_entity_id?: string | null;
  idp_sso_url?: string | null;
  sp_entity_id?: string | null;
};

/**
 * List SAML providers by reusing the OAuth provider list endpoint and
 * filtering client-side by `provider_type === 'saml'`.
 *
 * The trailing slash on `/settings/oauth-providers/` is mandatory (FastAPI
 * 307 redirect quirk; CLAUDE.md note).
 */
export async function listSamlProviders(): Promise<SamlProviderConfig[]> {
  // Use apiFetch directly with the loose shape so we can read SAML-only fields
  // that aren't in the core OAuthProviderConfig type. SAML rows only appear
  // when the enterprise overlay is loaded.
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

// CRUD goes through the SAME endpoints as OAuth (D-12). The OAuth-typed
// wrappers in settings.ts narrow `provider_type` to 'google' | 'microsoft'
// | 'oidc' and require `client_id` / `client_secret`, which excludes the
// SAML shape — so we wrap them here with SAML-specific types and a single
// `as never` cast at the boundary. The wire shape is identical (the
// backend Pydantic schema accepts both shapes after Plan 03 made
// client_id/client_secret optional and added 'saml' to the discriminator;
// see backend/app/modules/auth/oauth/schemas.py).
//
// The update wrapper resolves to HTTP PUT (verified at
// backend/app/modules/settings/router.py:399 — `@router.put`, NOT `@router.patch`).
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
  return apiFetch<SamlProviderConfig>(`/settings/oauth-providers/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteSamlProvider(id: string): Promise<void> {
  return apiFetch<void>(`/settings/oauth-providers/${id}`, {
    method: 'DELETE',
  });
}

/**
 * Fetch the SP metadata XML for a SAML provider.
 *
 * Note: this does NOT use `apiFetch` — the response is `application/samlmetadata+xml`,
 * not JSON. Returns the raw XML string for download/inspection.
 *
 * Hits the FastAPI app via the Vite dev proxy (`/api/...` → backend), matching
 * the proxy rewrite at frontend/vite.config.ts:80-87.
 */
export async function fetchSamlMetadata(slug: string): Promise<string> {
  const response = await fetch(`/api/auth/saml/${slug}/metadata`);
  if (!response.ok) {
    throw new Error(`Metadata fetch failed: ${response.status}`);
  }
  return response.text();
}
