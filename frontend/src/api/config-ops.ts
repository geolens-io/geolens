import { apiFetch } from './client';

// --- Types matching backend config_ops schemas ---

export interface ConfigExport {
  version: string;
  exported_at: string;
  settings: Record<string, unknown>;
  oauth_providers: Record<string, unknown>[];
}

export type ImportMode = 'merge' | 'overwrite';

export interface ConfigImportRequest {
  settings?: Record<string, unknown> | null;
  oauth_providers?: Record<string, unknown>[] | null;
}

export interface SettingChange {
  key: string;
  current: unknown;
  imported: unknown;
  action: 'update' | 'no_change' | 'reset' | 'skip_unknown' | 'skip_restricted';
  reason?: string | null;
}

export interface OAuthProviderChange {
  slug: string;
  action: 'create' | 'update' | 'no_change' | 'delete' | 'replace';
  changed_fields?: string[] | null;
  dependent_accounts_deleted: number;
}

export interface DryRunResult {
  settings: {
    changes: SettingChange[];
    skipped_unknown?: string[];
    skipped_restricted?: string[];
  };
  oauth_providers: {
    changes: OAuthProviderChange[];
    dependent_accounts_deleted: number;
  };
  preview_token?: string | null;
}

export interface ImportResult {
  settings_applied: number;
  settings_skipped: number;
  settings_skipped_restricted?: string[];
  oauth_created: number;
  oauth_updated: number;
  oauth_deleted: number;
  oauth_accounts_deleted: number;
}

// --- API functions ---

export async function exportConfig(): Promise<ConfigExport> {
  return apiFetch<ConfigExport>('/config-ops/export/');
}

export async function dryRunImport(
  data: ConfigImportRequest,
  mode: ImportMode,
): Promise<DryRunResult> {
  return apiFetch<DryRunResult>(`/config-ops/dry-run/?mode=${mode}`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function importConfig(
  data: ConfigImportRequest,
  mode: ImportMode,
  previewToken?: string | null,
): Promise<ImportResult> {
  return apiFetch<ImportResult>(`/config-ops/import/?mode=${mode}`, {
    method: 'POST',
    headers: previewToken
      ? { 'X-Config-Preview-Token': previewToken }
      : undefined,
    body: JSON.stringify(data),
  });
}

// --- Connectivity validation types and API function ---

export interface ServiceProbeResult {
  name: string;
  status: 'ok' | 'error';
  latency_ms: number;
  error: string | null;
}

export interface ConnectivityResult {
  storage: ServiceProbeResult;
  cache: ServiceProbeResult;
  oidc_providers: Record<string, ServiceProbeResult>;
}

export async function validateConnectivity(): Promise<ConnectivityResult> {
  return apiFetch<ConnectivityResult>('/config-ops/validate/', { method: 'POST' });
}
