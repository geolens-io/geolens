import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { listMyApiKeys, createMyApiKey, revokeMyApiKey } from '@/api/auth';

export function useMyApiKeys() {
  return useQuery({
    queryKey: ['my-api-keys'],
    queryFn: listMyApiKeys,
  });
}

export function useCreateMyApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => createMyApiKey(name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['my-api-keys'] });
    },
  });
}

export function useRevokeMyApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) => revokeMyApiKey(keyId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['my-api-keys'] });
    },
  });
}
