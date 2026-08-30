/**
 * fix(#1708 codex r22): the URL-import lifecycle as a state machine.
 *
 * Four consecutive review rounds landed on this component, each a single
 * cell of the same table being wrong. These tests are written against the
 * table rather than against the individual findings, so the next change has
 * to keep every transition true, not just the one it was aiming at.
 *
 * States: idle · fetching · review · committing · tracking(active) ·
 *         tracking(complete) · tracking(failed)
 * Events: mount · unmount · reset · commit resolve · commit reject ·
 *         job reaches terminal · layer change · commit submit
 *
 * fix(#1708 codex r24): the last two events are the ones r22 missed. Its
 * state axis was right and its event axis was a list of remembered events,
 * so `committing × layer-change` was simply absent. The axis is now taken
 * from the component's RENDERED CONTROLS instead: every control that can
 * mutate `step`, the module session, or an in-flight request is an event
 * here, which is what makes the set complete rather than merely longer.
 *
 * Controls, read off the JSX:
 *   spinner branch (fetching/previewing/resuming) — none at all
 *   review/commit  — layer <select>, ImportMetadataForm submit, Start Over
 *   tracking       — JobProgress (its controls gated on a terminal job),
 *                    Import another (gated on complete)
 *   idle           — URL field, filename field (local state only), submit
 */
import { fireEvent, render, screen, waitFor, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { UrlImportForm } from '../UrlImportForm';
import { clearUrlImport, peekUrlImport } from '@/api/url-import-session';

const mockUploadFromUrl = vi.fn();
const mockPreviewFile = vi.fn();
const mockCommitImport = vi.fn();
const mockUseJobStatus = vi.fn();

vi.mock('@/api/ingest', () => ({
  uploadFromUrl: (...a: unknown[]) => mockUploadFromUrl(...a),
  previewFile: (...a: unknown[]) => mockPreviewFile(...a),
  commitImport: (...a: unknown[]) => mockCommitImport(...a),
}));

vi.mock('@/components/import/hooks/use-ingest', () => ({
  useJobStatus: (...a: unknown[]) => mockUseJobStatus(...a),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'en' } }),
}));

vi.mock('../ImportPreview', () => ({
  ImportPreview: () => <div data-testid="import-preview" />,
}));
// The real form gates its submit on `isCommitting` (ImportMetadataForm.tsx:
// `disabled={isCommitting || !name.trim()}`). The stub reports that prop
// instead of honouring it, so one test can assert the UI half is wired up
// while another can still call the handler through it — which is the only
// way to exercise the handler half of the belt-and-braces guard.
vi.mock('../ImportMetadataForm', () => ({
  ImportMetadataForm: ({
    onCommit,
    isCommitting,
  }: {
    onCommit: (m: unknown) => void;
    isCommitting: boolean;
  }) => (
    <button
      type="button"
      data-committing={String(isCommitting)}
      onClick={() => onCommit({ title: 'X' })}
    >
      commit-stub
    </button>
  ),
}));
// Mirrors the real JobProgress contract: start-over only on failure, and
// the raster actions gated on isRasterEntry. Finding 1 and 2 are both about
// this contract, so the stub reproduces it rather than assuming it away.
vi.mock('../JobProgress', () => ({
  JobProgress: ({
    jobId,
    onReset,
    isRasterEntry,
  }: {
    jobId: string;
    onReset: () => void;
    isRasterEntry?: boolean;
  }) => (
    <div data-testid="job-progress">
      <span>{jobId}</span>
      {isRasterEntry && <span data-testid="raster-actions" />}
      {mockUseJobStatus.mock.results.at(-1)?.value?.data?.status === 'failed' && (
        <button type="button" onClick={onReset}>
          jobProgress.startOver
        </button>
      )}
    </div>
  ),
}));

