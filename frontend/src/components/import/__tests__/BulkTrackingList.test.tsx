import { render, screen, within, waitFor } from '@/test/test-utils';
import { useQueries } from '@tanstack/react-query';
import { BulkTrackingList } from '../BulkTrackingList';
import type { FileEntry } from '@/types/api';
import { randomId } from '@/lib/random-id';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (typeof opts?.defaultValue === 'string') return opts.defaultValue;
      return key;
    },
  }),
}));

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-query')>();
  return {
    ...actual,
    useQueries: vi.fn(),
  };
});

vi.mock('../JobProgress', () => ({
  JobProgress: ({ jobId }: { jobId: string }) => (
    <div data-testid={`job-progress-${jobId}`}>Job {jobId}</div>
  ),
}));

vi.mock('../VrtCreateDialog', () => ({
  VrtCreateDialog: () => null,
}));

// AI availability is toggled per test via aiState; the ingest AI-metadata CTA
// only renders when AI is available (and a single dataset completed).
const { aiState } = vi.hoisted(() => ({ aiState: { value: false } }));
vi.mock('@/hooks/use-ai-availability', () => ({
  useAIAvailability: () => ({ isAIAvailable: aiState.value }),
}));

const mockUseQueries = vi.mocked(useQueries);

function makeEntry(overrides: Partial<FileEntry> = {}): FileEntry {
  return {
    id: randomId(),
    file: null,
    fileName: 'sample.geojson',
    status: 'tracking',
    jobId: 'job-1',
    previewData: null,
    error: null,
    submittedTitle: 'Sample dataset',
    submittedVisibility: 'private',
    submittedKind: 'vector',
    ...overrides,
  };
}

