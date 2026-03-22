import { render, screen } from '@/test/test-utils';
import { CollectionSearchCard } from '../CollectionSearchCard';

describe('CollectionSearchCard', () => {
  const defaultProps = {
    id: 'abc-123',
    title: 'Test Collection',
    description: 'A test collection with datasets',
    datasetCount: 7,
  };

  it('renders the collection title', () => {
    render(<CollectionSearchCard {...defaultProps} />);

    expect(screen.getByText('Test Collection')).toBeInTheDocument();
  });

  it('renders the dataset count badge', () => {
    render(<CollectionSearchCard {...defaultProps} />);

    expect(screen.getByText('7 datasets')).toBeInTheDocument();
  });

  it('renders the collection type badge with amber styling', () => {
    render(<CollectionSearchCard {...defaultProps} />);

    const badge = screen.getByText('Collection');
    expect(badge).toBeInTheDocument();
    expect(badge.closest('[data-slot="badge"]')?.className).toMatch(/bg-amber-100/);
  });

  it('renders the description', () => {
    render(<CollectionSearchCard {...defaultProps} />);

    expect(screen.getByText('A test collection with datasets')).toBeInTheDocument();
  });

  it('links to /collections/:id', () => {
    render(<CollectionSearchCard {...defaultProps} />);

    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', '/collections/abc-123');
  });

  it('omits description when null', () => {
    render(<CollectionSearchCard {...defaultProps} description={null} />);

    expect(screen.queryByText('A test collection with datasets')).not.toBeInTheDocument();
    expect(screen.getByText('Test Collection')).toBeInTheDocument();
  });
});
