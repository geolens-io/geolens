import { buildSignedTileUrl } from '@/lib/tile-utils';

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
});

