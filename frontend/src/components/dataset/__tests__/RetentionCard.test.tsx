import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { RetentionCard } from '@/components/dataset/RetentionCard';
import { setDatasetRetention } from '@/api/datasets';
import type { DatasetResponse } from '@/types/api';

vi.mock('@/api/datasets', () => ({
  setDatasetRetention: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function feed(overrides: Partial<DatasetResponse> = {}): DatasetResponse {
  return {
    id: 'ds-1',
    title: 'Device feed',
    record_type: 'vector_dataset',
    geometry_type: 'POINT',
    column_info: [
      { name: 'seen_at', type: 'timestamp with time zone' },
      { name: 'label', type: 'text' },
    ],
    retention: { column: 'seen_at', days: 30 },
    ...overrides,
  } as DatasetResponse;
}

beforeAll(() => {
  // jsdom lacks the pointer and scroll APIs the Radix select calls.
  Element.prototype.hasPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
});

beforeEach(() => {
  vi.mocked(setDatasetRetention).mockReset();
});

describe('RetentionCard', () => {
  it('shows only to someone who can edit a feature dataset', () => {
    const { unmount } = render(<RetentionCard dataset={feed()} canEdit={false} />);
    expect(screen.queryByText('Retention')).not.toBeInTheDocument();
    unmount();

    const raster = render(
      <RetentionCard dataset={feed({ record_type: 'raster_dataset', retention: null })} canEdit />,
    );
    expect(screen.queryByText('Retention')).not.toBeInTheDocument();
    raster.unmount();

    const noGeometry = render(
      <RetentionCard dataset={feed({ record_type: 'table', geometry_type: null, retention: null })} canEdit />,
    );
    expect(screen.queryByText('Retention')).not.toBeInTheDocument();
    noGeometry.unmount();

    render(<RetentionCard dataset={feed()} canEdit />);
    expect(screen.getByRole('heading', { level: 2, name: 'Retention' })).toBeInTheDocument();
    expect(screen.getByTestId('retention-status')).toHaveTextContent(
      'Keeping the last 30 days of rows, judged by seen_at.',
    );
  });

  it('offers only temporal columns whose names the API accepts', async () => {
    const user = userEvent.setup();
    render(
      <RetentionCard
        dataset={feed({
          retention: null,
          column_info: [
            { name: 'Event Time', type: 'timestamp with time zone' },
            { name: 'seen_at', type: 'timestamp with time zone' },
          ],
        })}
        canEdit
      />,
    );

    await user.click(screen.getByRole('combobox', { name: 'Date column' }));

    expect(screen.getByRole('option', { name: 'seen_at' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Event Time' })).not.toBeInTheDocument();
  });

  it('shows the no-column state when no temporal name is usable', () => {
    render(
      <RetentionCard
        dataset={feed({
          retention: null,
          column_info: [{ name: 'event-time', type: 'date' }],
        })}
        canEdit
      />,
    );

    expect(screen.getByText(/no date or timestamp column/)).toBeInTheDocument();
  });

  it('offers no form when the dataset has no temporal column', () => {
    render(
      <RetentionCard
        dataset={feed({ retention: null, column_info: [{ name: 'label', type: 'text' }] })}
        canEdit
      />,
    );

    expect(screen.getByText(/no date or timestamp column/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
  });

  it('keeps Turn off for a setting left on a dataset that lost its geometry', async () => {
    const user = userEvent.setup();
    vi.mocked(setDatasetRetention).mockResolvedValue({ retention: null, rows_past_cutoff: null, cutoff: null });
    render(<RetentionCard dataset={feed({ record_type: 'table', geometry_type: null })} canEdit />);

    expect(screen.getByText(/no longer has geometry/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Days to keep')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Turn off' }));

    await waitFor(() => expect(setDatasetRetention).toHaveBeenCalledWith('ds-1', null, { dryRun: undefined }));
  });

  it('keeps Save off while a dropped retention column is still selected', async () => {
    const user = userEvent.setup();
    render(
      <RetentionCard
        dataset={feed({
          retention: { column: 'seen_at', days: 30 },
          column_info: [{ name: 'observed_on', type: 'date' }],
        })}
        canEdit
      />,
    );

    const save = screen.getByRole('button', { name: 'Save' });
    expect(save).toBeDisabled();
    await user.click(screen.getByRole('combobox', { name: 'Date column' }));
    await user.click(screen.getByRole('option', { name: 'observed_on' }));

    expect(save).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Turn off' })).toBeEnabled();
  });

  it('still offers Turn off when the retention column is gone', async () => {
    const user = userEvent.setup();
    vi.mocked(setDatasetRetention).mockResolvedValue({ retention: null, rows_past_cutoff: 0, cutoff: null });
    render(
      <RetentionCard
        dataset={feed({ column_info: [{ name: 'label', type: 'text' }] })}
        canEdit
      />,
    );

    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Turn off' }));

    await waitFor(() => expect(setDatasetRetention).toHaveBeenCalledWith('ds-1', null, { dryRun: undefined }));
  });

  it('asks before saving a setting that deletes rows now, showing how many', async () => {
    const user = userEvent.setup();
    vi.mocked(setDatasetRetention)
      .mockResolvedValueOnce({
        retention: { column: 'seen_at', days: 7 },
        rows_past_cutoff: 12345,
        cutoff: '2026-10-10T12:00:00Z',
      })
      .mockResolvedValueOnce({
        retention: { column: 'seen_at', days: 7 },
        rows_past_cutoff: 12345,
        cutoff: '2026-10-10T12:00:00Z',
      });
    render(<RetentionCard dataset={feed()} canEdit />);

    const days = screen.getByLabelText('Days to keep');
    await user.clear(days);
    await user.type(days, '7');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('12,345 rows are older than');
    expect(dialog).toHaveTextContent('Hourly runs delete them in batches, so a large backlog can take several runs.');
    expect(dialog).not.toHaveTextContent('within the hour');
    expect(setDatasetRetention).toHaveBeenCalledTimes(1);
    expect(setDatasetRetention).toHaveBeenCalledWith('ds-1', { column: 'seen_at', days: 7 }, { dryRun: true });

    await user.click(screen.getByRole('button', { name: 'Delete and save' }));

    await waitFor(() => expect(setDatasetRetention).toHaveBeenCalledTimes(2));
    expect(setDatasetRetention).toHaveBeenLastCalledWith(
      'ds-1',
      { column: 'seen_at', days: 7 },
      { dryRun: undefined },
    );
  });

  describe('west of UTC', () => {
    const originalTz = process.env.TZ;
    beforeAll(() => { process.env.TZ = 'America/Los_Angeles'; });
    afterAll(() => { process.env.TZ = originalTz; });

    it('shows a timestamp column\'s cutoff with its time in UTC', async () => {
      const user = userEvent.setup();
      vi.mocked(setDatasetRetention).mockResolvedValue({
        retention: { column: 'seen_at', days: 7 },
        rows_past_cutoff: 2,
        cutoff: '2026-10-10T12:00:00Z',
      });
      render(<RetentionCard dataset={feed()} canEdit />);

      const days = screen.getByLabelText('Days to keep');
      await user.clear(days);
      await user.type(days, '7');
      await user.click(screen.getByRole('button', { name: 'Save' }));

      const dialog = await screen.findByRole('alertdialog');
      expect(dialog).toHaveTextContent('2 rows are older than Oct 10, 2026, 12:00 PM UTC.');
    });

    it('shows a date column\'s cutoff as its own day', async () => {
      const user = userEvent.setup();
      expect(new Date('2026-09-17T00:00:00Z').getDate()).toBe(16);
      vi.mocked(setDatasetRetention).mockResolvedValue({
        retention: { column: 'seen_on', days: 30 },
        rows_past_cutoff: 6,
        cutoff: '2026-09-17T00:00:00Z',
      });
      render(
        <RetentionCard
          dataset={feed({
            column_info: [{ name: 'seen_on', type: 'date' }],
            retention: { column: 'seen_on', days: 60 },
          })}
          canEdit
        />,
      );

      const days = screen.getByLabelText('Days to keep');
      await user.clear(days);
      await user.type(days, '30');
      await user.click(screen.getByRole('button', { name: 'Save' }));

      const dialog = await screen.findByRole('alertdialog');
      expect(dialog).toHaveTextContent('6 rows are older than Sep 17, 2026.');
    });
  });

  it('saves without asking when no row is past the cutoff', async () => {
    const user = userEvent.setup();
    vi.mocked(setDatasetRetention).mockResolvedValue({
      retention: { column: 'seen_at', days: 60 },
      rows_past_cutoff: 0,
      cutoff: '2026-08-18T12:00:00Z',
    });
    render(<RetentionCard dataset={feed()} canEdit />);

    const days = screen.getByLabelText('Days to keep');
    await user.clear(days);
    await user.type(days, '60');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(setDatasetRetention).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('cancelling the confirmation saves nothing', async () => {
    const user = userEvent.setup();
    vi.mocked(setDatasetRetention).mockResolvedValue({
      retention: { column: 'seen_at', days: 7 },
      rows_past_cutoff: 1,
      cutoff: '2026-10-10T12:00:00Z',
    });
    render(<RetentionCard dataset={feed()} canEdit />);

    const days = screen.getByLabelText('Days to keep');
    await user.clear(days);
    await user.type(days, '7');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('1 row is older than');

    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(setDatasetRetention).toHaveBeenCalledTimes(1);
  });

  it('turns retention off without a confirmation', async () => {
    const user = userEvent.setup();
    vi.mocked(setDatasetRetention).mockResolvedValue({ retention: null, rows_past_cutoff: 0, cutoff: null });
    render(<RetentionCard dataset={feed()} canEdit />);

    await user.click(screen.getByRole('button', { name: 'Turn off' }));

    await waitFor(() => expect(setDatasetRetention).toHaveBeenCalledWith('ds-1', null, { dryRun: undefined }));
  });

  it('refuses a days value outside 1 to 3650', async () => {
    const user = userEvent.setup();
    render(<RetentionCard dataset={feed()} canEdit />);

    const days = screen.getByLabelText('Days to keep');
    await user.clear(days);
    await user.type(days, '3651');

    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(days).toHaveAttribute('aria-invalid', 'true');
  });
});
