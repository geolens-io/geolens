import { act, render as rtlRender, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@/test/test-utils';
import {
  useReuploadDataset,
  useReuploadPreview,
  useReuploadServicePreview,
  useReuploadCommit,
} from '@/components/dataset/hooks/use-dataset';
import { useJobStatus, useUploadConfig } from '@/components/import/hooks/use-ingest';
import { probeService } from '@/api/ingest';
import { ApiError } from '@/api/client';
import { queryKeys } from '@/lib/query-keys';
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
    attribution: null,
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

// #1289: raster reupload fixture — upload -> commit, no schema preview.
function makeRasterDataset(): DatasetResponse {
  return {
    ...makeDataset(),
    id: 'dataset-raster-1',
    table_name: 'ortho',
    title: 'Orthophoto',
    source_format: 'GeoTIFF',
    source_filename: 'ortho.tif',
    record_type: 'raster_dataset',
    raster: {
      tile_url: '/raster-tiles/dataset-raster-1/{z}/{x}/{y}.png',
    } as DatasetResponse['raster'],
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

function renderRasterDialog() {
  render(
    <ReuploadDialog
      dataset={makeRasterDataset()}
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

  // fix(#1746): this is a request-only service token, not a login credential,
  // so it must opt every password manager out explicitly.
  it('opts every password manager out of the service token field', async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole('button', { name: 'Service URL' }));

    const input = screen.getByLabelText('Access Token (optional)');
    expect(input).toHaveAttribute('type', 'password');
    expect(input).toHaveAttribute('autocomplete', 'new-password');
    expect(input).toHaveAttribute('data-1p-ignore');
    expect(input).toHaveAttribute('data-lpignore', 'true');
    expect(input).toHaveAttribute('data-bwignore');
  });

  it('advertises only formats supported by vector and table reupload', async () => {
    const user = userEvent.setup();
    renderDialog();

    await openFileSource(user);

    expect(screen.getByText('.geojson')).toBeInTheDocument();
    expect(screen.queryByText('.tif')).not.toBeInTheDocument();
    expect(screen.queryByText('.tiff')).not.toBeInTheDocument();
    expect(screen.queryByText('.vrt')).not.toBeInTheDocument();
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

  // fix(#1768): the commit carries the origin the dialog SAW when it staged
  // the replacement, so the server can refuse a dataset rebound mid-flow
  // instead of severing the new binding on the swap.
  it('sends the origin it saw with a file-source commit', async () => {
    const user = userEvent.setup();
    render(
      <ReuploadDialog
        dataset={{ ...makeDataset(), origin: 'upload' }}
        open
        onOpenChange={vi.fn()}
      />,
    );

    await openFileSource(user);
    await dropFile();
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });
    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    await waitFor(() => {
      expect(commitMutateAsync).toHaveBeenCalled();
    });
    expect(commitMutateAsync.mock.calls[0][0].expectedOriginKind).toBe('upload');
  });

  it('sends the origin it saw with a service-source commit', async () => {
    const user = userEvent.setup();
    render(
      <ReuploadDialog
        dataset={{ ...makeDataset(), origin: 'service' }}
        open
        onOpenChange={vi.fn()}
      />,
    );

    await openServicePreview(user);
    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    await waitFor(() => {
      expect(commitMutateAsync).toHaveBeenCalled();
    });
    expect(commitMutateAsync.mock.calls[0][0].expectedOriginKind).toBe('service');
  });

  it('asserts no origin when the dataset reports none', async () => {
    const user = userEvent.setup();
    renderDialog();

    await openFileSource(user);
    await dropFile();
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });
    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    await waitFor(() => {
      expect(commitMutateAsync).toHaveBeenCalled();
    });
    expect(commitMutateAsync.mock.calls[0][0].expectedOriginKind).toBeNull();
  });

  it('sends the staged origin, not the origin the live dataset now reports', async () => {
    // The point of the condition: `dataset` is a live query result, so a
    // rebinding that lands mid-flow updates the prop. Reading it at confirm
    // time would send the changed value and always agree with the server,
    // which is exactly the race #1768 is about.
    const user = userEvent.setup();
    const { rerender } = render(
      <ReuploadDialog
        dataset={{ ...makeDataset(), origin: 'upload' }}
        open
        onOpenChange={vi.fn()}
      />,
    );

    await openFileSource(user);
    await dropFile();
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });

    rerender(
      <ReuploadDialog
        dataset={{ ...makeDataset(), origin: 'service' }}
        open
        onOpenChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    await waitFor(() => {
      expect(commitMutateAsync).toHaveBeenCalled();
    });
    expect(commitMutateAsync.mock.calls[0][0].expectedOriginKind).toBe('upload');
  });

  // fix(#1768 round 1): the refusal tells the user to start the replacement
  // again, and `handleRetry` clears the captured origin — but the origin is
  // re-captured from the `dataset` prop, which is served from the cache the
  // server just disagreed with. Without the invalidation the retry re-sends
  // the same stale kind and 409s forever.
  // fix(#1822): "Try Again" stays disabled until the origin refetch lands.
  it('keeps "Try Again" disabled until the origin refetch resolves, then enables it', async () => {
    const user = userEvent.setup();
    commitMutateAsync.mockRejectedValueOnce(
      new ApiError('This dataset’s source changed', 409, {
        code: 'origin_changed',
        origin_kind: 'service',
        expected_origin_kind: 'upload',
      }),
    );

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
    });
    let resolveRefetch: () => void = () => {};
    const refetch = vi.spyOn(queryClient, 'refetchQueries').mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveRefetch = () => resolve(undefined);
        }),
    );

    rtlRender(
      <QueryClientProvider client={queryClient}>
        <ReuploadDialog
          dataset={{ ...makeDataset(), origin: 'upload' }}
          open
          onOpenChange={vi.fn()}
        />
      </QueryClientProvider>,
    );

    await openFileSource(user);
    await dropFile();
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });
    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    const retryButton = await screen.findByTestId('reupload-try-again');
    await waitFor(() => {
      expect(retryButton).toBeDisabled();
    });
    expect(retryButton).toHaveTextContent('Refreshing...');
    expect(refetch).toHaveBeenCalledWith(
      { queryKey: queryKeys.datasets.detail('dataset-1') },
      { throwOnError: true },
    );

    // A click while disabled must not proceed — retrying now would still
    // send the stale prop's origin.
    await user.click(retryButton);
    expect(commitMutateAsync).toHaveBeenCalledTimes(1);

    resolveRefetch();

    await waitFor(() => {
      expect(retryButton).not.toBeDisabled();
    });
    expect(retryButton).toHaveTextContent('Try Again');
  });

  it('shows the refetch error and keeps "Try Again" disabled when the origin refetch fails', async () => {
    const user = userEvent.setup();
    commitMutateAsync.mockRejectedValueOnce(
      new ApiError('This dataset’s source changed', 409, {
        code: 'origin_changed',
        origin_kind: 'service',
        expected_origin_kind: 'upload',
      }),
    );

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
    });
    vi.spyOn(queryClient, 'refetchQueries').mockRejectedValue(new Error('network error'));

    rtlRender(
      <QueryClientProvider client={queryClient}>
        <ReuploadDialog
          dataset={{ ...makeDataset(), origin: 'upload' }}
          open
          onOpenChange={vi.fn()}
        />
      </QueryClientProvider>,
    );

    await openFileSource(user);
    await dropFile();
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });
    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    await screen.findByText(
      "Could not refresh the dataset's info after this conflict. Reload the page and try again.",
    );
    // The original commit error is superseded — retrying is dead either way,
    // and the refetch failure is the one the user needs to act on.
    expect(screen.queryByText('This dataset’s source changed')).not.toBeInTheDocument();

    const retryButton = screen.getByTestId('reupload-try-again');
    expect(retryButton).toBeDisabled();
    expect(retryButton).toHaveTextContent('Try Again');
  });

  it('does not touch the origin refetch or disable "Try Again" for an unrelated commit failure', async () => {
    // The counterfactual's other half: the recovery refetch is keyed on the
    // refusal code, not fired on every commit error.
    const user = userEvent.setup();
    commitMutateAsync.mockRejectedValueOnce(
      new ApiError('A refresh is already running', 409, { code: 'dataset_busy' }),
    );

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
    });
    const refetch = vi.spyOn(queryClient, 'refetchQueries').mockResolvedValue(undefined);

    rtlRender(
      <QueryClientProvider client={queryClient}>
        <ReuploadDialog
          dataset={{ ...makeDataset(), origin: 'upload' }}
          open
          onOpenChange={vi.fn()}
        />
      </QueryClientProvider>,
    );

    await openFileSource(user);
    await dropFile();
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });
    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    await screen.findByText('A refresh is already running');
    const retryButton = screen.getByTestId('reupload-try-again');
    expect(retryButton).not.toBeDisabled();
    expect(retryButton).toHaveTextContent('Try Again');
    expect(refetch).not.toHaveBeenCalled();
  });

  // fix(#1822 review P2): DatasetPage always renders ReuploadDialog and only
  // toggles its `open` prop, so closing it does not unmount the component —
  // a refetch started before the close keeps running after resetState.
  it('ignores a stale refetch completion from before a reset (dialog closed mid-refetch)', async () => {
    const user = userEvent.setup();
    const originChangedError = () =>
      new ApiError('This dataset’s source changed', 409, {
        code: 'origin_changed',
        origin_kind: 'service',
        expected_origin_kind: 'upload',
      });
    commitMutateAsync
      .mockRejectedValueOnce(originChangedError())
      .mockRejectedValueOnce(originChangedError());

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
    });
    let settleFirst: () => void = () => {};
    let settleSecond: () => void = () => {};
    vi.spyOn(queryClient, 'refetchQueries')
      .mockImplementationOnce(
        () =>
          new Promise((_resolve, reject) => {
            settleFirst = () => reject(new Error('cancelled'));
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            settleSecond = () => resolve(undefined);
          }),
      );

    rtlRender(
      <QueryClientProvider client={queryClient}>
        <ReuploadDialog
          dataset={{ ...makeDataset(), origin: 'upload' }}
          open
          onOpenChange={vi.fn()}
        />
      </QueryClientProvider>,
    );

    // First attempt: origin_changed, refetch #1 starts and hangs.
    await openFileSource(user);
    await dropFile();
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });
    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    let retryButton = await screen.findByTestId('reupload-try-again');
    await waitFor(() => expect(retryButton).toBeDisabled());

    // Close while refetch #1 is still in flight.
    await user.click(within(retryButton.parentElement as HTMLElement).getByRole('button', { name: 'Close' }));

    // Re-stage and confirm again: a second origin_changed, a second refetch.
    await openFileSource(user);
    await dropFile();
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });
    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    retryButton = await screen.findByTestId('reupload-try-again');
    await waitFor(() => expect(retryButton).toBeDisabled());

    // Attempt #1 settles late (as a cancellation would) — must be ignored.
    settleFirst();
    await waitFor(() => {
      expect(
        screen.queryByText(
          "Could not refresh the dataset's info after this conflict. Reload the page and try again.",
        ),
      ).not.toBeInTheDocument();
    });
    expect(retryButton).toBeDisabled();

    // Attempt #2 succeeds — it governs the UI.
    settleSecond();
    await waitFor(() => expect(retryButton).not.toBeDisabled());
    expect(retryButton).toHaveTextContent('Try Again');
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

