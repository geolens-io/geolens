import { render, screen } from '@/test/test-utils';
import { IngestWarningsBanner } from '../IngestWarningsBanner';
import type { IngestJobWarning } from '@/types/api';

function job(warnings: IngestJobWarning[]) {
  return {
    warnings,
    archive_failed: false,
    temporal_parse_errors: {},
  };
}

describe('IngestWarningsBanner', () => {
  it('renders nothing when the job has no warnings', () => {
    const { container } = render(<IngestWarningsBanner job={job([])} />);
    expect(container).toBeEmptyDOMElement();
  });

  // fix(#888): the Mercator clamp used to destroy geometry in silence.
  it('names the dropped feature count for a mercator_clip warning', () => {
    render(
      <IngestWarningsBanner
        job={job([
          {
            kind: 'mercator_clip',
            details: { dropped_features: 12, clipped_features: 3 },
          },
        ])}
      />,
    );

    expect(
      screen.getByText('Geometry outside the Web Mercator latitude limit'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('12 features lost their geometry entirely'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('3 features were trimmed at ±85.06° latitude'),
    ).toBeInTheDocument();
  });

  it('uses the singular form for a single dropped feature', () => {
    render(
      <IngestWarningsBanner
        job={job([
          {
            kind: 'mercator_clip',
            details: { dropped_features: 1, clipped_features: 0 },
          },
        ])}
      />,
    );

    expect(
      screen.getByText('1 feature lost its geometry entirely'),
    ).toBeInTheDocument();
    // A zero clipped count must not render an empty bullet.
    expect(screen.queryByText(/trimmed at/)).not.toBeInTheDocument();
  });

  it('still renders the pre-existing warning kinds', () => {
    render(
      <IngestWarningsBanner
        job={job([
          { kind: 'reserved_rename', details: [{ original: 'geom', renamed: 'src_geom' }] },
          {
            kind: 'dbf_truncation_collision',
            details: [{ truncated: 'population', originals: ['population_2020', 'population_2021'] }],
          },
        ])}
      />,
    );

    expect(
      screen.getByText('Reserved column names renamed'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Shapefile field name collisions'),
    ).toBeInTheDocument();
  });
});
