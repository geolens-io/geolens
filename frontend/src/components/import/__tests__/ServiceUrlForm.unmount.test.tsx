/**
 * fix(#1712): a Service-tab import must survive the form unmounting.
 *
 * The Import page renders tabs conditionally, so switching away mid-preview
 * or mid-commit unmounts ServiceUrlForm. The request keeps running
 * server-side (previewServiceLayer stages a `pending` IngestJob regardless),
 * so if the job id lands in dead component state the user is left with an
 * unreachable pending job until the stale-pending sweep collects it.
 *
 * Mirrors UrlImportForm.unmount.test.tsx (#1708) for the module-scoped
 * session this lane adds, `service-url-session.ts`.
 */
import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { ServiceUrlForm } from '../ServiceUrlForm';
import { clearServiceImport, peekServiceImport } from '@/api/service-url-session';
import type { ProbeResponse } from '@/types/api';

const mockProbeService = vi.fn();
const mockPreviewServiceLayer = vi.fn();
const mockCommitImport = vi.fn();
const mockArcgisSignin = vi.fn();

vi.mock('@/api/ingest', () => ({
  probeService: (...args: unknown[]) => mockProbeService(...args),
  previewServiceLayer: (...args: unknown[]) => mockPreviewServiceLayer(...args),
  commitImport: (...args: unknown[]) => mockCommitImport(...args),
  arcgisSignin: (...args: unknown[]) => mockArcgisSignin(...args),
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
  ImportMetadataForm: ({ onCommit }: { onCommit: (metadata: { title: string }) => void }) => (
    <div data-testid="import-metadata-form">
      <button onClick={() => onCommit({ title: 'test-dataset' })}>Commit (test)</button>
    </div>
  ),
}));

vi.mock('../JobProgress', () => ({
  JobProgress: ({ jobId }: { jobId: string }) => (
    <div data-testid="job-progress">{jobId}</div>
  ),
}));

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
});

beforeEach(() => {
  vi.clearAllMocks();
  clearServiceImport();
});

afterEach(() => {
  clearServiceImport();
});

const WFS_PROBE: ProbeResponse = {
  service_type: 'WFS 2.0',
  url: 'https://example.test/wfs',
  selected_layer_id: null,
  layers: [
    {
      name: 'roads',
      title: 'Roads',
      geometry_type: 'LineString',
      feature_count: 10,
      layer_type: 'layer',
      layer_id: null,
      object_id_field: null,
      kind: 'vector',
    },
  ],
};

const VECTOR_PREVIEW = {
  job_id: 'job-survives',
  source_filename: null,
  columns: [{ name: 'id', type: 'Integer' }],
  crs: 4326,
  geometry_type: 'LineString',
  feature_count: 10,
  sample_rows: [],
  layer_name: 'roads',
};

/** Probe a WFS URL and click through to the layer-select step. */
async function connectToWfsService(user: ReturnType<typeof userEvent.setup>) {
  const view = render(<ServiceUrlForm />);
  mockProbeService.mockResolvedValue(WFS_PROBE);
  await user.type(screen.getByPlaceholderText('serviceUrl.placeholder'), 'https://example.test/wfs');
  await user.click(screen.getByRole('button', { name: 'Probe →' }));
  await screen.findByText('Roads');
  return view;
}

