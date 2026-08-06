import { render, screen } from '@/test/test-utils';
import { EphemeralBadge } from '../EphemeralBadge';

// fix(#1009): still live, and every case below still load-bearing. The badge
// stopped being the builder's wide-layout surface (that is the ephemeral stack
// row now) but remains the surface for the public viewer and the builder's
// <1100px rail, neither of which has a layer stack to host a row. Nothing here
// was builder-specific: the count strings are shared with the row via
// ephemeral-preview.ts, and the z-20 case still guards the rail layout, where
// PluginHost's bottom-left slot is a real neighbour.
//
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

  // fix(#727): the honest-partial-result state this issue exists to fix — a
  // capped preview reads as a failed operation unless the badge (and the
  // stack row it shares copy with, via ephemeral-preview.ts) discloses BOTH
  // that it is partial and what it is partial AGAINST. A viewport-scoped
  // total names the extent instead of implying it describes the whole
  // dataset the way an unscoped total does.
  it('names the previewed extent when the total was computed against it', () => {
    // fix(#727 codex round 6): "previewed extent", not "in view" — by the
    // time this badge renders, useEphemeralLayers' fitBounds() has often
    // already re-fit the map to the RESULT geometry's own (possibly much
    // smaller) bbox, so "in view" would claim a current-tense fact that fit
    // already made false. "Previewed extent" names what the total is scoped
    // to without claiming it still matches the screen.
    render(
      <EphemeralBadge
        featureCount={180}
        totalCount={22324}
        truncated
        viewportScoped
        onDismiss={vi.fn()}
      />
    );
    expect(
      screen.getByText('Result · 180 of 22,324 features in the previewed extent'),
    ).toBeInTheDocument();
    // Not the unscoped sentence — the two must never render side by side.
    expect(screen.queryByText('Result · 180 of 22,324 features')).not.toBeInTheDocument();
  });

  it('does not claim viewport scoping when the total is whole-dataset', () => {
    render(
      <EphemeralBadge featureCount={500} totalCount={22324} truncated onDismiss={vi.fn()} />
    );
    expect(screen.getByText('Result · 500 of 22,324 features')).toBeInTheDocument();
    expect(screen.queryByText(/previewed extent/)).not.toBeInTheDocument();
  });

  it('ignores viewportScoped when the result is not truncated', () => {
    // A complete result has nothing to be honest ABOUT — viewportScoped with
    // no truncation must not leak "previewed extent" onto an ordinary count.
    render(
      <EphemeralBadge featureCount={42} viewportScoped onDismiss={vi.fn()} />
    );
    expect(screen.getByText('Result · 42 features')).toBeInTheDocument();
  });

  // fix(#787 item 1): the badge sat at z-[8], under every z-10 PluginHost slot, so
  // an open plugin panel taller than the bottom-left offset covered it.
  it('stacks above the PluginHost slots', () => {
    const { container } = render(<EphemeralBadge featureCount={1} onDismiss={vi.fn()} />);
    expect(container.firstElementChild).toHaveClass('z-20');
  });
});
