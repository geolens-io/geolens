import { fireEvent, render, screen } from '@/test/test-utils';
import {
  useDistributions,
  useSetPrimaryDistribution,
} from '@/components/dataset/hooks/use-records';
import { useTileConfig } from '@/hooks/use-settings';
import { resolveDistributionUrl } from '@/lib/dataset-access';
import {
  DistributionsList,
  getDistributionGroup,
} from '@/components/dataset/DistributionsList';

vi.mock('@/components/dataset/hooks/use-records', () => ({
  useDistributions: vi.fn(),
  useSetPrimaryDistribution: vi.fn(),
}));

vi.mock('@/hooks/use-settings', () => ({
  useTileConfig: vi.fn(),
}));

const mockUseDistributions = vi.mocked(useDistributions);
const mockUseSetPrimaryDistribution = vi.mocked(useSetPrimaryDistribution);
const mockUseTileConfig = vi.mocked(useTileConfig);
const mutate = vi.fn();

/** A manual, non-primary "Viewer App" row alongside the three generated ones
 * used throughout this file — the only shape #1395's control can act on. */
const DISTRIBUTIONS_WITH_MANUAL_ROW = [
  {
    id: 'download-1',
    record_id: 'record-1',
    distribution_type: 'download',
    format: 'gpkg',
    url: '/datasets/1/export?format=gpkg',
    title: 'GeoPackage Download',
    description: null,
    protocol: 'HTTP',
    media_type: 'application/geopackage+sqlite3',
    is_primary: true,
    auto_generated: true,
  },
  {
    id: 'ogc-1',
    record_id: 'record-1',
    distribution_type: 'ogc_features',
    format: 'geojson',
    url: '/collections/1/items',
    title: 'OGC API Features',
    description: null,
    protocol: 'OGC:OAFeat',
    media_type: 'application/geo+json',
    is_primary: false,
    auto_generated: true,
  },
  {
    id: 'app-1',
    record_id: 'record-1',
    distribution_type: 'webApp',
    format: 'html',
    url: 'https://example.com/app',
    title: 'Viewer App',
    description: null,
    protocol: 'HTTPS',
    media_type: 'text/html',
    is_primary: false,
    auto_generated: false,
  },
];