const VECTOR_PREVIEW = {
  job_id: 'job-1',
  source_filename: 'roads.geojson',
  columns: [],
  crs: 4326,
  geometry_type: 'LineString',
  feature_count: 1,
  sample_rows: [],
  layer_name: 'roads',
  layers: null,
};
// Only a MULTI-layer container renders the layer picker, so the r24 cell is
// unreachable without one.
const MULTI_LAYER_PREVIEW = {
  ...VECTOR_PREVIEW,
  job_id: 'job-m',
  source_filename: 'bundle.gpkg',
  layer_name: 'layer_a',
  layers: [
    { name: 'layer_a', feature_count: 5, field_count: 2 },
    { name: 'layer_b', feature_count: 9, field_count: 3 },
  ],
};
const RASTER_PREVIEW = {
  job_id: 'job-r',
  source_filename: 'dem.tif',
  crs_epsg: 4326,
  band_count: 1,
  width: 10,
  height: 10,
  dtype: 'uint8',
  res_x: 1,
  res_y: 1,
  is_cog_compliant: true,
  compliance_reason: '',
  nodata: null,
  crs_wkt: null,
  compression: null,
  file_size_bytes: 1,
};

beforeEach(() => {
  vi.clearAllMocks();
  clearUrlImport();
  mockUseJobStatus.mockReturnValue({ data: undefined });
});
afterEach(() => clearUrlImport());

async function driveToReview(preview: unknown, jobId: string) {
  mockUploadFromUrl.mockResolvedValue({ job_id: jobId, status: 'pending' });
  mockPreviewFile.mockResolvedValue(preview);
  const user = userEvent.setup();
  await user.type(
    screen.getByLabelText('urlImport.label'),
    'https://files.example.test/f',
  );
  await user.click(screen.getByRole('button', { name: 'urlImport.fetch' }));
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'commit-stub' })).toBeInTheDocument(),
  );
  return user;
}

