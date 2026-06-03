import { apiFetch } from './client';

export interface EditionInfo {
  edition: 'community' | 'enterprise';
  features: string[];
}

export async function fetchEdition(): Promise<EditionInfo> {
  return apiFetch<EditionInfo>('/settings/edition/');
}
