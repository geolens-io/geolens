import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { useAuthStore } from '@/stores/auth-store';
import {
  createSavedSearch,
  deleteSavedSearch,
  fetchSavedSearches,
} from '@/api/saved-searches';

export function useSavedSearches() {
  // SF-06: gate on !!token so anonymous routes (e.g. /login) never fire
  // /api/search/saved/ — eliminates 401 console noise pre-auth.
  const token = useAuthStore((s) => s.token);
  return useQuery({
    queryKey: queryKeys.savedSearches.all,
    queryFn: fetchSavedSearches,
    enabled: !!token,
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
