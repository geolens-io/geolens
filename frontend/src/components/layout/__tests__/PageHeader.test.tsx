import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { PageHeader } from '../PageHeader';

function renderWithRouter(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe('PageHeader', () => {
  it('renders title', () => {
    renderWithRouter(<PageHeader title="Datasets" />);
    expect(screen.getByRole('heading', { name: 'Datasets' })).toBeInTheDocument();
  });

  it('renders description when provided', () => {
    renderWithRouter(<PageHeader title="Datasets" description="Browse all datasets" />);
    expect(screen.getByText('Browse all datasets')).toBeInTheDocument();
  });

  it('does not render description when omitted', () => {
    const { container } = renderWithRouter(<PageHeader title="Datasets" />);
    const muted = container.querySelector('p.text-muted-foreground');
    expect(muted).not.toBeInTheDocument();
  });

  it('renders back-link when provided', () => {
    renderWithRouter(
      <PageHeader title="Dataset" backLink={{ to: '/', label: 'Back to search' }} />,
    );
    const link = screen.getByRole('link', { name: /Back to search/ });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/');
  });

  it('does not render back-link when omitted', () => {
    renderWithRouter(<PageHeader title="Datasets" />);
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('renders actions when provided', () => {
    renderWithRouter(<PageHeader title="Datasets" actions={<button>Delete</button>} />);
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument();
  });

  it('uses font-semibold on title (not font-bold)', () => {
    renderWithRouter(<PageHeader title="Datasets" />);
    const heading = screen.getByRole('heading', { name: 'Datasets' });
    expect(heading).toHaveClass('font-semibold');
    expect(heading).not.toHaveClass('font-bold');
  });

  it('renders breadcrumbs when provided', () => {
    renderWithRouter(
      <PageHeader
        title="Parcels"
        breadcrumbs={[{ label: 'Collections', to: '/collections' }]}
      />,
    );
    const nav = screen.getByRole('navigation', { name: 'breadcrumb' });
    expect(nav).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Collections' });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/collections');
    // Current page title appears as non-link text
    expect(screen.getByText('Parcels', { selector: '[data-slot="breadcrumb-page"]' })).toBeInTheDocument();
  });

  it('renders backLink when both backLink and breadcrumbs provided', () => {
    renderWithRouter(
      <PageHeader
        title="Parcels"
        backLink={{ to: '/', label: 'Back' }}
        breadcrumbs={[{ label: 'Collections', to: '/collections' }]}
      />,
    );
    // backLink wins -- ArrowLeft link renders
    const backLink = screen.getByRole('link', { name: /Back/ });
    expect(backLink).toBeInTheDocument();
    expect(backLink).toHaveAttribute('href', '/');
    // breadcrumb nav should not render
    expect(screen.queryByRole('navigation', { name: 'breadcrumb' })).not.toBeInTheDocument();
  });
});
