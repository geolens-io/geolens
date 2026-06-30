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
  it('default runtime: renders unavailable notice without loading SamlProvidersSection', () => {
    mockUseEdition.mockReturnValue({
      edition: 'community',
      features: [],
      isEnterprise: false,
      isMultiTenant: false,
      isLoading: false,
    });

    render(<AdminSamlPage />, { route: '/admin/saml' });

    // The notice heading should be present.
    const heading = screen.getByRole('heading', { level: 2 });
    expect(heading.textContent).toMatch(/saml is not available/i);
    expect(screen.getByText(/supports local accounts and OAuth providers/i)).toBeInTheDocument();
    // SamlProvidersSection must NOT render (default runtime must not hit gated API).
    expect(screen.queryByTestId('saml-providers-section')).not.toBeInTheDocument();
  });

  it('SAML-enabled runtime: renders SamlProvidersSection, not the unavailable notice', () => {
    mockUseEdition.mockReturnValue({
      edition: 'enterprise',
      features: [],
      isEnterprise: true,
      isMultiTenant: false,
      isLoading: false,
    });

    render(<AdminSamlPage />, { route: '/admin/saml' });

    expect(screen.getByTestId('saml-providers-section')).toBeInTheDocument();
    // The unavailable h2 notice must not appear.
    expect(screen.queryByRole('heading', { level: 2 })).not.toBeInTheDocument();
  });

  it('loading state: renders LoadingState while edition resolves', () => {
    mockUseEdition.mockReturnValue({
      edition: 'community',
      features: [],
      isEnterprise: false,
      isMultiTenant: false,
      isLoading: true,
    });

    render(<AdminSamlPage />, { route: '/admin/saml' });

    // Neither the providers section nor the unavailable notice should appear.
    expect(screen.queryByTestId('saml-providers-section')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2 })).not.toBeInTheDocument();
  });

  it('no redirect regression: default runtime stays at /admin/saml (no Navigate away)', () => {
    mockUseEdition.mockReturnValue({
      edition: 'community',
      features: [],
      isEnterprise: false,
      isMultiTenant: false,
      isLoading: false,
    });

    render(<AdminSamlPage />, { route: '/admin/saml' });

    // The unavailable notice is visible, which proves no redirect fired.
    // If Navigate to /admin had fired, the notice would not be in the document
    // (the component would have unmounted itself via navigation).
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(/saml is not available/i);
    expect(screen.getByText(/supports local accounts and OAuth providers/i)).toBeInTheDocument();
    // SamlProvidersSection must not appear.
    expect(screen.queryByTestId('saml-providers-section')).not.toBeInTheDocument();
  });
});
