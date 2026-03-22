import { useMutation, useQueryClient } from '@tanstack/react-query';
import { createFeature, updateFeature, deleteFeature } from '@/api/features';
import { addColumn, dropColumn } from '@/api/datasets';

export function useCreateFeature() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      datasetId,
      geometry,
      properties,
    }: {
      datasetId: string;
      geometry: Record<string, unknown>;
      properties?: Record<string, unknown>;
    }) => createFeature(datasetId, geometry, properties),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['dataset', variables.datasetId] });
      qc.invalidateQueries({ queryKey: ['dataset-rows', variables.datasetId] });
    },
  });
}

export function useUpdateFeature() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      datasetId,
      gid,
      geometry,
      properties,
    }: {
      datasetId: string;
      gid: number;
      geometry?: Record<string, unknown>;
      properties?: Record<string, unknown>;
    }) => updateFeature(datasetId, gid, geometry, properties),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['dataset', variables.datasetId] });
      qc.invalidateQueries({ queryKey: ['dataset-rows', variables.datasetId] });
    },
  });
}

export function useDeleteFeature() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      datasetId,
      gid,
    }: {
      datasetId: string;
      gid: number;
    }) => deleteFeature(datasetId, gid),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['dataset', variables.datasetId] });
      qc.invalidateQueries({ queryKey: ['dataset-rows', variables.datasetId] });
    },
  });
}

export function useAddColumn() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      datasetId,
      column,
    }: {
      datasetId: string;
      column: { name: string; type: string };
    }) => addColumn(datasetId, column),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['dataset', variables.datasetId] });
      qc.invalidateQueries({ queryKey: ['dataset-rows', variables.datasetId] });
      qc.invalidateQueries({ queryKey: ['attributes', variables.datasetId] });
    },
  });
}

export function useDropColumn() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      datasetId,
      columnName,
    }: {
      datasetId: string;
      columnName: string;
    }) => dropColumn(datasetId, columnName),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['dataset', variables.datasetId] });
      qc.invalidateQueries({ queryKey: ['dataset-rows', variables.datasetId] });
      qc.invalidateQueries({ queryKey: ['attributes', variables.datasetId] });
    },
  });
}
