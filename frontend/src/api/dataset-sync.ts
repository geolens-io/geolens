import { apiFetch } from './client';
import { randomId } from '@/lib/random-id';

export type SyncCadence =
  | { kind: 'hourly'; minute: number }
  | { kind: 'daily'; hour: number; minute: number }
  | { kind: 'weekly'; weekday: number; hour: number; minute: number };

export interface SyncSource {
  connector: 'arcgis_feature_server';
  service_url: string;
  layer_id: number;
  source_binding_fingerprint?: string;
}

export interface SyncCredentialMetadata {
  id: string;
  connector_name: 'arcgis_feature_server';
  allowed_origin: string;
  display_name: string;
  current_version: number;
  current_expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SyncAutomation {
  id: string;
  dataset_id: string;
  revision: number;
  status: 'draft' | 'enabled' | 'paused';
  pause_reason: string | null;
  source: SyncSource;
  credential: { id: string; version: number; display_name: string; expires_at: string | null } | null;
  cadence: SyncCadence;
  next_due_at: string | null;
  eligibility: { eligible: boolean; reasons: string[]; policy_version: string };
  last_occurrence: {
    id: string;
    state: 'planned' | 'admitted' | 'delivered' | 'claimed' | 'completed' | 'failed' | 'cancelled' | 'expired';
    scheduled_for: string | null;
    /** Stable safe code for a failed or expired occurrence; never diagnostic text. */
    error_code?: string | null;
  } | null;
  created_at: string;
  updated_at: string;
}

export interface CreateSyncAutomationRequest {
  source: Pick<SyncSource, 'connector' | 'service_url' | 'layer_id'>;
  credential_id?: string;
  cadence: SyncCadence;
  revision?: 0;
}

export interface UpdateSyncAutomationRequest {
  revision: number;
  source?: Pick<SyncSource, 'connector' | 'service_url' | 'layer_id'>;
  credential_id?: string;
  /** Explicitly detach the stored credential before switching to a public source. */
  clear_credential?: boolean;
  cadence?: SyncCadence;
}

export interface SyncRunResponse {
  occurrence_id: string;
  run_id: string;
  job_id: string;
  state: string;
}

export interface CreateSyncCredentialRequest {
  connector_name: 'arcgis_feature_server';
  allowed_origin: string;
  display_name: string;
  token: string;
  expires_at?: string;
}

export interface ReplaceSyncCredentialRequest {
  token: string;
  expires_at?: string;
}

export async function getDatasetSync(datasetId: string): Promise<SyncAutomation | null> {
  return apiFetch<SyncAutomation | null>(`/datasets/${datasetId}/sync`, { expected404: true });
}

export async function createDatasetSync(
  datasetId: string,
  request: CreateSyncAutomationRequest,
): Promise<SyncAutomation> {
  return apiFetch<SyncAutomation>(`/datasets/${datasetId}/sync`, {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export async function updateDatasetSync(
  datasetId: string,
  request: UpdateSyncAutomationRequest,
): Promise<SyncAutomation> {
  return apiFetch<SyncAutomation>(`/datasets/${datasetId}/sync`, {
    method: 'PATCH',
    body: JSON.stringify(request),
  });
}

export async function deleteDatasetSync(datasetId: string, revision: number): Promise<void> {
  await apiFetch(`/datasets/${datasetId}/sync`, {
    method: 'DELETE',
    body: JSON.stringify({ revision }),
  });
}

export async function pauseDatasetSync(datasetId: string, revision: number): Promise<SyncAutomation> {
  return apiFetch<SyncAutomation>(`/datasets/${datasetId}/sync/pause`, {
    method: 'POST',
    body: JSON.stringify({ revision }),
  });
}

export async function resumeDatasetSync(datasetId: string, revision: number): Promise<SyncAutomation> {
  return apiFetch<SyncAutomation>(`/datasets/${datasetId}/sync/resume`, {
    method: 'POST',
    body: JSON.stringify({ revision }),
  });
}

export async function runDatasetSync(
  datasetId: string,
  revision?: number,
): Promise<SyncRunResponse> {
  return apiFetch<SyncRunResponse>(`/datasets/${datasetId}/sync/run`, {
    method: 'POST',
    headers: { 'Idempotency-Key': randomId() },
    body: JSON.stringify(revision === undefined ? {} : { revision }),
  });
}

export async function listSyncCredentials(datasetId: string): Promise<SyncCredentialMetadata[]> {
  const result = await apiFetch<{ items: SyncCredentialMetadata[] }>(
    `/sync/credentials?dataset_id=${encodeURIComponent(datasetId)}`,
  );
  return result.items;
}

export async function createSyncCredential(
  request: CreateSyncCredentialRequest,
): Promise<SyncCredentialMetadata> {
  return apiFetch<SyncCredentialMetadata>('/sync/credentials', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export async function replaceSyncCredential(
  credentialId: string,
  request: ReplaceSyncCredentialRequest,
): Promise<SyncCredentialMetadata> {
  return apiFetch<SyncCredentialMetadata>(`/sync/credentials/${credentialId}`, {
    method: 'PUT',
    body: JSON.stringify(request),
  });
}

export async function deleteSyncCredential(credentialId: string): Promise<void> {
  await apiFetch(`/sync/credentials/${credentialId}`, { method: 'DELETE' });
}
