import { render, screen } from '@/test/test-utils';
import { ErrorState } from '../ErrorState';

describe('ErrorState', () => {
  it('renders error message', () => {
    render(<ErrorState message="Something broke" />);
    expect(screen.getByText('Something broke')).toBeInTheDocument();
  });

  it('renders title when provided', () => {
    render(<ErrorState message="Something broke" title="Not Found" />);
    expect(screen.getByText('Not Found')).toBeInTheDocument();
  });

  it('does not render title when omitted', () => {
    const { container } = render(<ErrorState message="Something broke" />);
    const headings = container.querySelectorAll('h2');
    expect(headings).toHaveLength(0);
  });

  it('renders action when provided', () => {
    render(<ErrorState message="Something broke" action={<button>Retry</button>} />);
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('uses destructive border and background styling', () => {
    const { container } = render(<ErrorState message="Something broke" />);
    expect(container.firstChild).toHaveClass('border-destructive/30');
    expect(container.firstChild).toHaveClass('bg-destructive/5');
  });

  it('merges custom className', () => {
    const { container } = render(<ErrorState message="Something broke" className="my-8" />);
    expect(container.firstChild).toHaveClass('my-8');
  });
});
