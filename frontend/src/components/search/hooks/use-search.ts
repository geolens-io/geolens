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

/** Search visible maps separately because catalog dataset search does not index them. */
export function useMapSearchResults() {
  const q = useSearchStore((s) => s.q).trim();

  return useQuery({
    queryKey: queryKeys.search.maps(q),
    queryFn: () => listMaps({ search: q, limit: 6 }),
    enabled: q.length > 0,
    staleTime: 30_000,
    // Do not retain map cards after the user clears the search query.
    placeholderData: q.length > 0 ? keepPreviousData : undefined,
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
