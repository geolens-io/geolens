import { render, screen } from '@/test/test-utils';
import { NotFoundPage } from '../NotFoundPage';

describe('NotFoundPage', () => {
  it('renders 404 text', () => {
    render(<NotFoundPage />);
    expect(screen.getByText('404')).toBeInTheDocument();
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
