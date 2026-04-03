import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@/components/ui/tooltip';
import { AppLayout } from '../AppLayout';
import { useEdition } from '@/hooks/use-edition';
import { useBranding } from '@/hooks/use-settings';

vi.mock('@/hooks/use-edition', () => ({
  useEdition: vi.fn(),
}));

vi.mock('@/hooks/use-settings', () => ({
  useBranding: vi.fn(),
}));

const mockedUseEdition = vi.mocked(useEdition);
const mockedUseBranding = vi.mocked(useBranding);

function renderAppLayout(initialEntries: string[] = ['/']) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <MemoryRouter initialEntries={initialEntries}>
          <AppLayout />
        </MemoryRouter>
      </TooltipProvider>
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
    mockedUseBranding.mockReturnValue({
      data: { show_badge: true },
    } as ReturnType<typeof useBranding>);
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

  it('hides footer badge in enterprise mode when show_badge is false', () => {
    mockedUseEdition.mockReturnValue({
      edition: 'enterprise',
      features: ['branding'],
      isEnterprise: true,
      isLoading: false,
    });
    mockedUseBranding.mockReturnValue({
      data: { show_badge: false },
    } as ReturnType<typeof useBranding>);
    renderAppLayout();
    expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
  });

  it('shows footer badge in enterprise mode when show_badge is true', () => {
    mockedUseEdition.mockReturnValue({
      edition: 'enterprise',
      features: ['branding'],
      isEnterprise: true,
      isLoading: false,
    });
    mockedUseBranding.mockReturnValue({
      data: { show_badge: true },
    } as ReturnType<typeof useBranding>);
    renderAppLayout();
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
  });

  it('always shows footer badge in community mode regardless of branding setting', () => {
    mockedUseBranding.mockReturnValue({
      data: { show_badge: false },
    } as ReturnType<typeof useBranding>);
    renderAppLayout();
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
  });

  it('moves focus to the main landmark when the skip link is activated', async () => {
    const user = userEvent.setup();
    renderAppLayout();

    const skipLink = screen.getByRole('link', { name: /skip to main content/i });
    const main = screen.getByRole('main');

    await user.click(skipLink);

    expect(main).toHaveFocus();
    expect(main).toHaveAttribute('id', 'main-content');
    expect(main).toHaveAttribute('tabindex', '-1');
  });
});
