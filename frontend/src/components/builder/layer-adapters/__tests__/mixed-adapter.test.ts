// mixedFamilyFilter composes a data filter with each geometry family's filter, and the interactive ids leave out the outline.
import { describe, it, expect } from 'vitest';
import { mixedFamilyFilter, mixedInteractiveLayerIds } from '../mixed-adapter';

describe('mixed adapter — data filters COMPOSE with family filters (never replace)', () => {
  const dataFilter = ['==', ['get', 'category'], 'A'] as unknown as import('maplibre-gl').FilterSpecification;

  it('mixedFamilyFilter wraps the data filter in ["all", family, data]', () => {
    const composed = mixedFamilyFilter('point', dataFilter) as unknown[];
    expect(composed[0]).toBe('all');
    expect(JSON.stringify(composed[1])).toContain('geometry-type');
    expect(composed[2]).toEqual(dataFilter);
  });

  it('mixedFamilyFilter returns the bare family filter when the data filter is empty', () => {
    for (const empty of [null, undefined, [] as unknown[]]) {
      const bare = mixedFamilyFilter('line', empty) as unknown[];
      expect(bare[0]).toBe('in');
      expect(JSON.stringify(bare)).toContain('LineString');
    }
  });

  it('normalizes legacy-syntax data filters before composing (fix #431 codex r3)', () => {
    // A legacy child would make MapLibre classify the whole ['all', ...] as a
    // legacy filter and reject the expression-syntax family predicate.
    const composed = mixedFamilyFilter('point', ['==', 'status', 'open']) as unknown[];
    expect(composed[0]).toBe('all');
    expect(composed[2]).toEqual(['==', ['get', 'status'], 'open']);
  });

  it('passes expression-syntax data filters through unchanged', () => {
    const expr = ['==', ['get', 'pop'], 5] as unknown as import('maplibre-gl').FilterSpecification;
    const composed = mixedFamilyFilter('line', expr) as unknown[];
    expect(composed[2]).toEqual(['==', ['get', 'pop'], 5]);
  });
});

describe('mixed adapter — id contracts', () => {
  it('mixedInteractiveLayerIds excludes the outline (fill already covers polygon hits)', () => {
    expect(mixedInteractiveLayerIds('layer-abc')).toEqual([
      'layer-abc',
      'layer-abc-lines',
      'layer-abc-points',
    ]);
  });
});
