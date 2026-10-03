import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { useShallow } from 'zustand/react/shallow';
import { useSearchStore } from '@/stores/search-store';
import { searchDatasets, fetchCatalogSummary, fetchFacets } from '@/api/search';
import { listMaps } from '@/api/maps';

function searchResultsOptions(params: Record<string, string>) {
  return {
    queryKey: queryKeys.search.results(params),
    queryFn: () => searchDatasets(params),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  };
}

export function useSearchResults() {
  const params = useSearchStore(useShallow((s) => s.toParams()));

  return useQuery(searchResultsOptions(params));
}

/** Search visible maps separately because catalog dataset search does not index them. */
export function useMapSearchResults() {
  const q = useSearchStore((s) => s.q).trim();

  return useQuery({
    queryKey: queryKeys.search.maps(q),
    queryFn: () => listMaps({ search: q, limit: 6 }),
    enabled: q.length > 0,
    staleTime: 30_000,
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

/**
 * Total for the Type filter's All option: the result total without the selected
 * type. It only reads the results already cached for the untyped params, so it
 * issues no request; undefined means "not known" and callers fall back to the
 * facet sum.
 */
export function useAllTypesTotal(totalResults: number | undefined, isPlaceholderData = false) {
  const params = useSearchStore(useShallow((s) => s.toParams()));
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { record_type, offset, ...untyped } = params;
  // Same options as useSearchResults so this observer never replaces the shared
  // query's fetch function; disabled so it only reads the cache.
  const { data } = useQuery({ ...searchResultsOptions(untyped), enabled: false });
  // While the main query still shows the previous (typed) results, only the
  // cached untyped total is correct.
  return record_type || isPlaceholderData ? data?.numberMatched : totalResults;
}
