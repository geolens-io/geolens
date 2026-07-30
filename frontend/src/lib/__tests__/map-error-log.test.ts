// fix(#755): `logUnhandledMapError` is the <Map> `onError` prop for every
// surface with its own tile-auth recovery (builder, viewer, dataset preview).
// It must drop the console log ONLY for the handled first-party 401/403
// vector-tile case — the recovery path owns those — and replicate the
// react-maplibre wrapper's default `console.error(e.error)` for everything
// else, so real failures stay visible in devtools and the problem report.

import {
  isHandledTileAuthError,
  isRasterTileAuthError,
  isRasterTileUrl,
  isRefreshableRasterAuthError,
  logUnhandledMapError,
} from '@/lib/map-error-log';
import { isSessionRenewalPending } from '@/hooks/use-tile-auth-recovery';

vi.mock('@/hooks/use-tile-auth-recovery', () => ({
  isSessionRenewalPending: vi.fn(() => false),
}));

function ajaxError(status: number, url: string) {
  return { error: { message: `AJAXError: (${status}): ${url}`, status, url } };
}

describe('logUnhandledMapError (fix #755)', () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    errorSpy.mockRestore();
  });

  it('logs nothing for a handled 403 on a same-origin signed vector tile (tab-return burst)', () => {
    const e = ajaxError(
      403,
      `${window.location.origin}/api/tiles/data.prueba/4/8/5.pbf?sig=abc&exp=1785148200&scope=prueba&cols=id&_v=1`,
    );
    logUnhandledMapError(e);
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it('logs nothing for a handled 401 on a relative tile URL without a sig (attach race)', () => {
    logUnhandledMapError(ajaxError(401, '/api/tiles/data.parcels/12/1205/1539.pbf'));
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it('logs nothing for a handled 403 on a CDN-fronted signed tile URL', () => {
    logUnhandledMapError(
      ajaxError(403, 'https://cdn.example.com/tiles/clusters/data.points/3/4/2.pbf?sig=abc&exp=1&scope=points'),
    );
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it('keeps the default single log for a third-party 403 without a GeoLens signature', () => {
    const e = ajaxError(403, 'https://demotiles.maplibre.org/tiles/3/4/2.pbf');
    logUnhandledMapError(e);
    expect(errorSpy).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalledWith(e.error);
  });

  // audit(w3-maps A1): real raster/DEM URLs carry a second `/tiles/` segment
  // (`/raster-tiles/{id}/tiles/{z}/{x}/{y}.png`), which previously satisfied
  // the `/tiles/` match and misclassified raster auth errors as handled.
  it('keeps the default single log for a raster-tiles 403 (real backend URL shape)', () => {
    const e = ajaxError(403, `${window.location.origin}/raster-tiles/0b0af5ab-1f3e-4c1a-9d7e-8f1f0c9d2e11/tiles/9/151/191.png`);
    logUnhandledMapError(e);
    expect(errorSpy).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalledWith(e.error);
  });

  it('keeps the default single log for a relative raster-tiles 401', () => {
    const e = ajaxError(401, '/raster-tiles/0b0af5ab-1f3e-4c1a-9d7e-8f1f0c9d2e11/tiles/9/151/191.png');
    logUnhandledMapError(e);
    expect(errorSpy).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalledWith(e.error);
  });

  it('keeps the default single log for a signed raster-tiles 403 (exclusion beats the sig= match)', () => {
    const e = ajaxError(403, 'https://cdn.example.com/raster-tiles/0b0af5ab-1f3e-4c1a-9d7e-8f1f0c9d2e11/tiles/9/151/191.png?sig=abc');
    logUnhandledMapError(e);
    expect(errorSpy).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalledWith(e.error);
  });

  it('keeps the default single log for a 404 no-data tile', () => {
    const e = ajaxError(404, `${window.location.origin}/api/tiles/data.prueba/4/8/5.pbf?sig=abc`);
    logUnhandledMapError(e);
    expect(errorSpy).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalledWith(e.error);
  });

  it('keeps the default single log for a tile 500', () => {
    const e = ajaxError(500, `${window.location.origin}/api/tiles/data.prueba/4/8/5.pbf?sig=abc`);
    logUnhandledMapError(e);
    expect(errorSpy).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalledWith(e.error);
  });

  it('keeps the default single log for a status-less runtime/style error', () => {
    const e = { error: { message: 'Unimplemented type: 4' } };
    logUnhandledMapError(e);
    expect(errorSpy).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalledWith(e.error);
  });
});

describe('isHandledTileAuthError (fix #755)', () => {
  it('matches only first-party tile-auth statuses', () => {
    const url = `${window.location.origin}/api/tiles/data.t/1/2/3.pbf?sig=a`;
    expect(isHandledTileAuthError(ajaxError(401, url))).toBe(true);
    expect(isHandledTileAuthError(ajaxError(403, url))).toBe(true);
    expect(isHandledTileAuthError(ajaxError(404, url))).toBe(false);
    expect(isHandledTileAuthError(ajaxError(500, url))).toBe(false);
    expect(isHandledTileAuthError({ error: { message: 'no status' } })).toBe(false);
    expect(isHandledTileAuthError({})).toBe(false);
  });

  it('requires a tile URL — a 403 without one stays loggable', () => {
    expect(isHandledTileAuthError({ error: { status: 403 } })).toBe(false);
    expect(isHandledTileAuthError(ajaxError(403, `${window.location.origin}/api/datasets/`))).toBe(false);
  });

  it('excludes raster-tiles URLs despite their second /tiles/ segment (audit w3-maps A1)', () => {
    const rasterUrl = `${window.location.origin}/raster-tiles/0b0af5ab-1f3e-4c1a-9d7e-8f1f0c9d2e11/tiles/9/151/191.png`;
    expect(isHandledTileAuthError(ajaxError(401, rasterUrl))).toBe(false);
    expect(isHandledTileAuthError(ajaxError(403, rasterUrl))).toBe(false);
    // Vector tile URLs stay handled after the exclusion.
    expect(isHandledTileAuthError(ajaxError(403, `${window.location.origin}/api/tiles/data.t/1/2/3.pbf?sig=a`))).toBe(true);
  });
});

// fix(#890): the surfaces' own error handlers claimed to have "handled" raster
// 401/403s (re-mint requested) even though nothing there can cure them, which
// left one suppressed report row next to the unsuppressed console row above.
// They now share this predicate, so the two sides cannot disagree again.
describe('isRasterTileAuthError (fix #890)', () => {
  const rasterUrl = `${window.location.origin}/raster-tiles/0b0af5ab-1f3e-4c1a-9d7e-8f1f0c9d2e11/tiles/9/151/191.png`;
  const vectorUrl = `${window.location.origin}/api/tiles/data.t/1/2/3.pbf?sig=a`;

  it('matches raster/DEM tile auth statuses only', () => {
    expect(isRasterTileAuthError(ajaxError(401, rasterUrl))).toBe(true);
    expect(isRasterTileAuthError(ajaxError(403, rasterUrl))).toBe(true);
    expect(isRasterTileAuthError(ajaxError(404, rasterUrl))).toBe(false);
    expect(isRasterTileAuthError(ajaxError(500, rasterUrl))).toBe(false);
  });

  it('never matches a vector tile, a non-tile URL, or a status-less error', () => {
    expect(isRasterTileAuthError(ajaxError(403, vectorUrl))).toBe(false);
    expect(isRasterTileAuthError(ajaxError(403, `${window.location.origin}/api/datasets/`))).toBe(false);
    expect(isRasterTileAuthError({ error: { status: 403 } })).toBe(false);
    expect(isRasterTileAuthError({ error: { message: 'no status' } })).toBe(false);
    expect(isRasterTileAuthError({})).toBe(false);
  });

  it('matches relative and CDN-fronted raster URLs alike', () => {
    expect(isRasterTileAuthError(ajaxError(403, '/raster-tiles/abc/tiles/9/151/191.png'))).toBe(true);
    expect(isRasterTileAuthError(ajaxError(403, 'https://cdn.example.com/raster-tiles/abc/tiles/9/151/191.png?sig=a'))).toBe(true);
  });

  it('is mutually exclusive with isHandledTileAuthError', () => {
    for (const url of [rasterUrl, vectorUrl, '/raster-tiles/a/tiles/1/2/3.png', '/api/tiles/x/1/2/3.pbf']) {
      const e = ajaxError(403, url);
      expect(isRasterTileAuthError(e) && isHandledTileAuthError(e)).toBe(false);
    }
  });

  it('classifies raster tile URLs regardless of status', () => {
    expect(isRasterTileUrl(rasterUrl)).toBe(true);
    expect(isRasterTileUrl(vectorUrl)).toBe(false);
    expect(isRasterTileUrl(undefined)).toBe(false);
  });
});

// fix(#907): a raster 401 is unrecoverable — EXCEPT while a session renewal is
// in flight, which is the one thing that fixes it. Logging it then would leave
// an unsuppressed red report entry for a tab return that healed itself.
describe('logUnhandledMapError during a session renewal (fix #907)', () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(isSessionRenewalPending).mockReturnValue(false);
  });

  afterEach(() => {
    errorSpy.mockRestore();
  });

  const rasterAuthError = ajaxError(401, '/raster-tiles/abc/tiles/12/1/1.png');

  it('logs a raster 401 when no renewal is running', () => {
    logUnhandledMapError(rasterAuthError);
    expect(errorSpy).toHaveBeenCalledTimes(1);
  });

  it('stays silent for a raster 401 while a renewal is running', () => {
    vi.mocked(isSessionRenewalPending).mockReturnValue(true);
    logUnhandledMapError(rasterAuthError);
    expect(errorSpy).not.toHaveBeenCalled();
  });

  // codex on #907: Titiler and its object store pass a genuine 403 through, and
  // a fresh JWT cannot cure that. Suppressing it would leave the preview blank
  // with no overlay once the window closed.
  it('still logs a raster 403 during a renewal', () => {
    vi.mocked(isSessionRenewalPending).mockReturnValue(true);
    logUnhandledMapError(ajaxError(403, '/raster-tiles/abc/tiles/12/1/1.png'));
    expect(errorSpy).toHaveBeenCalledTimes(1);
  });

  it('still logs a non-auth raster failure during a renewal', () => {
    vi.mocked(isSessionRenewalPending).mockReturnValue(true);
    logUnhandledMapError(ajaxError(500, '/raster-tiles/abc/tiles/12/1/1.png'));
    expect(errorSpy).toHaveBeenCalledTimes(1);
  });
});

describe('isRefreshableRasterAuthError (fix #907)', () => {
  it('is true only for a raster 401', () => {
    expect(isRefreshableRasterAuthError(ajaxError(401, '/raster-tiles/a/tiles/1/1/1.png'))).toBe(true);
  });

  it('is false for a raster 403 — an upstream denial a refresh cannot cure', () => {
    expect(isRefreshableRasterAuthError(ajaxError(403, '/raster-tiles/a/tiles/1/1/1.png'))).toBe(false);
  });

  it('is false for a vector 401, which the re-sign path owns', () => {
    expect(isRefreshableRasterAuthError(ajaxError(401, '/api/tiles/data.x/1/1/1.pbf'))).toBe(false);
  });

  it('is false for a non-auth raster failure', () => {
    expect(isRefreshableRasterAuthError(ajaxError(500, '/raster-tiles/a/tiles/1/1/1.png'))).toBe(false);
  });
});
