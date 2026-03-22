import { qualityScoreClasses } from '@/lib/status-colors';

describe('qualityScoreClasses', () => {
  it('returns neutral styling for score 70 (60-79 range)', () => {
    const result = qualityScoreClasses(70);
    expect(result).toContain('bg-secondary');
    expect(result).not.toContain('amber');
  });

  it('returns emerald styling for score 85 (80+ range)', () => {
    const result = qualityScoreClasses(85);
    expect(result).toContain('emerald');
  });

  it('returns rose styling for score 40 (below 60)', () => {
    const result = qualityScoreClasses(40);
    expect(result).toContain('rose');
  });

  it('returns emerald styling for score 95 (high score)', () => {
    const result = qualityScoreClasses(95);
    expect(result).toContain('emerald');
  });

  it('returns rose styling for score 55 (just below 60)', () => {
    const result = qualityScoreClasses(55);
    expect(result).toContain('rose');
  });
});
