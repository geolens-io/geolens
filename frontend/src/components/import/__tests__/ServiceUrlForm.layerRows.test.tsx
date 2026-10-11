import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { ServiceUrlForm } from '../ServiceUrlForm';
import type { ProbeResponse } from '@/types/api';

const mockProbeService = vi.fn();

vi.mock('@/api/ingest', () => ({
  probeService: (...args: unknown[]) => mockProbeService(...args),
  previewServiceLayer: vi.fn(),
  commitImport: vi.fn(),
  arcgisSignin: vi.fn(),
}));

vi.mock('../ImportPreview', () => ({ ImportPreview: () => null }));
vi.mock('../ImportMetadataForm', () => ({ ImportMetadataForm: () => null }));
vi.mock('../JobProgress', () => ({ JobProgress: () => null }));

describe('ServiceUrlForm layer rows', () => {
  function layer(overrides: Partial<ProbeResponse['layers'][number]>) {
    return {
      name: 'parcels',
      title: 'parcels',
      geometry_type: 'Polygon' as const,
      feature_count: 1234,
      layer_type: 'Feature Layer',
      layer_id: 3,
      object_id_field: 'OBJECTID',
      kind: 'vector' as const,
      ...overrides,
    };
  }

  async function probeWith(layers: ProbeResponse['layers']) {
    mockProbeService.mockResolvedValue({
      service_type: 'arcgis',
      url: 'https://example.test/arcgis/rest/services/Rec/FeatureServer',
      selected_layer_id: null,
      layers,
    });
    const user = userEvent.setup();
    render(<ServiceUrlForm />);
    await user.type(
      screen.getByRole('textbox'),
      'https://example.test/arcgis/rest/services/Rec/FeatureServer',
    );
    await user.click(screen.getByRole('button', { name: 'Probe →' }));
    return screen.findByRole('button', { name: /parcels|Parcels/ });
  }

  it('shows the geometry and feature count once, without repeating the name', async () => {
    const row = await probeWith([layer({})]);

    expect(row).toHaveTextContent('Polygon · 1,234 features');
    expect(row.textContent?.match(/parcels/g)).toHaveLength(1);
  });

  it('omits the count when the probe did not return one', async () => {
    const row = await probeWith([layer({ feature_count: null })]);

    expect(row).toHaveTextContent('Polygon');
    expect(row).not.toHaveTextContent('features');
  });

  it('keeps the machine name beside the geometry when the title differs', async () => {
    const row = await probeWith([layer({ title: 'Parcels' })]);

    expect(row).toHaveTextContent('Parcels');
    expect(row).toHaveTextContent('parcels · Polygon · 1,234 features');
  });

  it('shows no geometry or count on a layer that cannot be imported', async () => {
    const row = await probeWith([
      layer({ importable: false, source_layer_type: 'Group Layer', feature_count: 99 }),
    ]);

    expect(row).toBeDisabled();
    expect(row).not.toHaveTextContent('99');
    expect(row).not.toHaveTextContent('Polygon');
  });
});