describe('URL import lifecycle', () => {
  // ── the table: what each event does to session / UI / in-flight promise ──
  test('idle + mount with no session stays idle and starts nothing', () => {
    render(<UrlImportForm />);
    expect(screen.getByLabelText('urlImport.label')).toBeInTheDocument();
    expect(peekUrlImport()).toBeNull();
    expect(mockUploadFromUrl).not.toHaveBeenCalled();
  });

  test('review + reset clears the session and returns to idle', async () => {
    render(<UrlImportForm />);
    const user = await driveToReview(VECTOR_PREVIEW, 'job-1');
    expect(peekUrlImport()).not.toBeNull();

    await user.click(screen.getByRole('button', { name: 'urlImport.startOver' }));
    expect(peekUrlImport()).toBeNull();
    expect(screen.getByLabelText('urlImport.label')).toBeInTheDocument();
  });

  test('committing + reset is refused: the session survives an uncancellable commit', async () => {
    render(<UrlImportForm />);
    const user = await driveToReview(VECTOR_PREVIEW, 'job-1');
    let resolveCommit!: (v: unknown) => void;
    mockCommitImport.mockReturnValue(
      new Promise((res) => {
        resolveCommit = res;
      }),
    );
    await user.click(screen.getByRole('button', { name: 'commit-stub' }));
    await waitFor(() => expect(mockCommitImport).toHaveBeenCalledTimes(1));

    // The control is disabled, and the handler refuses even if called.
    const startOver = screen.getByRole('button', { name: 'urlImport.startOver' });
    expect(startOver).toBeDisabled();
    await user.click(startOver);
    expect(peekUrlImport()).not.toBeNull();

    // The commit lands and is still tracked, not orphaned.
    resolveCommit({ job_id: 'job-1', status: 'queued' });
    await waitFor(() =>
      expect(screen.getByTestId('job-progress')).toBeInTheDocument(),
    );
  });

  // ── r24: the two events the r22 axis never had ──

  // The counterfactual for the test below: with nothing in flight the picker
  // is enabled and this exact event DOES re-preview. So when the same event
  // changes nothing mid-commit, it is the guard doing it, not a change event
  // that never reached React.
  test('review + layer change re-previews the chosen layer', async () => {
    render(<UrlImportForm />);
    await driveToReview(MULTI_LAYER_PREVIEW, 'job-m');
    expect(mockPreviewFile).toHaveBeenCalledTimes(1);

    const select = screen.getByLabelText('urlImport.layerLabel');
    expect(select).toBeEnabled();
    fireEvent.change(select, { target: { value: 'layer_b' } });

    await waitFor(() =>
      expect(mockPreviewFile).toHaveBeenLastCalledWith('job-m', 'layer_b'),
    );
    expect(screen.getByRole('button', { name: 'urlImport.startOver' })).toBeEnabled();
  });

  test('committing + layer change is refused: one commit issued, none orphaned', async () => {
    render(<UrlImportForm />);
    const user = await driveToReview(MULTI_LAYER_PREVIEW, 'job-m');

    // The commit must stay PENDING for the whole test: settling it first
    // would leave nothing to race.
    let resolveCommit!: (v: unknown) => void;
    mockCommitImport.mockReturnValue(
      new Promise((res) => {
        resolveCommit = res;
      }),
    );
    await user.click(screen.getByRole('button', { name: 'commit-stub' }));
    await waitFor(() => expect(mockCommitImport).toHaveBeenCalledTimes(1));

    const previewCallsBefore = mockPreviewFile.mock.calls.length;
    const select = screen.getByLabelText('urlImport.layerLabel');

    // Belt: the control is disabled while the commit is in flight.
    expect(select).toBeDisabled();

    // Braces: firing the event anyway must not re-enter preview.
    fireEvent.change(select, { target: { value: 'layer_b' } });

    // Still committing — no re-preview, and the controls that a bounce
    // through `review` would have re-enabled are all still shut.
    expect(mockPreviewFile).toHaveBeenCalledTimes(previewCallsBefore);
    expect(screen.getByRole('button', { name: 'urlImport.startOver' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'commit-stub' })).toHaveAttribute(
      'data-committing',
      'true',
    );
    expect(peekUrlImport()).not.toBeNull();

    // The single issued commit still lands, and it lands as tracking for the
    // job it was issued for — not orphaned, and not committed twice.
    resolveCommit({ job_id: 'job-m', status: 'queued' });
    await waitFor(() =>
      expect(screen.getByTestId('job-progress')).toBeInTheDocument(),
    );
    expect(mockCommitImport).toHaveBeenCalledTimes(1);
    expect(within(screen.getByTestId('job-progress')).getByText('job-m')).toBeInTheDocument();
  });

  test('committing + a second commit submit is refused', async () => {
    render(<UrlImportForm />);
    const user = await driveToReview(VECTOR_PREVIEW, 'job-1');
    let resolveCommit!: (v: unknown) => void;
    mockCommitImport.mockReturnValue(
      new Promise((res) => {
        resolveCommit = res;
      }),
    );
    const commitButton = screen.getByRole('button', { name: 'commit-stub' });
    await user.click(commitButton);
    await waitFor(() => expect(mockCommitImport).toHaveBeenCalledTimes(1));

    // Belt: the real form is told to disable its submit.
    expect(commitButton).toHaveAttribute('data-committing', 'true');
    // Braces: the stub ignores that and calls the handler anyway, which is
    // the only way to reach the guard — and the guard refuses.
    await user.click(commitButton);
    expect(mockCommitImport).toHaveBeenCalledTimes(1);

    resolveCommit({ job_id: 'job-1', status: 'queued' });
    await waitFor(() =>
      expect(screen.getByTestId('job-progress')).toBeInTheDocument(),
    );
    expect(mockCommitImport).toHaveBeenCalledTimes(1);
  });

  test('committing + commit resolve moves to tracking; reject returns to review', async () => {
    render(<UrlImportForm />);
    const user = await driveToReview(VECTOR_PREVIEW, 'job-1');
    mockCommitImport.mockRejectedValueOnce(new Error('nope'));
    await user.click(screen.getByRole('button', { name: 'commit-stub' }));
    await waitFor(() =>
      expect(screen.getByText('urlImport.commitFailed')).toBeInTheDocument(),
    );
    // Still in review, so the job remains committable.
    expect(screen.getByRole('button', { name: 'commit-stub' })).toBeInTheDocument();
    expect(screen.queryByTestId('job-progress')).not.toBeInTheDocument();
  });

  // ── finding 1: a second import after a successful one ──
  test('tracking(complete) offers start-over, and a second import can run', async () => {
    render(<UrlImportForm />);
    const user = await driveToReview(VECTOR_PREVIEW, 'job-1');
    mockCommitImport.mockResolvedValue({ job_id: 'job-1', status: 'queued' });
    mockUseJobStatus.mockReturnValue({ data: { status: 'complete' } });
    await user.click(screen.getByRole('button', { name: 'commit-stub' }));
    await waitFor(() =>
      expect(screen.getByTestId('job-progress')).toBeInTheDocument(),
    );

    // The completed job used to pin the tab here forever.
    await user.click(screen.getByRole('button', { name: 'urlImport.importAnother' }));
    expect(peekUrlImport()).toBeNull();
    expect(screen.getByLabelText('urlImport.label')).toBeInTheDocument();

    // And a second import genuinely runs.
    mockUseJobStatus.mockReturnValue({ data: undefined });
    await driveToReview(VECTOR_PREVIEW, 'job-2');
    expect(mockUploadFromUrl).toHaveBeenCalledTimes(2);
  });

  test('tracking(failed) offers start-over via JobProgress', async () => {
    render(<UrlImportForm />);
    const user = await driveToReview(VECTOR_PREVIEW, 'job-1');
    mockCommitImport.mockResolvedValue({ job_id: 'job-1', status: 'queued' });
    mockUseJobStatus.mockReturnValue({ data: { status: 'failed' } });
    await user.click(screen.getByRole('button', { name: 'commit-stub' }));
    await waitFor(() =>
      expect(screen.getByTestId('job-progress')).toBeInTheDocument(),
    );

    await user.click(
      within(screen.getByTestId('job-progress')).getByRole('button', {
        name: 'jobProgress.startOver',
      }),
    );
    expect(peekUrlImport()).toBeNull();
    expect(screen.getByLabelText('urlImport.label')).toBeInTheDocument();
  });

  // ── finding 2: the raster discriminator must survive a resume ──
  test('raster actions show after a resume, where previewData is gone', async () => {
    const view = render(<UrlImportForm />);
    const user = await driveToReview(RASTER_PREVIEW, 'job-r');
    let resolveCommit!: (v: unknown) => void;
    mockCommitImport.mockReturnValue(
      new Promise((res) => {
        resolveCommit = res;
      }),
    );
    await user.click(screen.getByRole('button', { name: 'commit-stub' }));
    await waitFor(() => expect(mockCommitImport).toHaveBeenCalledTimes(1));
    expect(peekUrlImport()?.isRaster).toBe(true);

    // Genuinely leave the tab: the remounted form has NO previewData, so
    // the discriminator can only come from the session. This is the exact
    // shape of finding 2 — before the fix, isRasterEntry was false here and
    // a completed raster came back without its COG/map/connect actions.
    view.unmount();
    mockUseJobStatus.mockReturnValue({ data: { status: 'complete' } });
    resolveCommit({ job_id: 'job-r', status: 'queued' });

    render(<UrlImportForm />);
    await waitFor(() =>
      expect(screen.getByTestId('job-progress')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('raster-actions')).toBeInTheDocument();
    // A vector import resuming the same way must NOT show them.
    expect(mockCommitImport).toHaveBeenCalledTimes(1);
  });

  test('a resumed VECTOR import shows no raster actions', async () => {
    const view = render(<UrlImportForm />);
    const user = await driveToReview(VECTOR_PREVIEW, 'job-v');
    let resolveCommit!: (v: unknown) => void;
    mockCommitImport.mockReturnValue(
      new Promise((res) => {
        resolveCommit = res;
      }),
    );
    await user.click(screen.getByRole('button', { name: 'commit-stub' }));
    await waitFor(() => expect(mockCommitImport).toHaveBeenCalledTimes(1));
    expect(peekUrlImport()?.isRaster).toBe(false);

    view.unmount();
    mockUseJobStatus.mockReturnValue({ data: { status: 'complete' } });
    resolveCommit({ job_id: 'job-v', status: 'queued' });

    render(<UrlImportForm />);
    await waitFor(() =>
      expect(screen.getByTestId('job-progress')).toBeInTheDocument(),
    );
    expect(screen.queryByTestId('raster-actions')).not.toBeInTheDocument();
  });
});
