import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { listMyApiKeys, createMyApiKey, revokeMyApiKey } from '@/api/auth';
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';

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
    onError: () => { toast.error(i18n.t('admin:apiKeys.createError')); },
  });
}

export function useRevokeMyApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) => revokeMyApiKey(keyId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.apiKeys.mine });
    },
    onError: () => { toast.error(i18n.t('admin:apiKeys.revokeError')); },
  });
}
