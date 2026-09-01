/**
 * fix(#1746): ServiceUrlForm regression tests.
 *
 * Two findings pinned here:
 * - Finding 4: the service-token field is a request-only credential, not a
 *   login password, so it must opt every password manager out explicitly
 *   (autoComplete="off" alone does not stop Chrome from offering to save it).
 * - Finding 8: the layer picker must be keyed by layer_id, not layer.name —
 *   two ArcGIS sublayers can share a display name (e.g. two sublayers both
 *   titled REC_PassiveConservedAccessScore), and a name-keyed list would
 *   collapse or misroute the duplicates.
 */
import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { ServiceUrlForm } from '../ServiceUrlForm';
import type { ProbeResponse } from '@/types/api';

const mockProbeService = vi.fn();
const mockPreviewServiceLayer = vi.fn();
const mockCommitImport = vi.fn();

vi.mock('@/api/ingest', () => ({
  probeService: (...args: unknown[]) => mockProbeService(...args),
  previewServiceLayer: (...args: unknown[]) => mockPreviewServiceLayer(...args),
  commitImport: (...args: unknown[]) => mockCommitImport(...args),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? key,
  }),
}));

vi.mock('../ImportPreview', () => ({
  ImportPreview: () => <div data-testid="import-preview" />,
}));

vi.mock('../ImportMetadataForm', () => ({
  ImportMetadataForm: () => <div data-testid="import-metadata-form" />,
}));

vi.mock('../JobProgress', () => ({
  JobProgress: () => <div data-testid="job-progress" />,
}));

beforeEach(() => {
  vi.clearAllMocks();
});

const DUPLICATE_NAME_PROBE: ProbeResponse = {
  service_type: 'arcgis',
  url: 'https://example.test/arcgis/rest/services/Rec/FeatureServer',
  selected_layer_id: null,
  layers: [
    {
      name: 'REC_PassiveConservedAccessScore',
      title: 'REC_PassiveConservedAccessScore',
      geometry_type: 'Polygon',
      feature_count: 10,
      layer_type: 'Feature Layer',
      layer_id: 15,
      object_id_field: 'OBJECTID',
      kind: 'vector',
    },
    {
      name: 'REC_PassiveConservedAccessScore',
      title: 'REC_PassiveConservedAccessScore',
      geometry_type: 'Polygon',
      feature_count: 20,
      layer_type: 'Feature Layer',
      layer_id: 17,
      object_id_field: 'OBJECTID',
      kind: 'vector',
    },
  ],
};

async function connectToDuplicateNameService() {
  const user = userEvent.setup();
  render(<ServiceUrlForm />);

  await user.type(
    screen.getByPlaceholderText('serviceUrl.placeholder'),
    'https://example.test/arcgis/rest/services/Rec/FeatureServer',
  );
  await user.click(screen.getByRole('button', { name: 'Probe →' }));

  await waitFor(() => {
    expect(mockProbeService).toHaveBeenCalled();
  });

  const layerButtons = await waitFor(() => {
    const buttons = screen
      .getAllByRole('button')
      .filter((btn) => btn.textContent?.includes('REC_PassiveConservedAccessScore'));
    expect(buttons).toHaveLength(2);
    return buttons;
  });

  return { user, layerButtons };
}

describe('ServiceUrlForm token input', () => {
  it('opts every password manager out of the service token field', () => {
    render(<ServiceUrlForm />);
    const input = screen.getByLabelText('serviceUrl.tokenLabel');

    expect(input).toHaveAttribute('type', 'password');
    expect(input).toHaveAttribute('autocomplete', 'new-password');
    expect(input).toHaveAttribute('data-1p-ignore');
    expect(input).toHaveAttribute('data-lpignore', 'true');
    expect(input).toHaveAttribute('data-bwignore');
  });
});

describe('ServiceUrlForm layer picker with a shared layer name', () => {
  it('renders both same-named layers as distinct, independently selectable rows', async () => {
    mockProbeService.mockResolvedValue(DUPLICATE_NAME_PROBE);
    const { layerButtons } = await connectToDuplicateNameService();

    expect(layerButtons).toHaveLength(2);
  });

  it('routes the first duplicate-named row to its own layer_id', async () => {
    mockProbeService.mockResolvedValue(DUPLICATE_NAME_PROBE);
    mockPreviewServiceLayer.mockResolvedValue({
      job_id: 'job-1',
      source_filename: null,
      columns: [],
      crs: 4326,
      geometry_type: 'Polygon',
      feature_count: 10,
      sample_rows: [],
      layer_name: 'REC_PassiveConservedAccessScore',
      layers: null,
    });

    const { user, layerButtons } = await connectToDuplicateNameService();
    await user.click(layerButtons[0]);

    await waitFor(() =>
      expect(mockPreviewServiceLayer).toHaveBeenCalledWith(
        expect.objectContaining({ layer_id: 15 }),
      ),
    );
  });

  it('routes the second duplicate-named row to its own layer_id', async () => {
    mockProbeService.mockResolvedValue(DUPLICATE_NAME_PROBE);
    mockPreviewServiceLayer.mockResolvedValue({
      job_id: 'job-2',
      source_filename: null,
      columns: [],
      crs: 4326,
      geometry_type: 'Polygon',
      feature_count: 20,
      sample_rows: [],
      layer_name: 'REC_PassiveConservedAccessScore',
      layers: null,
    });

    const { user, layerButtons } = await connectToDuplicateNameService();
    await user.click(layerButtons[1]);

    await waitFor(() =>
      expect(mockPreviewServiceLayer).toHaveBeenCalledWith(
        expect.objectContaining({ layer_id: 17 }),
      ),
    );
  });
});
