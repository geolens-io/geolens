import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import {
  createDataset,
  getDataset,
  getDatasetRows,
  updateDataset,
  updatePublicationStatus,
  deleteDataset,
  getDatasetHistory,
  reuploadDataset,
  reuploadPreview,
  reuploadServicePreview,
  reuploadCommit,
  getDatasetVersions,
  listAttributes,
  updateAttribute,
  validateDataset,
} from '@/api/datasets';
import type {
  CreateDatasetRequest,
  DatasetUpdateRequest,
  AttributeMetadataUpdate,
  ReuploadServicePreviewRequest,
} from '@/types/api';

export function useCreateDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateDatasetRequest) => createDataset(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['datasets'] });
      qc.invalidateQueries({ queryKey: ['search'] });
    },
  });
}

export function useDataset(id: string, options?: { refetchInterval?: number | false | ((query: any) => number | false) }) {
  return useQuery({
    queryKey: ['dataset', id],
    queryFn: () => getDataset(id),
    enabled: !!id,
    refetchInterval: options?.refetchInterval,
  });
}

export function useDatasetRows(id: string, limit: number, cursor: number, filters?: Record<string, string>) {
  return useQuery({
    queryKey: ['dataset-rows', id, limit, cursor, filters],
    queryFn: () => getDatasetRows(id, { limit, after: cursor, filters }),
    enabled: !!id,
    placeholderData: keepPreviousData,
  });
}

export function useUpdateDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, data }: { datasetId: string; data: DatasetUpdateRequest }) =>
      updateDataset(datasetId, data),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['dataset', variables.datasetId] });
      qc.invalidateQueries({ queryKey: ['datasets'] });
      qc.invalidateQueries({ queryKey: ['search'] });
    },
  });
}

export function useUpdatePublicationStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, status }: { datasetId: string; status: string }) =>
      updatePublicationStatus(datasetId, status),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['dataset', variables.datasetId] });
      qc.invalidateQueries({ queryKey: ['datasets'] });
      qc.invalidateQueries({ queryKey: ['search'] });
    },
  });
}

export function useDeleteDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, confirmName }: { datasetId: string; confirmName: string }) =>
      deleteDataset(datasetId, confirmName),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['dataset', variables.datasetId] });
      qc.invalidateQueries({ queryKey: ['datasets'] });
      qc.invalidateQueries({ queryKey: ['search'] });
      qc.invalidateQueries({ queryKey: ['admin', 'stats'] });
    },
  });
}

export function useDatasetHistory(datasetId: string, skip = 0, limit = 50) {
  return useQuery({
    queryKey: ['dataset-history', datasetId, skip, limit],
    queryFn: () => getDatasetHistory(datasetId, { skip, limit }),
    enabled: !!datasetId,
    placeholderData: keepPreviousData,
  });
}

export function useReuploadDataset() {
  return useMutation({
    mutationFn: ({ datasetId, file }: { datasetId: string; file: File }) =>
      reuploadDataset(datasetId, file),
  });
}

export function useReuploadPreview() {
  return useMutation({
    mutationFn: ({ datasetId, jobId }: { datasetId: string; jobId: string }) =>
      reuploadPreview(datasetId, jobId),
  });
}

export function useReuploadServicePreview() {
  return useMutation({
    mutationFn: ({
      datasetId,
      request,
    }: {
      datasetId: string;
      request: ReuploadServicePreviewRequest;
    }) => reuploadServicePreview(datasetId, request),
  });
}

export function useReuploadCommit() {
  return useMutation({
    mutationFn: ({
      datasetId,
      jobId,
      sridOverride,
      token,
    }: {
      datasetId: string;
      jobId: string;
      sridOverride?: number | null;
      token?: string;
    }) => reuploadCommit(datasetId, jobId, sridOverride, token),
  });
}

export function useDatasetVersions(datasetId: string, skip = 0, limit = 50) {
  return useQuery({
    queryKey: ['dataset-versions', datasetId, skip, limit],
    queryFn: () => getDatasetVersions(datasetId, { skip, limit }),
    enabled: !!datasetId,
    placeholderData: keepPreviousData,
  });
}

export function useAttributes(datasetId: string | undefined) {
  return useQuery({
    queryKey: ['attributes', datasetId],
    queryFn: () => listAttributes(datasetId!),
    enabled: !!datasetId,
  });
}

export function useUpdateAttribute(datasetId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ attributeId, data }: { attributeId: string; data: AttributeMetadataUpdate }) =>
      updateAttribute(datasetId!, attributeId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['attributes', datasetId] });
    },
  });
}

export function useValidation(datasetId: string | undefined) {
  return useQuery({
    queryKey: ['validation', datasetId],
    queryFn: () => validateDataset(datasetId!),
    enabled: !!datasetId,
    staleTime: 30_000,
  });
}
