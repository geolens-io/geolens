// The raster editor's paint keys, and the tile URL a colormap and stretch build.
import { describe, it, expect } from 'vitest';

describe('RASTER_OWNED_PAINT_PROPERTIES export', () => {
  it('exports exactly the 4 user-facing raster paint property keys in canonical order', async () => {
    const { RASTER_OWNED_PAINT_PROPERTIES } = await import('../raster-adapter');
    expect(RASTER_OWNED_PAINT_PROPERTIES).toEqual([
      'raster-brightness-min',
      'raster-contrast',
      'raster-saturation',
      'raster-hue-rotate',
    ]);
  });

  it('does NOT include raster-brightness-max, raster-resampling, raster-fade-duration, or raster-opacity', async () => {
    const { RASTER_OWNED_PAINT_PROPERTIES } = await import('../raster-adapter');
    const forbidden = ['raster-brightness-max', 'raster-resampling', 'raster-fade-duration', 'raster-opacity'];
    for (const key of forbidden) {
      expect(RASTER_OWNED_PAINT_PROPERTIES as readonly string[]).not.toContain(key);
    }
  });

  it('Pitfall 6: does NOT include _colormap or _stretch (builder-private keys must never reach setPaintProperty)', async () => {
    const { RASTER_OWNED_PAINT_PROPERTIES } = await import('../raster-adapter');
    expect(RASTER_OWNED_PAINT_PROPERTIES as readonly string[]).not.toContain('_colormap');
    expect(RASTER_OWNED_PAINT_PROPERTIES as readonly string[]).not.toContain('_stretch');
  });
});

