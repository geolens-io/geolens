import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { createDatasetApiKey, listDatasetApiKeys, revokeDatasetApiKey } from '@/api/datasets';
import { formatMutationError } from '@/lib/error-map';
import { queryKeys } from '@/lib/query-keys';
import i18n from '@/i18n/i18n';

export function useDatasetApiKeys(datasetId: string) {
  return useQuery({
    queryKey: queryKeys.apiKeys.dataset(datasetId),
    queryFn: () => listDatasetApiKeys(datasetId),
  });
}

export function useCreateDatasetApiKey(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; expires_at: string }) =>
      createDatasetApiKey(datasetId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.apiKeys.dataset(datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.apiKeys.mine });
    },
    onError: (err) => { toast.error(formatMutationError('admin:apiKeys.createError', err)); },
  });
}

export function useRevokeDatasetApiKey(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) => revokeDatasetApiKey(datasetId, keyId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.apiKeys.dataset(datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.apiKeys.mine });
    },
    onError: () => { toast.error(i18n.t('admin:apiKeys.revokeError')); },
  });
}
