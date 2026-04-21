import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { listMyApiKeys, createMyApiKey, revokeMyApiKey } from '@/api/auth';
import { toast } from 'sonner';

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
    onError: () => { toast.error('Failed to create API key'); },
  });
}

export function useRevokeMyApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) => revokeMyApiKey(keyId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.apiKeys.mine });
    },
    onError: () => { toast.error('Failed to revoke API key'); },
  });
}
