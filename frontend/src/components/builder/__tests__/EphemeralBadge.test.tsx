import { render, screen } from '@/test/test-utils';
import { EphemeralBadge } from '../EphemeralBadge';

// fix(#788): the badge strings carry plural variants and locale-grouped
// numbers ({{count, number}} / {{total, number}}) — these tests pin the
// singular form and the grouping of BOTH numbers in the truncated sentence
// (previously the pre-grouped total sat next to an ungrouped count).
describe('EphemeralBadge', () => {
  it('renders the singular form for a single feature', () => {
    render(<EphemeralBadge featureCount={1} onDismiss={vi.fn()} />);
    expect(screen.getByText('Result · 1 feature')).toBeInTheDocument();
  });

  it('locale-groups the plural feature count', () => {
    render(<EphemeralBadge featureCount={5000} onDismiss={vi.fn()} />);
    expect(screen.getByText('Result · 5,000 features')).toBeInTheDocument();
  });

  it('locale-groups count AND total consistently in the truncated sentence', () => {
    render(
      <EphemeralBadge
        featureCount={5000}
        totalCount={250000}
        truncated
        onDismiss={vi.fn()}
      />
    );
    expect(screen.getByText('Result · 5,000 of 250,000 features')).toBeInTheDocument();
  });

  // fix(#787 item 1): the badge sat at z-[8], under every z-10 PluginHost slot, so
  // an open plugin panel taller than the bottom-left offset covered it.
  it('stacks above the PluginHost slots', () => {
    const { container } = render(<EphemeralBadge featureCount={1} onDismiss={vi.fn()} />);
    expect(container.firstElementChild).toHaveClass('z-20');
  });
});
