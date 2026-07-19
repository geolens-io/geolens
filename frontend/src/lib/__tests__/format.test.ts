import { formatDateTimeSmart, formatBytes, formatGsd } from '@/lib/format';

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

describe('formatGsd', () => {
  it('formats projected-CRS gsd as cm/m/km (unchanged behavior)', () => {
    expect(formatGsd(0.5, { isGeographic: false }, 'en-US')).toBe('50 cm');
    expect(formatGsd(30, { isGeographic: false }, 'en-US')).toBe('30 m');
    expect(formatGsd(2000, { isGeographic: false }, 'en-US')).toBe('2.0 km');
  });

  it('fix(#569): geographic-CRS gsd renders arc units with approx ground distance, not meters', () => {
    // 60 arc-seconds = 1/60 degree — previously rendered "2 cm"
    const label = formatGsd(1 / 60, { isGeographic: true }, 'en-US');
    expect(label).toContain('60″');
    expect(label).toContain('≈');
    expect(label).toContain('km');
    // arc-minutes and degrees branches
    expect(formatGsd(0.5, { isGeographic: true }, 'en-US')).toContain('30′');
    expect(formatGsd(2, { isGeographic: true }, 'en-US')).toContain('2°');
  });

  it('fix(#588): sub-arcsecond pixels keep their precision instead of rounding to 0\u2033', () => {
    // ~30 cm EPSG:4326 imagery ≈ 0.0097 arc-seconds — a fixed 1-decimal
    // format rendered this as '0″ (≈30 cm)'.
    const label = formatGsd(0.3 / 111_320, { isGeographic: true }, 'en-US');
    expect(label).not.toMatch(/(^|[^.\d])0\u2033/);
    expect(label).toContain('0.0097');
    expect(label).toContain('30 cm');
    // 1″ and above keep the compact single-decimal form
    expect(formatGsd(1 / 3600, { isGeographic: true }, 'en-US')).toContain('1\u2033');
    expect(formatGsd(1.5 / 3600, { isGeographic: true }, 'en-US')).toContain('1.5\u2033');
  });

  it('falls back to the EPSG:4326 heuristic for payloads without the flag', () => {
    expect(formatGsd(1 / 60, { crs: 'EPSG:4326' }, 'en-US')).toContain('″');
    // unknown CRS without the flag keeps the legacy meters formatting
    expect(formatGsd(30, { crs: 'EPSG:32618' }, 'en-US')).toBe('30 m');
  });

  it('explicit flag wins over the CRS heuristic', () => {
    expect(formatGsd(1 / 60, { isGeographic: true, crs: 'EPSG:9518' }, 'en-US')).toContain('″');
    expect(formatGsd(30, { isGeographic: false, crs: 'EPSG:4326' }, 'en-US')).toBe('30 m');
  });
});
