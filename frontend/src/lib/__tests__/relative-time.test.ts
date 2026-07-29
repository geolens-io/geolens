// chore(#835): the single relative-time formatter (was written out 4x).
import { formatRelativeTime, formatLastUsedRelativeTime } from '@/lib/relative-time';

const NOW = new Date('2026-07-29T12:00:00Z');

describe('formatRelativeTime', () => {
  it('clamps sub-minute deltas to "now" by default', () => {
    expect(formatRelativeTime(new Date(NOW.getTime() - 42_000), NOW, 'en')).toBe('now');
  });

  it('renders exact second counts with exactSeconds (problem-report behavior)', () => {
    expect(
      formatRelativeTime(new Date(NOW.getTime() - 42_000), NOW, 'en', { exactSeconds: true }),
    ).toBe('42 seconds ago');
  });

  it('renders minutes, hours, days, months, and years', () => {
    expect(formatRelativeTime(new Date(NOW.getTime() - 5 * 60_000), NOW, 'en')).toBe('5 minutes ago');
    expect(formatRelativeTime(new Date(NOW.getTime() - 3 * 3_600_000), NOW, 'en')).toBe('3 hours ago');
    expect(formatRelativeTime(new Date(NOW.getTime() - 2 * 86_400_000), NOW, 'en')).toBe('2 days ago');
    expect(formatRelativeTime(new Date(NOW.getTime() - 65 * 86_400_000), NOW, 'en')).toBe('2 months ago');
    expect(formatRelativeTime(new Date(NOW.getTime() - 800 * 86_400_000), NOW, 'en')).toBe('2 years ago');
  });

  it('caps at hours with maxUnit (problem-report behavior)', () => {
    expect(
      formatRelativeTime(new Date(NOW.getTime() - 49 * 3_600_000), NOW, 'en', { maxUnit: 'hour' }),
    ).toBe('49 hours ago');
  });

  it('handles future timestamps', () => {
    expect(formatRelativeTime(new Date(NOW.getTime() + 5 * 60_000), NOW, 'en')).toBe('in 5 minutes');
  });

  it('returns an empty string instead of throwing on an invalid locale tag', () => {
    expect(formatRelativeTime(new Date(NOW.getTime() - 5 * 60_000), NOW, 'not a locale!')).toBe('');
  });
});

describe('formatLastUsedRelativeTime', () => {
  // Echo the key + count so assertions pin both the key and the floor math.
  const t = (key: string, options?: Record<string, unknown>) =>
    options && 'count' in options ? `${key}:${options.count}` : key;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns the never-used key for null', () => {
    expect(formatLastUsedRelativeTime(null, t)).toBe('admin:apiKeys.neverUsed');
  });

  it('floors to just-now / minutes / hours / days (pre-consolidation behavior)', () => {
    expect(formatLastUsedRelativeTime(new Date(NOW.getTime() - 30_000).toISOString(), t)).toBe('admin:apiKeys.justNow');
    expect(formatLastUsedRelativeTime(new Date(NOW.getTime() - 59 * 60_000).toISOString(), t)).toBe('admin:apiKeys.minutesAgo:59');
    expect(formatLastUsedRelativeTime(new Date(NOW.getTime() - 90 * 60_000).toISOString(), t)).toBe('admin:apiKeys.hoursAgo:1');
    expect(formatLastUsedRelativeTime(new Date(NOW.getTime() - 25 * 3_600_000).toISOString(), t)).toBe('admin:apiKeys.daysAgo:1');
  });
});
