import { render, screen, fireEvent, waitFor } from '@/test/test-utils';
import { TemporalExtentCard } from '@/components/dataset/TemporalExtentCard';
import { buildDatasetEditCapabilities } from '@/components/dataset/hooks/use-dataset-edit-capabilities';

const mutateAsync = vi.hoisted(() => vi.fn());
vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useUpdateDataset: () => ({ mutateAsync }),
}));

function renderCard() {
  return render(
    <TemporalExtentCard
      datasetId="ds-1"
      dataVintageStart="1950-01-01"
      dataVintageEnd={null}
      capabilities={buildDatasetEditCapabilities({ isEditor: true })}
    />,
  );
}

describe('TemporalExtentCard editing', () => {
  beforeEach(() => {
    mutateAsync.mockReset().mockResolvedValue(undefined);
  });

  it('edits the raw ISO date and saves an ISO date', async () => {
    renderCard();
    fireEvent.click(screen.getByText('Jan 1, 1950'));
    const input = screen.getByDisplayValue('1950-01-01') as HTMLInputElement;
    expect(input.type).toBe('date');
    fireEvent.change(input, { target: { value: '1950-01-02' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        datasetId: 'ds-1',
        data: { data_vintage_start: '1950-01-02' },
      }),
    );
  });

  it('clears the date by sending null', async () => {
    renderCard();
    fireEvent.click(screen.getByText('Jan 1, 1950'));
    const input = screen.getByDisplayValue('1950-01-01');
    fireEvent.change(input, { target: { value: '' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        datasetId: 'ds-1',
        data: { data_vintage_start: null },
      }),
    );
  });

  it('does not clear the stored date when the date input is left half-edited', async () => {
    renderCard();
    fireEvent.click(screen.getByText('Jan 1, 1950'));
    const input = screen.getByDisplayValue('1950-01-01') as HTMLInputElement;
    Object.defineProperty(input, 'validity', { value: { badInput: true } });
    fireEvent.change(input, { target: { value: '' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(screen.getByText('Jan 1, 1950')).toBeInTheDocument());
    expect(mutateAsync).not.toHaveBeenCalled();
  });
});
