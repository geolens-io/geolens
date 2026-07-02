import { render, screen } from '@/test/test-utils';
import { AdminOverviewPage } from '@/pages/admin/AdminOverviewPage';

// Mock StatsOverview since its internals are tested separately and can pull
// in heavy query dependencies.
vi.mock('@/components/admin/StatsOverview', () => ({
  StatsOverview: () => <div data-testid="stats-overview">Stats</div>,
}));

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

const useEditionMock = vi.fn(() => ({
  edition: 'community' as 'community' | 'enterprise',
  features: [] as string[],
  isEnterprise: false,
  isMultiTenant: false,
  isLoading: false,
}));
vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => useEditionMock(),
}));

describe('AdminOverviewPage', () => {
  it('renders the page header with the overview title', () => {
    render(<AdminOverviewPage />);

    // PageHeader renders a level-1 heading with the title
    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading).toBeInTheDocument();
    expect(heading.textContent).toBeTruthy();
  });

  it('renders the stats overview region', () => {
    render(<AdminOverviewPage />);

    expect(screen.getByTestId('stats-overview')).toBeInTheDocument();
  });

  it('renders the breadcrumbs navigation', () => {
    render(<AdminOverviewPage />);

    // PageHeader exposes breadcrumbs inside a nav landmark
    const nav = screen.getByRole('navigation');
    expect(nav).toBeInTheDocument();
  });

  it('shows the Community edition badge by default', () => {
    render(<AdminOverviewPage />);

    expect(screen.getByText('Community')).toBeInTheDocument();
  });

  it('shows the Enterprise edition badge on enterprise instances', () => {
    useEditionMock.mockReturnValueOnce({
      edition: 'enterprise',
      features: ['sso'],
      isEnterprise: true,
      isMultiTenant: false,
      isLoading: false,
    });
    render(<AdminOverviewPage />);

    expect(screen.getByText('Enterprise')).toBeInTheDocument();
  });

  it('hides the edition badge while the edition query is loading', () => {
    useEditionMock.mockReturnValueOnce({
      edition: 'community',
      features: [],
      isEnterprise: false,
      isMultiTenant: false,
      isLoading: true,
    });
    render(<AdminOverviewPage />);

    expect(screen.queryByText('Community')).not.toBeInTheDocument();
    expect(screen.queryByText('Enterprise')).not.toBeInTheDocument();
  });
});
