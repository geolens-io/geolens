import { render, screen } from '@/test/test-utils';
import type { SourceFreshness, SourceHealth } from '@/types/api';
import { FreshnessChip, HealthChip } from '../SourceStateChips';

describe('FreshnessChip', () => {
  it.each([
    ['fresh', 'Source fresh', 'text-success'],
    ['due', 'Source refresh due', 'text-info'],
    ['overdue', 'Source refresh overdue', 'text-warning'],
  ] satisfies Array<[Exclude<SourceFreshness, 'unknown'>, string, string]>)(
    'renders the %s state with visible text, an icon, and semantic color',
    (state, label, colorClass) => {
      render(<FreshnessChip state={state} />);

      const chip = screen.getByTestId('source-freshness-chip');
      expect(chip).toHaveAttribute('data-state', state);
      expect(chip).toHaveTextContent(label);
      expect(chip).toHaveAttribute('title');
      expect(chip).toHaveClass(colorClass);
      expect(chip.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
    },
  );

  it('renders nothing for unknown freshness', () => {
    const { container } = render(<FreshnessChip state="unknown" />);

    expect(screen.queryByTestId('source-freshness-chip')).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });
});

describe('HealthChip', () => {
  it.each([
    ['healthy', 'Source healthy', 'text-success'],
    ['missing', 'Source missing', 'text-destructive'],
    ['inaccessible', 'Source inaccessible', 'text-warning'],
  ] satisfies Array<[Exclude<SourceHealth, 'unknown'>, string, string]>)(
    'renders the %s state with visible text, an icon, and semantic color',
    (state, label, colorClass) => {
      render(<HealthChip state={state} />);

      const chip = screen.getByTestId('source-health-chip');
      expect(chip).toHaveAttribute('data-state', state);
      expect(chip).toHaveTextContent(label);
      expect(chip).toHaveAttribute('title');
      expect(chip).toHaveClass(colorClass);
      expect(chip.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
    },
  );

  it('renders nothing for unknown health', () => {
    const { container } = render(<HealthChip state="unknown" />);

    expect(screen.queryByTestId('source-health-chip')).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });
});
