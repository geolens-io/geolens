import { render, screen } from '@/test/test-utils';
import type { EmbeddingStatsResponse } from '@/types/api';
import { BackfillRunStatus } from '../BackfillRunStatus';

// fix(#2025): an operator could not see how far a backfill had got, what
// earlier runs did, or how long one would take before starting it.

const base: EmbeddingStatsResponse = {
  total_records: 1200,
  embedded_records: 900,
  missing_records: 300,
  stale_records: 0,
  coverage_percent: 75,
  current_run: null,
  recent_runs: [],
  estimate: null,
};

describe('BackfillRunStatus', () => {
  it('renders nothing when there is no run, history or estimate', () => {
    const { container } = render(<BackfillRunStatus stats={base} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the running job as records processed over total', () => {
    render(
      <BackfillRunStatus
        stats={{
          ...base,
          current_run: {
            job_id: 'a1',
            status: 'running',
            records_processed: 384,
            records_total: 1200,
            started_at: '2026-09-09T10:00:00Z',
            heartbeat_at: '2026-09-09T10:02:00Z',
          },
        }}
      />,
    );

    expect(screen.getByText('384 of 1200 records')).toBeInTheDocument();
    expect(screen.getByTestId('backfill-progress-bar')).toHaveStyle({ width: '32%' });
  });

  it('says the run is starting until it has counted its records', () => {
    render(
      <BackfillRunStatus
        stats={{
          ...base,
          current_run: {
            job_id: 'a1',
            status: 'pending',
            records_processed: 0,
            records_total: null,
            started_at: null,
            heartbeat_at: null,
          },
        }}
      />,
    );

    expect(screen.getByText('Starting')).toBeInTheDocument();
  });

  it('estimates both actions in minutes before a run starts', () => {
    render(
      <BackfillRunStatus
        stats={{ ...base, estimate: { missing_seconds: 150, all_seconds: 600 } }}
      />,
    );

    expect(
      screen.getByText('Generating the missing embeddings should take about 3 minutes'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Regenerating every embedding should take about 10 minutes'),
    ).toBeInTheDocument();
  });

  it('rounds a sub-minute estimate up rather than to no time at all', () => {
    render(
      <BackfillRunStatus
        stats={{ ...base, estimate: { missing_seconds: 4, all_seconds: 9 } }}
      />,
    );

    expect(
      screen.getByText('Generating the missing embeddings should take about 1 minute'),
    ).toBeInTheDocument();
  });

  it('hides the estimate while a run is in flight', () => {
    render(
      <BackfillRunStatus
        stats={{
          ...base,
          estimate: { missing_seconds: 150, all_seconds: 600 },
          current_run: {
            job_id: 'a1',
            status: 'running',
            records_processed: 1,
            records_total: 2,
            started_at: '2026-09-09T10:00:00Z',
            heartbeat_at: null,
          },
        }}
      />,
    );

    expect(
      screen.queryByText(/should take about/),
    ).not.toBeInTheDocument();
  });

  it('lists past runs with their outcome, error code and record count', () => {
    render(
      <BackfillRunStatus
        stats={{
          ...base,
          recent_runs: [
            {
              job_id: 'r1',
              status: 'failed',
              started_at: '2026-09-08T09:00:00Z',
              finished_at: '2026-09-08T09:05:00Z',
              records_processed: 0,
              error_code: 'all_embeddings_failed',
            },
            {
              job_id: 'r2',
              status: 'complete',
              started_at: '2026-09-07T09:00:00Z',
              finished_at: '2026-09-07T09:20:00Z',
              records_processed: 1,
              error_code: null,
            },
          ],
        }}
      />,
    );

    expect(screen.getByText('Recent runs')).toBeInTheDocument();
    expect(
      screen.getByText('Failed (all_embeddings_failed) · 0 records'),
    ).toBeInTheDocument();
    expect(screen.getByText('Finished · 1 record')).toBeInTheDocument();
  });
});
