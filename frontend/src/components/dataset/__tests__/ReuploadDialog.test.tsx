import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '@/test/test-utils';
import {
  useReuploadDataset,
  useReuploadPreview,
  useReuploadServicePreview,
  useReuploadCommit,
} from '@/components/dataset/hooks/use-dataset';
import { useJobStatus, useUploadConfig } from '@/components/import/hooks/use-ingest';
import { probeService } from '@/api/ingest';
import { ReuploadDialog } from '../ReuploadDialog';
import type { DatasetResponse, ProbeResponse, ReuploadPreviewResponse } from '@/types/api';

let dropHandler: ((acceptedFiles: File[]) => void) | null = null;

vi.mock('react-dropzone', () => ({
  useDropzone: vi.fn((options: { onDrop: (acceptedFiles: File[]) => void }) => {
    dropHandler = options.onDrop;
    return {
      getRootProps: (props: Record<string, unknown> = {}) => props,
      getInputProps: () => ({}),
      isDragActive: false,
      isDragReject: false,
    };
  }),
}));

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useReuploadDataset: vi.fn(),
  useReuploadPreview: vi.fn(),
  useReuploadServicePreview: vi.fn(),
  useReuploadCommit: vi.fn(),
}));

vi.mock('@/components/import/hooks/use-ingest', () => ({
  useUploadConfig: vi.fn(),
  useJobStatus: vi.fn(),
}));

vi.mock('@/api/ingest', () => ({
  probeService: vi.fn(),
}));

vi.mock('@/api/datasets', () => ({
  reuploadPresigned: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    message: vi.fn(),
  },
}));

const mockUseReuploadDataset = vi.mocked(useReuploadDataset);
const mockUseReuploadPreview = vi.mocked(useReuploadPreview);
const mockUseReuploadServicePreview = vi.mocked(useReuploadServicePreview);
const mockUseReuploadCommit = vi.mocked(useReuploadCommit);
const mockUseUploadConfig = vi.mocked(useUploadConfig);
const mockUseJobStatus = vi.mocked(useJobStatus);
const mockProbeService = vi.mocked(probeService);

const uploadMutateAsync = vi.fn();
const previewMutateAsync = vi.fn();
const servicePreviewMutateAsync = vi.fn();
const commitMutateAsync = vi.fn();

function makeDataset(): DatasetResponse {
  return {
    id: 'dataset-1',
    record_id: 'record-1',
    table_name: 'roads',
    title: 'Roads',
    summary: 'Road centerlines',
    srid: 4326,
    geometry_type: 'LineString',
    feature_count: 42,
    extent_bbox: [-1, -1, 1, 1],
    column_info: [{ name: 'name', type: 'text' }],
    license: null,
    source_organization: null,
    data_vintage_start: null,
    data_vintage_end: null,
    source_format: 'GeoJSON',
    source_filename: 'roads.geojson',
    original_srid: 4326,
    visibility: 'public',
    created_by: 'user-1',
    created_by_display: 'editor-user',
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
    last_edited_by_display: null,
    last_edited_at: null,
    record_status: 'published',
    lineage_summary: null,
    update_frequency: null,
    usage_constraints: null,
    access_constraints: null,
    sensitivity_classification: null,
    theme_category: null,
    owner_org: null,
    published_at: null,
    updated_by: null,
    current_version: 1,
    source_url: null,
    quality_statement: null,
    collections: [],
    tile_columns: null,
    quality_detail: null,
    record_type: 'vector_dataset',
    raster: null,
  };
}

function makeProbeResponse(): ProbeResponse {
  return {
    service_type: 'WFS',
    url: 'https://example.com/wfs',
    selected_layer_id: null,
    layers: [
      {
        name: 'parcels',
        title: 'Parcels',
        geometry_type: 'Polygon',
        feature_count: 12,
        layer_type: 'vector',
        layer_id: 1,
        object_id_field: null,
        kind: 'vector' as const,
      },
      {
        name: 'roads',
        title: 'Roads',
        geometry_type: 'LineString',
        feature_count: 30,
        layer_type: 'vector',
        layer_id: 2,
        object_id_field: null,
        kind: 'vector' as const,
      },
    ],
  };
}

