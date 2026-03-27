import { apiFetch } from './client';

export interface SavedSearch {
  id: string;
  name: string;
  params: Record<string, string>;
  created_at: string;
  updated_at: string;
}

export async function fetchSavedSearches(): Promise<{ searches: SavedSearch[]; total: number }> {
  return apiFetch<{ searches: SavedSearch[]; total: number }>('/search/saved');
}

export async function createSavedSearch(data: {
  name: string;
  params: Record<string, string>;
}): Promise<SavedSearch> {
  return apiFetch<SavedSearch>('/search/saved', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function deleteSavedSearch(id: string): Promise<void> {
  await apiFetch<void>(`/search/saved/${id}`, { method: 'DELETE' });
}
