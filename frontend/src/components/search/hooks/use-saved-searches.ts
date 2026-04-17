import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import {
  createSavedSearch,
  deleteSavedSearch,
  fetchSavedSearches,
} from '@/api/saved-searches';

export function useSavedSearches() {
  return useQuery({
    queryKey: queryKeys.savedSearches.all,
    queryFn: fetchSavedSearches,
    staleTime: 60_000,
  });
}

export function useSaveSearch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createSavedSearch,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.savedSearches.all });
    },
  });
}

export function useDeleteSavedSearch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteSavedSearch,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.savedSearches.all });
    },
  });
}
