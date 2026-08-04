import { apiFetch } from './client';
import type {
  ContactCreate,
  ContactResponse,
  ContactListResponse,
  DistributionListResponse,
  KeywordCreate,
  KeywordResponse,
  KeywordListResponse,
} from '@/types/api';

// Contacts
export async function listContacts(recordId: string): Promise<ContactListResponse> {
  return apiFetch<ContactListResponse>(`/records/${recordId}/contacts/`);
}

export async function createContact(recordId: string, data: ContactCreate): Promise<ContactResponse> {
  return apiFetch<ContactResponse>(`/records/${recordId}/contacts/`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function deleteContact(recordId: string, contactId: string): Promise<void> {
  await apiFetch(`/records/${recordId}/contacts/${contactId}/`, { method: 'DELETE' });
}

// Keywords
export async function listKeywords(
  recordId: string,
  // feat(#1070): counterfactual audience for inherited_audience_gap — "would
  // this visibility/status expose inherited keywords past their source?"
  opts?: { audienceVisibility?: string; audienceRecordStatus?: string },
): Promise<KeywordListResponse> {
  const params = new URLSearchParams();
  if (opts?.audienceVisibility) params.set('audience_visibility', opts.audienceVisibility);
  if (opts?.audienceRecordStatus) params.set('audience_record_status', opts.audienceRecordStatus);
  const qs = params.size > 0 ? `?${params.toString()}` : '';
  return apiFetch<KeywordListResponse>(`/records/${recordId}/keywords/${qs}`);
}

export async function createKeyword(recordId: string, data: KeywordCreate): Promise<KeywordResponse> {
  return apiFetch<KeywordResponse>(`/records/${recordId}/keywords/`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function deleteKeyword(recordId: string, keywordId: string): Promise<void> {
  await apiFetch(`/records/${recordId}/keywords/${keywordId}/`, { method: 'DELETE' });
}

// Distributions (read-only surface — the UI has no distribution editor;
// chore(#835) deleted the callerless create/update/delete mutations)
export async function listDistributions(recordId: string): Promise<DistributionListResponse> {
  return apiFetch<DistributionListResponse>(`/records/${recordId}/distributions/`);
}