function makePreviewResponse(
  overrides: Partial<ReuploadPreviewResponse> = {},
): ReuploadPreviewResponse {
  return {
    job_id: 'job-1',
    source_filename: 'roads.geojson',
    columns: [{ name: 'name', type: 'text' }],
    crs: 4326,
    geometry_type: 'LineString',
    feature_count: 42,
    sample_rows: [{ name: 'Main St' }],
    layer_name: 'roads',
    schema_diff: {
      columns_added: [],
      columns_removed: [],
      type_changes: [],
      row_count_old: 40,
      row_count_new: 42,
      row_count_delta: 2,
    },
    // GPKG-01 Phase 1058: default single-layer — null means no layer-select step
    all_layers: null,
    previous_source_layer: null,
    ...overrides,
  };
}

function renderDialog() {
  render(
    <ReuploadDialog
      dataset={makeDataset()}
      open
      onOpenChange={vi.fn()}
    />,
  );
}

async function openFileSource(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'File' }));
  expect(screen.getByTestId('reupload-file-dropzone')).toBeInTheDocument();
}

async function dropFile(fileName = 'roads.geojson') {
  const file = new File(['{}'], fileName, { type: 'application/geo+json' });
  await act(async () => {
    if (!dropHandler) {
      throw new Error('drop handler not ready');
    }
    dropHandler([file]);
  });
}

async function openServicePreview(
  user: ReturnType<typeof userEvent.setup>,
  options: { token?: string } = {},
) {
  await user.click(screen.getByRole('button', { name: 'Service URL' }));
  await user.type(
    screen.getByLabelText('Service URL'),
    'https://example.com/wfs',
  );
  if (options.token) {
    await user.type(screen.getByLabelText('Access Token (optional)'), options.token);
  }
  await user.click(screen.getByRole('button', { name: 'Connect' }));
  await screen.findByText('Select a layer');
  await user.click(screen.getByText('Parcels'));
  await user.click(screen.getByRole('button', { name: 'Preview Layer' }));
  await screen.findByRole('button', { name: 'Confirm Re-Upload' });
}