describe('ServiceUrlForm unmount survival (#1712)', () => {
  test('a preview job id returned while unmounted is captured and resumed on remount', async () => {
    const user = userEvent.setup();
    const view = await connectToWfsService(user);

    let resolvePreview!: (v: typeof VECTOR_PREVIEW) => void;
    mockPreviewServiceLayer.mockReturnValue(
      new Promise((resolve) => {
        resolvePreview = resolve;
      }),
    );

    await user.click(screen.getByRole('button', { name: /Roads/i }));
    await waitFor(() => expect(mockPreviewServiceLayer).toHaveBeenCalledTimes(1));

    // Switch tabs: the Import page unmounts the form.
    view.unmount();

    // The server answers only after the form is gone.
    resolvePreview(VECTOR_PREVIEW);
    await waitFor(() => expect(peekServiceImport()?.jobId).toBe('job-survives'));

    // Coming back re-attaches to the same preview instead of stranding it,
    // and does NOT re-probe or re-preview (which would strand the first
    // job AND stage a duplicate).
    render(<ServiceUrlForm />);
    await waitFor(() => expect(screen.getByTestId('import-preview')).toBeInTheDocument());
    expect(mockPreviewServiceLayer).toHaveBeenCalledTimes(1);
    expect(mockProbeService).toHaveBeenCalledTimes(1);
  });

  test('a remount while the preview is still in flight adopts it, not a new one', async () => {
    const user = userEvent.setup();
    const view = await connectToWfsService(user);

    mockPreviewServiceLayer.mockReturnValue(new Promise(() => {}));
    await user.click(screen.getByRole('button', { name: /Roads/i }));
    await waitFor(() => expect(mockPreviewServiceLayer).toHaveBeenCalledTimes(1));

    view.unmount();
    render(<ServiceUrlForm />);

    // Still exactly one server-side preview, and the remounted form shows
    // the in-flight state rather than the idle URL form.
    expect(mockPreviewServiceLayer).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.getByText('serviceUrl.loadingPreview')).toBeInTheDocument(),
    );
  });

  test('unmounting mid-commit resumes into tracking, not a blank form', async () => {
    const user = userEvent.setup();
    const view = await connectToWfsService(user);

    mockPreviewServiceLayer.mockResolvedValue(VECTOR_PREVIEW);
    await user.click(screen.getByRole('button', { name: /Roads/i }));
    await waitFor(() => expect(screen.getByTestId('import-metadata-form')).toBeInTheDocument());

    let resolveCommit!: (v: unknown) => void;
    mockCommitImport.mockReturnValue(
      new Promise((resolve) => {
        resolveCommit = resolve;
      }),
    );
    await user.click(screen.getByRole('button', { name: 'Commit (test)' }));
    await waitFor(() => expect(mockCommitImport).toHaveBeenCalledTimes(1));

    // The user switches tabs while the commit is still in flight, and
    // comes back BEFORE it settles.
    view.unmount();
    expect(peekServiceImport()?.commit).not.toBeNull();
    render(<ServiceUrlForm />);
    resolveCommit({ job_id: 'job-survives', status: 'queued', message: 'ok' });
    await waitFor(() =>
      expect(screen.getByTestId('job-progress')).toHaveTextContent('job-survives'),
    );
    // ...without re-previewing and without committing a second time.
    expect(mockCommitImport).toHaveBeenCalledTimes(1);
    expect(mockPreviewServiceLayer).toHaveBeenCalledTimes(1);
  });

  test('a commit that fails while unmounted leaves the job previewable again', async () => {
    const user = userEvent.setup();
    const view = await connectToWfsService(user);

    mockPreviewServiceLayer.mockResolvedValue(VECTOR_PREVIEW);
    await user.click(screen.getByRole('button', { name: /Roads/i }));
    await waitFor(() => expect(screen.getByTestId('import-metadata-form')).toBeInTheDocument());

    let rejectCommit!: (e: unknown) => void;
    mockCommitImport.mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectCommit = reject;
      }),
    );
    await user.click(screen.getByRole('button', { name: 'Commit (test)' }));
    await waitFor(() => expect(mockCommitImport).toHaveBeenCalledTimes(1));

    // Remount FIRST, while the commit is still in flight, then let it fail.
    view.unmount();
    render(<ServiceUrlForm />);
    rejectCommit(new Error('commit boom'));

    // The subscriber learns the real outcome: back to review, with the job
    // still previewable (from the session's retained preview data, no
    // re-fetch), instead of a dead committing spinner.
    await waitFor(() => expect(screen.getByTestId('import-preview')).toBeInTheDocument());
    expect(screen.queryByTestId('job-progress')).not.toBeInTheDocument();
    expect(mockPreviewServiceLayer).toHaveBeenCalledTimes(1);
    expect(mockCommitImport).toHaveBeenCalledTimes(1);
  });
});
