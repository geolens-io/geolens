// Pure-logic coverage for the measurement plugin's geometry + unit formatting.
// The React component needs a live MapLibre instance (not available in jsdom),
// but the math is extractable and deterministic.

// formatDistance/formatArea read i18n.language for locale-aware number grouping;
// pin it to 'en' so toLocaleString is deterministic and never throws on a
// pseudo-locale like i18next's 'cimode'.
vi.mock('@/i18n/i18n', () => ({ default: { language: 'en' } }));

import { rebuildMeasurement, formatDistance, formatArea } from '../MeasurementPlugin';

const P = (lng: number, lat: number) => ({ lng, lat });

describe('rebuildMeasurement', () => {
  it('returns null result and no features for an empty point set', () => {
    const { result, features } = rebuildMeasurement([], 'distance');
    expect(result).toBeNull();
    expect(features).toEqual([]);
  });

  it('distance: one point yields a point feature but no measurement', () => {
    const { result, features } = rebuildMeasurement([P(0, 0)], 'distance');
    expect(result).toBeNull();
    expect(features).toHaveLength(1); // single point marker, no line
    expect(features[0].geometry.type).toBe('Point');
  });

  it('distance: two points yield a positive length and a connecting line', () => {
    const { result, features } = rebuildMeasurement([P(0, 0), P(0, 1)], 'distance');
    expect(result).toBeGreaterThan(0);
    // 2 point markers + 1 LineString
    expect(features).toHaveLength(3);
    expect(features.some((f) => f.geometry.type === 'LineString')).toBe(true);
  });

  it('area: needs >= 3 points; two points produce no area', () => {
    expect(rebuildMeasurement([P(0, 0), P(1, 1)], 'area').result).toBeNull();
  });

  it('area: three points yield a positive area and a closed ring line', () => {
    const { result, features } = rebuildMeasurement([P(0, 0), P(0, 1), P(1, 1)], 'area');
    expect(result).toBeGreaterThan(0);
    // 3 point markers + 1 closed LineString
    expect(features).toHaveLength(4);
    const line = features.find((f) => f.geometry.type === 'LineString');
    expect(line).toBeDefined();
    const coords = (line!.geometry as GeoJSON.LineString).coordinates;
    // Ring is explicitly closed (first coord repeated as last)
    expect(coords[0]).toEqual(coords[coords.length - 1]);
  });
});

describe('formatDistance', () => {
  it('metric: sub-kilometre rounds to whole metres', () => {
    expect(formatDistance(500, 'metric')).toBe('500 m');
  });
  it('metric: >= 1 km switches to kilometres with two decimals', () => {
    expect(formatDistance(1500, 'metric')).toBe('1.50 km');
  });
  it('imperial: sub-mile reports feet', () => {
    expect(formatDistance(500, 'imperial')).toContain('ft');
    expect(formatDistance(500, 'imperial')).not.toContain('mi');
  });
  it('imperial: >= 1 mile reports miles', () => {
    expect(formatDistance(2000, 'imperial')).toContain('mi');
  });
});

describe('formatArea', () => {
  it('metric: small areas report square metres', () => {
    expect(formatArea(500, 'metric')).toBe('500 m²');
  });
  it('metric: >= 1 km² switches to square kilometres', () => {
    expect(formatArea(2_000_000, 'metric')).toBe('2.00 km²');
  });
  it('imperial: small areas report square feet', () => {
    expect(formatArea(500, 'imperial')).toContain('ft²');
  });
  it('imperial: large areas report square miles', () => {
    expect(formatArea(30_000_000, 'imperial')).toContain('mi²');
  });
});
