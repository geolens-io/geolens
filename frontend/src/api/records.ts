import { apiFetch } from './client';
import type {
  ContactCreate,
  ContactResponse,
  ContactListResponse,
  KeywordCreate,
  KeywordResponse,
  KeywordListResponse,
  DistributionListResponse,
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

// Distributions
export async function listDistributions(recordId: string): Promise<DistributionListResponse> {
  return apiFetch<DistributionListResponse>(`/records/${recordId}/distributions/`);
}
