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
  | 'sort_by'
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
  sort_by: string;
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
  setSortBy: (sort_by: string) => void;
  setSpatialPanelOpen: (open: boolean) => void;
  toParams: () => Record<string, string>;
  restoreParams: (params: Record<string, string>) => void;
  /**
   * fix(#1713, then #1761 review round 2 P2): drop every query-shaping
   * field on an identity change, called from the choke point in
   * lib/auth-cache-reset.ts. Round 1 reset only q/bbox/collection_id/
   * keywords/geometry, on the theory that the rest were "display
   * preferences" — wrong for most of them: geometry_type,
   * source_organization, record_type, srid, spatial_predicate,
   * exclude_synthetic and the date/vintage fields all shape which records
   * a search returns, and `toParams()` plus the URL-sync hook carry them
   * straight to the next identity. A stale `offset` compounds this: the
   * next identity's own query can have fewer results, landing them on an
   * empty page with no visible reason why.
   *
   * See `SEARCH_PRESENTATION_PREFERENCE_KEYS` for the only fields this
   * deliberately leaves alone, and why.
   */
  clearIdentityScopedFilters: () => void;
  /**
   * fix(#1761 review P2): bumped by clearIdentityScopedFilters on every
   * identity change (never by resetFilters/restoreParams, so it is
   * excluded from `initialState` below the same way drawing-store excludes
   * its session epoch from CLEARED_STATE). SearchBar keys its local input
   * state and pending debounce timer on this: when `q` is already '' at
   * the moment identity changes (nothing had been committed to the store
   * yet), `q` does not change value, so a `useEffect` keyed on `q` alone
   * does not re-run, and a debounce timer already counting down a
   * previous-identity keystroke still lands. This counter always changes.
   */
  resetEpoch: number;
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
  sort_by: 'relevance',
  offset: 0,
  limit: DEFAULT_PAGE_SIZE,
  exclude_synthetic: true,
  geometry: '',
  spatial_predicate: 'intersects',
  spatialPanelOpen: false,
};

/**
 * fix(#1761 review round 2 P2, corrected round 4): the ONLY fields
 * `clearIdentityScopedFilters` preserves across an identity change —
 * everything else in `initialState` is query-shaping and gets reset (see
 * that method). Each one is a genuine presentation preference, not
 * something that changes which records a search returns:
 *   - `sort_by` — sort direction/field.
 *   - `limit` — page size.
 *
 * fix(#1761 review round 4, sweep): `spatialPanelOpen` was wrongly listed
 * here as "a view toggle, not a filter". It gates whether
 * FilterPanel mounts SpatialFilterPanel, which holds its own uncommitted
 * `pendingBbox`/`predicate` draft — the exact same shape of bug as
 * FilterPanel/FilterSheet's date-range draft (finding 1 of this round),
 * just for the bbox filter, and reached through onApply rather than
 * through this store directly. Left in the "kept" set, an identity change
 * would leave the panel open with the previous identity's drawn geometry,
 * and Apply would write it into the just-cleared store. Removed from this
 * list: clearIdentityScopedFilters's `...initialState` spread now resets
 * it to `false`, which unmounts SpatialFilterPanel and, as a consequence,
 * discards its local draft state for free.
 *
 * Exported so search-store.test.ts can iterate the store's own keys and
 * assert every field is classified one way or the other — a field added to
 * `initialState` later and left out of this list is reset by default
 * (the safe direction: reset, not leak), but the test will still show it
 * landing in the "reset" bucket so that default is a visible choice rather
 * than an accident.
 */
export const SEARCH_PRESENTATION_PREFERENCE_KEYS: readonly (keyof typeof initialState)[] = [
  'sort_by',
  'limit',
];

export const useSearchStore = create<SearchState>()((set, get) => ({
  ...initialState,
  resetEpoch: 0,

  setQuery: (q) => set({ q, offset: 0 }),

  setFilter: (key, value) => set({ [key]: value, offset: 0 }),

  resetFilters: () => set({ ...initialState }),

  setPage: (offset) => set({ offset }),

  setSortBy: (sort_by) => set({ sort_by, offset: 0 }),

  setSpatialPanelOpen: (open) => set({ spatialPanelOpen: open }),

  clearIdentityScopedFilters: () =>
    set((s) => ({
      ...initialState,
      // Presentation preferences (see SEARCH_PRESENTATION_PREFERENCE_KEYS):
      // kept as they were, not reset to their defaults. spatialPanelOpen is
      // deliberately NOT here — see that constant's doc comment — so the
      // `...initialState` spread above resets it to false.
      sort_by: s.sort_by,
      limit: s.limit,
      resetEpoch: s.resetEpoch + 1,
    })),

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
    if (state.sort_by && state.sort_by !== 'relevance') params.sort_by = state.sort_by;
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
      sort_by: params.sort_by || 'relevance',
      offset: params.offset ? parseInt(params.offset, 10) || 0 : 0,
      limit: params.limit ? parseInt(params.limit, 10) || DEFAULT_PAGE_SIZE : DEFAULT_PAGE_SIZE,
      exclude_synthetic: params.exclude_synthetic === 'false' ? false : true,
    }),
}));
