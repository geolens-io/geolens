import { useSearchStore, SEARCH_PRESENTATION_PREFERENCE_KEYS } from '@/stores/search-store';

const initialState = useSearchStore.getState();

describe('useSearchStore', () => {
  beforeEach(() => {
    useSearchStore.setState(initialState, true);
  });

  it('setQuery updates q and resets offset to 0', () => {
    useSearchStore.setState({ offset: 20 });
    useSearchStore.getState().setQuery('parks');

    expect(useSearchStore.getState().q).toBe('parks');
    expect(useSearchStore.getState().offset).toBe(0);
  });

  it('setFilter sets the filter key and resets offset', () => {
    useSearchStore.setState({ offset: 20 });
    useSearchStore.getState().setFilter('geometry_type', 'Polygon');

    expect(useSearchStore.getState().geometry_type).toBe('Polygon');
    expect(useSearchStore.getState().offset).toBe(0);
  });

  it('setFilter sets keywords array', () => {
    useSearchStore.getState().setFilter('keywords', ['water', 'rivers']);

    expect(useSearchStore.getState().keywords).toEqual(['water', 'rivers']);
  });

  it('resetFilters restores initial state', () => {
    useSearchStore.getState().setQuery('parks');
    useSearchStore.getState().setFilter('geometry_type', 'Polygon');
    useSearchStore.getState().resetFilters();

    expect(useSearchStore.getState().q).toBe('');
    expect(useSearchStore.getState().geometry_type).toBe('');
    expect(useSearchStore.getState().keywords).toEqual([]);
  });

  it('setPage updates offset', () => {
    useSearchStore.getState().setPage(30);

    expect(useSearchStore.getState().offset).toBe(30);
  });

  it('setSortBy updates sort_by and resets offset', () => {
    useSearchStore.setState({ offset: 10 });
    useSearchStore.getState().setSortBy('name');

    expect(useSearchStore.getState().sort_by).toBe('name');
    expect(useSearchStore.getState().offset).toBe(0);
  });

  it('toParams omits empty and default values', () => {
    useSearchStore.getState().setQuery('rivers');
    const params = useSearchStore.getState().toParams();

    expect(params.q).toBe('rivers');
    expect(params).not.toHaveProperty('sort_by');
    expect(params).not.toHaveProperty('offset');
    expect(params).not.toHaveProperty('geometry_type');
  });

  it('toParams includes non-default sort_by', () => {
    useSearchStore.getState().setSortBy('name');

    expect(useSearchStore.getState().toParams().sort_by).toBe('name');
  });

  it('restoreParams sets state from URL params', () => {
    useSearchStore.getState().restoreParams({
      q: 'test',
      geometry_type: 'Point',
      keywords: 'a,b',
    });

    expect(useSearchStore.getState().q).toBe('test');
    expect(useSearchStore.getState().geometry_type).toBe('Point');
    expect(useSearchStore.getState().keywords).toEqual(['a', 'b']);
  });

  it('toParams includes non-default spatial_predicate', () => {
    useSearchStore.getState().setFilter('spatial_predicate', 'within');
    const params = useSearchStore.getState().toParams();

    expect(params.spatial_predicate).toBe('within');
  });

  it('toParams omits default spatial_predicate', () => {
    const params = useSearchStore.getState().toParams();

    expect(params).not.toHaveProperty('spatial_predicate');
  });

  it('restoreParams restores spatial_predicate', () => {
    useSearchStore.getState().restoreParams({
      q: 'test',
      spatial_predicate: 'within',
    });

    expect(useSearchStore.getState().spatial_predicate).toBe('within');
  });

  it('restoreParams defaults spatial_predicate to intersects', () => {
    useSearchStore.getState().restoreParams({ q: 'test' });

    expect(useSearchStore.getState().spatial_predicate).toBe('intersects');
  });

  it('resetFilters resets spatial_predicate to intersects', () => {
    useSearchStore.getState().setFilter('spatial_predicate', 'within');
    useSearchStore.getState().resetFilters();

    expect(useSearchStore.getState().spatial_predicate).toBe('intersects');
  });

  // fix(#1713): drop the typed/drawn search intent that could implicate the
  // previous identity, called from the identity-change choke point (see
  // lib/__tests__/auth-cache-reset.test.ts for that wiring).
  it('clearIdentityScopedFilters clears search-shaping fields', () => {
    useSearchStore.setState({
      q: 'parks',
      bbox: '1,2,3,4',
      collection_id: 'c1',
      keywords: ['water'],
      geometry: '{"type":"Point","coordinates":[0,0]}',
      srid: '4326',
      sort_by: 'name',
    });

    useSearchStore.getState().clearIdentityScopedFilters();

    const state = useSearchStore.getState();
    expect(state.q).toBe('');
    expect(state.bbox).toBe('');
    expect(state.collection_id).toBe('');
    expect(state.keywords).toEqual([]);
    expect(state.geometry).toBe('');
    // fix(#1761 review round 2 P2): srid shapes the query too — reset,
    // where round 1 wrongly left it alone.
    expect(state.srid).toBe('');
    // Presentation preference: survives.
    expect(state.sort_by).toBe('name');
  });

  /**
   * fix(#1761 review round 2 P2): round 1's partial reset left
   * geometry_type, source_organization, record_type, the date/vintage
   * fields, srid, spatial_predicate, exclude_synthetic and the pagination
   * offset untouched — all query-shaping, all exposed to the next identity
   * via toParams()/the URL-sync hook, and a stale offset could additionally
   * land the next identity on an empty page of their own results.
   *
   * This iterates every DATA key the store actually has (not a hardcoded
   * list) so a field added to SearchState later is automatically checked
   * against SEARCH_PRESENTATION_PREFERENCE_KEYS: either it is declared a
   * presentation preference and this proves it survives, or it isn't and
   * this proves it resets. Nothing can slip through unclassified.
   */
  it('resets every query-shaping field and preserves only the declared presentation preferences', () => {
    const before = useSearchStore.getState();
    const dataKeys = (Object.keys(before) as (keyof typeof before)[]).filter(
      (key) => typeof before[key] !== 'function' && key !== 'resetEpoch',
    );
    const originalValues: Record<string, unknown> = {};
    const dirtyValues: Record<string, unknown> = {};
    for (const key of dataKeys) {
      const current = (before as unknown as Record<string, unknown>)[key];
      originalValues[key as string] = current;
      dirtyValues[key as string] = makeDistinctValue(current);
    }
    useSearchStore.setState(dirtyValues);

    useSearchStore.getState().clearIdentityScopedFilters();

    const after = useSearchStore.getState() as unknown as Record<string, unknown>;
    const preserved = new Set<string>(SEARCH_PRESENTATION_PREFERENCE_KEYS);
    for (const key of dataKeys as string[]) {
      if (preserved.has(key)) {
        expect(after[key]).toEqual(dirtyValues[key]);
      } else {
        expect(after[key]).toEqual(originalValues[key]);
      }
    }
  });

  // fix(#1761 review P2): SearchBar keys its local input/debounce state on
  // resetEpoch precisely because clearIdentityScopedFilters can leave `q`
  // unchanged (already ''), so the counter has to move on every call.
  it('clearIdentityScopedFilters bumps resetEpoch even when q is already empty', () => {
    const before = useSearchStore.getState().resetEpoch;

    useSearchStore.getState().clearIdentityScopedFilters();

    expect(useSearchStore.getState().resetEpoch).toBe(before + 1);
  });

  it('resetFilters and restoreParams do not touch resetEpoch', () => {
    useSearchStore.getState().clearIdentityScopedFilters();
    const epoch = useSearchStore.getState().resetEpoch;

    useSearchStore.getState().resetFilters();
    expect(useSearchStore.getState().resetEpoch).toBe(epoch);

    useSearchStore.getState().restoreParams({ q: 'test' });
    expect(useSearchStore.getState().resetEpoch).toBe(epoch);
  });
});

/** Produces a value of the same type as `current`, guaranteed different. */
function makeDistinctValue(current: unknown): unknown {
  if (typeof current === 'string') return `${current}__dirty`;
  if (typeof current === 'number') return current + 999;
  if (typeof current === 'boolean') return !current;
  if (Array.isArray(current)) return [...current, '__dirty'];
  return current;
}
