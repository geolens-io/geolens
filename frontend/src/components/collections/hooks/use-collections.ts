import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import {
  listCollections,
  getCollection,
  getCollectionDatasets,
  createCollection,
  updateCollection,
  deleteCollection,
  addDatasetsToCollection,
  removeDatasetFromCollection,
} from '@/api/collections';
import type { CollectionUpdateRequest } from '@/types/api';
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';

// Collections change rarely (append-only from the user's perspective).
// 60s stale time prevents refetch on every mount while still picking up
// changes from other tabs within a reasonable window.
const COLLECTIONS_STALE_TIME = 60_000;

export function useCollections(skip = 0, limit = 50) {
  return useQuery({
    queryKey: queryKeys.collections.list(skip, limit),
    queryFn: () => listCollections({ skip, limit }),
    placeholderData: keepPreviousData,
    staleTime: COLLECTIONS_STALE_TIME,
  });
}

export function useCollection(id: string) {
  return useQuery({
    queryKey: queryKeys.collections.detail(id),
    queryFn: () => getCollection(id),
    enabled: !!id,
    staleTime: COLLECTIONS_STALE_TIME,
  });
}

export function useCollectionDatasets(collectionId: string, skip = 0, limit = 20) {
  return useQuery({
    queryKey: queryKeys.collections.datasets(collectionId, skip, limit),
    queryFn: () => getCollectionDatasets(collectionId, { skip, limit }),
    enabled: !!collectionId,
    placeholderData: keepPreviousData,
    staleTime: COLLECTIONS_STALE_TIME,
  });
}

export function useCreateCollection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createCollection,
    onSuccess: () => {
      qc.invalidateQueries({
        predicate: (query) =>
          Array.isArray(query.queryKey) && query.queryKey[0] === 'collections',
      });
    },
    onError: () => { toast.error(i18n.t('collections:toasts.createFailed')); },
  });
}

export function useUpdateCollection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: CollectionUpdateRequest }) =>
      updateCollection(id, data),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.collections.detail(variables.id) });
      qc.invalidateQueries({
        predicate: (query) =>
          Array.isArray(query.queryKey) && query.queryKey[0] === 'collections',
      });
    },
    onError: () => { toast.error(i18n.t('collections:toasts.updateFailed')); },
  });
}

export function useDeleteCollection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteCollection(id),
    onSuccess: () => {
      qc.invalidateQueries({
        predicate: (query) =>
          Array.isArray(query.queryKey) && query.queryKey[0] === 'collections',
      });
    },
    onError: () => { toast.error(i18n.t('collections:toasts.deleteFailed')); },
  });
}

export function useAddDatasetsToCollection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ collectionId, datasetIds }: { collectionId: string; datasetIds: string[] }) =>
      addDatasetsToCollection(collectionId, datasetIds),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.collections.detail(variables.collectionId) });
      qc.invalidateQueries({ queryKey: queryKeys.collections.datasetsPrefix(variables.collectionId) });
      qc.invalidateQueries({
        predicate: (query) =>
          Array.isArray(query.queryKey) && query.queryKey[0] === 'collections',
      });
      for (const datasetId of variables.datasetIds) {
        qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(datasetId) });
      }
    },
    onError: () => { toast.error(i18n.t('collections:toasts.addDatasetsFailed')); },
  });
}

export function useRemoveDatasetFromCollection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ collectionId, datasetId }: { collectionId: string; datasetId: string }) =>
      removeDatasetFromCollection(collectionId, datasetId),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.collections.detail(variables.collectionId) });
      qc.invalidateQueries({ queryKey: queryKeys.collections.datasetsPrefix(variables.collectionId) });
      qc.invalidateQueries({
        predicate: (query) =>
          Array.isArray(query.queryKey) && query.queryKey[0] === 'collections',
      });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(variables.datasetId) });
    },
    onError: () => { toast.error(i18n.t('collections:toasts.removeDatasetFailed')); },
  });
}
