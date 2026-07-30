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

  // codex round 2 on #908: dropping the whole query string merged two cluster
  // layers over the same dataset, which are distinct sources.
  it('keeps two cluster sources over one dataset apart', () => {
    for (const radius of [50, 80]) {
      pushReportEntry({
        severity: 'error',
        source: 'maplibre',
        message: `AJAXError: Internal Server Error (500): /api/tiles/clusters/data.trees/12/1/1.pbf?cluster_radius=${radius}&sig=abc`,
      });
    }

    expect(countDistinctFailures(getReportEntries())).toBe(2);
  });

  it('still collapses the same source across a rotated sig', () => {
    for (const sig of ['abc', 'def']) {
      pushReportEntry({
        severity: 'error',
        source: 'maplibre',
        message: `AJAXError: Internal Server Error (500): /api/tiles/data.parcels/12/1/1.pbf?sig=${sig}&exp=1`,
      });
    }

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

  // codex round 3 on #908: message-only correlation is for the maplibre/console
  // pair. Two boundaries throwing the same common message from different panels
  // are two failures. (Back-to-back identical rows are collapsed by the buffer
  // itself, so this is the interleaved case — the one the key decides.)
  it('keeps same-message failures from different panels apart', () => {
    pushReportEntry({
      severity: 'error',
      source: 'react',
      message: 'Cannot read properties of undefined',
      detail: 'at LayerPanel',
    });
    pushReportEntry({ severity: 'error', source: 'runtime', message: 'unrelated' });
    pushReportEntry({
      severity: 'error',
      source: 'react',
      message: 'Cannot read properties of undefined',
      detail: 'at AnalysisPanel',
    });

    expect(getReportEntries()).toHaveLength(3);
    expect(countDistinctFailures(getReportEntries())).toBe(3);
  });

  // codex round 4 on #908: getSourceIdForLayer gives each cluster layer its own
  // MapLibre source, so two broken layers over one dataset can fail with
  // byte-identical URLs. Those are two failures.
  it('keeps two failing map sources apart even with identical urls', () => {
    const message = 'AJAXError: Internal Server Error (500): /api/tiles/data.trees/12/1/1.pbf';
    // Interleaved with the console echo each one produces, which is also how
    // they arrive: back-to-back rows are collapsed by the buffer itself, which
    // compares the message and ignores detail.
    for (const sourceId of ['layer-a-src', 'layer-b-src']) {
      pushReportEntry({ severity: 'error', source: 'maplibre', message, detail: `source: ${sourceId}` });
      pushReportEntry({ severity: 'error', source: 'console', message });
    }

    expect(getReportEntries()).toHaveLength(4);
    // Two broken layers; both console echoes are the other halves.
    expect(countDistinctFailures(getReportEntries())).toBe(2);
  });

  it('counts a console-only failure (viewer and dataset preview push no row)', () => {
    pushReportEntry({
      severity: 'error',
      source: 'console',
      message: 'AJAXError: Internal Server Error (500): /api/tiles/data.parcels/12/1/1.pbf',
    });

    expect(countDistinctFailures(getReportEntries())).toBe(1);
  });

  // codex round 4 on #908: an admin-configured remote style may address tiles by
  // quadkey or bbox, where there is no z/x/y triple to normalize.
  it('collapses a broken quadkey-addressed basemap to one failure', () => {
    for (const quadkey of ['0313102310', '0313102311', '0313102312']) {
      pushReportEntry({
        severity: 'error',
        source: 'maplibre',
        message: `AJAXError: Not Found (404): https://tiles.example.com/${quadkey}.png`,
        detail: 'source: basemap',
      });
    }

    expect(countDistinctFailures(getReportEntries())).toBe(1);
  });

  it('collapses a broken quadkey basemap at low zoom too', () => {
    // A quadkey's length IS the zoom level, so zoom 1-5 keys are 1-5 digits.
    for (const quadkey of ['0', '03', '031', '0313', '03131']) {
      pushReportEntry({
        severity: 'error',
        source: 'maplibre',
        message: `AJAXError: Not Found (404): https://tiles.example.com/${quadkey}.png`,
        detail: 'source: basemap',
      });
    }

    expect(countDistinctFailures(getReportEntries())).toBe(1);
  });

  it('does not collapse two sources that merely share a short path segment', () => {
    pushReportEntry({
      severity: 'error',
      source: 'maplibre',
      message: 'AJAXError: Not Found (404): https://a.example.com/2/style/tiles.json',
      detail: 'source: a',
    });
    pushReportEntry({
      severity: 'error',
      source: 'maplibre',
      message: 'AJAXError: Not Found (404): https://a.example.com/2/other/tiles.json',
      detail: 'source: b',
    });

    expect(countDistinctFailures(getReportEntries())).toBe(2);
  });

  it('collapses a broken bbox-addressed basemap to one failure', () => {
    for (const bbox of ['-20037508,0,0,20037508', '0,0,20037508,20037508']) {
      pushReportEntry({
        severity: 'error',
        source: 'maplibre',
        message: `AJAXError: Not Found (404): https://wms.example.com/?service=WMS&bbox=${bbox}`,
        detail: 'source: basemap',
      });
    }

    expect(countDistinctFailures(getReportEntries())).toBe(1);
  });

  // codex round 5 on #908: MapLibre's {prefix} resolves to a per-tile shard
  // label in the hostname, so one broken sharded basemap otherwise counts once
  // per tile.
  // codex rounds 6-9 on #908: a resolved `{prefix}` shard cannot be told apart
  // from a meaningful short label in a single URL — `a.tiles…` looks exactly
  // like `ca.tiles…`, and both basemaps carry the fixed source id `basemap`.
  // Guessing merged two genuinely different basemaps, so this keeps them
  // distinct and accepts that one sharded source may be counted more than once.
  it('keeps two basemaps apart when they differ only by a short host label', () => {
    for (const region of ['ca', 'de']) {
      pushReportEntry({
        severity: 'error',
        source: 'maplibre',
        message: `AJAXError: Not Found (404): https://${region}.tiles.example.com/5/1/1.png`,
        detail: 'source: basemap',
      });
    }

    expect(countDistinctFailures(getReportEntries())).toBe(2);
  });

  // codex round 6/7 on #908: a resolved path-segment {prefix} cannot be told
  // apart from a meaningful static segment in a single URL, so it is left
  // alone — keeping two real sources distinct matters more to a problem
  // reporter than collapsing a sharded one.
  it('keeps two sources apart when they differ only by a short path segment', () => {
    for (const region of ['ca', 'de']) {
      pushReportEntry({
        severity: 'error',
        source: 'console',
        message: `AJAXError: Not Found (404): https://tiles.example.com/${region}/5/1/1.png`,
      });
    }

    expect(countDistinctFailures(getReportEntries())).toBe(2);
  });

  // codex round 7 on #908: {ratio} resolves to an @2x suffix on a retina
  // display. Note what the buffer actually stores: redact() runs at capture and
  // reads `/1539@2x.png` as an email, so the y coordinate is already gone by
  // the time the key is computed.
  it('collapses a retina source whose tiles carry an @2x suffix', () => {
    for (const [x, y] of [[1205, 1539], [1206, 1539], [1205, 1540]]) {
      pushReportEntry({
        severity: 'error',
        source: 'console',
        message: `AJAXError: Not Found (404): https://tiles.example.com/12/${x}/${y}@2x.png`,
      });
    }

    expect(countDistinctFailures(getReportEntries())).toBe(1);
  });

  // codex round 8 on #908: toMaplibreStyle gives every custom basemap the fixed
  // source id `basemap`, so the id alone merged two different failing basemaps.
  it('keeps two custom basemaps apart despite their shared source id', () => {
    for (const host of ['a-tiles.example.com', 'b-tiles.example.com']) {
      pushReportEntry({
        severity: 'error',
        source: 'maplibre',
        message: `AJAXError: Not Found (404): https://${host}/5/1/1.png`,
        detail: 'source: basemap',
      });
    }

    expect(countDistinctFailures(getReportEntries())).toBe(2);
  });

  // codex round 10 on #908: a validator-accepted template may put a static
  // suffix after the coordinates, which every shape-anchored rule missed.
  it('collapses coordinates followed by a static path suffix', () => {
    for (const [x, y] of [[1205, 1539], [1206, 1539], [1205, 1540]]) {
      pushReportEntry({
        severity: 'error',
        source: 'console',
        message: `AJAXError: Not Found (404): https://tiles.example.com/12/${x}/${y}/tile.png`,
      });
    }

    expect(countDistinctFailures(getReportEntries())).toBe(1);
  });

  // codex round 11 on #908: a template may carry the whole tile address in the
  // query string, which the custom-basemap validator accepts.
  it('collapses a source whose coordinates ride the query string', () => {
    for (const [x, y] of [[1205, 1539], [1206, 1539], [1205, 1540]]) {
      pushReportEntry({
        severity: 'error',
        source: 'console',
        message: `AJAXError: Not Found (404): https://tiles.example.com/tile?z=12&x=${x}&y=${y}`,
      });
    }

    expect(countDistinctFailures(getReportEntries())).toBe(1);
  });

  it('keeps a source-defining query param while dropping the coordinates', () => {
    for (const layer of ['roads', 'rivers']) {
      pushReportEntry({
        severity: 'error',
        source: 'console',
        message: `AJAXError: Not Found (404): https://wms.example.com/?layer=${layer}&Z=5&X=1&Y=1`,
      });
    }

    expect(countDistinctFailures(getReportEntries())).toBe(2);
  });

  // codex round 12 on #908: a template can name the coordinate params anything.
  // The standard names are covered; a value-based rule is not, because
  // `?layer=3` is numeric and source-defining.
  it('collapses coordinates carried under WMTS parameter names', () => {
    for (const [row, col] of [[1539, 1205], [1539, 1206], [1540, 1205]]) {
      pushReportEntry({
        severity: 'error',
        source: 'console',
        message: `AJAXError: Not Found (404): https://wmts.example.com/?TileMatrix=12&TileRow=${row}&TileCol=${col}`,
      });
    }

    expect(countDistinctFailures(getReportEntries())).toBe(1);
  });

  it('keeps TileMatrixSet, which names the grid rather than a tile', () => {
    for (const grid of ['EPSG:3857', 'EPSG:4326']) {
      pushReportEntry({
        severity: 'error',
        source: 'console',
        message: `AJAXError: Not Found (404): https://wmts.example.com/?TileMatrixSet=${grid}&TileMatrix=12&TileRow=1&TileCol=1`,
      });
    }

    expect(countDistinctFailures(getReportEntries())).toBe(2);
  });

  it('keeps a numeric source-defining param, which is not a coordinate', () => {
    for (const layer of [3, 4]) {
      pushReportEntry({
        severity: 'error',
        source: 'console',
        message: `AJAXError: Not Found (404): https://tiles.example.com/tile?layer=${layer}&z=5&x=1&y=1`,
      });
    }

    expect(countDistinctFailures(getReportEntries())).toBe(2);
  });

  // codex round 14 on #908: normalizing every numeric segment merged two
  // sources that differ only by a numeric version, tenant, or region.
  it('keeps a numeric version segment while still collapsing the coordinates', () => {
    for (const version of [1, 2]) {
      for (const [x, y] of [[1205, 1539], [1206, 1539]]) {
        pushReportEntry({
          severity: 'error',
          source: 'console',
          message: `AJAXError: Not Found (404): https://tiles.example.com/v/${version}/12/${x}/${y}.png`,
        });
      }
    }

    // Two sources, each with its tiles collapsed — not one, and not four.
    expect(countDistinctFailures(getReportEntries())).toBe(2);
  });

  it('collapses a quadkey behind a numeric version segment', () => {
    for (const quadkey of ['0313102310', '0313102311']) {
      pushReportEntry({
        severity: 'error',
        source: 'console',
        message: `AJAXError: Not Found (404): https://tiles.example.com/v/2/${quadkey}.png`,
      });
    }

    expect(countDistinctFailures(getReportEntries())).toBe(1);
  });

  // codex round 15 on #908: an accepted template may label its coordinates
  // (`/z/{z}/x/{x}/y/{y}`), which no consecutive-segment rule can see.
  it('collapses coordinates carried behind path labels', () => {
    for (const [x, y] of [[1205, 1539], [1206, 1539], [1205, 1540]]) {
      pushReportEntry({
        severity: 'error',
        source: 'console',
        message: `AJAXError: Not Found (404): https://tiles.example.com/z/12/x/${x}/y/${y}.png`,
      });
    }

    expect(countDistinctFailures(getReportEntries())).toBe(1);
  });

  it('does not mistake a labelled version for a coordinate', () => {
    for (const version of [1, 2]) {
      pushReportEntry({
        severity: 'error',
        source: 'console',
        message: `AJAXError: Not Found (404): https://tiles.example.com/v/${version}/z/12/x/1/y/1.png`,
      });
    }

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
