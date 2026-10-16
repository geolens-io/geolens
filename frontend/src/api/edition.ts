import { apiFetch } from './client';

interface EditionInfo {
  edition: 'community' | 'enterprise';
  features: string[];
  tenancy_mode?: 'single_tenant' | 'multi_tenant';
}

export async function fetchEdition(): Promise<EditionInfo> {
  return apiFetch<EditionInfo>('/settings/edition/');
}
