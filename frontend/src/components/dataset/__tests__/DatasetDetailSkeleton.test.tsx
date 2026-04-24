import { render, screen } from '@/test/test-utils';
import { DatasetDetailSkeleton } from '../DatasetDetailSkeleton';

describe('DatasetDetailSkeleton', () => {
  it('renders hero skeleton with h-96 class by default', () => {
    render(<DatasetDetailSkeleton />);

    const hero = screen.getByTestId('hero-skeleton');
    expect(hero.className).toContain('h-96');
  });

  it('renders compact card placeholder when isTable is true', () => {
    render(<DatasetDetailSkeleton isTable />);

    // Table skeleton should not have the tall map hero
    expect(screen.queryByTestId('hero-skeleton')).not.toBeInTheDocument();

    // Should render the compact card placeholder with border
    const card = document.querySelector('.rounded-lg.border.bg-muted\\/20');
    expect(card).toBeInTheDocument();
  });
});
