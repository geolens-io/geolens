import { render, screen } from '@/test/test-utils';
import { AdminGroupsPage } from '@/pages/admin/AdminGroupsPage';

vi.mock('@/components/admin/GroupList', () => ({
  GroupList: () => <div data-testid="group-list">Group list region</div>,
}));

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

describe('AdminGroupsPage', () => {
  it('renders the level-1 page heading and the breadcrumbs landmark', () => {
    render(<AdminGroupsPage />);

    expect(screen.getByRole('heading', { level: 1, name: 'Groups' })).toBeInTheDocument();
    expect(screen.getByRole('navigation')).toBeInTheDocument();
  });

  it('renders the group list region', () => {
    render(<AdminGroupsPage />);

    expect(screen.getByTestId('group-list')).toBeInTheDocument();
  });
});
