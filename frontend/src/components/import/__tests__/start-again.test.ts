import { startAgainPath } from '../start-again';

describe('startAgainPath', () => {
  it('opens the service tab with the URL minus userinfo and redacted credentials', () => {
    const path = startAgainPath(
      'service',
      'https://redacted@maps.example.com/arcgis/rest/services/Roads/FeatureServer?f=json&token=%3Credacted%3E&layer=3',
    );
    const url = new URL(path, 'http://localhost');

    expect(url.pathname).toBe('/import');
    expect(url.searchParams.get('tab')).toBe('service');
    const prefill = new URL(url.searchParams.get('url') ?? '');
    expect(prefill.username).toBe('');
    expect(prefill.searchParams.has('token')).toBe(false);
    expect(prefill.searchParams.get('layer')).toBe('3');
    expect(path).not.toContain('redacted');
  });

  it('opens the file URL tab without a URL when the job kept none', () => {
    expect(startAgainPath('url', null)).toBe('/import?tab=url');
  });

  it('drops a source URL that is not http(s) or does not parse', () => {
    expect(startAgainPath('service', 'javascript:alert(1)')).toBe('/import?tab=service');
    expect(startAgainPath('service', 'not a url')).toBe('/import?tab=service');
  });
});