describe('DistributionsList', () => {
  beforeEach(() => {
    mockUseDistributions.mockReturnValue({
      data: {
        distributions: [],
        total: 0,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof useDistributions>);
    mockUseTileConfig.mockReturnValue({
      data: {
        cdn_base_url: null,
        public_app_url: 'https://catalog.example.com',
        public_api_url: 'https://catalog.example.com/api',
        public_base_url: 'https://catalog.example.com',
      },
    } as ReturnType<typeof useTileConfig>);
    mutate.mockReset();
    mockUseSetPrimaryDistribution.mockReturnValue({
      mutate,
      isPending: false,
      variables: undefined,
    } as unknown as ReturnType<typeof useSetPrimaryDistribution>);
  });

  it('maps backend distribution types into stable UI groups', () => {
    expect(getDistributionGroup('download')).toBe('download');
    expect(getDistributionGroup('ogc_features')).toBe('api');
    expect(getDistributionGroup('ogcService')).toBe('api');
    expect(getDistributionGroup('vector_tiles')).toBe('tiles');
    expect(getDistributionGroup('webApp')).toBe('other');
    expect(getDistributionGroup('unexpected_type')).toBe('other');
  });

  it('prefixes relative distribution URLs with the configured public base URL', () => {
    expect(resolveDistributionUrl('/datasets/1/export?format=gpkg', 'https://catalog.example.com/api')).toBe(
      'https://catalog.example.com/api/datasets/1/export?format=gpkg',
    );
    expect(resolveDistributionUrl('collections/1/items', 'https://catalog.example.com/api/')).toBe(
      'https://catalog.example.com/api/collections/1/items',
    );
    expect(resolveDistributionUrl('/tiles/data.example/{z}/{x}/{y}.pbf', 'https://catalog.example.com/api')).toBe(
      'https://catalog.example.com/api/tiles/data.example/{z}/{x}/{y}.pbf',
    );
    expect(resolveDistributionUrl('https://example.com/app', 'https://catalog.example.com/api')).toBe(
      'https://example.com/app',
    );
  });

  it('renders api, tile, and fallback sections from normalized backend types', () => {
    mockUseDistributions.mockReturnValue({
      data: {
        distributions: [
          {
            id: 'download-1',
            record_id: 'record-1',
            distribution_type: 'download',
            format: 'gpkg',
            url: '/datasets/1/export?format=gpkg',
            title: 'GeoPackage Download',
            description: null,
            protocol: 'HTTP',
            media_type: 'application/geopackage+sqlite3',
            is_primary: true,
            auto_generated: true,
          },
          {
            id: 'ogc-1',
            record_id: 'record-1',
            distribution_type: 'ogc_features',
            format: 'geojson',
            url: '/collections/1/items',
            title: 'OGC API Features',
            description: null,
            protocol: 'OGC:OAFeat',
            media_type: 'application/geo+json',
            is_primary: false,
            auto_generated: true,
          },
          {
            id: 'tiles-1',
            record_id: 'record-1',
            distribution_type: 'vector_tiles',
            format: 'pbf',
            url: '/tiles/data.example/{z}/{x}/{y}.pbf',
            title: 'Vector Tiles',
            description: null,
            protocol: 'XYZ',
            media_type: 'application/vnd.mapbox-vector-tile',
            is_primary: false,
            auto_generated: true,
          },
          {
            id: 'app-1',
            record_id: 'record-1',
            distribution_type: 'webApp',
            format: 'html',
            url: 'https://example.com/app',
            title: 'Viewer App',
            description: null,
            protocol: 'HTTPS',
            media_type: 'text/html',
            is_primary: false,
            auto_generated: false,
          },
        ],
        total: 4,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof useDistributions>);

    render(<DistributionsList recordId="record-1" />);

    expect(screen.getByText('Downloads')).toBeInTheDocument();
    expect(screen.getByText('API Endpoints')).toBeInTheDocument();
    expect(screen.getByText('Tile Services')).toBeInTheDocument();
    expect(screen.getByText('Additional Access')).toBeInTheDocument();

    expect(screen.getByText('OGC API Features')).toBeInTheDocument();
    expect(screen.getByText('Vector Tiles')).toBeInTheDocument();
    expect(screen.getByText('Viewer App')).toBeInTheDocument();
    expect(screen.getByText('https://catalog.example.com/api/datasets/1/export?format=gpkg')).toBeInTheDocument();
    expect(screen.getByText('https://catalog.example.com/api/collections/1/items')).toBeInTheDocument();
    expect(screen.getByText('https://catalog.example.com/api/tiles/data.example/{z}/{x}/{y}.pbf')).toBeInTheDocument();
    expect(screen.getByText('https://example.com/app')).toBeInTheDocument();
  });

  // fix(#1856): each distribution row was copyable text only — there was no
  // way to actually fetch the resource without hand-editing the URL.
  it('renders a download link per row that points at the resolved URL', () => {
    mockUseDistributions.mockReturnValue({
      data: { distributions: DISTRIBUTIONS_WITH_MANUAL_ROW, total: 3 },
      isLoading: false,
    } as unknown as ReturnType<typeof useDistributions>);

    render(<DistributionsList recordId="record-1" />);

    const links = screen.getAllByRole('link', { name: 'Download' });
    expect(links).toHaveLength(3);
    expect(links[0]).toHaveAttribute(
      'href',
      'https://catalog.example.com/api/datasets/1/export?format=gpkg',
    );
    expect(links[0]).toHaveAttribute('download');
    expect(links[0]).toHaveAttribute('target', '_blank');
    expect(links[0].getAttribute('rel')).toContain('noopener');
  });

  // feat(#1395): set-primary control.
  describe('set-primary control', () => {
    beforeEach(() => {
      mockUseDistributions.mockReturnValue({
        data: { distributions: DISTRIBUTIONS_WITH_MANUAL_ROW, total: 3 },
        isLoading: false,
      } as unknown as ReturnType<typeof useDistributions>);
    });

    it('is not rendered for a reader (canEdit unset)', () => {
      render(<DistributionsList recordId="record-1" />);

      expect(screen.queryByRole('button', { name: /as primary/i })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /primary distribution/i })).not.toBeInTheDocument();
    });

    it('is not rendered for a reader (canEdit explicitly false)', () => {
      render(<DistributionsList recordId="record-1" canEdit={false} />);

      expect(screen.queryByRole('button', { name: /as primary/i })).not.toBeInTheDocument();
    });

    it('renders for an owner, only on the manual non-primary row', () => {
      render(<DistributionsList recordId="record-1" canEdit />);

      // The two auto-generated rows (the primary GeoPackage and the
      // non-primary OGC Features row) never get the control — the backend
      // rejects any PATCH against an auto_generated distribution.
      expect(screen.getAllByRole('button', { name: /as primary/i })).toHaveLength(1);
      expect(
        screen.getByRole('button', { name: 'Set Viewer App (app-1) as primary' }),
      ).toBeInTheDocument();
    });

    // fix(#1395 codex round 1): the accessible name names the row, so two
    // "Set as primary" buttons on the same page are distinguishable.
    // fix(#1395 codex round 3): the discriminator is the row's own id, not a
    // (possibly-colliding, possibly-truncated) URL fragment.
    it('has an accessible name that names the distribution, not a label-for that could steal it', () => {
      render(<DistributionsList recordId="record-1" canEdit />);

      // getByRole computes the accessible name; a <label for> stealing a
      // button's name (as opposed to a plain aria-label) would make this
      // query fail even though the button is visible.
      const button = screen.getByRole('button', { name: /^Set Viewer App/ });
      expect(button).toBeInTheDocument();
      expect(button).toHaveAccessibleName('Set Viewer App (app-1) as primary');
    });

    it('PATCHes the clicked row when an owner sets it primary', () => {
      render(<DistributionsList recordId="record-1" canEdit />);

      fireEvent.click(screen.getByRole('button', { name: /^Set Viewer App/ }));

      expect(mutate).toHaveBeenCalledTimes(1);
      expect(mutate).toHaveBeenCalledWith('app-1');
    });

    it('disables the control and shows a spinner while its own PATCH is pending', () => {
      mockUseSetPrimaryDistribution.mockReturnValue({
        mutate,
        isPending: true,
        variables: 'app-1',
      } as unknown as ReturnType<typeof useSetPrimaryDistribution>);

      render(<DistributionsList recordId="record-1" canEdit />);

      expect(screen.getByRole('button', { name: /^Set Viewer App/ })).toBeDisabled();
    });

    // fix(#1395 codex round 1): a second manual, non-primary row must go
    // disabled too while ANY promotion is in flight — not just the row that
    // was clicked — so a second click can't fire a concurrent PATCH that
    // races the first against uq_record_distribution_primary.
    it('disables every sibling set-primary control while one promotion is in flight', () => {
      mockUseDistributions.mockReturnValue({
        data: {
          distributions: [
            ...DISTRIBUTIONS_WITH_MANUAL_ROW,
            {
              id: 'app-2',
              record_id: 'record-1',
              distribution_type: 'offlineAccess',
              format: 'zip',
              url: 'https://example.com/offline.zip',
              title: 'Offline Bundle',
              description: null,
              protocol: 'HTTPS',
              media_type: 'application/zip',
              is_primary: false,
              auto_generated: false,
            },
          ],
          total: 4,
        },
        isLoading: false,
      } as unknown as ReturnType<typeof useDistributions>);
      // "Viewer App" is the one being promoted; "Offline Bundle" is idle but
      // must still go disabled.
      mockUseSetPrimaryDistribution.mockReturnValue({
        mutate,
        isPending: true,
        variables: 'app-1',
      } as unknown as ReturnType<typeof useSetPrimaryDistribution>);

      render(<DistributionsList recordId="record-1" canEdit />);

      expect(screen.getByRole('button', { name: /^Set Viewer App/ })).toBeDisabled();
      expect(screen.getByRole('button', { name: /^Set Offline Bundle/ })).toBeDisabled();
    });

    // fix(#1395 codex round 2): uq_record_distribution covers
    // (record_id, distribution_type, format, url), not title — two manual
    // rows are free to share a title, and the accessible name must still
    // tell them apart.
    it('gives two manual rows with the same title distinct accessible names', () => {
      mockUseDistributions.mockReturnValue({
        data: {
          distributions: [
            {
              id: 'mirror-1',
              record_id: 'record-1',
              distribution_type: 'download',
              format: 'zip',
              url: 'https://mirror-a.example.com/archive.zip',
              title: 'Mirror',
              description: null,
              protocol: 'HTTPS',
              media_type: 'application/zip',
              is_primary: false,
              auto_generated: false,
            },
            {
              id: 'mirror-2',
              record_id: 'record-1',
              distribution_type: 'download',
              format: 'zip',
              url: 'https://mirror-b.example.com/archive.zip',
              title: 'Mirror',
              description: null,
              protocol: 'HTTPS',
              media_type: 'application/zip',
              is_primary: false,
              auto_generated: false,
            },
          ],
          total: 2,
        },
        isLoading: false,
      } as unknown as ReturnType<typeof useDistributions>);

      render(<DistributionsList recordId="record-1" canEdit />);

      const buttons = screen.getAllByRole('button', { name: /^Set Mirror/ });
      expect(buttons).toHaveLength(2);
      const names = buttons.map((b) => b.getAttribute('aria-label'));
      expect(new Set(names).size).toBe(2);

      fireEvent.click(buttons[1]);
      expect(mutate).toHaveBeenCalledWith('mirror-2');
    });
  });
});
