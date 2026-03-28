import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { listMyApiKeys, createMyApiKey, revokeMyApiKey } from '@/api/auth';

export function useMyApiKeys() {
  return useQuery({
    queryKey: queryKeys.apiKeys.mine,
    queryFn: listMyApiKeys,
  });
}

export function useCreateMyApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => createMyApiKey(name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.apiKeys.mine });
    },
  });
}

export function useRevokeMyApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) => revokeMyApiKey(keyId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.apiKeys.mine });
    },
  });
}
