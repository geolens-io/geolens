import { render, screen } from '@/test/test-utils';
import { NotFoundPage } from '../NotFoundPage';

describe('NotFoundPage', () => {
  it('renders 404 text', () => {
    render(<NotFoundPage />);
    expect(screen.getByText('404')).toBeInTheDocument();
  });

  it('hides the decorative numeral and keeps it at a readable contrast', () => {
    render(<NotFoundPage />);
    const numeral = screen.getByText('404');
    expect(numeral).toHaveAttribute('aria-hidden', 'true');
    expect(numeral).not.toHaveClass('text-muted-foreground/50');
  });

  it('renders translated title', () => {
    render(<NotFoundPage />);
    expect(screen.getByText('Page not found')).toBeInTheDocument();
  });

  it('renders translated description', () => {
    render(<NotFoundPage />);
    expect(screen.getByText(/does not exist/i)).toBeInTheDocument();
  });

  it('has a link pointing to home', () => {
    render(<NotFoundPage />);
    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', '/');
  });

  it('sets document.title to "Page not found - GeoLens" (ROUTE-02)', () => {
    render(<NotFoundPage />);
    expect(document.title).toBe('Page not found - GeoLens');
  });
});
