import { stashChatResult, takeChatResult, toChatResultHandoff } from '@/lib/chat-result-handoff';

const fc: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };
const bbox: [number, number, number, number] = [-74.5, 40.4, -73.4, 41.1];

beforeEach(() => {
  sessionStorage.clear();
});

describe('toChatResultHandoff', () => {
  it('accepts a valid FeatureCollection + bbox', () => {
    expect(toChatResultHandoff(fc, bbox)).toEqual({ geojson: fc, bbox });
  });

  it.each([
    ['non-object geojson', 'nope', bbox],
    ['non-FeatureCollection geojson', { type: 'Feature' }, bbox],
    ['missing bbox', fc, undefined],
    ['short bbox', fc, [-74, 40, -73]],
    ['NaN in bbox', fc, [-74, NaN, -73, 41]],
    ['out-of-range bbox', fc, [-181, 40, -73, 41]],
    ['inverted bbox', fc, [-73, 40, -74, 41]],
  ])('rejects %s', (_label, geojson, badBbox) => {
    expect(toChatResultHandoff(geojson, badBbox)).toBeNull();
  });
});

describe('stashChatResult / takeChatResult', () => {
  it('round-trips a result and clears it on take', () => {
    expect(stashChatResult({ geojson: fc, bbox })).toBe(true);
    expect(takeChatResult()).toEqual({ geojson: fc, bbox });
    // One-shot: second take finds nothing.
    expect(takeChatResult()).toBeNull();
  });

  it('returns null when nothing is stashed', () => {
    expect(takeChatResult()).toBeNull();
  });

  it('returns null (and clears) on a malformed payload', () => {
    sessionStorage.setItem('geolens-chat-result', 'not json');
    expect(takeChatResult()).toBeNull();
    sessionStorage.setItem('geolens-chat-result', JSON.stringify({ geojson: fc, bbox: [1, 2] }));
    expect(takeChatResult()).toBeNull();
    expect(sessionStorage.getItem('geolens-chat-result')).toBeNull();
  });

  // feat(#1241 codex r1): the builder can save a carried result as a dataset,
  // so the stash has to say whether it is the whole answer. Geometry alone
  // arrived on the other side looking complete.
  it('round-trips the completeness pair and the prompt', () => {
    expect(
      stashChatResult({ geojson: fc, bbox, truncated: true, totalCount: 300, prompt: 'all parks' }),
    ).toBe(true);
    expect(takeChatResult()).toEqual({
      geojson: fc,
      bbox,
      truncated: true,
      totalCount: 300,
      prompt: 'all parks',
    });
  });

  it('drops fields of the wrong type instead of trusting the stash', () => {
    sessionStorage.setItem(
      'geolens-chat-result',
      JSON.stringify({ geojson: fc, bbox, truncated: 'yes', totalCount: 'lots', prompt: 42 }),
    );
    // A truthy-but-not-true `truncated` must not become a disclosure, and a
    // non-numeric total must not reach a count label as "N of lots".
    expect(takeChatResult()).toEqual({ geojson: fc, bbox });
  });

  it('returns false when storage write throws (quota/private mode)', () => {
    // jsdom's Storage proxy turns method assignment into a stored item, so
    // spyOn can't replace setItem — stub the whole global instead.
    vi.stubGlobal('sessionStorage', {
      setItem: () => {
        throw new DOMException('quota', 'QuotaExceededError');
      },
      getItem: () => null,
      removeItem: () => {},
    });
    try {
      expect(stashChatResult({ geojson: fc, bbox })).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
