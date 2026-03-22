import { render, screen } from '@testing-library/react';
import { QualityScoreCard } from '@/components/dataset/QualityScoreCard';

describe('QualityScoreCard', () => {
  const baseQualityScore = {
    overall: 87,
    metadata_completeness: 90,
    geometry_validity: 92,
    attribute_completeness: 81,
    crs_defined: 100,
    computed_at: '2026-03-01T12:00:00Z',
  };

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-03-05T12:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders fresh quality state with timestamp, relative age, and cadence guidance', () => {
    render(<QualityScoreCard qualityScore={baseQualityScore} updateFrequency="annually" />);

    expect(screen.getByTestId('quality-freshness-time')).toHaveTextContent('Mar 1, 2026');
    expect(screen.getByTestId('quality-freshness-time')).toHaveTextContent('4 days ago');
    expect(screen.getByTestId('quality-freshness-badge')).toHaveTextContent('Fresh');
    expect(screen.getByTestId('quality-cadence-guidance')).toHaveTextContent('Expected annual refresh cadence.');
    expect(screen.queryByTestId('quality-remediation-hint')).not.toBeInTheDocument();
  });

  it('marks stale freshness and shows remediation guidance when score age exceeds cadence threshold', () => {
    render(
      <QualityScoreCard
        qualityScore={{ ...baseQualityScore, computed_at: '2025-12-01T12:00:00Z' }}
        updateFrequency="monthly"
      />,
    );

    expect(screen.getByTestId('quality-freshness-badge')).toHaveTextContent('Stale');
    expect(screen.getByTestId('quality-cadence-guidance')).toHaveTextContent('Expected monthly refresh cadence.');
    expect(screen.getByTestId('quality-remediation-hint')).toBeInTheDocument();
  });

  it('shows missing freshness state and unknown cadence guidance when computed time is absent', () => {
    render(
      <QualityScoreCard
        qualityScore={{ ...baseQualityScore, computed_at: null as unknown as string }}
        updateFrequency="unmapped-frequency"
      />,
    );

    expect(screen.getByTestId('quality-freshness-badge')).toHaveTextContent('Freshness missing');
    expect(screen.getByTestId('quality-freshness-time')).toHaveTextContent('Not available');
    expect(screen.getByTestId('quality-freshness-time')).toHaveTextContent('Unknown age');
    expect(screen.getByTestId('quality-cadence-guidance')).toHaveTextContent(
      'Cadence is unknown; confirm the refresh schedule.',
    );
    expect(screen.getByTestId('quality-remediation-hint')).toBeInTheDocument();
  });

  it('maps cadence guidance for daily, monthly, annually, and unknown frequencies', () => {
    const { rerender } = render(
      <QualityScoreCard qualityScore={baseQualityScore} updateFrequency="daily" />,
    );
    expect(screen.getByTestId('quality-cadence-guidance')).toHaveTextContent('Expected daily refresh cadence.');

    rerender(<QualityScoreCard qualityScore={baseQualityScore} updateFrequency="monthly" />);
    expect(screen.getByTestId('quality-cadence-guidance')).toHaveTextContent('Expected monthly refresh cadence.');

    rerender(<QualityScoreCard qualityScore={baseQualityScore} updateFrequency="annually" />);
    expect(screen.getByTestId('quality-cadence-guidance')).toHaveTextContent('Expected annual refresh cadence.');

    rerender(<QualityScoreCard qualityScore={baseQualityScore} updateFrequency="unknown" />);
    expect(screen.getByTestId('quality-cadence-guidance')).toHaveTextContent(
      'Cadence is unknown; confirm the refresh schedule.',
    );
  });
});
