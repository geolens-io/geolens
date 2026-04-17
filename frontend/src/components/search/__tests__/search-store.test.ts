import { useSearchStore } from '@/components/search/search-store';

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
});
