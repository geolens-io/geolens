import {
  buildClusterTileUrl,
  buildSignedTileUrl,
  buildTileTransformRequest,
  getMvtSourceLayerName,
  isMvtSourceLayerConfigReady,
  isThirdPartyTileUrl,
  refreshRasterTileSources,
} from '@/lib/tile-utils';
import { useAuthStore } from '@/stores/auth-store';

describe('buildSignedTileUrl', () => {
  const mockToken = { sig: 'abc123', exp: 1700000000, scope: 'ds_test' };

  it('appends sig/exp/scope query params when token is provided', () => {
    const url = buildSignedTileUrl('my_table', mockToken, 'https://tiles.example.com');
    expect(url).toBe(
      'https://tiles.example.com/tiles/data.my_table/{z}/{x}/{y}.pbf?sig=abc123&exp=1700000000&scope=ds_test',
    );
  });

  it('returns clean URL without query params when token is null', () => {
    const url = buildSignedTileUrl('my_table', null, 'https://tiles.example.com');
    expect(url).toBe('https://tiles.example.com/tiles/data.my_table/{z}/{x}/{y}.pbf');
  });

  it('uses custom tileBaseUrl when provided', () => {
    const url = buildSignedTileUrl('tbl', mockToken, 'https://cdn.example.com/');
    expect(url).toContain('https://cdn.example.com/tiles/data.tbl/');
  });

  it('uses window.location.origin/api when tileBaseUrl is not provided', () => {
    const url = buildSignedTileUrl('tbl', mockToken);
    expect(url).toContain(`${window.location.origin}/api/tiles/data.tbl/`);
  });

  it('uses window.location.origin/api when tileBaseUrl is null', () => {
    const url = buildSignedTileUrl('tbl', null, null);
    expect(url).toBe(`${window.location.origin}/api/tiles/data.tbl/{z}/{x}/{y}.pbf`);
  });

  it('appends _v param when tileVersion is provided with token', () => {
    const url = buildSignedTileUrl('tbl', mockToken, 'https://cdn.example.com', '2026-03-20T12:00:00Z');
    expect(url).toContain('sig=abc123');
    expect(url).toContain('_v=2026-03-20T12%3A00%3A00Z');
  });

  it('appends _v param when tileVersion is provided without token', () => {
    const url = buildSignedTileUrl('tbl', null, 'https://cdn.example.com', '2026-03-20T12:00:00Z');
    expect(url).toBe('https://cdn.example.com/tiles/data.tbl/{z}/{x}/{y}.pbf?_v=2026-03-20T12%3A00%3A00Z');
  });

  it('omits _v param when tileVersion is null', () => {
    const url = buildSignedTileUrl('tbl', mockToken, 'https://cdn.example.com', null);
    expect(url).not.toContain('_v=');
  });

  it('omits _v param when tileVersion is undefined', () => {
    const url = buildSignedTileUrl('tbl', mockToken, 'https://cdn.example.com');
    expect(url).not.toContain('_v=');
  });

  it('appends cols= when extraCols is provided', () => {
    const url = buildSignedTileUrl('tbl', null, 'https://cdn.example.com', null, ['economy']);
    expect(url).toBe('https://cdn.example.com/tiles/data.tbl/{z}/{x}/{y}.pbf?cols=economy');
  });

  it('sorts and dedupes cols for stable cache keys', () => {
    const url1 = buildSignedTileUrl('tbl', null, 'https://cdn.example.com', null, ['b', 'a', 'a']);
    const url2 = buildSignedTileUrl('tbl', null, 'https://cdn.example.com', null, ['a', 'b']);
    expect(url1).toBe(url2);
    expect(url1).toContain('cols=a%2Cb');
  });

  it('omits cols= when extraCols is empty / null / undefined', () => {
    const url1 = buildSignedTileUrl('tbl', null, 'https://cdn.example.com', null, []);
    const url2 = buildSignedTileUrl('tbl', null, 'https://cdn.example.com', null, null);
    const url3 = buildSignedTileUrl('tbl', null, 'https://cdn.example.com');
    expect(url1).not.toContain('cols=');
    expect(url2).not.toContain('cols=');
    expect(url3).not.toContain('cols=');
  });

  it('combines cols with signed params', () => {
    const url = buildSignedTileUrl('tbl', mockToken, 'https://cdn.example.com', null, ['pop']);
    expect(url).toContain('sig=abc123');
    expect(url).toContain('cols=pop');
  });
});

