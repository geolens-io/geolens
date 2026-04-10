import userEvent from '@testing-library/user-event';
import { render, screen } from '@/test/test-utils';
import { CollectionsPage } from '@/pages/CollectionsPage';
import { useCollections } from '@/hooks/use-collections';
import { useAuthStore } from '@/stores/auth-store';
import type { UserResponse } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('@/hooks/use-collections', () => ({
  useCollections: vi.fn(),
}));

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

vi.mock('@/components/collections/CollectionCard', () => ({
  CollectionCard: ({ collection }: { collection: { name: string } }) => <div>{collection.name}</div>,
}));

vi.mock('@/components/collections/CollectionCardSkeleton', () => ({
  CollectionCardSkeleton: () => <div>loading</div>,
}));

vi.mock('@/components/collections/CollectionCreateDialog', () => ({
  CollectionCreateDialog: ({ open }: { open: boolean }) => (
    <div data-testid="collection-create-dialog">{open ? 'open' : 'closed'}</div>
  ),
}));

const mockUseCollections = vi.mocked(useCollections);

const EDITOR_USER: UserResponse = {
  id: 'user-editor',
  username: 'editor-user',
  email: 'editor@example.com',
  is_active: true,
  status: 'active',
  last_login_at: null,
  created_at: '2026-03-01T00:00:00Z',
  roles: ['editor'],
};

describe('CollectionsPage', () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: 'token',
      refreshToken: 'refresh-token',
      expiresAt: Date.now() + 60_000,
      user: EDITOR_USER,
    });

    mockUseCollections.mockReturnValue({
      data: {
        collections: [
          {
            id: 'collection-1',
            name: 'Transit',
            description: null,
            dataset_count: 4,
            created_at: '2026-03-01T00:00:00Z',
            updated_at: '2026-03-02T00:00:00Z',
          },
        ],
        total: 1,
      },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useCollections>);
  });

  afterEach(() => {
    useAuthStore.getState().logout();
  });

  it('shows a page-local create action for editors and opens the dialog from the header', async () => {
    const user = userEvent.setup();

    render(<CollectionsPage />, { route: '/collections' });

    expect(screen.getByRole('button', { name: 'newCollection' })).toBeInTheDocument();
    expect(screen.getByTestId('collection-create-dialog')).toHaveTextContent('closed');

    await user.click(screen.getByRole('button', { name: 'newCollection' }));

    expect(screen.getByTestId('collection-create-dialog')).toHaveTextContent('open');
  });
});
