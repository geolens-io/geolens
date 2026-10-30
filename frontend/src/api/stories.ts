import { toast } from 'sonner';
import { formatMutationError } from '@/lib/error-map';
import { apiFetch, ApiError } from './client';
import { xhrUpload, type UploadProgress } from './ingest';
import type {
  StoryAssetResponse,
  StoryChapter,
  StoryCreate,
  StoryDraftResponse,
  StoryGroupsResponse,
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

/** Where a story image is served; fetch it with `apiFetchBlob`, since a private story's needs the reader's token. */
export function storyAssetPath(storyId: string, assetId: string): string {
  return `/stories/${encodeURIComponent(storyId)}/assets/${encodeURIComponent(assetId)}`;
}

/** Uploads an image to a story, reporting the share of bytes sent. */
export async function uploadStoryImage(
  storyId: string,
  file: File,
  onProgress?: UploadProgress,
  signal?: AbortSignal,
): Promise<StoryAssetResponse> {
  const form = new FormData();
  form.append('file', file);
  return xhrUpload<StoryAssetResponse>(
    `/stories/${encodeURIComponent(storyId)}/assets`,
    form,
    onProgress,
    signal,
  );
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

/** What a story write may do about maps that block it: share the ones you may share with the groups lacking them. */
export type ShareBlockingMaps = 'share_maps';

export async function publishStory(id: string, revision: number, confirm?: ShareBlockingMaps): Promise<StoryResponse> {
  return apiFetch<StoryResponse>(`/stories/${encodeURIComponent(id)}/publish`, {
    method: 'POST',
    body: JSON.stringify({ revision, ...(confirm ? { confirm } : {}) }),
  });
}

/**
 * Share a story with exactly these groups; an empty list unshares it. Without
 * `confirm`, maps of the published story that some new group can't read come
 * back as a `maps_narrower_than_story` conflict.
 */
export async function setStoryGroups(
  id: string,
  groupIds: string[],
  confirm?: ShareBlockingMaps,
): Promise<StoryGroupsResponse> {
  return apiFetch<StoryGroupsResponse>(`/stories/${encodeURIComponent(id)}/groups/`, {
    method: 'PUT',
    body: JSON.stringify({ group_ids: groupIds, ...(confirm ? { confirm } : {}) }),
  });
}

export async function discardStoryDraft(id: string, revision: number): Promise<StoryDraftResponse> {
  return apiFetch<StoryDraftResponse>(`/stories/${encodeURIComponent(id)}/discard`, {
    method: 'POST',
    body: JSON.stringify({ revision }),
  });
}

export type BlockingMap = { id: string; name: string; canShare: boolean };
export type MapsBlockingStory = {
  code: 'maps_narrower_than_story';
  maps: BlockingMap[];
  unreadableMaps: number;
};

/** Whether sharing the author's own maps would clear every map in `blocked`. */
export function sharingMapsClears(blocked: MapsBlockingStory): boolean {
  return blocked.unreadableMaps === 0 && blocked.maps.length > 0 && blocked.maps.every((m) => m.canShare);
}
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
      ? detail.maps
          .filter(
            (m): m is { id: string; name: string; can_share?: unknown } =>
              typeof m?.id === 'string' && typeof m?.name === 'string',
          )
          .map((m) => ({ id: m.id, name: m.name, canShare: m.can_share === true }))
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
