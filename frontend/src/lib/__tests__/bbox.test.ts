import {
  bboxCenterLon,
  bboxLonSpan,
  crossesAntimeridian,
  splitBbox,
  toFitBounds,
  toSpanBbox,
  type Bbox,
} from '../bbox';

// fix(#903): the shape the backend can now produce (RFC 7946 §5.2 / STAC spec
// form) and that nothing on the frontend understood. Fiji is the canonical
// case: ~3° of longitude reported as `west > east`.
const FIJI: Bbox = [178.5, -20, -178.5, -15];
const NYC: Bbox = [-74.5, 40.5, -73.5, 41.5];
const WORLD: Bbox = [-180, -90, 180, 90];

describe('crossesAntimeridian', () => {
  it('is true only when west runs past east', () => {
    expect(crossesAntimeridian(FIJI)).toBe(true);
    expect(crossesAntimeridian(NYC)).toBe(false);
    expect(crossesAntimeridian(WORLD)).toBe(false);
  });

  it('treats a zero-width extent as non-crossing', () => {
    expect(crossesAntimeridian([10, 0, 10, 1])).toBe(false);
  });
});

describe('splitBbox', () => {
  it('splits a crossing bbox at the seam, west half first', () => {
    expect(splitBbox(FIJI)).toEqual([
      [178.5, -20, 180, -15],
      [-180, -20, -178.5, -15],
    ]);
  });

  it('returns a non-crossing bbox unchanged, as a single box', () => {
    expect(splitBbox(NYC)).toEqual([NYC]);
  });
});

describe('toSpanBbox', () => {
  it('widens a crossing bbox to the monotonic world span', () => {
    expect(toSpanBbox(FIJI)).toEqual([-180, -20, 180, -15]);
  });

  it('leaves a non-crossing bbox untouched', () => {
    expect(toSpanBbox(NYC)).toEqual(NYC);
    expect(toSpanBbox(WORLD)).toEqual(WORLD);
  });
});

describe('bboxLonSpan', () => {
  it('measures a crossing bbox the short way round', () => {
    expect(bboxLonSpan(FIJI)).toBeCloseTo(3, 10);
  });

  it('matches plain subtraction for a non-crossing bbox', () => {
    expect(bboxLonSpan(NYC)).toBeCloseTo(1, 10);
    expect(bboxLonSpan(WORLD)).toBe(360);
  });
});

describe('bboxCenterLon', () => {
  // The bug this exists to prevent: (178.5 + -178.5) / 2 === 0, the antipode.
  it('centers a crossing bbox on the data, not its antipode', () => {
    expect(bboxCenterLon(FIJI)).toBeCloseTo(180, 10);
    expect(bboxCenterLon([170, 0, -170, 10])).toBeCloseTo(180, 10);
    expect(bboxCenterLon([179, 0, -179, 10])).toBeCloseTo(180, 10);
  });

  it('wraps back into -180..180', () => {
    expect(bboxCenterLon([175, 0, -175, 10])).toBeLessThanOrEqual(180);
    expect(bboxCenterLon([-170, 0, 170, 10])).toBeCloseTo(0, 10);
  });

  it('matches the plain midpoint for a non-crossing bbox', () => {
    expect(bboxCenterLon(NYC)).toBeCloseTo(-74, 10);
    expect(bboxCenterLon(WORLD)).toBe(0);
  });
});

describe('toFitBounds', () => {
  it('lets east run past 180 for a crossing bbox (MapLibre normalizes it)', () => {
    expect(toFitBounds(FIJI)).toEqual([
      [178.5, -20],
      [181.5, -15],
    ]);
  });

  it('passes a non-crossing bbox through as the same corners', () => {
    expect(toFitBounds(NYC)).toEqual([
      [-74.5, 40.5],
      [-73.5, 41.5],
    ]);
  });
});
