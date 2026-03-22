import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
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

export function useCollections(skip = 0, limit = 50) {
  return useQuery({
    queryKey: ['collections', skip, limit],
    queryFn: () => listCollections({ skip, limit }),
    placeholderData: keepPreviousData,
  });
}

export function useCollection(id: string) {
  return useQuery({
    queryKey: ['collection', id],
    queryFn: () => getCollection(id),
    enabled: !!id,
  });
}

export function useCollectionDatasets(collectionId: string, skip = 0, limit = 20) {
  return useQuery({
    queryKey: ['collection-datasets', collectionId, skip, limit],
    queryFn: () => getCollectionDatasets(collectionId, { skip, limit }),
    enabled: !!collectionId,
    placeholderData: keepPreviousData,
  });
}

export function useCreateCollection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createCollection,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['collections'] });
    },
  });
}

export function useUpdateCollection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: CollectionUpdateRequest }) =>
      updateCollection(id, data),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['collection', variables.id] });
      qc.invalidateQueries({ queryKey: ['collections'] });
    },
  });
}

export function useDeleteCollection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteCollection(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['collections'] });
    },
  });
}

export function useAddDatasetsToCollection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ collectionId, datasetIds }: { collectionId: string; datasetIds: string[] }) =>
      addDatasetsToCollection(collectionId, datasetIds),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['collection', variables.collectionId] });
      qc.invalidateQueries({ queryKey: ['collection-datasets', variables.collectionId] });
      qc.invalidateQueries({ queryKey: ['collections'] });
      for (const datasetId of variables.datasetIds) {
        qc.invalidateQueries({ queryKey: ['dataset', datasetId] });
      }
    },
  });
}

export function useRemoveDatasetFromCollection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ collectionId, datasetId }: { collectionId: string; datasetId: string }) =>
      removeDatasetFromCollection(collectionId, datasetId),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['collection', variables.collectionId] });
      qc.invalidateQueries({ queryKey: ['collection-datasets', variables.collectionId] });
      qc.invalidateQueries({ queryKey: ['collections'] });
      qc.invalidateQueries({ queryKey: ['dataset', variables.datasetId] });
    },
  });
}
