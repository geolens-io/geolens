import { create } from 'zustand';
import { DEFAULT_PAGE_SIZE } from '@/lib/constants';

/** Valid keys for setFilter — excludes methods and non-filter state fields. */
export type SearchFilterKey =
  | 'q'
  | 'bbox'
  | 'keywords'
  | 'geometry_type'
  | 'srid'
  | 'source_organization'
  | 'record_type'
  | 'collection_id'
  | 'datetime'
  | 'date_from'
  | 'date_to'
  | 'vintage_start'
  | 'vintage_end'
  | 'sortBy'
  | 'exclude_synthetic'
  | 'geometry'
  | 'spatial_predicate';

interface SearchState {
  q: string;
  bbox: string;
  keywords: string[];
  geometry_type: string;
  srid: string;
  source_organization: string;
  record_type: string;
  collection_id: string;
  datetime: string;
  date_from: string;
  date_to: string;
  vintage_start: string;
  vintage_end: string;
  sortBy: string;
  offset: number;
  limit: number;
  exclude_synthetic: boolean;
  geometry: string;
  spatial_predicate: string;
  spatialPanelOpen: boolean;
  setQuery: (q: string) => void;
  setFilter: (key: SearchFilterKey, value: string | string[] | boolean) => void;
  resetFilters: () => void;
  setPage: (offset: number) => void;
  setSortBy: (sortBy: string) => void;
  setSpatialPanelOpen: (open: boolean) => void;
  toParams: () => Record<string, string>;
  restoreParams: (params: Record<string, string>) => void;
}

const initialState = {
  q: '',
  bbox: '',
  keywords: [] as string[],
  geometry_type: '',
  srid: '',
  source_organization: '',
  record_type: '',
  collection_id: '',
  datetime: '',
  date_from: '',
  date_to: '',
  vintage_start: '',
  vintage_end: '',
  sortBy: 'relevance',
  offset: 0,
  limit: DEFAULT_PAGE_SIZE,
  exclude_synthetic: true,
  geometry: '',
  spatial_predicate: 'intersects',
  spatialPanelOpen: false,
};

export const useSearchStore = create<SearchState>()((set, get) => ({
  ...initialState,

  setQuery: (q) => set({ q, offset: 0 }),

  setFilter: (key, value) => set({ [key]: value, offset: 0 }),

  resetFilters: () => set({ ...initialState }),

  setPage: (offset) => set({ offset }),

  setSortBy: (sortBy) => set({ sortBy, offset: 0 }),

  setSpatialPanelOpen: (open) => set({ spatialPanelOpen: open }),

  toParams: () => {
    const state = get();
    const params: Record<string, string> = {};

    if (state.q) params.q = state.q;
    if (state.bbox) params.bbox = state.bbox;
    if (state.geometry) params.geometry = state.geometry;
    if (state.keywords.length > 0) params.keywords = state.keywords.join(',');
    if (state.geometry_type) params.geometry_type = state.geometry_type;
    if (state.srid) params.srid = state.srid;
    if (state.source_organization) params.source_organization = state.source_organization;
    if (state.record_type) params.record_type = state.record_type;
    if (state.collection_id) params.collection_id = state.collection_id;
    if (state.datetime) params.datetime = state.datetime;
    if (state.date_from) params.date_from = state.date_from;
    if (state.date_to) params.date_to = state.date_to;
    if (state.vintage_start) params.vintage_start = state.vintage_start;
    if (state.vintage_end) params.vintage_end = state.vintage_end;
    if (state.spatial_predicate && state.spatial_predicate !== 'intersects') params.spatial_predicate = state.spatial_predicate;
    if (state.sortBy && state.sortBy !== 'relevance') params.sort_by = state.sortBy;
    if (state.offset > 0) params.offset = String(state.offset);
    if (state.limit !== DEFAULT_PAGE_SIZE) params.limit = String(state.limit);
    if (!state.exclude_synthetic) params.exclude_synthetic = 'false';

    return params;
  },

  restoreParams: (params) =>
    set({
      ...initialState,
      q: params.q || '',
      bbox: params.bbox || '',
      geometry: params.geometry || '',
      keywords: params.keywords ? params.keywords.split(',') : [],
      geometry_type: params.geometry_type || '',
      srid: params.srid || '',
      source_organization: params.source_organization || '',
      record_type: params.record_type || '',
      collection_id: params.collection_id || '',
      datetime: params.datetime || '',
      date_from: params.date_from || '',
      date_to: params.date_to || '',
      vintage_start: params.vintage_start || '',
      vintage_end: params.vintage_end || '',
      spatial_predicate: params.spatial_predicate || 'intersects',
      sortBy: params.sort_by || 'relevance',
      offset: params.offset ? parseInt(params.offset, 10) || 0 : 0,
      limit: params.limit ? parseInt(params.limit, 10) || DEFAULT_PAGE_SIZE : DEFAULT_PAGE_SIZE,
      exclude_synthetic: params.exclude_synthetic === 'false' ? false : true,
    }),
}));
