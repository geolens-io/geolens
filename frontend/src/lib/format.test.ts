import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { formatDate } from '@/lib/format';

describe('formatDate', () => {
  const originalTz = process.env.TZ;

  beforeAll(() => {
    process.env.TZ = 'America/New_York';
  });

  afterAll(() => {
    if (originalTz === undefined) delete process.env.TZ;
    else process.env.TZ = originalTz;
  });

  it('shows a date-only value as that calendar day west of UTC', () => {
    expect(formatDate('1950-01-01')).toContain('Jan 1, 1950');
  });

  it('keeps full timestamps in local time', () => {
    expect(formatDate('2024-03-10T02:00:00Z')).toContain('Mar 9, 2024');
  });
});
