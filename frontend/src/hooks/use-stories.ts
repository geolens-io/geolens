import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  createStory,
  deleteStory,
  duplicateStory,
  getStory,
  getStoryDraft,
  listStories,
} from '@/api/stories';
import { ApiError } from '@/api/client';
import { queryKeys } from '@/lib/query-keys';
import { formatMutationError } from '@/lib/error-map';
import type { StoryCreate } from '@/types/api';

export function useStories(params: { skip: number; limit: number }) {
  return useQuery({
    queryKey: queryKeys.stories.list(params),
    queryFn: () => listStories(params),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useStory(id: string | undefined, opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.stories.detail(id),
    queryFn: () => getStory(id!),
    enabled: !!id && (opts?.enabled ?? true),
    staleTime: 60_000,
    // A missing or hidden story stays that way; retrying only delays the not-found state.
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 1,
  });
}

/** The draft and its revision, for the story's owner or an admin. */
export function useStoryDraft(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.stories.draft(id),
    queryFn: () => getStoryDraft(id!),
    enabled: !!id,
    // The editor keeps its own copy once loaded, so only a mount reads the draft again.
    staleTime: Infinity,
    refetchOnMount: 'always',
    refetchOnWindowFocus: false,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && (error.status === 404 || error.status === 403)) &&
      failureCount < 1,
  });
}

export function useCreateStory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: StoryCreate) => createStory(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.stories.all });
    },
    onError: (err) => {
      toast.error(formatMutationError('stories:create.failed', err));
    },
  });
}

export function useDuplicateStory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => duplicateStory(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.stories.all });
    },
    onError: (err) => {
      toast.error(formatMutationError('stories:list.duplicateFailed', err));
    },
  });
}

export function useDeleteStory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id }: { id: string; leavingPage?: boolean }) => deleteStory(id),
    onSuccess: (_data, { id, leavingPage }) => {
      qc.removeQueries({ queryKey: queryKeys.stories.detail(id) });
      // A list leaving an emptied page loads the page before it, so there's nothing to refetch now.
      qc.invalidateQueries({ queryKey: queryKeys.stories.all, refetchType: leavingPage ? 'none' : 'active' });
    },
    // The hook owns the error toast; callers must not raise a second one.
    onError: (err) => {
      toast.error(formatMutationError('stories:list.deleteFailed', err));
    },
  });
}
