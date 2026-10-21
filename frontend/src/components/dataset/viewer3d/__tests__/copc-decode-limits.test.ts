import { describe, expect, it } from 'vitest';
import { checkDecodeLimits } from '../copc-decode-limits';
import { MAX_RANGE_BYTES, MAX_WKT_LENGTH, POINT_BUDGET } from '../copc-limits';

const ok = () => ({
  node: { pointCount: 1000 },
  bytes: new ArrayBuffer(100),
  copc: { header: { pointDataRecordLength: 34 } },
  horizontalWkt: 'PROJCS["x"]',
  zToMeters: 1,
  origin: [-123, 44],
});

describe('checkDecodeLimits', () => {
  it('accepts a request inside the caps', () => {
    expect(() => checkDecodeLimits(ok())).not.toThrow();
  });

  it.each([
    ['a point count past the cap', (r: ReturnType<typeof ok>) => (r.node.pointCount = POINT_BUDGET + 1)],
    ['a fractional point count', (r: ReturnType<typeof ok>) => (r.node.pointCount = 2.5)],
    ['a decoded size past the cap', (r: ReturnType<typeof ok>) => { r.node.pointCount = POINT_BUDGET; r.copc.header.pointDataRecordLength = 65535; }],
    ['a zero record length', (r: ReturnType<typeof ok>) => (r.copc.header.pointDataRecordLength = 0)],
    ['compressed bytes past the cap', (r: ReturnType<typeof ok>) => (r.bytes = new ArrayBuffer(MAX_RANGE_BYTES + 1))],
    ['an oversized CRS', (r: ReturnType<typeof ok>) => (r.horizontalWkt = 'x'.repeat(MAX_WKT_LENGTH + 1))],
    ['a non-finite unit factor', (r: ReturnType<typeof ok>) => (r.zToMeters = Number.NaN)],
    ['a non-finite origin', (r: ReturnType<typeof ok>) => (r.origin = [Number.POSITIVE_INFINITY, 0])],
  ])('refuses %s', (_label, mutate) => {
    const request = ok();
    mutate(request);
    expect(() => checkDecodeLimits(request)).toThrow();
  });
});
