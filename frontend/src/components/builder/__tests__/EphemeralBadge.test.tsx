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

  // fix(#1076): a clip filters rows, so the server reports no source total for
  // it and the honest answer to "of how many?" is unknown. Falling back to the
  // plain count presented a capped preview as the complete result.
  it('says the result was capped when no total is known', () => {
    render(<EphemeralBadge featureCount={500} truncated onDismiss={vi.fn()} />);
    expect(screen.getByText('Result · first 500 features')).toBeInTheDocument();
  });

  // The other direction matters as much: a badge that fires on an uncapped
  // preview has traded a silent truncation for a wrong one.
  it('says nothing about a cap when the preview was complete', () => {
    render(<EphemeralBadge featureCount={500} onDismiss={vi.fn()} />);
    expect(screen.getByText('Result · 500 features')).toBeInTheDocument();
    expect(screen.queryByText(/first/)).not.toBeInTheDocument();
    expect(screen.queryByText(/of/)).not.toBeInTheDocument();
  });

  it('keeps the "N of M" form when the total IS known', () => {
    render(
      <EphemeralBadge featureCount={500} totalCount={10651} truncated onDismiss={vi.fn()} />
    );
    // Unchanged by #1076 — only the total-less case is new.
    expect(screen.getByText('Result · 500 of 10,651 features')).toBeInTheDocument();
  });

  // fix(#787 item 1): the badge sat at z-[8], under every z-10 PluginHost slot, so
  // an open plugin panel taller than the bottom-left offset covered it.
  it('stacks above the PluginHost slots', () => {
    const { container } = render(<EphemeralBadge featureCount={1} onDismiss={vi.fn()} />);
    expect(container.firstElementChild).toHaveClass('z-20');
  });
});
