import { featureGid } from '@/lib/tile-utils';

describe('featureGid', () => {
  it('returns a safe integer tile id and nothing else', () => {
    expect(featureGid({ id: 7 })).toBe(7);
    expect(featureGid({ id: '7' })).toBeUndefined();
    expect(featureGid({ id: 1.5 })).toBeUndefined();
    expect(featureGid({ id: 2 ** 60 })).toBeUndefined();
    expect(featureGid({})).toBeUndefined();
  });
});
