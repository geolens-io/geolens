import { apiFetch } from './client';

// --- Shared types (used by admin + public pages) ---

export interface BasemapEntry {
  id: string;
  label: string;
  url: string;
  enabled: boolean;
  is_preset: boolean;
  attribution?: string;
  api_key?: string | null;
}

export interface MapDefaults {
  center_lat: number;
  center_lng: number;
  zoom: number;
}

export interface TileConfig {
  cdn_base_url: string | null;
  public_app_url: string | null;
  public_api_url: string | null;
  public_base_url: string | null;
}

// --- Unified settings types (admin-only) ---

export interface SettingItem {
  key: string;
  value: unknown;
  source: 'default' | 'overridden' | 'env_only';
  label: string;
}

export interface AllSettingsResponse {
  env_only: boolean;
  tabs: Record<string, SettingItem[]>;
}

export interface ConfigModeResponse {
  env_only: boolean;
}

// --- Public endpoints (used by non-admin pages) ---

export async function getBasemaps(): Promise<BasemapEntry[]> {
  return apiFetch<BasemapEntry[]>('/settings/basemaps/');
}

export async function getMapDefaults(): Promise<MapDefaults> {
  return apiFetch<MapDefaults>('/settings/map-defaults/');
}

export async function getTileConfig(): Promise<TileConfig> {
  return apiFetch<TileConfig>('/settings/tile-config/');
}

export async function getEnabledWidgets(): Promise<string[] | null> {
  return apiFetch<string[] | null>('/settings/enabled-widgets/');
}

// --- Unified admin endpoints ---

export async function getAllSettings(): Promise<AllSettingsResponse> {
  return apiFetch<AllSettingsResponse>('/settings/all/');
}

export async function updateSettings(settings: Record<string, unknown>): Promise<AllSettingsResponse> {
  return apiFetch<AllSettingsResponse>('/settings/', {
    method: 'PUT',
    body: JSON.stringify({ settings }),
  });
}

export async function resetSettings(keys: string[]): Promise<AllSettingsResponse> {
  return apiFetch<AllSettingsResponse>('/settings/reset/', {
    method: 'POST',
    body: JSON.stringify({ keys }),
  });
}

export async function getConfigMode(): Promise<ConfigModeResponse> {
  return apiFetch<ConfigModeResponse>('/settings/config-mode/');
}

export interface ApiKeyStatusResponse {
  anthropic_configured: boolean;
  openai_configured: boolean;
}

export async function getApiKeyStatus(): Promise<ApiKeyStatusResponse> {
  return apiFetch<ApiKeyStatusResponse>('/settings/api-key-status/');
}

// --- Embedding dimension detection ---

export interface DetectEmbeddingDimsResponse {
  dimensions: number;
}

export async function detectEmbeddingDims(): Promise<DetectEmbeddingDimsResponse> {
  return apiFetch<DetectEmbeddingDimsResponse>('/settings/detect-embedding-dims/', {
    method: 'POST',
  });
}

// --- Branding endpoints ---

export interface BrandingConfig {
  show_badge: boolean;
}

export async function getBranding(): Promise<BrandingConfig> {
  return apiFetch<BrandingConfig>('/settings/branding/');
}

export async function updateBranding(data: Partial<BrandingConfig>): Promise<void> {
  const settings: Record<string, unknown> = {};
  if (data.show_badge !== undefined) settings.branding_show_badge = data.show_badge;
  await updateSettings(settings);
}

// --- OAuth provider types and endpoints (admin-only) ---

export interface OAuthProviderConfig {
  id: string;
  slug: string;
  display_name: string;
  provider_type: 'google' | 'microsoft' | 'oidc' | 'saml';
  client_id: string;
  discovery_url: string | null;
  authorize_url: string | null;
  token_url: string | null;
  userinfo_url: string | null;
  scopes: string;
  default_role: string;
  group_claim: string | null;
  group_role_mapping: Record<string, string> | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  idp_entity_id?: string | null;
  sp_entity_id?: string | null;
}

export interface OAuthProviderCreateData {
  slug: string;
  display_name: string;
  provider_type: 'google' | 'microsoft' | 'oidc' | 'saml';
  client_id?: string;
  client_secret?: string;
  discovery_url?: string | null;
  authorize_url?: string | null;
  token_url?: string | null;
  userinfo_url?: string | null;
  scopes?: string;
  default_role?: string;
  group_claim?: string | null;
  group_role_mapping?: Record<string, string> | null;
  enabled?: boolean;
  metadata_xml?: string | null;
}

export type OAuthProviderUpdateData = Partial<OAuthProviderCreateData>;

export async function listOAuthProviders(): Promise<OAuthProviderConfig[]> {
  return apiFetch<OAuthProviderConfig[]>('/settings/oauth-providers/');
}

export async function createOAuthProvider(data: OAuthProviderCreateData): Promise<OAuthProviderConfig> {
  return apiFetch<OAuthProviderConfig>('/settings/oauth-providers/', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateOAuthProvider(id: string, data: OAuthProviderUpdateData): Promise<OAuthProviderConfig> {
  return apiFetch<OAuthProviderConfig>(`/settings/oauth-providers/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteOAuthProvider(id: string): Promise<void> {
  return apiFetch<void>(`/settings/oauth-providers/${id}`, {
    method: 'DELETE',
  });
}
