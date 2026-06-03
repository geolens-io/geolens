import { formatDateTimeSmart, formatBytes } from '@/lib/format';

describe('formatDateTimeSmart', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-03-17T12:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns N/A for null input', () => {
    expect(formatDateTimeSmart(null)).toBe('N/A');
  });

  it('returns N/A for invalid date string', () => {
    expect(formatDateTimeSmart('invalid')).toBe('N/A');
  });

  it('returns time-only for today', () => {
    const todayAt2pm = '2026-03-17T14:00:00Z';
    const result = formatDateTimeSmart(todayAt2pm);
    // Should contain time component but not month name
    expect(result).not.toContain('Mar');
    expect(result).toMatch(/\d/);
  });

  it('returns "Yesterday, <time>" for yesterday', () => {
    const yesterdayAt3pm = '2026-03-16T15:00:00Z';
    const result = formatDateTimeSmart(yesterdayAt3pm);
    expect(result).toMatch(/^Yesterday/);
  });

  it('includes month and time for same-year date', () => {
    const sameYearDate = '2026-01-15T10:30:00Z';
    const result = formatDateTimeSmart(sameYearDate);
    expect(result).toContain('Jan');
    expect(result).toMatch(/\d{1,2}:\d{2}/);
  });

  it('returns date-only format for different year', () => {
    const differentYearDate = '2024-06-15T10:30:00Z';
    const result = formatDateTimeSmart(differentYearDate);
    // Should use formatDate output (month short, day, year)
    expect(result).toContain('2024');
    expect(result).not.toMatch(/\d{1,2}:\d{2}/);
  });
});

describe('formatBytes', () => {
  it('returns N/A for null', () => {
    expect(formatBytes(null)).toBe('N/A');
  });

  it('returns "0 B" for zero bytes', () => {
    expect(formatBytes(0)).toBe('0 B');
  });

  it('returns a KB value for 1500 bytes', () => {
    expect(formatBytes(1500)).toContain('KB');
  });

  it('returns an MB value for 1_500_000 bytes', () => {
    expect(formatBytes(1_500_000)).toContain('MB');
  });

  it('returns a GB value for 2_500_000_000 bytes', () => {
    expect(formatBytes(2_500_000_000)).toContain('GB');
  });
});
