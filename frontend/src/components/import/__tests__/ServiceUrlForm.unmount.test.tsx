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
import { render, screen, waitFor, act } from '@/test/test-utils';
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

  // fix(#1834 round 1 P2): a remount used to restore only `previewData` —
  // `url`, the credential method, and its fields all came back at
  // component defaults, so a resumed review's eventual `handleCommit`
  // rebuilt `auth` from EMPTY state and the recovered import failed
  // against a protected service. Pins that a Basic credential entered
  // before the preview survives an unmount and reaches the SAME commit
  // request after remounting.
  test('a resumed session after a Basic-auth preview still sends the same auth on commit', async () => {
    const user = userEvent.setup();
    const view = render(<ServiceUrlForm />);
    mockProbeService.mockResolvedValue(WFS_PROBE);

    await user.type(screen.getByPlaceholderText('serviceUrl.placeholder'), 'https://example.test/wfs');
    await user.click(screen.getByRole('combobox', { name: 'Authentication' }));
    await user.click(await screen.findByRole('option', { name: 'Username and password' }));
    await user.type(screen.getByLabelText('Username', { exact: true }), 'alice');
    await user.type(screen.getByLabelText('Password', { exact: true }), 'hunter2');
    await user.click(screen.getByRole('button', { name: 'Probe →' }));
    await screen.findByText('Roads');

    let resolvePreview!: (v: typeof VECTOR_PREVIEW) => void;
    mockPreviewServiceLayer.mockReturnValue(
      new Promise((resolve) => {
        resolvePreview = resolve;
      }),
    );
    await user.click(screen.getByRole('button', { name: /Roads/i }));
    await waitFor(() => expect(mockPreviewServiceLayer).toHaveBeenCalledTimes(1));
    expect(mockPreviewServiceLayer).toHaveBeenCalledWith(
      expect.objectContaining({
        auth: { method: 'basic', username: 'alice', password: 'hunter2' },
      }),
    );

    // Switch tabs before the preview even settles.
    view.unmount();
    resolvePreview(VECTOR_PREVIEW);
    await waitFor(() => expect(peekServiceImport()?.status).toBe('fulfilled'));

    // Coming back reaches the metadata form directly (the resumed review),
    // with no memory of the credential visible in any form field — the
    // fix is that `handleCommit` still has it internally.
    render(<ServiceUrlForm />);
    await waitFor(() => expect(screen.getByTestId('import-metadata-form')).toBeInTheDocument());

    mockCommitImport.mockResolvedValue({ job_id: 'job-survives', status: 'queued', message: 'ok' });
    await user.click(screen.getByRole('button', { name: 'Commit (test)' }));

    await waitFor(() => expect(mockCommitImport).toHaveBeenCalledTimes(1));
    expect(mockCommitImport).toHaveBeenCalledWith(
      'job-survives',
      expect.objectContaining({
        auth: { method: 'basic', username: 'alice', password: 'hunter2' },
      }),
    );
    // Never the deprecated bearer field alongside the structured object —
    // this session's shape was 'basic', not ArcGIS bearer.
    expect(mockCommitImport.mock.calls[0][1].token).toBeFalsy();
  });
});

// fix(#1835): a restored session used to carry the minted ArcGIS token but
// not its expiry, so isTokenExpiredOrPast() always read `tokenExpiresAt` as
// null and a commit could forward an expired token silently.
describe('ServiceUrlForm resumed ArcGIS token expiry (#1835)', () => {
  const ARCGIS_URL = 'https://services6.arcgis.com/abcd1234/arcgis/rest/services/Foo/FeatureServer';
  const ARCGIS_PROBE: ProbeResponse = {
    service_type: 'arcgis',
    url: ARCGIS_URL,
    selected_layer_id: null,
    layers: [
      {
        name: 'Layer0',
        title: 'Layer0',
        geometry_type: 'Polygon',
        feature_count: 5,
        layer_type: 'Feature Layer',
        layer_id: 0,
        object_id_field: 'OBJECTID',
        kind: 'vector',
      },
    ],
  };
  const ARCGIS_PREVIEW = {
    job_id: 'job-arcgis-resume',
    source_filename: null,
    columns: [],
    crs: 4326,
    geometry_type: 'Polygon',
    feature_count: 5,
    sample_rows: [],
    layer_name: 'Layer0',
  };

  async function signInAndReachReview(user: ReturnType<typeof userEvent.setup>, expiresAt: string) {
    const view = render(<ServiceUrlForm />);
    await user.type(screen.getByPlaceholderText('serviceUrl.placeholder'), ARCGIS_URL);
    await user.click(screen.getByRole('combobox', { name: 'Authentication' }));
    await user.click(await screen.findByRole('option', { name: 'Sign in with username and password' }));
    await user.type(screen.getByLabelText('Portal URL'), 'https://myorg.maps.arcgis.com');
    await user.type(screen.getByLabelText('Username'), 'alice');
    await user.type(screen.getByLabelText('Password'), 'hunter2');
    mockArcgisSignin.mockResolvedValue({ token: 'minted-token', expires_at: expiresAt });
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    await waitFor(() => expect(screen.getByLabelText('Token or API key')).toHaveValue('minted-token'));

    mockProbeService.mockResolvedValue(ARCGIS_PROBE);
    await user.click(screen.getByRole('button', { name: 'Probe →' }));
    await waitFor(() => expect(mockProbeService).toHaveBeenCalled());

    mockPreviewServiceLayer.mockResolvedValue(ARCGIS_PREVIEW);
    await user.click(await screen.findByRole('button', { name: /Layer0/ }));
    await waitFor(() => expect(screen.getByTestId('import-metadata-form')).toBeInTheDocument());
    return view;
  }

  test('a resumed session with a deadline already past is treated as expired, refusing Commit', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const user = userEvent.setup({ delay: null });
      const view = await signInAndReachReview(user, new Date(Date.now() + 60_000).toISOString());

      // Tab switch unmounts the form (clearing its own timer); real time
      // passes well past the deadline while nothing is mounted to react.
      view.unmount();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(70_000);
      });

      render(<ServiceUrlForm />);
      await waitFor(() => expect(screen.getByTestId('import-metadata-form')).toBeInTheDocument());

      await user.click(screen.getByRole('button', { name: 'Commit (test)' }));

      expect(mockCommitImport).not.toHaveBeenCalled();
      expect(
        screen.getByText(/Your ArcGIS sign-in expired while this was open/),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  test('a resumed session with a future deadline reschedules the expiry timer, which fires at it', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const user = userEvent.setup({ delay: null });
      const view = await signInAndReachReview(user, new Date(Date.now() + 60_000).toISOString());

      // Unmount and remount immediately — the deadline is still ahead.
      view.unmount();
      render(<ServiceUrlForm />);
      await waitFor(() => expect(screen.getByTestId('import-metadata-form')).toBeInTheDocument());

      // Past the 30s margin on the 60s deadline: the RESCHEDULED timer
      // (not a leftover from the unmounted first instance, which was
      // cleared on unmount) must be what fires here.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(31_000);
      });

      await user.click(screen.getByRole('button', { name: 'Commit (test)' }));

      expect(mockCommitImport).not.toHaveBeenCalled();
      expect(
        screen.getByText(/Your ArcGIS sign-in expired while this was open/),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