describe('BulkTrackingList', () => {
  beforeEach(() => {
    mockUseQueries.mockReset();
    aiState.value = false;
  });

  it('describes a finished table without implying a map and exposes valid statistics', async () => {
    mockUseQueries.mockReturnValue([
      { data: { status: 'complete', dataset_id: 'table-1', source_filename: 'rows.csv' } },
    ] as never);
    const onOutcomeChange = vi.fn();
    render(<BulkTrackingList entries={[makeEntry({ fileName: 'rows.csv', submittedKind: 'table' })]} onReset={vi.fn()} onOutcomeChange={onOutcomeChange} />);

    expect(screen.getByText('complete.heroDescTables')).toBeInTheDocument();
    expect(screen.getByText('Tabular', { selector: 'dt' }).closest('dl')).toBeInTheDocument();
    await waitFor(() => expect(onOutcomeChange).toHaveBeenCalledWith('complete', ['table']));
  });

  it('settles mixed success and failure with the failed job still available', async () => {
    mockUseQueries.mockReturnValue([
      { data: { status: 'complete', dataset_id: 'table-1', source_filename: 'rows.csv' } },
      { data: { status: 'failed', dataset_id: null, source_filename: 'broken.csv' } },
    ] as never);
    const onOutcomeChange = vi.fn();
    render(<BulkTrackingList entries={[
      makeEntry({ fileName: 'rows.csv', submittedKind: 'table' }),
      makeEntry({ id: 'failed', jobId: 'job-2', fileName: 'broken.csv', submittedKind: 'table' }),
    ]} onReset={vi.fn()} onOutcomeChange={onOutcomeChange} />);

    expect(screen.getByText('complete.partialTitle')).toBeInTheDocument();
    expect(screen.getByTestId('job-progress-job-2')).toBeInTheDocument();
    await waitFor(() => expect(onOutcomeChange).toHaveBeenCalledWith('partial', ['table']));
  });

  it('keeps a staging failure visible beside a successful import', async () => {
    mockUseQueries.mockReturnValue([
      { data: { status: 'complete', dataset_id: 'table-1', source_filename: 'rows.csv' } },
    ] as never);
    const onOutcomeChange = vi.fn();
    render(<BulkTrackingList entries={[
      makeEntry({ fileName: 'rows.csv', submittedKind: 'table' }),
      makeEntry({ id: 'failed', jobId: null, fileName: 'broken.csv', status: 'upload-failed', error: 'Unsupported file' }),
    ]} onReset={vi.fn()} onOutcomeChange={onOutcomeChange} />);

    expect(screen.getByText('complete.partialTitle')).toBeInTheDocument();
    expect(screen.getByText('Unsupported file')).toBeInTheDocument();
    await waitFor(() => expect(onOutcomeChange).toHaveBeenCalledWith('partial', ['table']));
  });

  it('surfaces completed datasets in the summary while keeping only active jobs in the main list', () => {
    mockUseQueries
      .mockReturnValueOnce([
        {
          data: {
            status: 'complete',
            dataset_id: 'dataset-1',
            source_filename: 'sample.geojson',
          },
        },
        {
          data: {
            status: 'running',
            dataset_id: null,
            source_filename: 'pending.csv',
          },
        },
      ] as never)
      .mockReturnValueOnce([] as never);

    render(
      <BulkTrackingList
        entries={[
          makeEntry(),
          makeEntry({
            id: 'entry-2',
            fileName: 'pending.csv',
            jobId: 'job-2',
            submittedTitle: 'Pending dataset',
            submittedKind: 'table',
          }),
        ]}
        onReset={vi.fn()}
      />,
    );

    expect(screen.getByRole('link', { name: 'Open dataset' })).toHaveAttribute('href', '/datasets/dataset-1');
    expect(within(screen.getByText('Sample dataset').parentElement!).getByText('complete.statVector')).toBeInTheDocument();
    expect(screen.queryByTestId('job-progress-job-1')).not.toBeInTheDocument();
    expect(screen.getByTestId('job-progress-job-2')).toBeInTheDocument();
  });

  it('counts a finished tileset as 3D Tiles and describes it as ready for a 3D Tiles client', () => {
    mockUseQueries.mockReturnValueOnce([
      { data: { status: 'complete', dataset_id: 'dataset-3', source_filename: 'campus.zip' } },
    ] as never);

    render(
      <BulkTrackingList
        entries={[makeEntry({ fileName: 'campus.zip', submittedTitle: 'Campus', submittedKind: 'tiles3d' })]}
        onReset={vi.fn()}
      />,
    );

    expect(screen.getByText('complete.heroDescTilesets')).toBeInTheDocument();
    expect(screen.queryByText(/ingested, tiled, and indexed/)).not.toBeInTheDocument();
    expect(screen.getByText('complete.statTilesets', { selector: 'dt' }).nextElementSibling).toHaveTextContent('1');
    expect(within(screen.getByText('Campus').nextElementSibling as HTMLElement).getByText('complete.statTilesets')).toBeInTheDocument();
    expect(screen.queryByText('tiles3d')).not.toBeInTheDocument();
  });

  it('offers the AI-metadata CTA on a single completed dataset when AI is available', () => {
    aiState.value = true;
    mockUseQueries.mockReturnValueOnce([
      { data: { status: 'complete', dataset_id: 'dataset-9', source_filename: 'sample.geojson' } },
    ] as never);

    render(<BulkTrackingList entries={[makeEntry()]} onReset={vi.fn()} />);

    expect(screen.getByRole('link', { name: /Add AI metadata/ })).toHaveAttribute(
      'href',
      '/datasets/dataset-9',
    );
  });

  it('hides the AI-metadata CTA when AI is unavailable', () => {
    aiState.value = false;
    mockUseQueries.mockReturnValueOnce([
      { data: { status: 'complete', dataset_id: 'dataset-9', source_filename: 'sample.geojson' } },
    ] as never);

    render(<BulkTrackingList entries={[makeEntry()]} onReset={vi.fn()} />);

    expect(screen.queryByRole('link', { name: /Add AI metadata/ })).not.toBeInTheDocument();
  });
});