describe('buildColormapTileUrl', () => {
  let buildColormapTileUrl: (baseUrl: string, paint: Record<string, unknown>) => string;

  beforeEach(async () => {
    // Use dynamic import so vi.resetModules() in other tests doesn't pollute
    ({ buildColormapTileUrl } = await import('../raster-adapter'));
  });

  const BASE = '/api/raster-tiles/abc/tiles/{z}/{x}/{y}.png';

  it('appends colormap_name for a non-gray colormap', () => {
    const result = buildColormapTileUrl(BASE, { _colormap: 'viridis' });
    expect(result).toBe(`${BASE}?colormap_name=viridis`);
  });

  it('appends both colormap_name and stretch when stretch is non-minmax', () => {
    const result = buildColormapTileUrl(BASE, { _colormap: 'viridis', _stretch: 'percentile' });
    expect(result).toContain('colormap_name=viridis');
    expect(result).toContain('stretch=percentile');
    expect(result.startsWith(BASE)).toBe(true);
  });

  // fix(#688): the raster template now arrives signed, so the base already
  // carries a query string. A blind `?` folded the style params into the
  // `scope` VALUE — a "Scope mismatch" 403 on a private raster, and silently
  // dropped styling on a public one.
  it('merges into an existing query string instead of starting a second one', () => {
    const signed = `${BASE}?sig=deadbeef&exp=1700000000&scope=abc`;

    const result = buildColormapTileUrl(signed, { _colormap: 'viridis' });

    expect(result).toBe(`${signed}&colormap_name=viridis`);
    expect(result.split('?')).toHaveLength(2);
    // The scope must survive intact — it is what the server re-derives.
    expect(new URLSearchParams(result.split('?')[1]).get('scope')).toBe('abc');
  });

  it('leaves a signed template untouched when there is nothing to append', () => {
    const signed = `${BASE}?sig=deadbeef&exp=1700000000&scope=abc`;

    expect(buildColormapTileUrl(signed, { _colormap: 'gray' })).toBe(signed);
  });

  it('returns base URL unchanged for gray colormap (Titiler single-band default)', () => {
    const result = buildColormapTileUrl(BASE, { _colormap: 'gray' });
    expect(result).toBe(BASE);
  });

  it('returns base URL unchanged when paint is empty', () => {
    const result = buildColormapTileUrl(BASE, {});
    expect(result).toBe(BASE);
  });

  it('returns base URL unchanged when _colormap is undefined', () => {
    const result = buildColormapTileUrl(BASE, { _colormap: undefined });
    expect(result).toBe(BASE);
  });

  it('appends colormap_name only (no stretch param) when _stretch is minmax', () => {
    const result = buildColormapTileUrl(BASE, { _colormap: 'viridis', _stretch: 'minmax' });
    expect(result).toContain('colormap_name=viridis');
    expect(result).not.toContain('stretch=');
  });

  it('appends stretch param for stddev (helper is robust to any non-minmax stretch)', () => {
    const result = buildColormapTileUrl(BASE, { _colormap: 'inferno', _stretch: 'stddev' });
    expect(result).toContain('colormap_name=inferno');
    expect(result).toContain('stretch=stddev');
  });

  // RASTER-STRETCH-UI-02: stretch is forwarded independently of colormap so
  // percentile/stddev apply on the default grayscale render too.
  it('forwards stretch with NO colormap_name on the default gray colormap', () => {
    const result = buildColormapTileUrl(BASE, { _colormap: 'gray', _stretch: 'percentile' });
    expect(result).toBe(`${BASE}?stretch=percentile`);
    expect(result).not.toContain('colormap_name');
  });

  it('forwards stretch when no colormap is set at all', () => {
    const result = buildColormapTileUrl(BASE, { _stretch: 'stddev' });
    expect(result).toBe(`${BASE}?stretch=stddev`);
  });

  it('returns base URL unchanged for gray colormap + minmax stretch (no params)', () => {
    const result = buildColormapTileUrl(BASE, { _colormap: 'gray', _stretch: 'minmax' });
    expect(result).toBe(BASE);
  });

  it('absolutize+colormap composition yields a well-formed origin/path?colormap_name=... URL', () => {
    // Simulate what absolutizeTileUrl would produce when origin is available
    const relative = '/api/raster-tiles/abc/tiles/{z}/{x}/{y}.png';
    const withColormap = buildColormapTileUrl(relative, { _colormap: 'plasma' });
    // Should still be a valid relative URL with single ? separator
    expect(withColormap).toBe(`${relative}?colormap_name=plasma`);
    // When prefixed with an origin, the result is well-formed
    const absolutized = `https://example.com${withColormap}`;
    expect(absolutized).toBe('https://example.com/api/raster-tiles/abc/tiles/{z}/{x}/{y}.png?colormap_name=plasma');
  });

  // ── RASTER-STRETCH-UI-01: pmin / pmax / sigma forwarding ──────────────────

  it('forwards pmin/pmax for non-default percentile (5/95)', () => {
    const result = buildColormapTileUrl(BASE, { _stretch: 'percentile', _pmin: 5, _pmax: 95 });
    expect(result).toContain('stretch=percentile');
    expect(result).toContain('pmin=5');
    expect(result).toContain('pmax=95');
  });

  it('omits pmin/pmax for default percentile bounds (2/98)', () => {
    const result = buildColormapTileUrl(BASE, { _stretch: 'percentile', _pmin: 2, _pmax: 98 });
    expect(result).toContain('stretch=percentile');
    expect(result).not.toContain('pmin');
    expect(result).not.toContain('pmax');
  });

  it('forwards only pmin when pmax is left at default (98)', () => {
    const result = buildColormapTileUrl(BASE, { _stretch: 'percentile', _pmin: 5 });
    expect(result).toContain('pmin=5');
    expect(result).not.toContain('pmax');
  });

  it('forwards sigma for non-default stddev (3)', () => {
    const result = buildColormapTileUrl(BASE, { _stretch: 'stddev', _sigma: 3 });
    expect(result).toContain('stretch=stddev');
    expect(result).toContain('sigma=3');
  });

  it('omits sigma for default stddev (2)', () => {
    const result = buildColormapTileUrl(BASE, { _stretch: 'stddev', _sigma: 2 });
    expect(result).toContain('stretch=stddev');
    expect(result).not.toContain('sigma');
  });

  it('never forwards pmin/pmax when stretch is not percentile', () => {
    const result = buildColormapTileUrl(BASE, { _stretch: 'stddev', _pmin: 5, _pmax: 95 });
    expect(result).not.toContain('pmin');
    expect(result).not.toContain('pmax');
  });

  it('never forwards sigma when stretch is not stddev', () => {
    const result = buildColormapTileUrl(BASE, { _stretch: 'percentile', _sigma: 3 });
    expect(result).not.toContain('sigma');
  });

  it('default percentile URL is byte-identical to today (no bound keys → no pmin/pmax)', () => {
    // No _pmin/_pmax keys present — must produce the exact same URL as before this change.
    const result = buildColormapTileUrl(BASE, { _colormap: 'viridis', _stretch: 'percentile' });
    expect(result).toBe(`${BASE}?colormap_name=viridis&stretch=percentile`);
  });
});
