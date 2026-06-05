import { describe, it, expect, beforeEach } from 'vitest';
import {
  clearReportEntries,
  getReportEntries,
  pushReportEntry,
  reportNetworkError,
} from '../report-buffer';

beforeEach(() => {
  clearReportEntries();
});

describe('report buffer', () => {
  it('stores entries newest-first', () => {
    pushReportEntry({ severity: 'error', source: 'console', message: 'first' });
    pushReportEntry({ severity: 'warning', source: 'console', message: 'second' });
    const entries = getReportEntries();
    expect(entries).toHaveLength(2);
    expect(entries[0].message).toBe('second');
  });

  it('collapses consecutive duplicates into a count', () => {
    pushReportEntry({ severity: 'error', source: 'console', message: 'dup' });
    pushReportEntry({ severity: 'error', source: 'console', message: 'dup' });
    const entries = getReportEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].count).toBe(2);
  });

  it('does not collapse across different sources', () => {
    pushReportEntry({ severity: 'error', source: 'console', message: 'same' });
    pushReportEntry({ severity: 'error', source: 'network', message: 'same' });
    expect(getReportEntries()).toHaveLength(2);
  });

  it('redacts credentials at capture time', () => {
    pushReportEntry({ severity: 'error', source: 'network', message: 'failed api_key=SUPERSECRET' });
    expect(getReportEntries()[0].message).not.toContain('SUPERSECRET');
  });

  it('caps the buffer at 200 entries', () => {
    for (let i = 0; i < 250; i += 1) {
      pushReportEntry({ severity: 'info', source: 'console', message: `m${i}` });
    }
    expect(getReportEntries().length).toBeLessThanOrEqual(200);
  });

  it('classifies network severity by status', () => {
    reportNetworkError({ status: 503 });
    reportNetworkError({ status: 404 });
    reportNetworkError({ status: 0 });
    const [offline, notFound, serverError] = getReportEntries();
    expect(offline.severity).toBe('error'); // status 0
    expect(notFound.severity).toBe('warning'); // 4xx
    expect(serverError.severity).toBe('error'); // 5xx
  });
});