describe('buildSignedTileUrl extraCols edge cases', () => {
  it('omits &cols= when extraCols contains only whitespace', () => {
    // normalizeExtraCols filters entries that are falsy or whitespace-only.
    // A caller passing ['   '] (e.g. from a stale state value) must not
    // produce ?cols= in the URL, which would confuse the tile server.
    const url = buildSignedTileUrl('tbl', null, 'https://cdn.example.com', null, ['   ']);
    expect(url).not.toContain('cols=');
  });

  it('omits &cols= when extraCols contains only falsy entries', () => {
    // Explicit null/undefined entries that somehow end up in the extraCols
    // array (TypeScript coercion) must be stripped.  Distinct from the
    // existing empty-array case (lines 66-73) which covers [] / null / undefined
    // at the array level — this covers falsy items INSIDE a non-empty array.
    const url = buildSignedTileUrl('tbl', null, 'https://cdn.example.com', null, [
      undefined as unknown as string,
      null as unknown as string,
    ]);
    expect(url).not.toContain('cols=');
  });

  it('URL-encodes the comma separator as %2C when multiple cols are present', () => {
    // appendTileParams (tile-utils.ts:65) encodes the comma between column
    // names as %2C so the URL is safe for HTTP transport.
    // The existing test at line 63 asserts `.toContain('cols=a%2Cb')` using
    // single-char names; this assertion uses full-word column names to confirm
    // the encoding is not accidentally bypassed for multi-char names.
    const url = buildSignedTileUrl('tbl', null, 'https://cdn.example.com', null, ['col_a', 'col_b']);
    expect(url).toContain('cols=col_a%2Ccol_b');
  });
});

describe('buildClusterTileUrl', () => {
  const mockToken = { sig: 'abc123', exp: 1700000000, scope: 'ds_test' };

  it('targets the cluster tile endpoint with cluster options and signed params', () => {
    const url = buildClusterTileUrl('my_table', mockToken, 'https://tiles.example.com', null, {
      clusterRadius: 64,
      clusterMaxZoom: 12,
    });

    expect(url).toBe(
      'https://tiles.example.com/tiles/clusters/data.my_table/{z}/{x}/{y}.pbf?sig=abc123&exp=1700000000&scope=ds_test&cluster_radius=64&cluster_max_zoom=12',
    );
  });

  it('supports public or embed-token cluster tiles without signed params', () => {
    const url = buildClusterTileUrl('my_table', null, 'https://tiles.example.com', 'v1', {
      clusterRadius: 48,
      clusterMaxZoom: 14,
    });

    expect(url).toBe(
      'https://tiles.example.com/tiles/clusters/data.my_table/{z}/{x}/{y}.pbf?cluster_radius=48&cluster_max_zoom=14&_v=v1',
    );
  });

  // fix(#403): unclustered features on the server-cluster path are styled and
  // popup-inspected like plain vector features, so the cols= opt-in must ride
  // the cluster tile URL too (sorted + deduped for cache-key stability).
  it('appends normalized cols= so unclustered features carry attributes', () => {
    const url = buildClusterTileUrl(
      'my_table',
      null,
      'https://tiles.example.com',
      null,
      { clusterRadius: 48, clusterMaxZoom: 14 },
      ['mass_kg', 'fall', 'mass_kg', ' '],
    );

    expect(url).toBe(
      'https://tiles.example.com/tiles/clusters/data.my_table/{z}/{x}/{y}.pbf?cluster_radius=48&cluster_max_zoom=14&cols=fall%2Cmass_kg',
    );
  });

  it('omits cols= when extraCols is empty', () => {
    const url = buildClusterTileUrl('my_table', null, 'https://tiles.example.com', null, {}, []);
    expect(url).toBe('https://tiles.example.com/tiles/clusters/data.my_table/{z}/{x}/{y}.pbf');
  });
});

