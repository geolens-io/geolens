import { useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { createFeature, updateFeature, deleteFeature } from '@/api/features';
import { addColumn, dropColumn } from '@/api/datasets';
import type { Geometry } from 'geojson';
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';

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
    }) => createFeature(datasetId, geometry, properties),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.rowsPrefix(variables.datasetId) });
    },
    onError: (err) => {
      console.error('[useCreateFeature]', err);
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
    }) => updateFeature(datasetId, gid, geometry, properties),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.rowsPrefix(variables.datasetId) });
    },
    onError: (err) => {
      console.error('[useUpdateFeature]', err);
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
    onError: (err) => {
      console.error('[useDeleteFeature]', err);
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
    onError: () => { toast.error(i18n.t('dataset:schema.addFailed')); },
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
    onError: () => { toast.error(i18n.t('dataset:schema.removeFailed')); },
  });
}
