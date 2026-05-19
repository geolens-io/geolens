import { render, screen } from '@/test/test-utils';
import { AdminSamlPage } from '@/pages/admin/AdminSamlPage';

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

vi.mock('@/hooks/use-edition', () => ({
  useEdition: vi.fn(),
}));

vi.mock('@/components/admin/saml/SamlProvidersSection', () => ({
  SamlProvidersSection: () => <div data-testid="saml-providers-section">SAML Providers</div>,
}));

import { useEdition } from '@/hooks/use-edition';
const mockUseEdition = vi.mocked(useEdition);

describe('AdminSamlPage', () => {
  it('community edition: renders enterprise-only notice with docs link (not SamlProvidersSection)', () => {
    mockUseEdition.mockReturnValue({
      edition: 'community',
      features: [],
      isEnterprise: false,
      isLoading: false,
    });

    render(<AdminSamlPage />, { route: '/admin/saml' });

    // The notice heading should be present
    const heading = screen.getByRole('heading', { level: 2 });
    expect(heading.textContent).toMatch(/enterprise/i);
    // The docs link must point to the SAML enterprise docs
    const link = screen.getByRole('link', { name: /docs/i });
    expect(link).toHaveAttribute('href', 'https://docs.getgeolens.com/guides/enterprise/saml/');
    // SamlProvidersSection must NOT render (community must not hit gated API)
    expect(screen.queryByTestId('saml-providers-section')).not.toBeInTheDocument();
  });

  it('enterprise edition: renders SamlProvidersSection, not the enterprise-only notice', () => {
    mockUseEdition.mockReturnValue({
      edition: 'enterprise',
      features: [],
      isEnterprise: true,
      isLoading: false,
    });

    render(<AdminSamlPage />, { route: '/admin/saml' });

    expect(screen.getByTestId('saml-providers-section')).toBeInTheDocument();
    // The enterprise-only h2 notice must not appear
    expect(screen.queryByRole('heading', { level: 2 })).not.toBeInTheDocument();
  });

  it('loading state: renders LoadingState while edition resolves', () => {
    mockUseEdition.mockReturnValue({
      edition: 'community',
      features: [],
      isEnterprise: false,
      isLoading: true,
    });

    render(<AdminSamlPage />, { route: '/admin/saml' });

    // Neither the providers section nor the enterprise-only notice should appear
    expect(screen.queryByTestId('saml-providers-section')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2 })).not.toBeInTheDocument();
  });

  it('no redirect regression: community edition stays at /admin/saml (no Navigate away)', () => {
    mockUseEdition.mockReturnValue({
      edition: 'community',
      features: [],
      isEnterprise: false,
      isLoading: false,
    });

    render(<AdminSamlPage />, { route: '/admin/saml' });

    // The enterprise-only notice is visible — this proves no redirect fired.
    // If Navigate to /admin had fired, the notice would not be in the document
    // (the component would have unmounted itself via navigation).
    const link = screen.getByRole('link', { name: /docs/i });
    expect(link).toBeInTheDocument();
    // SamlProvidersSection must not appear
    expect(screen.queryByTestId('saml-providers-section')).not.toBeInTheDocument();
  });
});
