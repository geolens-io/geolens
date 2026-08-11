// feat(#1241 codex r1): the overlay-completeness rule, in one place.
//
// The defect this exists for: `truncated` is the SQL sandbox's row-cap flag.
// backend/app/processing/ai/chat_actions.py slices the FeatureCollection to a
// 50-row overlay budget AFTER the sandbox returns (which runs at its 1000-row
// default when the model selected geometry itself), so a 300-row answer
// arrives as 50 features with truncated=false. Every consumer that read the
// flag alone believed that preview was complete.
import { chatOverlayCompleteness, overlayFeatureCount } from '../chat-result-completeness';

describe('chatOverlayCompleteness', () => {
  it('says nothing about a complete overlay', () => {
    expect(chatOverlayCompleteness({ row_count: 12 }, 12)).toEqual({});
    expect(chatOverlayCompleteness({}, 12)).toEqual({});
    expect(chatOverlayCompleteness({ truncated: false, row_count: 3 }, 3)).toEqual({});
  });

  // The case the flag misses: nothing was truncated by the SQL cap, but the
  // overlay still holds a fraction of the answer.
  it('reports a clipped overlay the truncated flag never mentions', () => {
    expect(chatOverlayCompleteness({ truncated: false, row_count: 300 }, 50)).toEqual({
      truncated: true,
      totalCount: 300,
    });
  });

  it('keeps the server-reported cap and its total', () => {
    expect(chatOverlayCompleteness({ truncated: true, row_count: 10651 }, 500)).toEqual({
      truncated: true,
      totalCount: 10651,
    });
  });

  // fix(#1076): a clip filters rows, so no source total is reported. The flag
  // must survive without one.
  it('keeps a cap that arrives without a total', () => {
    expect(chatOverlayCompleteness({ truncated: true }, 500)).toEqual({ truncated: true });
  });

  it('ignores a non-numeric row_count instead of inventing a total', () => {
    expect(chatOverlayCompleteness({ row_count: 'lots' }, 50)).toEqual({});
    expect(chatOverlayCompleteness({ truncated: true, row_count: null }, 50)).toEqual({
      truncated: true,
    });
  });

  // Not a bug: more features than rows cannot mean "incomplete". (A geometry
  // collection exploded into parts, say.)
  it('does not call an overlay clipped when it holds more than the row count', () => {
    expect(chatOverlayCompleteness({ row_count: 3 }, 7)).toEqual({});
  });
});

describe('overlayFeatureCount', () => {
  it('counts the features', () => {
    expect(
      overlayFeatureCount({
        type: 'FeatureCollection',
        features: [
          { type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: {} },
        ],
      }),
    ).toBe(1);
  });

  it('treats a payload with no features array as holding nothing', () => {
    // Wire data, not a trusted type: a malformed collection must count as
    // zero rather than throw inside the dispatch path.
    expect(overlayFeatureCount({ type: 'FeatureCollection' } as GeoJSON.FeatureCollection)).toBe(0);
  });
});