describe('ReuploadDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    dropHandler = null;

    uploadMutateAsync.mockResolvedValue({ job_id: 'file-job' });
    previewMutateAsync.mockResolvedValue(
      makePreviewResponse({ job_id: 'file-job' }),
    );
    servicePreviewMutateAsync.mockResolvedValue(
      makePreviewResponse({
        job_id: 'service-job',
        source_filename: 'Parcels',
        layer_name: 'parcels',
      }),
    );
    commitMutateAsync.mockResolvedValue({
      job_id: 'commit-job',
      status: 'pending',
      message: 'queued',
    });
    mockProbeService.mockResolvedValue(makeProbeResponse());

    mockUseReuploadDataset.mockReturnValue({
      mutateAsync: uploadMutateAsync,
    } as unknown as ReturnType<typeof useReuploadDataset>);
    mockUseReuploadPreview.mockReturnValue({
      mutateAsync: previewMutateAsync,
    } as unknown as ReturnType<typeof useReuploadPreview>);
    mockUseReuploadServicePreview.mockReturnValue({
      mutateAsync: servicePreviewMutateAsync,
    } as unknown as ReturnType<typeof useReuploadServicePreview>);
    mockUseReuploadCommit.mockReturnValue({
      mutateAsync: commitMutateAsync,
    } as unknown as ReturnType<typeof useReuploadCommit>);
    mockUseUploadConfig.mockReturnValue({
      data: {
        presigned_uploads: false,
        presigned_threshold_bytes: 10485760,
        max_file_size_bytes: 524288000,
        allowed_extensions: '.zip,.gpkg,.geojson,.json,.csv,.tif,.tiff,.xlsx,.xls',
      },
    } as unknown as ReturnType<typeof useUploadConfig>);
    mockUseJobStatus.mockReturnValue({
      data: null,
    } as unknown as ReturnType<typeof useJobStatus>);
  });

  it('renders source selector and allows switching between service and file sources', async () => {
    const user = userEvent.setup();
    renderDialog();

    expect(screen.getByTestId('reupload-source-selector')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Service URL' }));
    expect(screen.getByLabelText('Service URL')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByTestId('reupload-source-selector')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'File' }));
    expect(screen.getByTestId('reupload-file-dropzone')).toBeInTheDocument();
  });

  it('moves through service probe and layer selection into schema diff preview', async () => {
    const user = userEvent.setup();
    renderDialog();

    await openServicePreview(user);

    expect(servicePreviewMutateAsync).toHaveBeenCalledWith({
      datasetId: 'dataset-1',
      request: expect.objectContaining({
        url: 'https://example.com/wfs',
        service_type: 'WFS',
        layer_name: 'parcels',
      }),
    });
    expect(screen.getByRole('button', { name: 'Confirm Re-Upload' })).toBeInTheDocument();
  });

  it('sends no commit token for file-source re-upload', async () => {
    const user = userEvent.setup();
    renderDialog();

    await openFileSource(user);
    await dropFile();
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });

    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    await waitFor(() => {
      expect(commitMutateAsync).toHaveBeenCalled();
    });
    const payload = commitMutateAsync.mock.calls[0][0];
    expect(payload.datasetId).toBe('dataset-1');
    expect(payload.jobId).toBe('file-job');
    expect(payload.token).toBeUndefined();
  });

  it('includes service token in commit payload when provided', async () => {
    const user = userEvent.setup();
    renderDialog();

    await openServicePreview(user, { token: 'secret-token' });
    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    await waitFor(() => {
      expect(commitMutateAsync).toHaveBeenCalled();
    });
    const payload = commitMutateAsync.mock.calls[0][0];
    expect(payload.datasetId).toBe('dataset-1');
    expect(payload.jobId).toBe('service-job');
    expect(payload.token).toBe('secret-token');
  });

  it('omits service token in commit payload when not provided', async () => {
    const user = userEvent.setup();
    renderDialog();

    await openServicePreview(user);
    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    await waitFor(() => {
      expect(commitMutateAsync).toHaveBeenCalled();
    });
    const payload = commitMutateAsync.mock.calls[0][0];
    expect(payload.token).toBeUndefined();
  });

  it('shows schema warning copy for file-source previews with destructive changes', async () => {
    const user = userEvent.setup();
    previewMutateAsync.mockResolvedValueOnce(
      makePreviewResponse({
        schema_diff: {
          columns_added: [],
          columns_removed: [{ name: 'legacy_col', type: 'text' }],
          type_changes: [],
          row_count_old: 40,
          row_count_new: 42,
          row_count_delta: 2,
        },
      }),
    );
    renderDialog();

    await openFileSource(user);
    await dropFile();
    await screen.findByText(
      'Warning: This re-upload includes schema changes that may affect existing queries.',
    );
  });

  it('pre-fills service URL from dataset source_url', async () => {
    const user = userEvent.setup();
    const dataset = makeDataset();
    dataset.source_url = 'https://services.arcgis.com/org/arcgis/rest/services/Layer/FeatureServer';

    render(
      <ReuploadDialog
        dataset={dataset}
        open
        onOpenChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Service URL' }));
    const urlInput = screen.getByLabelText('Service URL') as HTMLInputElement;
    expect(urlInput.value).toBe(
      'https://services.arcgis.com/org/arcgis/rest/services/Layer/FeatureServer',
    );
  });

  it('service URL is empty when dataset has no source_url', async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole('button', { name: 'Service URL' }));
    const urlInput = screen.getByLabelText('Service URL') as HTMLInputElement;
    expect(urlInput.value).toBe('');
  });

  it('shows schema warning copy for service-source previews with destructive changes', async () => {
    const user = userEvent.setup();
    servicePreviewMutateAsync.mockResolvedValueOnce(
      makePreviewResponse({
        job_id: 'service-warning-job',
        layer_name: 'parcels',
        source_filename: 'Parcels',
        schema_diff: {
          columns_added: [],
          columns_removed: [],
          type_changes: [
            { name: 'parcel_id', old_type: 'integer', new_type: 'text' },
          ],
          row_count_old: 10,
          row_count_new: 10,
          row_count_delta: 0,
        },
      }),
    );
    renderDialog();

    await openServicePreview(user);
    expect(
      screen.getByText(
        'Warning: This re-upload includes schema changes that may affect existing queries.',
      ),
    ).toBeInTheDocument();
  });

  // GPKG-02 Phase 1058: guard — service URL preview still uses service layer name, not file-path layer
  it('service URL preview Layer: line uses service layer name (not file-path layer)', async () => {
    const user = userEvent.setup();
    servicePreviewMutateAsync.mockResolvedValueOnce(
      makePreviewResponse({
        job_id: 'service-job',
        layer_name: 'parcels',
        source_filename: 'Parcels',
      }),
    );
    renderDialog();

    await openServicePreview(user);

    // The preview pane should show "Layer:" followed by the service layer name ('Parcels')
    expect(screen.getByText(/Layer:/)).toBeInTheDocument();
    // The service layer humanized name "Parcels" (from probeResult layer title) should be visible
    expect(screen.getByText('Parcels')).toBeInTheDocument();
    // There should be NO "File:" header line in service-URL preview
    expect(screen.queryByText(/^File:/)).not.toBeInTheDocument();
  });
});

