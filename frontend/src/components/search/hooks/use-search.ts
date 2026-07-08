import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { useShallow } from 'zustand/react/shallow';
import { useSearchStore } from '@/stores/search-store';
import { searchDatasets, fetchCatalogSummary, fetchFacets } from '@/api/search';
import { listMaps } from '@/api/maps';

export function useSearchResults() {
  const params = useSearchStore(useShallow((s) => s.toParams()));

  return useQuery({
    queryKey: queryKeys.search.results(params),
    queryFn: () => searchDatasets(params),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

/**
 * fix(V-08): catalog search (`searchDatasets` above) only queries
 * Dataset/DatasetGrant/Record — maps are never indexed into it, so a home
 * search for a map's name (e.g. "matterhorn") surfaced zero results even
 * though a public map by that name exists. Cheaper than teaching catalog
 * search about maps: issue a PARALLEL request to the existing `/api/maps/`
 * list endpoint with the same `q`, which already scopes results to what the
 * caller can see (anonymous -> public maps only). Only fires with a non-empty
 * query — this is a search-results affordance, not a "browse maps" one.
 */
export function useMapSearchResults() {
  const q = useSearchStore((s) => s.q).trim();

  return useQuery({
    queryKey: queryKeys.search.maps(q),
    queryFn: () => listMaps({ search: q, limit: 6 }),
    enabled: q.length > 0,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

export function useFacets() {
  const params = useSearchStore(useShallow((s) => s.toParams()));
  // Exclude record_type and collection_id from facet params -- facets show counts for all types/collections
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { record_type, collection_id, ...facetParams } = params;

  return useQuery({
    queryKey: queryKeys.search.facets(facetParams),
    queryFn: () => fetchFacets(facetParams),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  });
}

export function useCatalogSummary() {
  return useQuery({
    queryKey: queryKeys.search.summary,
    queryFn: () => fetchCatalogSummary(),
    staleTime: 5 * 60_000,
    select: (data) => data.summaries,
  });
}
