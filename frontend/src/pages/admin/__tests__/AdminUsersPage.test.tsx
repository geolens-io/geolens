import { render, screen } from '@/test/test-utils';
import { AdminUsersPage } from '@/pages/admin/AdminUsersPage';

// UserList pulls the live API + filters through TanStack Query; mock to keep
// the page-level test focused on route composition and header structure.
vi.mock('@/components/admin/UserList', () => ({
  UserList: () => <div data-testid="user-list">User list region</div>,
}));

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

describe('AdminUsersPage', () => {
  it('renders the level-1 page heading', () => {
    render(<AdminUsersPage />);

    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading).toBeInTheDocument();
    expect(heading.textContent).toBeTruthy();
  });

  it('renders the breadcrumbs navigation landmark', () => {
    render(<AdminUsersPage />);

    expect(screen.getByRole('navigation')).toBeInTheDocument();
  });

  it('renders the user list region', () => {
    render(<AdminUsersPage />);

    expect(screen.getByTestId('user-list')).toBeInTheDocument();
  });
});
