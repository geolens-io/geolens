/**
 * Real i18next pluralization for the layer-count summary shown after a
 * probe. ServiceUrlForm.test.tsx mocks react-i18next for its own tests, so
 * a plural-form regression needs a separate file that renders against the
 * real bundles.
 */
import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { ServiceUrlForm } from '../ServiceUrlForm';
import type { LayerInfo, ProbeResponse } from '@/types/api';
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

function makeLayer(name: string, layerId: number): LayerInfo {
  return {
    name,
    title: name,
    geometry_type: 'Polygon',
    feature_count: 10,
    layer_type: 'Feature Layer',
    layer_id: layerId,
    object_id_field: null,
    kind: 'vector',
  };
}

function probeWith(layers: LayerInfo[]): ProbeResponse {
  return {
    service_type: 'wfs',
    url: 'https://example.test/wfs',
    selected_layer_id: null,
    layers,
  };
}

async function submitProbe() {
  const user = userEvent.setup();
  render(<ServiceUrlForm />);

  await user.type(
    screen.getByPlaceholderText('https://example.com/wfs, ArcGIS FeatureServer, or OGC API endpoint'),
    'https://example.test/wfs',
  );
  await user.click(screen.getByRole('button', { name: 'Probe →' }));
  await waitFor(() => expect(mockProbeService).toHaveBeenCalled());
}

describe('ServiceUrlForm layer count summary', () => {
  it('uses the singular form for exactly one layer', async () => {
    mockProbeService.mockResolvedValue(probeWith([makeLayer('parks', 0)]));
    await submitProbe();

    expect(await screen.findByText('1 layer available')).toBeInTheDocument();
    expect(screen.queryByText('1 layers available')).not.toBeInTheDocument();
  });

  it('uses the plural form for more than one layer', async () => {
    mockProbeService.mockResolvedValue(
      probeWith([makeLayer('parks', 0), makeLayer('trails', 1)]),
    );
    await submitProbe();

    expect(await screen.findByText('2 layers available')).toBeInTheDocument();
    expect(screen.queryByText('2 layer available')).not.toBeInTheDocument();
  });
});

describe('ServiceUrlForm layers that hold no features', () => {
  it('disables a group layer with its reason and keeps feature layers selectable', async () => {
    mockProbeService.mockResolvedValue(
      probeWith([
        {
          ...makeLayer('Detailed', 0),
          geometry_type: null,
          source_layer_type: 'Group Layer',
          importable: false,
        },
        { ...makeLayer('Hydrants', 1), source_layer_type: 'Feature Layer', parent_layer_id: 0 },
      ]),
    );
    await submitProbe();

    const group = await screen.findByRole('button', { name: /Detailed/ });
    expect(group).toBeDisabled();
    expect(group).toHaveTextContent('Group Layer holds no features');
    expect(screen.getByRole('button', { name: /Hydrants/ })).toBeEnabled();
  });
});
