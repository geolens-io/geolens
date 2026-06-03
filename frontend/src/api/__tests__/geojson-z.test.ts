import { fetchBoundedGeoJson, fetchGeoJsonZ, asFeatureCollection } from '@/api/geojson-z';
import { useAuthStore } from '@/stores/auth-store';

vi.mock('@/api/auth', () => ({
  refreshAccessToken: vi.fn(),
}));

vi.mock('@/lib/error-map', () => ({
  translateError: (msg: string) => msg,
}));

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'OK',
    json: () => Promise.resolve(data),
    headers: new Headers(),
  } as Response;
}

const boundedGeoJson = {
  type: 'FeatureCollection' as const,
  features: [
    {
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [0, 0] },
      properties: { id: 1 },
    },
  ],
  truncated: false,
  total_count: 1,
};

describe('fetchBoundedGeoJson', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
  });

  it('uses the authenticated API path without duplicating the /api prefix', async () => {
    useAuthStore.setState({ token: 'jwt-token' });
    mockFetch.mockResolvedValueOnce(jsonResponse(boundedGeoJson));

    await fetchBoundedGeoJson('dataset-1');

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/datasets/dataset-1/features.geojson',
      expect.objectContaining({ headers: expect.any(Headers) }),
    );

    const headers: Headers = mockFetch.mock.calls[0][1].headers;
    expect(headers.get('Authorization')).toBe('Bearer jwt-token');
    expect(headers.get('Content-Type')).toBe('application/json');
  });

  it('uses the embed-token header for public embed contexts', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(boundedGeoJson));

    await fetchBoundedGeoJson('dataset-1', { embedToken: 'embed-token' });

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/datasets/dataset-1/features.geojson',
      { headers: { 'X-Embed-Token': 'embed-token' } },
    );
  });

  it('uses the API key query parameter for public API-key contexts', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(boundedGeoJson));

    await fetchBoundedGeoJson('dataset-1', { apiKey: 'key 1' });

    expect(mockFetch).toHaveBeenCalledWith('/api/datasets/dataset-1/features.geojson?api_key=key%201');
  });

  it('keeps fetchGeoJsonZ as a compatibility alias', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(boundedGeoJson));

    const response = await fetchGeoJsonZ('dataset-1', { apiKey: 'key' });

    expect(response).toEqual(boundedGeoJson);
    expect(mockFetch).toHaveBeenCalledWith('/api/datasets/dataset-1/features.geojson?api_key=key');
  });

  it('converts bounded GeoJSON responses to plain FeatureCollections for MapLibre', () => {
    expect(asFeatureCollection(boundedGeoJson)).toEqual({
      type: 'FeatureCollection',
      features: boundedGeoJson.features,
    });
  });

  it('throws for failed direct bounded GeoJSON requests', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ detail: 'Forbidden' }, 403));

    await expect(fetchBoundedGeoJson('dataset-1', { apiKey: 'bad' }))
      .rejects
      .toThrow('Bounded GeoJSON fetch failed: 403');
  });
});
