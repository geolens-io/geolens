import { useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { createFeature, updateFeature, deleteFeature } from '@/api/features';
import { addColumn, dropColumn } from '@/api/datasets';
import type { Geometry } from 'geojson';

export function useCreateFeature() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      datasetId,
      geometry,
      properties,
    }: {
      datasetId: string;
      geometry: Geometry;
      properties?: Record<string, unknown>;
    }) => createFeature(datasetId, geometry as Record<string, unknown>, properties),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.rowsPrefix(variables.datasetId) });
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
      geometry?: Geometry;
      properties?: Record<string, unknown>;
    }) => updateFeature(datasetId, gid, geometry as Record<string, unknown> | undefined, properties),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.rowsPrefix(variables.datasetId) });
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
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.rowsPrefix(variables.datasetId) });
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
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.rowsPrefix(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.attributes(variables.datasetId) });
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
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.rowsPrefix(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.attributes(variables.datasetId) });
    },
  });
}
