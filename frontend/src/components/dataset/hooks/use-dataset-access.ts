import { useDistributions } from '@/components/dataset/hooks/use-records';
import { useTileConfig } from '@/hooks/use-settings';
import {
  getDatasetAccessEndpoints,
  getPublicApiBaseUrl,
  type DatasetAccessEndpoints,
} from '@/lib/dataset-access';
import type { DatasetResponse, DistributionResponse } from '@/types/api';

const EMPTY_DISTRIBUTIONS: DistributionResponse[] = [];

export function useDatasetAccessEndpoints(
  dataset: Pick<DatasetResponse, 'id' | 'record_id' | 'record_type' | 'table_name'>,
): { endpoints: DatasetAccessEndpoints; publicApiBaseUrl: string | null } {
  const { data: distributions } = useDistributions(dataset.record_id);
  const { data: tileConfig } = useTileConfig();
  const publicApiBaseUrl = getPublicApiBaseUrl(tileConfig);
  const endpoints = getDatasetAccessEndpoints(
    dataset,
    publicApiBaseUrl,
    distributions?.distributions ?? EMPTY_DISTRIBUTIONS,
  );
  return { endpoints, publicApiBaseUrl };
}
