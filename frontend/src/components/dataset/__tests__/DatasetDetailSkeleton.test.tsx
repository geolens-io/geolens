import { render, screen } from '@/test/test-utils';
import { DatasetDetailSkeleton } from '../DatasetDetailSkeleton';

describe('DatasetDetailSkeleton', () => {
  it('renders hero skeleton with h-80 class by default', () => {
    render(<DatasetDetailSkeleton />);

    const hero = screen.getByTestId('hero-skeleton');
    expect(hero.className).toContain('h-80');
    expect(hero.className).not.toContain('h-[60vh]');
  });

  it('renders hero skeleton with h-[60vh] class when isTable is true', () => {
    render(<DatasetDetailSkeleton isTable />);

    const hero = screen.getByTestId('hero-skeleton');
    expect(hero.className).toContain('h-[60vh]');
    expect(hero.className).not.toContain('h-80');
  });
});
