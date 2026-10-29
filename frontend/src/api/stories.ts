import { toast } from 'sonner';
import { formatMutationError } from '@/lib/error-map';
import { apiFetch, ApiError } from './client';
import type {
  StoryChapter,
  StoryCreate,
  StoryDraftResponse,
  StoryListResponse,
  StoryResponse,
  StoryUpdate,
} from '@/types/api';

export async function listStories(
  params: { skip?: number; limit?: number } = {},
): Promise<StoryListResponse> {
  const query = new URLSearchParams();
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  const qs = query.toString();
  return apiFetch<StoryListResponse>(`/stories/${qs ? `?${qs}` : ''}`);
}

export async function getStory(id: string): Promise<StoryResponse> {
  return apiFetch<StoryResponse>(`/stories/${encodeURIComponent(id)}`);
}

export async function duplicateStory(id: string): Promise<StoryDraftResponse> {
  return apiFetch<StoryDraftResponse>(`/stories/${encodeURIComponent(id)}/duplicate`, {
    method: 'POST',
  });
}

export async function deleteStory(id: string): Promise<void> {
  await apiFetch(`/stories/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function createStory(body: StoryCreate): Promise<StoryDraftResponse> {
  return apiFetch<StoryDraftResponse>('/stories/', { method: 'POST', body: JSON.stringify(body) });
}

export async function updateStory(id: string, body: StoryUpdate): Promise<StoryResponse> {
  return apiFetch<StoryResponse>(`/stories/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

export async function getStoryDraft(id: string): Promise<StoryDraftResponse> {
  return apiFetch<StoryDraftResponse>(`/stories/${encodeURIComponent(id)}/draft`);
}

export async function saveStoryDraft(
  id: string,
  revision: number,
  chapters: StoryChapter[],
): Promise<StoryDraftResponse> {
  return apiFetch<StoryDraftResponse>(`/stories/${encodeURIComponent(id)}/draft`, {
    method: 'PUT',
    body: JSON.stringify({ revision, document: { version: 1, chapters } }),
  });
}

export async function publishStory(id: string, revision: number): Promise<StoryResponse> {
  return apiFetch<StoryResponse>(`/stories/${encodeURIComponent(id)}/publish`, {
    method: 'POST',
    body: JSON.stringify({ revision }),
  });
}

export async function discardStoryDraft(id: string, revision: number): Promise<StoryDraftResponse> {
  return apiFetch<StoryDraftResponse>(`/stories/${encodeURIComponent(id)}/discard`, {
    method: 'POST',
    body: JSON.stringify({ revision }),
  });
}

export type MapsBlockingStory = {
  code: 'maps_narrower_than_story';
  maps: { id: string; name: string }[];
  unreadableMaps: number;
};
export type StoryConflict =
  | { code: 'stale_revision'; revision: number }
  | MapsBlockingStory
  | { code: 'story_maps_not_found'; mapIds: string[] };

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];

/** The structured refusals story writes answer with that the editor acts on; null for any other error. */
function storyConflictFromError(err: unknown): StoryConflict | null {
  if (!(err instanceof ApiError)) return null;
  const detail = err.body as
    | { code?: unknown; maps?: unknown; unreadable_maps?: unknown; revision?: unknown; map_ids?: unknown }
    | undefined;
  if (err.status === 422 && detail?.code === 'story_maps_not_found') {
    return { code: 'story_maps_not_found', mapIds: strings(detail.map_ids) };
  }
  if (err.status !== 409) return null;
  if (detail?.code === 'stale_revision' && typeof detail.revision === 'number') {
    return { code: 'stale_revision', revision: detail.revision };
  }
  if (detail?.code === 'maps_narrower_than_story') {
    const maps = Array.isArray(detail.maps)
      ? detail.maps.filter(
          (m): m is { id: string; name: string } =>
            typeof m?.id === 'string' && typeof m?.name === 'string',
        )
      : [];
    const unreadableMaps = typeof detail.unreadable_maps === 'number' ? detail.unreadable_maps : 0;
    return { code: 'maps_narrower_than_story', maps, unreadableMaps };
  }
  return null;
}

/** Hands a structured 409 to `onConflict` and reports any other failure as an error toast. */
export function reportStoryWriteError(
  err: unknown,
  fallbackKey: string,
  onConflict: (conflict: StoryConflict) => void,
): void {
  const conflict = storyConflictFromError(err);
  if (conflict) onConflict(conflict);
  else toast.error(formatMutationError(fallbackKey, err));
}
