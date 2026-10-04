import { render, screen } from '@/test/test-utils';
import { Pagination } from '../Pagination';

describe('Pagination', () => {
  it('is a named navigation landmark', () => {
    render(<Pagination total={120} offset={0} limit={20} onPageChange={vi.fn()} />);
    expect(screen.getByRole('navigation', { name: 'Pagination' })).toBeInTheDocument();
  });
});
