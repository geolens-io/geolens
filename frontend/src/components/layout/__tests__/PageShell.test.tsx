import { render, screen } from '@testing-library/react';
import { PageShell } from '../PageShell';

describe('PageShell', () => {
  it('renders children', () => {
    render(<PageShell><p>Hello</p></PageShell>);
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });

  it('applies default max-width (max-w-7xl)', () => {
    const { container } = render(<PageShell><p>Content</p></PageShell>);
    expect(container.firstChild).toHaveClass('max-w-7xl');
  });

  it('applies narrow max-width (max-w-4xl)', () => {
    const { container } = render(<PageShell maxWidth="narrow"><p>Content</p></PageShell>);
    expect(container.firstChild).toHaveClass('max-w-4xl');
  });

  it('applies consistent padding and spacing', () => {
    const { container } = render(<PageShell><p>Content</p></PageShell>);
    expect(container.firstChild).toHaveClass('px-6');
    expect(container.firstChild).toHaveClass('py-4');
    expect(container.firstChild).toHaveClass('space-y-4');
  });

  it('merges custom className', () => {
    const { container } = render(<PageShell className="mt-10"><p>Content</p></PageShell>);
    expect(container.firstChild).toHaveClass('mt-10');
  });
});