// #1289: raster reupload — upload -> commit, skipping the vector
// schema-preview step (the preview endpoint 400s for raster by design).
describe('ReuploadDialog raster reupload', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    dropHandler = null;

    uploadMutateAsync.mockResolvedValue({ job_id: 'raster-job' });
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

  // codex(#1362 r1): raster has no service path — the backend refuses a
  // raster service-preview outright, so the source selector must not offer it.
  it('shows only the File source option for raster datasets', () => {
    renderRasterDialog();

    expect(screen.getByTestId('reupload-source-selector')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'File' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Service URL' })).not.toBeInTheDocument();
  });

  it('advertises only raster formats for raster reupload', async () => {
    const user = userEvent.setup();
    renderRasterDialog();

    await openFileSource(user);

    // deriveFormatBadges collapses the .tif/.tiff alias pair into one badge.
    expect(screen.getByText('.tif')).toBeInTheDocument();
    expect(screen.queryByText('.tiff')).not.toBeInTheDocument();
    expect(screen.queryByText('.geojson')).not.toBeInTheDocument();
    expect(screen.queryByText('.gpkg')).not.toBeInTheDocument();
    expect(screen.queryByText('.vrt')).not.toBeInTheDocument();
  });

  it('skips the schema-preview call and lands on the confirm gate', async () => {
    const user = userEvent.setup();
    renderRasterDialog();

    await openFileSource(user);
    await dropFile('ortho.tif');

    await screen.findByRole('button', { name: 'Confirm Re-Upload' });

    // The preview endpoint 400s for raster by design — the raster branch
    // must never call it.
    expect(previewMutateAsync).not.toHaveBeenCalled();
    expect(servicePreviewMutateAsync).not.toHaveBeenCalled();
    // No schema diff to show for raster.
    expect(screen.queryByTestId('schema-change-advisory')).not.toBeInTheDocument();
    expect(screen.getByTestId('raster-preview-note')).toBeInTheDocument();
    expect(screen.getByText(/ortho\.tif/)).toBeInTheDocument();
  });

  it('commits using the uploaded job id when confirmed', async () => {
    const user = userEvent.setup();
    renderRasterDialog();

    await openFileSource(user);
    await dropFile('ortho.tif');
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });

    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    await waitFor(() => {
      expect(commitMutateAsync).toHaveBeenCalled();
    });
    const payload = commitMutateAsync.mock.calls[0][0];
    expect(payload.datasetId).toBe('dataset-raster-1');
    expect(payload.jobId).toBe('raster-job');
    expect(payload.token).toBeUndefined();
    expect(payload.layerName).toBeUndefined();
  });

  it('shows COG-conversion progress copy while tracking the background job', async () => {
    const user = userEvent.setup();
    mockUseJobStatus.mockReturnValue({
      data: { status: 'pending' },
    } as unknown as ReturnType<typeof useJobStatus>);
    renderRasterDialog();

    await openFileSource(user);
    await dropFile('ortho.tif');
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });
    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    await screen.findByText('Converting to Cloud Optimized GeoTIFF...');
    expect(
      screen.getByText(/This can take a few minutes/),
    ).toBeInTheDocument();
  });

  // codex(#1362 r1): the raster hero map's MapLibre source is added once and
  // never re-added on prop change (the tile URL is a fixed per-dataset route,
  // not content-versioned), so the caller needs an explicit signal to remount
  // it once the replacement job completes.
  it('calls onReplaceComplete once the replacement job completes', async () => {
    const user = userEvent.setup();
    const onReplaceComplete = vi.fn();
    mockUseJobStatus.mockReturnValue({
      data: { status: 'complete' },
    } as unknown as ReturnType<typeof useJobStatus>);

    render(
      <ReuploadDialog
        dataset={makeRasterDataset()}
        open
        onOpenChange={vi.fn()}
        onReplaceComplete={onReplaceComplete}
      />,
    );

    await openFileSource(user);
    await dropFile('ortho.tif');
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });
    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    await waitFor(() => {
      expect(onReplaceComplete).toHaveBeenCalledTimes(1);
    });
  });

  it('does not call onReplaceComplete while the job is still pending', async () => {
    const user = userEvent.setup();
    const onReplaceComplete = vi.fn();
    mockUseJobStatus.mockReturnValue({
      data: { status: 'pending' },
    } as unknown as ReturnType<typeof useJobStatus>);

    render(
      <ReuploadDialog
        dataset={makeRasterDataset()}
        open
        onOpenChange={vi.fn()}
        onReplaceComplete={onReplaceComplete}
      />,
    );

    await openFileSource(user);
    await dropFile('ortho.tif');
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });
    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    await screen.findByText('Converting to Cloud Optimized GeoTIFF...');
    expect(onReplaceComplete).not.toHaveBeenCalled();
  });

  // codex(#1362 r2): invalidateQueries only SCHEDULES a refetch — firing
  // onReplaceComplete without waiting for it raced the remount against the
  // still-in-flight dataset-detail refetch, so a replacement with a
  // different extent could remount using the OLD bbox. Uses a real
  // QueryClient (spied, not mocked away) so the fix's actual await matters.
  it('waits for the dataset invalidation to settle before firing onReplaceComplete', async () => {
    const user = userEvent.setup();
    const onReplaceComplete = vi.fn();
    mockUseJobStatus.mockReturnValue({
      data: { status: 'complete' },
    } as unknown as ReturnType<typeof useJobStatus>);

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
    });
    const pendingResolvers: Array<() => void> = [];
    vi.spyOn(queryClient, 'invalidateQueries').mockImplementation(
      () => new Promise<void>((resolve) => { pendingResolvers.push(resolve); }),
    );

    rtlRender(
      <QueryClientProvider client={queryClient}>
        <ReuploadDialog
          dataset={makeRasterDataset()}
          open
          onOpenChange={vi.fn()}
          onReplaceComplete={onReplaceComplete}
        />
      </QueryClientProvider>,
    );

    await openFileSource(user);
    await dropFile('ortho.tif');
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });
    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    // The invalidations were kicked off but left deliberately unresolved —
    // onReplaceComplete (and the 'complete' step transition) must not have
    // fired yet.
    await waitFor(() => {
      expect(pendingResolvers.length).toBeGreaterThan(0);
    });
    expect(onReplaceComplete).not.toHaveBeenCalled();
    expect(screen.queryByText('Re-upload complete!')).not.toBeInTheDocument();

    // Now let the invalidations settle.
    await act(async () => {
      pendingResolvers.forEach((resolve) => resolve());
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(onReplaceComplete).toHaveBeenCalledTimes(1);
    });
  });

  // codex(#1362 r3): the await above leaves the completion continuation in
  // flight across renders — closing the dialog before it settles must not
  // let it apply setStep('complete')/onReplaceComplete on top of the reset
  // state (or, worse, on top of a second reupload started in the meantime).
  it('ignores a stale completion once the dialog resets mid-invalidation', async () => {
    const user = userEvent.setup();
    const onReplaceComplete = vi.fn();
    mockUseJobStatus.mockReturnValue({
      data: { status: 'complete' },
    } as unknown as ReturnType<typeof useJobStatus>);

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
    });
    const pendingResolvers: Array<() => void> = [];
    vi.spyOn(queryClient, 'invalidateQueries').mockImplementation(
      () => new Promise<void>((resolve) => { pendingResolvers.push(resolve); }),
    );

    rtlRender(
      <QueryClientProvider client={queryClient}>
        <ReuploadDialog
          dataset={makeRasterDataset()}
          open
          onOpenChange={vi.fn()}
          onReplaceComplete={onReplaceComplete}
        />
      </QueryClientProvider>,
    );

    await openFileSource(user);
    await dropFile('ortho.tif');
    await screen.findByRole('button', { name: 'Confirm Re-Upload' });
    await user.click(screen.getByRole('button', { name: 'Confirm Re-Upload' }));

    await waitFor(() => {
      expect(pendingResolvers.length).toBeGreaterThan(0);
    });

    // User closes the dialog (its own X button) while the invalidation is
    // still in flight — this resets `step` out from under the pending run.
    await user.click(screen.getByRole('button', { name: 'Close' }));
    await screen.findByTestId('reupload-source-selector');

    // Let the stale invalidation settle now.
    await act(async () => {
      pendingResolvers.forEach((resolve) => resolve());
      await Promise.resolve();
    });

    expect(onReplaceComplete).not.toHaveBeenCalled();
    expect(screen.queryByText('Re-upload complete!')).not.toBeInTheDocument();
    // Reset really did win: still on the reset source-selector screen.
    expect(screen.getByTestId('reupload-source-selector')).toBeInTheDocument();
  });
});
