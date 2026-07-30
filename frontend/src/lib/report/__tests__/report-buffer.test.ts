import { describe, it, expect, beforeEach } from 'vitest';
import {
  clearReportEntries,
  countDistinctFailures,
  getReportEntries,
  pushReportEntry,
  reportNetworkError,
  reportTileTokenRemint,
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

// fix(#890): #881 replaced the reactive 403 burst with a proactive tab-return
// re-mint, which left no trace at all — the burst's warnings were at least
// evidence that a recovery had happened. This tap restores that signal.
describe('reportTileTokenRemint', () => {
  it('records a suppressed entry naming the surface and the trigger', () => {
    reportTileTokenRemint('viewer', 'tab-return');

    const entries = getReportEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({ severity: 'info', source: 'maplibre', suppressed: true });
    expect(entries[0].message).toContain('viewer');
    expect(entries[0].message).toContain('tab-return');
  });

  it('keeps two surfaces re-minting at once as separate entries', () => {
    reportTileTokenRemint('viewer', 'tab-return');
    reportTileTokenRemint('dataset-preview', 'tab-return');

    expect(getReportEntries()).toHaveLength(2);
  });

  it('keeps the tab-return and tile-error paths distinguishable', () => {
    reportTileTokenRemint('builder', 'tab-return');
    reportTileTokenRemint('builder', 'tile-error');

    expect(getReportEntries()).toHaveLength(2);
  });

  it('collapses repeat re-mints from the same surface and trigger into a count', () => {
    reportTileTokenRemint('builder', 'tile-error');
    reportTileTokenRemint('builder', 'tile-error');

    const entries = getReportEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].count).toBe(2);
  });
});

// fix(#908): one unrecovered map failure writes two error rows — a `maplibre`
// row carrying the sourceId and a `console` row derived from
// logUnhandledMapError. Both are worth keeping; counting them both is not.
describe('countDistinctFailures (fix #908)', () => {
  it('counts one failure for the maplibre + console pair a 5xx tile writes', () => {
    pushReportEntry({
      severity: 'error',
      source: 'maplibre',
      message: 'AJAXError: Internal Server Error (500)',
      detail: 'source: dataset-abc',
    });
    pushReportEntry({
      severity: 'error',
      source: 'console',
      message: 'AJAXError: Internal Server Error (500)',
    });

    expect(getReportEntries()).toHaveLength(2);
    expect(countDistinctFailures(getReportEntries())).toBe(1);
  });

  it('still counts genuinely different failures separately', () => {
    pushReportEntry({ severity: 'error', source: 'maplibre', message: 'tile 500' });
    pushReportEntry({ severity: 'error', source: 'runtime', message: 'Cannot read x of undefined' });

    expect(countDistinctFailures(getReportEntries())).toBe(2);
  });

  // codex on #908: MapLibre puts the failing tile URL in the AJAXError message,
  // so without normalization one broken source counts once per visible tile and
  // the badge still runs to 9+.
  it('counts one failure for every failing tile of the same source', () => {
    for (const [z, x, y] of [[12, 1205, 1539], [12, 1206, 1539], [12, 1205, 1540]]) {
      pushReportEntry({
        severity: 'error',
        source: 'maplibre',
        message: `AJAXError: Internal Server Error (500): /api/tiles/data.parcels/${z}/${x}/${y}.pbf?sig=abc`,
      });
    }

    expect(getReportEntries()).toHaveLength(3);
    expect(countDistinctFailures(getReportEntries())).toBe(1);
  });

  it('keeps two different failing sources apart', () => {
    pushReportEntry({
      severity: 'error',
      source: 'maplibre',
      message: 'AJAXError: Internal Server Error (500): /api/tiles/data.parcels/12/1/1.pbf',
    });
    pushReportEntry({
      severity: 'error',
      source: 'maplibre',
      message: 'AJAXError: Internal Server Error (500): /api/tiles/data.roads/12/1/1.pbf',
    });

    expect(countDistinctFailures(getReportEntries())).toBe(2);
  });

  it('leaves a message with no tile coordinates alone', () => {
    pushReportEntry({ severity: 'error', source: 'runtime', message: 'Cannot read x of undefined' });
    pushReportEntry({ severity: 'error', source: 'runtime', message: 'Cannot read y of undefined' });

    expect(countDistinctFailures(getReportEntries())).toBe(2);
  });

  it('ignores warnings and info rows', () => {
    pushReportEntry({ severity: 'warning', source: 'maplibre', message: 'no-data tile (404)' });
    reportTileTokenRemint('builder', 'tab-return');

    expect(countDistinctFailures(getReportEntries())).toBe(0);
  });

  it('is zero on an empty buffer', () => {
    expect(countDistinctFailures(getReportEntries())).toBe(0);
  });
});
