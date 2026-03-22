import { render, screen } from '@/test/test-utils';
import { LoadingState } from '../LoadingState';

describe('LoadingState', () => {
  it('renders spinner', () => {
    const { container } = render(<LoadingState />);
    const spinner = container.querySelector('.animate-spin');
    expect(spinner).toBeInTheDocument();
  });

  it('renders message when provided', () => {
    render(<LoadingState message="Loading datasets..." />);
    expect(screen.getByText('Loading datasets...')).toBeInTheDocument();
  });

  it('does not render message when omitted', () => {
    const { container } = render(<LoadingState />);
    const paragraphs = container.querySelectorAll('p');
    expect(paragraphs).toHaveLength(0);
  });

  it('merges custom className', () => {
    const { container } = render(<LoadingState className="py-24" />);
    expect(container.firstChild).toHaveClass('py-24');
  });
});