// ---------------------------------------------------------------------------
// fix(#394) VT-04: MVT source-layer ↔ tile-layer-name parity pin.
// The source-layer literal is produced by three derivation sites that must
// never drift, or the layer silently renders empty:
//   1. backend `app/processing/tiles/service.py` (`layer_name = f"{schema}.{table}"`,
//      single_tenant schema == "data", hosted schema == data_t_<tid>) — pinned by
//      `backend/tests/test_mvt_audit_fixes.py::test_get_tile_layer_name_is_schema_qualified`;
//   2. this helper (the ONLY frontend derivation — builder map-sync, viewer
//      ViewerMap, and use-map-layers all import it as of fix(#394) VT-03);
//   3. the exported style.json `_mvt_source_layer` (backend style_json.py).
// Tile-config supplies the server-resolved hosted prefix to the frontend.
// ---------------------------------------------------------------------------

describe('getMvtSourceLayerName (VT-04 parity pin)', () => {
  it('produces the canonical data.{table} literal the tile server emits', () => {
    expect(getMvtSourceLayerName('recent_earthquakes')).toBe('data.recent_earthquakes');
  });

  it('uses the tenant schema prefix emitted by the tile-config endpoint', () => {
    expect(
      getMvtSourceLayerName(
        'recent_earthquakes',
        'data_t_12345678_1234_1234_1234_123456789abc',
      ),
    ).toBe('data_t_12345678_1234_1234_1234_123456789abc.recent_earthquakes');
  });

  it('does not collapse an explicitly unresolved tenant prefix to data', () => {
    expect(() => getMvtSourceLayerName('roads', null)).toThrow(
      'MVT source-layer prefix is unresolved',
    );
  });
});