// GPKG-01 Phase 1058: multi-layer file path tests
describe('ReuploadDialog file path multi-layer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    dropHandler = null;

    uploadMutateAsync.mockResolvedValue({ job_id: 'file-job' });
    // Default: single-layer response (null all_layers) — existing tests unaffected
    previewMutateAsync.mockResolvedValue(
      makePreviewResponse({ job_id: 'file-job', all_layers: null }),
    );
    commitMutateAsync.mockResolvedValue({
      job_id: 'commit-job',
      status: 'pending',
      message: 'queued',
    });

    mockUseReuploadDataset.mockReturnValue({
      mutateAsync: uploadMutateAsync,
    } as unknown as ReturnType<typeof useReuploadDataset>);
    mockUseReuploadPreview.mockReturnValue({
      mutateAsync: previewMutateAsync,
    } as unknown as ReturnType<typeof useReuploadPreview>);
    mockUseReuploadServicePreview.mockReturnValue({
      mutateAsync: servicePreviewMutateAsync,
    } as unknown as ReturnType<typeof useReuploadServicePreview>);
    mockUseReuploadCommit.mockReturnValue({
      mutateAsync: commitMutateAsync,
    } as unknown as ReturnType<typeof useReuploadCommit>);
    mockUseUploadConfig.mockReturnValue({
      data: {
        presigned_uploads: false,
        presigned_threshold_bytes: 10485760,
        max_file_size_bytes: 524288000,
        allowed_extensions: '.zip,.gpkg,.geojson,.json,.csv,.tif,.tiff,.xlsx,.xls',
      },
    } as unknown as ReturnType<typeof useUploadConfig>);
    mockUseJobStatus.mockReturnValue({
      data: null,
    } as unknown as ReturnType<typeof useJobStatus>);
  });

  it('skips selecting-file-layer step for single-layer files', async () => {
    const user = userEvent.setup();
    // all_layers: null → skip the layer-select step
    previewMutateAsync.mockResolvedValue(
      makePreviewResponse({ job_id: 'file-job', all_layers: null }),
    );
    renderDialog();

    await user.click(screen.getByRole('button', { name: 'File' }));
    await dropFile();

    // Should land directly at preview step (Confirm Re-Upload visible, no layer table)
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });
    expect(screen.queryByTestId('reupload-file-layer-select')).not.toBeInTheDocument();
  });

  it('shows selecting-file-layer step when all_layers has multiple entries', async () => {
    const user = userEvent.setup();
    previewMutateAsync.mockResolvedValueOnce(
      makePreviewResponse({
        job_id: 'file-job',
        all_layers: [
          { name: 'buildings', feature_count: 10, field_count: 2 },
          { name: 'addresses', feature_count: 5, field_count: 3 },
        ],
        previous_source_layer: null,
      }),
    );
    renderDialog();

    await user.click(screen.getByRole('button', { name: 'File' }));
    await dropFile('multi.gpkg');

    // Layer-select step should be visible
    await screen.findByTestId('reupload-file-layer-select');
    expect(screen.getByText('buildings')).toBeInTheDocument();
    expect(screen.getByText('addresses')).toBeInTheDocument();
  });

  it('pre-selects previous_source_layer when present in all_layers', async () => {
    const user = userEvent.setup();
    // First preview call (initial upload) → shows layer-select
    previewMutateAsync.mockResolvedValueOnce(
      makePreviewResponse({
        job_id: 'file-job',
        all_layers: [
          { name: 'buildings', feature_count: 10, field_count: 2 },
          { name: 'addresses', feature_count: 5, field_count: 3 },
        ],
        previous_source_layer: 'buildings',
      }),
    );
    // Second preview call (after clicking Preview Layer) → returns normal preview
    previewMutateAsync.mockResolvedValueOnce(
      makePreviewResponse({ job_id: 'file-job', layer_name: 'buildings' }),
    );
    renderDialog();

    await user.click(screen.getByRole('button', { name: 'File' }));
    await dropFile('multi.gpkg');
    await screen.findByTestId('reupload-file-layer-select');

    // Preview button should be enabled (buildings was pre-selected)
    const previewBtn = screen.getByRole('button', { name: 'Preview Layer' });
    expect(previewBtn).not.toBeDisabled();

    // Click Preview — triggers second previewMutateAsync call with layerName
    await user.click(previewBtn);
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });

    // Assert second call included layerName: 'buildings'
    const secondCall = previewMutateAsync.mock.calls[1][0];
    expect(secondCall.layerName).toBe('buildings');
  });

  it('warns and forces explicit selection when previous_source_layer is missing from new file', async () => {
    const user = userEvent.setup();
    previewMutateAsync.mockResolvedValueOnce(
      makePreviewResponse({
        job_id: 'file-job',
        all_layers: [
          { name: 'addresses', feature_count: 5, field_count: 3 },
        ],
        previous_source_layer: 'buildings',
      }),
    );
    previewMutateAsync.mockResolvedValueOnce(
      makePreviewResponse({ job_id: 'file-job', layer_name: 'addresses' }),
    );
    renderDialog();

    await user.click(screen.getByRole('button', { name: 'File' }));
    await dropFile('multi.gpkg');
    await screen.findByTestId('reupload-file-layer-select');

    // Warning message should be visible
    expect(screen.getByText(/buildings/)).toBeInTheDocument();

    // Preview button initially disabled (no layer selected — buildings is missing)
    const previewBtn = screen.getByRole('button', { name: 'Preview Layer' });
    expect(previewBtn).toBeDisabled();

    // Click the addresses row to select it
    await user.click(screen.getByText('addresses'));

    // Preview button should now be enabled
    expect(previewBtn).not.toBeDisabled();

    // Click Preview
    await user.click(previewBtn);
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });

    // Second call must include layerName: 'addresses'
    const secondCall = previewMutateAsync.mock.calls[1][0];
    expect(secondCall.layerName).toBe('addresses');
  });

  it('plumbs selected layer through commit', async () => {
    const user = userEvent.setup();
    previewMutateAsync.mockResolvedValueOnce(
      makePreviewResponse({
        job_id: 'file-job',
        all_layers: [
          { name: 'buildings', feature_count: 10, field_count: 2 },
          { name: 'addresses', feature_count: 5, field_count: 3 },
        ],
        previous_source_layer: 'buildings',
      }),
    );
    previewMutateAsync.mockResolvedValueOnce(
      makePreviewResponse({ job_id: 'file-job', layer_name: 'buildings' }),
    );
    renderDialog();

    await user.click(screen.getByRole('button', { name: 'File' }));
    await dropFile('multi.gpkg');
    await screen.findByTestId('reupload-file-layer-select');

    // Click Preview (buildings pre-selected)
    await user.click(screen.getByRole('button', { name: 'Preview Layer' }));
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });

    // Click Confirm
    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    await waitFor(() => {
      expect(commitMutateAsync).toHaveBeenCalled();
    });
    const commitCall = commitMutateAsync.mock.calls[0][0];
    expect(commitCall.layerName).toBe('buildings');
  });

  // GPKG-02 Phase 1058: preview pane parity tests
  it('renders Layer line in preview when selectedFileLayer is set', async () => {
    const user = userEvent.setup();
    // First preview: multi-layer, triggers selecting-file-layer step
    previewMutateAsync.mockResolvedValueOnce(
      makePreviewResponse({
        job_id: 'file-job',
        all_layers: [
          { name: 'buildings', feature_count: 10, field_count: 2 },
          { name: 'addresses', feature_count: 5, field_count: 3 },
        ],
        previous_source_layer: 'buildings',
      }),
    );
    // Second preview: after layer selection
    previewMutateAsync.mockResolvedValueOnce(
      makePreviewResponse({ job_id: 'file-job', layer_name: 'buildings' }),
    );
    renderDialog();

    await user.click(screen.getByRole('button', { name: 'File' }));
    await dropFile('multi.gpkg');
    await screen.findByTestId('reupload-file-layer-select');

    // Click Preview (buildings pre-selected)
    await user.click(screen.getByRole('button', { name: 'Preview Layer' }));
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });

    // Both File: and Layer: lines should be visible, Layer: showing 'buildings'
    expect(screen.getByText(/File:/)).toBeInTheDocument();
    const layerElements = screen.getAllByText(/Layer:/);
    expect(layerElements.length).toBeGreaterThan(0);
    expect(screen.getByText('buildings')).toBeInTheDocument();
  });

  it('does NOT render Layer line for single-layer file', async () => {
    const user = userEvent.setup();
    // Single-layer: all_layers: null — skips selecting-file-layer step, selectedFileLayer stays null
    previewMutateAsync.mockResolvedValue(
      makePreviewResponse({ job_id: 'file-job', all_layers: null, layer_name: 'parcels' }),
    );
    renderDialog();

    await user.click(screen.getByRole('button', { name: 'File' }));
    await dropFile('single.geojson');
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });

    // File: line should exist; no standalone Layer: prefix in the preview header
    expect(screen.getByText(/File:/)).toBeInTheDocument();
    // The preview header should NOT show a Layer: line — only one <p> with File:
    // queryByText with regex that matches only the label "Layer:" (not inside layer table header)
    // Service layer table is not rendered here so this checks preview header only
    const layerLabels = screen.queryAllByText('Layer:');
    expect(layerLabels).toHaveLength(0);
  });

  it('renders schema-change advisory banner when columns_added or columns_removed is non-empty', async () => {
    const user = userEvent.setup();
    previewMutateAsync.mockResolvedValueOnce(
      makePreviewResponse({
        job_id: 'file-job',
        all_layers: [
          { name: 'buildings', feature_count: 10, field_count: 2 },
          { name: 'addresses', feature_count: 5, field_count: 3 },
        ],
        previous_source_layer: 'buildings',
      }),
    );
    // Second preview: schema diff has adds and removes
    previewMutateAsync.mockResolvedValueOnce(
      makePreviewResponse({
        job_id: 'file-job',
        layer_name: 'buildings',
        schema_diff: {
          columns_added: [{ name: 'foo', type: 'text' }],
          columns_removed: [{ name: 'bar', type: 'integer' }],
          type_changes: [],
          row_count_old: 40,
          row_count_new: 42,
          row_count_delta: 2,
        },
      }),
    );
    renderDialog();

    await user.click(screen.getByRole('button', { name: 'File' }));
    await dropFile('multi.gpkg');
    await screen.findByTestId('reupload-file-layer-select');

    await user.click(screen.getByRole('button', { name: 'Preview Layer' }));
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });

    // Advisory banner should be visible with the column counts
    expect(screen.getByTestId('schema-change-advisory')).toBeInTheDocument();
    expect(screen.getByText(/1 columns added, 1 removed/)).toBeInTheDocument();
  });

  it('does NOT render schema-change advisory when columns are identical', async () => {
    const user = userEvent.setup();
    previewMutateAsync.mockResolvedValueOnce(
      makePreviewResponse({
        job_id: 'file-job',
        all_layers: [
          { name: 'buildings', feature_count: 10, field_count: 2 },
          { name: 'addresses', feature_count: 5, field_count: 3 },
        ],
        previous_source_layer: 'buildings',
      }),
    );
    // Second preview: no column changes
    previewMutateAsync.mockResolvedValueOnce(
      makePreviewResponse({
        job_id: 'file-job',
        layer_name: 'buildings',
        schema_diff: {
          columns_added: [],
          columns_removed: [],
          type_changes: [],
          row_count_old: 40,
          row_count_new: 42,
          row_count_delta: 2,
        },
      }),
    );
    renderDialog();

    await user.click(screen.getByRole('button', { name: 'File' }));
    await dropFile('multi.gpkg');
    await screen.findByTestId('reupload-file-layer-select');

    await user.click(screen.getByRole('button', { name: 'Preview Layer' }));
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });

    // Advisory banner should NOT be rendered
    expect(screen.queryByTestId('schema-change-advisory')).not.toBeInTheDocument();
  });
});
