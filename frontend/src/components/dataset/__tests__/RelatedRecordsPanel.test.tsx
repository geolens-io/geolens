import { render, screen, waitFor } from '@/test/test-utils';
import { RelatedRecordsPanel } from '../RelatedRecordsPanel';
import { listRelationships } from '@/api/datasets';
import type { DatasetRelationship } from '@/types/api';

vi.mock('@/api/datasets', () => ({
  listRelationships: vi.fn(),
  getRelatedRecords: vi.fn(),
}));

const mockRelationship: DatasetRelationship = {
  id: 'rel-1',
  source_dataset_id: 'ds-1',
  source_column: 'county_id',
  target_dataset_id: 'ds-2',
  target_column: 'id',
  target_dataset_title: 'Counties',
  label: 'County Records',
  relationship_type: 'one-to-many',
};

describe('RelatedRecordsPanel', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('shows loading skeletons while fetching', () => {
    vi.mocked(listRelationships).mockImplementation(
      () => new Promise(() => {}), // never resolves
    );
    const { container } = render(
      <RelatedRecordsPanel datasetId="ds-1" featureGid={1} />,
    );
    // Skeleton elements render with data-slot="skeleton"
    const skeletons = container.querySelectorAll('[data-slot="skeleton"]');
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it('returns null when no relationships exist', async () => {
    vi.mocked(listRelationships).mockResolvedValue([]);
    render(
      <div data-testid="container">
        <RelatedRecordsPanel datasetId="ds-1" featureGid={1} />
      </div>,
    );
    await waitFor(() => {
      const wrapper = screen.getByTestId('container');
      expect(wrapper.children).toHaveLength(0);
    });
  });

  it('shows error state when fetch fails', async () => {
    vi.mocked(listRelationships).mockRejectedValue(new Error('Network error'));
    render(<RelatedRecordsPanel datasetId="ds-1" featureGid={1} />);
    await waitFor(() => {
      expect(screen.getByText('Failed to load relationships')).toBeInTheDocument();
    });
  });

  it('shows relationship label and column mapping when populated', async () => {
    vi.mocked(listRelationships).mockResolvedValue([mockRelationship]);
    render(<RelatedRecordsPanel datasetId="ds-1" featureGid={1} />);
    await waitFor(() => {
      expect(screen.getByText('County Records')).toBeInTheDocument();
    });
    expect(screen.getByText(/county_id/)).toBeInTheDocument();
  });
});
