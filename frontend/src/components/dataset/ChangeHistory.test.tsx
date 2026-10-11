import { render, screen } from '@/test/test-utils';
import { useDatasetHistory } from '@/components/dataset/hooks/use-dataset';
import { ChangeHistory } from '@/components/dataset/ChangeHistory';

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDatasetHistory: vi.fn(),
}));

describe('ChangeHistory', () => {
  it('labels an ownership transfer', () => {
    vi.mocked(useDatasetHistory).mockReturnValue({
      data: {
        logs: [
          {
            id: 'log-1',
            action: 'dataset.transfer_owner',
            username: 'admin',
            created_at: '2026-10-10T12:00:00Z',
            details: { previous_owner_id: 'a', new_owner_id: 'b' },
          },
        ],
      },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useDatasetHistory>);

    render(<ChangeHistory datasetId="dataset-1" />);

    expect(screen.getByText('Owner changed')).toBeInTheDocument();
  });
});
