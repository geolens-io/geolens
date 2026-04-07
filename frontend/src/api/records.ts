import { apiFetch } from './client';
import type {
  ContactCreate,
  ContactResponse,
  ContactListResponse,
  DistributionResponse,
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
export async function listKeywords(recordId: string): Promise<KeywordListResponse> {
  return apiFetch<KeywordListResponse>(`/records/${recordId}/keywords/`);
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

// Contacts - update
export async function updateContact(
  recordId: string,
  contactId: string,
  data: Partial<ContactCreate>,
): Promise<ContactResponse> {
  return apiFetch<ContactResponse>(`/records/${recordId}/contacts/${contactId}/`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

// Distributions
export async function listDistributions(recordId: string): Promise<DistributionListResponse> {
  return apiFetch<DistributionListResponse>(`/records/${recordId}/distributions/`);
}

export interface DistributionCreate {
  distribution_type: string;
  format: string;
  url: string;
  title?: string;
  description?: string;
  protocol?: string;
  media_type?: string;
  is_primary?: boolean;
}

export async function createDistribution(
  recordId: string,
  data: DistributionCreate,
): Promise<DistributionResponse> {
  return apiFetch<DistributionResponse>(`/records/${recordId}/distributions/`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateDistribution(
  recordId: string,
  distributionId: string,
  data: Partial<DistributionCreate>,
): Promise<DistributionResponse> {
  return apiFetch<DistributionResponse>(`/records/${recordId}/distributions/${distributionId}/`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function deleteDistribution(recordId: string, distributionId: string): Promise<void> {
  await apiFetch(`/records/${recordId}/distributions/${distributionId}/`, { method: 'DELETE' });
}
