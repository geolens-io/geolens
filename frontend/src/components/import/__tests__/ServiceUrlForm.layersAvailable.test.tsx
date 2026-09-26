/**
 * Real i18next pluralization for the layer-count summary shown after a
 * probe. ServiceUrlForm.test.tsx mocks react-i18next for its own tests, so
 * a plural-form regression needs a separate file that renders against the
 * real bundles.
 */
import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { ServiceUrlForm } from '../ServiceUrlForm';
import type { ProbeResponse } from '@/types/api';
import { clearServiceImport } from '@/api/service-url-session';

const mockProbeService = vi.fn();

vi.mock('@/api/ingest', () => ({
  probeService: (...args: unknown[]) => mockProbeService(...args),
  previewServiceLayer: vi.fn(),
  commitImport: vi.fn(),
  arcgisSignin: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  clearServiceImport();
});

afterEach(() => {
  clearServiceImport();
});

const ONE_LAYER_PROBE: ProbeResponse = {
  service_type: 'wfs',
  url: 'https://example.test/wfs',
  selected_layer_id: null,
  layers: [
    {
      name: 'parks',
      title: 'Parks',
      geometry_type: 'Polygon',
      feature_count: 10,
      layer_type: 'Feature Layer',
      layer_id: 0,
      object_id_field: null,
      kind: 'vector',
    },
  ],
};

describe('ServiceUrlForm layer count summary', () => {
  it('uses the singular form for exactly one layer', async () => {
    mockProbeService.mockResolvedValue(ONE_LAYER_PROBE);
    const user = userEvent.setup();
    render(<ServiceUrlForm />);

    await user.type(
      screen.getByPlaceholderText('https://example.com/wfs, ArcGIS FeatureServer, or OGC API endpoint'),
      'https://example.test/wfs',
    );
    await user.click(screen.getByRole('button', { name: 'Probe →' }));

    await waitFor(() => expect(mockProbeService).toHaveBeenCalled());
    expect(await screen.findByText('1 layer available')).toBeInTheDocument();
    expect(screen.queryByText('1 layers available')).not.toBeInTheDocument();
  });
});
