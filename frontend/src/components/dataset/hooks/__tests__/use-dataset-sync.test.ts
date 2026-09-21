import { useRef } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { renderHook, waitFor } from '@/test/test-utils';
import { getDatasetSync } from '@/api/dataset-sync';
import { useDatasetSync } from '@/components/dataset/hooks/use-dataset-sync';
import { queryKeys } from '@/lib/query-keys';

vi.mock('@/api/dataset-sync', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/dataset-sync')>();
  return { ...actual, getDatasetSync: vi.fn() };
});

const mockGetDatasetSync = vi.mocked(getDatasetSync);
const datasetId = 'dataset-1';
const derivedCacheKeys = [
  queryKeys.datasets.sync(datasetId),
  queryKeys.datasets.detail(datasetId),
  queryKeys.datasets.refreshRunsPrefix(datasetId),
  queryKeys.datasets.versionsPrefix(datasetId),
  queryKeys.datasets.rowsPrefix(datasetId),
  queryKeys.datasets.maps(datasetId),
  queryKeys.maps.columnValuesPrefix(datasetId),
  queryKeys.maps.columnStatsPrefix(datasetId),
];

function automationWithOccurrence(state: 'planned' | 'admitted' | 'delivered' | 'completed' | 'failed' | 'cancelled' | 'expired') {
  return {
    id: 'sync-1', dataset_id: datasetId, revision: 1, status: 'enabled' as const, pause_reason: null,
    source: { connector: 'arcgis_feature_server' as const, service_url: 'https://maps.example.test/FeatureServer', layer_id: 0 },
    credential: null, cadence: { kind: 'hourly' as const, minute: 0 }, next_due_at: null,
    eligibility: { eligible: true, reasons: [], policy_version: 'arcgis_id_set_v1' },
    last_occurrence: { id: 'occurrence-1', state, scheduled_for: '2026-09-19T12:00:00Z' },
    created_at: '2026-09-19T11:00:00Z', updated_at: '2026-09-19T11:00:00Z',
  };
}

function renderSyncWithClient() {
  let captured: QueryClient | null = null;
  const hook = renderHook(() => {
    const queryClient = useQueryClient();
    const clientRef = useRef<QueryClient | null>(null);
    if (!clientRef.current) clientRef.current = queryClient;
    captured = clientRef.current;
    return useDatasetSync(datasetId, true);
  });
  if (!captured) throw new Error('QueryClient capture failed');
  return { ...hook, queryClient: captured };
}

describe('useDatasetSync occurrence polling', () => {
  beforeEach(() => vi.clearAllMocks());

  it.each([
    ['planned', 'completed'],
    ['admitted', 'failed'],
    ['delivered', 'cancelled'],
    ['delivered', 'expired'],
  ] as const)('invalidates derived caches when polling observes %s to %s', async (activeState, terminalState) => {
    mockGetDatasetSync
      .mockResolvedValueOnce(automationWithOccurrence(activeState))
      .mockResolvedValue(automationWithOccurrence(terminalState));
    const { result, queryClient } = renderSyncWithClient();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

    await result.current.refetch();

    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({
      queryKey: queryKeys.datasets.versionsPrefix(datasetId),
    }));
    for (const queryKey of derivedCacheKeys) {
      expect(invalidate).toHaveBeenCalledWith({ queryKey });
    }
  });

  it('invalidates derived caches when its first observed occurrence is already terminal', async () => {
    mockGetDatasetSync.mockResolvedValue(automationWithOccurrence('completed'));
    const { result, queryClient } = renderSyncWithClient();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({
      queryKey: queryKeys.datasets.refreshRunsPrefix(datasetId),
    }));
    for (const queryKey of derivedCacheKeys) {
      expect(invalidate).toHaveBeenCalledWith({ queryKey });
    }
  });
});
