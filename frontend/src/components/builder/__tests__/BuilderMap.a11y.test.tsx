import { render, screen, waitFor } from '@/test/test-utils';
import { BuilderMap } from '../BuilderMap';

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({
    data: [
      {
        id: 'openfreemap-positron',
        label: 'Light',
        url: 'https://tiles.example.com/styles/basic',
        enabled: true,
      },
    ],
  }),
  useMapDefaults: () => ({ data: { center_lng: 0, center_lat: 0, zoom: 2 } }),
  useTileConfig: () => ({ data: null }),
  useEnabledWidgets: () => ({ data: [], isLoading: false }),
}));

vi.mock('@/hooks/use-tile-token', () => ({
  useTileTokens: () => [],
}));

vi.mock('@/hooks/use-webgl-recovery', () => ({
  useWebGLRecovery: () => ({ contextLost: false, reload: vi.fn() }),
}));

vi.mock('@/components/map/MapCoordReadout', () => ({
  MapCoordReadout: () => null,
}));

describe('BuilderMap accessibility recovery copy', () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('surfaces a non-blocking basemap recovery notice when the basemap style fails', async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new Error('network unavailable'))) as typeof fetch;

    render(
      <BuilderMap
        layers={[]}
        basemapStyle="openfreemap-positron"
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent('Basemap connection issue');
    });
    expect(screen.getByRole('status')).toHaveTextContent('Your data layers are still editable');
  });
});
