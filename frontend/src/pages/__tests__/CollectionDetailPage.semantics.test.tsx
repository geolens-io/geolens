import { useParams } from 'react-router';
import { render, screen } from '@/test/test-utils';
import { CollectionDetailPage } from '@/pages/CollectionDetailPage';

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return {
    ...actual,
    useParams: vi.fn(),
  };
});

vi.mock('@/hooks/use-collections', () => ({
  useCollection: vi.fn().mockReturnValue({
    data: {
      id: 'test-collection-id',
      name: 'Test Collection With A Reasonably Long Name For Mobile Testing',
      description: 'Test description',
      dataset_count: 5,
      extent_bbox: [-180, -90, 180, 90],
      temporal_start: '2020-01-01',
      temporal_end: '2024-12-31',
      created_at: '2023-01-01T00:00:00Z',
      updated_at: '2024-06-15T00:00:00Z',
    },
    isLoading: false,
    error: null,
  }),
  useRemoveDatasetFromCollection: vi.fn().mockReturnValue({
    mutateAsync: vi.fn(),
  }),
}));

vi.mock('@/components/collections/CollectionDatasetList', () => ({
  CollectionDatasetList: () => <div data-testid="collection-dataset-list-stub" />,
}));

vi.mock('@/components/collections/CollectionMembershipManager', () => ({
  CollectionMembershipManager: () => <div data-testid="collection-membership-manager-stub" />,
}));

vi.mock('@/components/collections/CollectionEditDialog', () => ({
  CollectionEditDialog: () => null,
}));

vi.mock('@/components/collections/CollectionDeleteDialog', () => ({
  CollectionDeleteDialog: () => null,
}));

vi.mock('@/components/layout/BBoxPreview', () => ({
  BBoxPreview: () => <div data-testid="bbox-preview-stub" />,
}));

const mockUseParams = vi.mocked(useParams);

beforeEach(() => {
  mockUseParams.mockReturnValue({ id: 'test-collection-id' });
});

describe('CollectionDetailPage semantics', () => {
  it('COLL-01: metadata card uses dl semantics', () => {
    const { container } = render(<CollectionDetailPage />);

    const dl = container.querySelector('dl');
    expect(dl).not.toBeNull();

    const dts = dl!.querySelectorAll('dt');
    expect(dts.length).toBeGreaterThanOrEqual(4);

    const dds = dl!.querySelectorAll('dd');
    expect(dds.length).toBeGreaterThanOrEqual(4);
  });

  it('COLL-02: header title supports word wrapping', () => {
    render(<CollectionDetailPage />);

    const h1 = screen.getByRole('heading', { level: 1 });
    expect(h1.className).toContain('break-words');
    expect(h1.className).not.toContain('truncate');
  });

  it('COLL-03: page uses flat layout, not tabs', () => {
    const { container } = render(<CollectionDetailPage />);

    expect(screen.queryByRole('tablist')).toBeNull();
    expect(container.querySelector('[data-slot="tabs"]')).toBeNull();
  });
});
