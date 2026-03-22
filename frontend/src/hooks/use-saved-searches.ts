import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createSavedSearch,
  deleteSavedSearch,
  fetchSavedSearches,
} from '@/api/saved-searches';

export function useSavedSearches() {
  return useQuery({
    queryKey: ['saved-searches'],
    queryFn: fetchSavedSearches,
    staleTime: 60_000,
  });
}

export function useSaveSearch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createSavedSearch,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['saved-searches'] });
    },
  });
}

export function useDeleteSavedSearch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteSavedSearch,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['saved-searches'] });
    },
  });
}
