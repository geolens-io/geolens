import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AppLayout } from '../AppLayout';
import { useEdition } from '@/hooks/use-edition';

vi.mock('@/hooks/use-edition', () => ({
  useEdition: vi.fn(),
}));

const mockedUseEdition = vi.mocked(useEdition);

function renderAppLayout(initialEntries: string[] = ['/']) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <AppLayout />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AppLayout', () => {
  beforeEach(() => {
    mockedUseEdition.mockReturnValue({
      edition: 'community',
      features: [],
      isEnterprise: false,
      isLoading: false,
    });
  });

  it('renders footer with Powered by GeoLens in community mode', () => {
    renderAppLayout();
    const footer = screen.getByRole('contentinfo');
    expect(footer).toBeInTheDocument();
    expect(footer).toHaveTextContent('Powered by GeoLens');
  });

  it('footer links to GitHub repository with correct attributes', () => {
    renderAppLayout();
    const link = screen.getByRole('link', { name: /powered by geolens/i });
    expect(link).toHaveAttribute('href', 'https://github.com/geolens-io/geolens');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('hides footer on dataset detail pages', () => {
    renderAppLayout(['/datasets/abc-123']);
    expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
  });

  it('hides footer badge in enterprise mode', () => {
    mockedUseEdition.mockReturnValue({
      edition: 'enterprise',
      features: ['branding'],
      isEnterprise: true,
      isLoading: false,
    });
    renderAppLayout();
    expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
  });
});
