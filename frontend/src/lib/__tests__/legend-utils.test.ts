import { breakLabel } from '@/lib/legend-utils';

// fix(#403): 4-digit break values are often years (a year-built legend used to
// render "1.9K – 1.9K"); abbreviation now starts at 10,000.
describe('breakLabel', () => {
  it('renders 4-digit integer breaks verbatim (years stay readable)', () => {
    const breaks = [1900, 1950, 2000];
    expect(breakLabel(0, breaks)).toBe('< 1,900');
    expect(breakLabel(1, breaks)).toBe('1,900 – 1,950');
    expect(breakLabel(3, breaks)).toBe('≥ 2,000');
  });

  it('still abbreviates from 10,000 upward', () => {
    const breaks = [12000, 250000];
    expect(breakLabel(1, breaks)).toBe('12.0K – 250.0K');
  });

  it('abbreviates millions with one decimal', () => {
    expect(breakLabel(1, [1000000, 8918925.75])).toBe('1.0M – 8.9M');
  });

  it('keeps sub-1000 formatting unchanged', () => {
    expect(breakLabel(1, [5, 7.25])).toBe('5 – 7.25');
  });

  it('returns empty string for empty breaks', () => {
    expect(breakLabel(0, [])).toBe('');
  });
});