describe('isMvtSourceLayerConfigReady', () => {
  it('fails closed while the request is absent, errored, or explicitly unresolved', () => {
    expect(isMvtSourceLayerConfigReady(undefined)).toBe(false);
    expect(isMvtSourceLayerConfigReady(null)).toBe(false);
    expect(isMvtSourceLayerConfigReady({ mvt_source_layer_prefix: null })).toBe(false);
  });

  it('accepts resolved tenant config and legacy single-tenant responses', () => {
    expect(isMvtSourceLayerConfigReady({ mvt_source_layer_prefix: 'data_t_acme' })).toBe(true);
    expect(isMvtSourceLayerConfigReady({})).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// chore(#835): shared first-party/third-party classifier + transformRequest
// builder. The three map surfaces (BuilderMap / ViewerMap / DatasetMap) had
// drifted apart here — the viewer's missing raster Bearer (#819) was this
// drift biting, so the header behavior is pinned below.
// ---------------------------------------------------------------------------

describe('isThirdPartyTileUrl', () => {
  it('treats missing url as first-party (preserves prior behavior)', () => {
    expect(isThirdPartyTileUrl(undefined)).toBe(false);
    expect(isThirdPartyTileUrl('')).toBe(false);
  });

  it('treats relative paths as first-party', () => {
    expect(isThirdPartyTileUrl('/api/tiles/data.roads/1/2/3.pbf')).toBe(false);
  });

  it('treats same-origin absolute URLs as first-party', () => {
    expect(isThirdPartyTileUrl(`${window.location.origin}/api/tiles/x.mvt`)).toBe(false);
  });

  it('classifies other origins as third-party', () => {
    expect(isThirdPartyTileUrl('https://tiles.openfreemap.org/styles/positron/sprite.json')).toBe(true);
  });

  it('origin-checks protocol-relative URLs instead of short-circuiting on the leading slash', () => {
    expect(isThirdPartyTileUrl('//tiles.openfreemap.org/styles/positron/sprite.json')).toBe(true);
  });

  it('treats the configured tile CDN origin as first-party', () => {
    const tileConfig = { cdn_base_url: 'https://cdn.example.com' };
    expect(isThirdPartyTileUrl('https://cdn.example.com/api/tiles/x.mvt', tileConfig)).toBe(false);
    expect(isThirdPartyTileUrl('https://elsewhere.example.net/api/tiles/x.mvt', tileConfig)).toBe(true);
  });
});

describe('buildTileTransformRequest', () => {
  const initialAuth = useAuthStore.getState();

  afterEach(() => {
    useAuthStore.setState({
      token: initialAuth.token,
      refreshToken: initialAuth.refreshToken,
      expiresAt: initialAuth.expiresAt,
      user: initialAuth.user,
    });
  });

  it('absolutifies relative URLs', () => {
    const transform = buildTileTransformRequest();
    expect(transform('/api/tiles/data.roads/1/2/3.pbf')).toEqual({
      url: `${window.location.origin}/api/tiles/data.roads/1/2/3.pbf`,
    });
  });

  // fix(#1688 follow-up): transformRequest runs before MapLibre's protocol
  // dispatch, so a pmtiles:// URL must pass through byte-identical or the
  // registered protocol handler never sees it.
  it('passes pmtiles:// URLs through unchanged with no headers', () => {
    useAuthStore.setState({ token: 'tok-123' });
    const transform = buildTileTransformRequest();
    const url = 'pmtiles://https://tiles.example.com/world.pmtiles';
    expect(transform(url)).toEqual({ url });
  });

  it('passes pmtiles:// URLs through unchanged on the embed surface (no X-Embed-Token)', () => {
    const transform = buildTileTransformRequest({ embedToken: 'embed-tok' });
    const url = 'pmtiles://https://tiles.example.com/world.pmtiles';
    expect(transform(url)).toEqual({ url });
  });

  it('leaves protocol-relative URLs alone rather than double-slashing the origin', () => {
    const transform = buildTileTransformRequest();
    expect(transform('//tiles.example.com/1/2/3.png')).toEqual({
      url: '//tiles.example.com/1/2/3.png',
    });
  });

  it('attaches the Bearer header to first-party raster tiles when signed in (#819 regression class)', () => {
    useAuthStore.setState({ token: 'jwt-abc' });
    const transform = buildTileTransformRequest();
    expect(transform('/raster-tiles/ds-1/tiles/1/2/3.png')).toEqual({
      url: `${window.location.origin}/raster-tiles/ds-1/tiles/1/2/3.png`,
      headers: { Authorization: 'Bearer jwt-abc' },
    });
  });

  it('sends no Bearer header when signed out', () => {
    useAuthStore.setState({ token: null });
    const transform = buildTileTransformRequest();
    expect(transform('/raster-tiles/ds-1/tiles/1/2/3.png')).toEqual({
      url: `${window.location.origin}/raster-tiles/ds-1/tiles/1/2/3.png`,
    });
  });

  it('never sends the Bearer header to a third-party host, even on a /raster-tiles/ path', () => {
    useAuthStore.setState({ token: 'jwt-abc' });
    const transform = buildTileTransformRequest();
    expect(transform('https://evil.example.net/raster-tiles/ds-1/tiles/1/2/3.png')).toEqual({
      url: 'https://evil.example.net/raster-tiles/ds-1/tiles/1/2/3.png',
    });
  });

  it('attaches X-Embed-Token to first-party requests on the embed surface', () => {
    const transform = buildTileTransformRequest({ embedToken: 'embed-tok' });
    expect(transform('/api/tiles/data.roads/1/2/3.pbf')).toEqual({
      url: `${window.location.origin}/api/tiles/data.roads/1/2/3.pbf`,
      headers: { 'X-Embed-Token': 'embed-tok' },
    });
  });

  it('prefers X-Embed-Token over the Bearer on a first-party raster URL (else-if precedence)', () => {
    // On the embed surface the embed token IS the credential — even a
    // signed-in session must not also leak the JWT on raster tiles.
    useAuthStore.setState({ token: 'jwt-abc' });
    const transform = buildTileTransformRequest({ embedToken: 'embed-tok' });
    expect(transform('/raster-tiles/ds-1/tiles/1/2/3.png')).toEqual({
      url: `${window.location.origin}/raster-tiles/ds-1/tiles/1/2/3.png`,
      headers: { 'X-Embed-Token': 'embed-tok' },
    });
  });

  it('never sends X-Embed-Token to third-party basemap CDNs (fix #394 SH-02/B-022)', () => {
    const transform = buildTileTransformRequest({ embedToken: 'embed-tok' });
    expect(transform('https://tiles.openfreemap.org/styles/positron/sprite.json')).toEqual({
      url: 'https://tiles.openfreemap.org/styles/positron/sprite.json',
    });
  });

  it('sends no Bearer header for raster tiles on the embed viewer surface, even with no embedToken (fix #1778)', () => {
    useAuthStore.setState({ token: 'jwt-abc' });
    const originalLocation = window.location;
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, pathname: '/m/share-123', search: '?embed=true' },
    });
    try {
      const transform = buildTileTransformRequest();
      expect(transform('/raster-tiles/ds-1/tiles/1/2/3.png')).toEqual({
        url: `${window.location.origin}/raster-tiles/ds-1/tiles/1/2/3.png`,
      });
    } finally {
      Object.defineProperty(window, 'location', {
        configurable: true,
        value: originalLocation,
      });
    }
  });

  it('honors a late-arriving CDN config through getTileConfig', () => {
    const config: { cdn_base_url: string | null } = { cdn_base_url: null };
    const transform = buildTileTransformRequest({
      embedToken: 'embed-tok',
      getTileConfig: () => config,
    });
    expect(transform('https://cdn.example.com/api/tiles/x.mvt').headers).toBeUndefined();
    config.cdn_base_url = 'https://cdn.example.com';
    expect(transform('https://cdn.example.com/api/tiles/x.mvt').headers).toEqual({
      'X-Embed-Token': 'embed-tok',
    });
  });
});

// fix(#907) (codex P1): a raster descriptor does not change when the session
// JWT rotates, so nothing in the token→setTiles plumbing retries the tiles that
// 401'd while MapLibre raced the refresh. This is the explicit reload.
describe('refreshRasterTileSources (fix #907)', () => {
  function fakeMap(sources: Record<string, { type: string }>) {
    return {
      getStyle: () => ({ sources }),
      refreshTiles: vi.fn(),
    };
  }

  it('reloads raster and raster-dem sources, and nothing else', () => {
    const map = fakeMap({
      'raster-a': { type: 'raster' },
      'dem-b': { type: 'raster-dem' },
      'vector-c': { type: 'vector' },
      'geojson-d': { type: 'geojson' },
    });

    expect(refreshRasterTileSources(map)).toBe(2);
    expect(map.refreshTiles.mock.calls.map(([id]) => id)).toEqual(['raster-a', 'dem-b']);
  });

  it('is a no-op without a map, and survives a torn-down style', () => {
    expect(refreshRasterTileSources(null)).toBe(0);
    expect(
      refreshRasterTileSources({
        getStyle: () => {
          throw new Error('style is not done loading');
        },
        refreshTiles: vi.fn(),
      }),
    ).toBe(0);
  });

  it('keeps going when one source is torn down mid-refresh', () => {
    const refreshTiles = vi.fn((id: string) => {
      if (id === 'raster-a') throw new Error('source removed');
    });
    const map = {
      getStyle: () => ({
        sources: { 'raster-a': { type: 'raster' }, 'raster-b': { type: 'raster' } },
      }),
      refreshTiles,
    };

    expect(refreshRasterTileSources(map)).toBe(1);
    expect(refreshTiles).toHaveBeenCalledTimes(2);
  });
});
