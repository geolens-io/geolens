import { describe, expect, it } from 'vitest';
import {
  GLOBE_EAST_BIAS,
  GLOBE_TILT_LAT,
  GLOBE_VIEW,
  LAND_DOTS,
  LAND_MASK_LENGTH,
  LATTICE_SIZE,
  landDotsPath,
  longitudeForUtcOffset,
  projectGlobePoint,
  restLongitude,
} from './login-globe';

const RAD = Math.PI / 180;

function project(latDeg: number, lonDeg: number, centerLon: number) {
  return projectGlobePoint(latDeg * RAD, lonDeg * RAD, centerLon);
}

/** Degrees from the nearest land dot, by great-circle distance. */
function degreesToLand(latDeg: number, lonDeg: number) {
  const lat = latDeg * RAD;
  const lon = lonDeg * RAD;
  let nearest = Infinity;
  for (const dot of LAND_DOTS) {
    const cos =
      Math.sin(lat) * Math.sin(dot.lat) + Math.cos(lat) * Math.cos(dot.lat) * Math.cos(lon - dot.lon);
    nearest = Math.min(nearest, Math.acos(Math.min(1, cos)) / RAD);
  }
  return nearest;
}

describe('login globe', () => {
  it('maps a UTC offset to a longitude, 15 degrees an hour and west for a positive offset', () => {
    expect(longitudeForUtcOffset(300)).toBe(-75);
    expect(longitudeForUtcOffset(-330)).toBe(82.5);
    expect(longitudeForUtcOffset(0)).toBe(0);
  });

  it('faces east of the visitor by the fixed bias and wraps at the antimeridian', () => {
    expect(restLongitude(300)).toBe(-75 + GLOBE_EAST_BIAS);
    expect(restLongitude(-720)).toBe(-150);
    expect(restLongitude(0)).toBe(GLOBE_EAST_BIAS);
  });

  it('puts the resting longitude and the fixed tilt at the middle of the view', () => {
    const lon = restLongitude(300);
    const p = project(GLOBE_TILT_LAT, lon, lon);
    expect(p.x).toBeCloseTo(GLOBE_VIEW.cx, 6);
    expect(p.y).toBeCloseTo(GLOBE_VIEW.cy, 6);
    expect(p.near).toBe(true);
  });

  it('draws east to the right and north up, so continents are not mirrored', () => {
    const lon = 10;
    const center = project(GLOBE_TILT_LAT, lon, lon);
    expect(project(GLOBE_TILT_LAT, lon + 20, lon).x).toBeGreaterThan(center.x);
    expect(project(GLOBE_TILT_LAT + 20, lon, lon).y).toBeLessThan(center.y);
  });

  it('hides the far hemisphere', () => {
    expect(project(-GLOBE_TILT_LAT, 190, 10).near).toBe(false);
  });

  it('holds one mask bit per lattice point, and no more bytes than that needs', () => {
    expect(LATTICE_SIZE).toBe(4584);
    expect(LAND_MASK_LENGTH).toBe(573);
    expect(LAND_MASK_LENGTH).toBe(Math.ceil(LATTICE_SIZE / 8));
    expect(LAND_DOTS).toHaveLength(1326);
  });

  it('keeps lattice dots on land and drops them at sea', () => {
    // Half the lattice spacing is 1.5°, so land always has a dot within about 2°.
    expect(degreesToLand(39.7, -105)).toBeLessThan(2.2); // Denver
    expect(degreesToLand(-23.7, 133.9)).toBeLessThan(2.2); // Alice Springs
    expect(degreesToLand(15, 20)).toBeLessThan(2.2); // Chad
    expect(degreesToLand(28, -81.5)).toBeLessThan(2.2); // Florida
    expect(degreesToLand(53, -1.5)).toBeLessThan(2.2); // Great Britain
    expect(degreesToLand(7.5, 80.7)).toBeLessThan(2.2); // Sri Lanka
    expect(degreesToLand(65, -18)).toBeLessThan(2.2); // Iceland
    expect(degreesToLand(30, -45)).toBeGreaterThan(8); // mid Atlantic
    expect(degreesToLand(0, -140)).toBeGreaterThan(8); // equatorial Pacific
    expect(degreesToLand(25, -90)).toBeGreaterThan(4); // Gulf of Mexico
    expect(degreesToLand(15, 88)).toBeGreaterThan(4); // Bay of Bengal
  });

  it('draws only the land that faces the viewer', () => {
    const lon = 10;
    const facing = LAND_DOTS.filter((dot) => projectGlobePoint(dot.lat, dot.lon, lon).near);
    expect(facing.length).toBeGreaterThan(0);
    expect(facing.length).toBeLessThan(LAND_DOTS.length);
    expect(landDotsPath(lon).match(/M/g)).toHaveLength(facing.length);
  });
});
