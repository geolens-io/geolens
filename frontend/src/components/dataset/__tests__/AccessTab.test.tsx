import { fireEvent, render, screen, waitFor, within } from '@/test/test-utils';
import {
  useDistributions,
  useSetPrimaryDistribution,
} from '@/components/dataset/hooks/use-records';
import { useUpdateDataset } from '@/components/dataset/hooks/use-dataset';
import { useCanSetPublicVisibility, useTileConfig } from '@/hooks/use-settings';
import { listKeywords } from '@/api/records';
import { toast } from 'sonner';
import { AccessTab } from '../tabs/AccessTab';
import type { DatasetResponse, RecordType } from '@/types/api';

vi.mock('@/components/dataset/hooks/use-records', () => ({
  useDistributions: vi.fn(),
  // DistributionsList calls this unconditionally; AccessTab's
  // own tests don't exercise the set-primary control, so a stable no-op
  // mutate is enough to keep it from throwing.
  useSetPrimaryDistribution: vi.fn(),
}));

// The visibility change probes the keywords endpoint for
// inherited keywords before mutating.
vi.mock('@/api/records', () => ({
  listKeywords: vi.fn(),
}));

vi.mock('@/hooks/use-settings', () => ({
  useTileConfig: vi.fn(),
  useCanSetPublicVisibility: vi.fn(),
}));

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useUpdateDataset: vi.fn(),
}));

let canEditMetadata = true;
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({ permissions: null, isLoading: false, can: () => canEditMetadata }),
}));

vi.mock('@/components/dataset/DatasetWriteKeys', () => ({
  DatasetWriteKeys: ({ datasetId, canCreate }: { datasetId: string; canCreate: boolean }) => (
    <div data-testid="dataset-write-keys" data-can-create={String(canCreate)}>
      {datasetId}
    </div>
  ),
}));

vi.mock('@/components/dataset/DatasetGroupShare', () => ({
  DatasetGroupShare: () => <div data-testid="dataset-group-share" />,
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const mockUseDistributions = vi.mocked(useDistributions);
const mockUseSetPrimaryDistribution = vi.mocked(useSetPrimaryDistribution);
const mockUseTileConfig = vi.mocked(useTileConfig);
const mockUseCanSetPublic = vi.mocked(useCanSetPublicVisibility);
const mockUseUpdateDataset = vi.mocked(useUpdateDataset);
const mockListKeywords = vi.mocked(listKeywords);
const mutate = vi.fn();

function makeDataset(overrides: Partial<DatasetResponse> = {}): DatasetResponse {
  return {
    id: 'ds-1',
    record_id: 'rec-1',
    table_name: 'public_parks',
    source_health: 'unknown',
    schema_drift_status: 'unknown',
    source_freshness: 'unknown',
    has_generic_geometry: false,
    title: 'Parks',
    summary: null,
    srid: 4326,
    geometry_type: null,
    feature_count: 3,
    extent_bbox: null,
    column_info: null,
    license: null,
    attribution: null,
    source_organization: null,
    data_vintage_start: null,
    data_vintage_end: null,
    source_format: 'csv',
    source_filename: 'parks.csv',
    original_srid: null,
    visibility: 'public',
    created_by: null,
    created_by_display: 'admin',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    last_edited_by_display: null,
    last_edited_at: null,
    record_status: 'published',
    lineage_summary: null,
    update_frequency: null,
    usage_constraints: null,
    access_constraints: null,
    sensitivity_classification: null,
    theme_category: null,
    owner_org: null,
    published_at: null,
    updated_by: null,
    current_version: 1,
    source_url: null,
    quality_statement: null,
    collections: null,
    record_type: 'table',
    raster: null,
    ...overrides,
    tile_columns: overrides.tile_columns ?? null,
  };
}

describe('AccessTab', () => {
  beforeEach(() => {
    mockUseCanSetPublic.mockReturnValue(true);
    mockUseDistributions.mockReturnValue({
      data: {
        distributions: [
          {
            id: 'dist-csv',
            record_id: 'rec-1',
            distribution_type: 'download',
            format: 'csv',
            url: '/datasets/ds-1/export?format=csv',
            title: 'CSV Download',
            description: null,
            protocol: 'HTTP',
            media_type: 'text/csv',
            is_primary: true,
            auto_generated: true,
          },
          {
            id: 'dist-ogc',
            record_id: 'rec-1',
            distribution_type: 'ogc_features',
            format: 'geojson',
            url: '/collections/ds-1/items',
            title: 'OGC API Features',
            description: null,
            protocol: 'OGC:OAFeat',
            media_type: 'application/geo+json',
            is_primary: false,
            auto_generated: true,
          },
        ],
        total: 2,
      },
      isLoading: false,
    } as unknown as ReturnType<typeof useDistributions>);
    mockUseSetPrimaryDistribution.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      variables: undefined,
    } as unknown as ReturnType<typeof useSetPrimaryDistribution>);
    mutate.mockReset();
    mockListKeywords.mockReset();
    mockListKeywords.mockResolvedValue({
      keywords: [],
      total: 0,
      inherited_audience_gap: false,
    });
    mockUseUpdateDataset.mockReturnValue({
      mutate,
      isPending: false,
    } as unknown as ReturnType<typeof useUpdateDataset>);
    mockUseTileConfig.mockReturnValue({
      data: {
        public_api_url: 'https://catalog.example.com/api',
        public_base_url: 'https://catalog.example.com',
      },
    } as ReturnType<typeof useTileConfig>);
  });

  it('truncates the code header URL so the copy button stays on screen', () => {
    render(<AccessTab dataset={makeDataset()} />);

    const header = screen.getByText('GET').parentElement as HTMLElement;
    const url = within(header).getByTitle(/collections\/ds-1\/items/);
    expect(url).toHaveClass('min-w-0', 'flex-1', 'truncate');
    expect(within(header).getByRole('button')).toHaveClass('shrink-0');
  });

  it('renders a distribution-backed OGC snippet and no duplicate export picker for table datasets', () => {
    render(<AccessTab dataset={makeDataset()} />);

    expect(screen.getByText('Connect with QGIS, Python, or curl')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Download another format' })).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Export format' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Export' })).not.toBeInTheDocument();

    const codeBlock = document.querySelector('pre');
    expect(codeBlock).not.toBeNull();
    expect(codeBlock).toHaveTextContent('https://catalog.example.com/api/collections/ds-1/items?limit=10');
    expect(codeBlock).not.toHaveTextContent('/api/v1/collections/public_parks');
    expect(codeBlock).not.toHaveTextContent('public_parks');
  });

  it('hides the API snippet for raster datasets that do not expose OGC features', () => {
    mockUseDistributions.mockReturnValue({
      data: { distributions: [], total: 0 },
      isLoading: false,
    } as unknown as ReturnType<typeof useDistributions>);
    render(
      <AccessTab
        dataset={makeDataset({
          record_type: 'raster_dataset',
          raster: {
            tile_url: 'https://tiles.example.com/{z}/{x}/{y}.png',
            connect: {
              download_url: '/datasets/ds-1/download/cog',
              tile_url: 'https://tiles.example.com/{z}/{x}/{y}.png',
              s3_uri: null,
            },
          } as DatasetResponse['raster'],
        })}
      />,
    );

    expect(screen.queryByText('Connect with QGIS, Python, or curl')).not.toBeInTheDocument();
    expect(screen.getByText('No additional downloads or services are listed here.')).toBeInTheDocument();
    expect(screen.getByText('https://tiles.example.com/{z}/{x}/{y}.png')).toBeInTheDocument();
  });

  it('explains every level of the visibility ladder, restricted included', () => {
    render(<AccessTab dataset={makeDataset({ visibility: 'restricted' })} canEdit />);
    expect(screen.getByText(/Private = .* Restricted = .* Internal = .* Public = /)).toBeInTheDocument();
  });

  describe('sharing with groups', () => {
    const groups = [{ id: 'g-1', name: 'Surveyors' }];

    it.each([
      ['an owner or admin whose dataset carries a group list', { groups }, true, true],
      ['a reader without write rights', { groups }, false, false],
      ['an editor when the server withheld the group list', { groups: null }, true, false],
    ])('group picker for %s', (_who, overrides, canEdit, shown) => {
      render(<AccessTab dataset={makeDataset(overrides)} canEdit={canEdit} />);
      expect(screen.queryByTestId('dataset-group-share') !== null).toBe(shown);
    });
  });

  describe('a tileset', () => {
    const tilesetDataset = makeDataset({
      record_type: 'tiles3d_dataset',
      tileset: {
        url: '/api/datasets/ds-1/tiles3d/tileset.json',
        size_bytes: 1024,
        version: '1.1',
        geometric_error: 16,
        bounding_volume: 'region',
      },
    });
    const noDistributions = {
      data: { distributions: [], total: 0 },
      isLoading: false,
    } as unknown as ReturnType<typeof useDistributions>;

    it('gets its client URL and no API snippet, export or empty access points', () => {
      mockUseDistributions.mockReturnValue(noDistributions);
      render(<AccessTab dataset={tilesetDataset} />);

      expect(screen.getByRole('heading', { name: 'Load in a 3D Tiles client' })).toBeInTheDocument();
      expect(
        screen.getByText(`${window.location.origin}/api/datasets/ds-1/tiles3d/tileset.json`),
      ).toBeInTheDocument();
      expect(screen.queryByRole('heading', { name: 'Downloads and connections' })).not.toBeInTheDocument();
      expect(screen.queryByText('Connect with QGIS, Python, or curl')).not.toBeInTheDocument();
      expect(screen.queryByRole('combobox', { name: 'Export format' })).not.toBeInTheDocument();
    });

    it('puts the key header in the snippet only for a tileset that is not public', () => {
      mockUseDistributions.mockReturnValue(noDistributions);
      const snippet = () => screen.getByText(/Cesium3DTileset\.fromUrl/).textContent;
      const { unmount } = render(<AccessTab dataset={tilesetDataset} />);
      expect(snippet()).not.toContain('X-Api-Key');
      unmount();

      render(<AccessTab dataset={{ ...tilesetDataset, visibility: 'restricted' }} />);
      expect(snippet()).toContain('headers: { "X-Api-Key": "YOUR_API_KEY" }');
    });

    it('keeps the access points when it has distributions', () => {
      render(<AccessTab dataset={tilesetDataset} />);

      expect(screen.getByRole('heading', { name: 'Downloads and connections' })).toBeInTheDocument();
    });

    it('leaves the access points of other record types alone when they have no distributions', () => {
      mockUseDistributions.mockReturnValue(noDistributions);
      render(<AccessTab dataset={makeDataset()} />);

      expect(screen.getByRole('heading', { name: 'Downloads and connections' })).toBeInTheDocument();
    });
  });

  describe('write keys', () => {
    beforeEach(() => {
      canEditMetadata = true;
    });

    it('lets an editor of a feature dataset manage and create its write keys', () => {
      render(<AccessTab dataset={makeDataset({ geometry_type: 'POINT' })} canEdit />);
      const card = screen.getByTestId('dataset-write-keys');
      expect(card).toHaveTextContent('ds-1');
      expect(card).toHaveAttribute('data-can-create', 'true');
    });

    it('is hidden from someone the key list refuses, such as a non-owner viewer', () => {
      render(<AccessTab dataset={makeDataset({ geometry_type: 'POINT' })} />);
      expect(screen.queryByTestId('dataset-write-keys')).not.toBeInTheDocument();
    });

    it('lets an owner without the edit permission list and revoke, but not create', () => {
      canEditMetadata = false;
      render(
        <AccessTab
          dataset={makeDataset({ geometry_type: 'POINT' })}
          canEdit={false}
          canManageKeys
        />,
      );
      expect(screen.getByTestId('dataset-write-keys')).toHaveAttribute('data-can-create', 'false');
    });

    it('follows the configured edit_metadata capability rather than the role name', () => {
      canEditMetadata = false;
      const { unmount } = render(
        <AccessTab dataset={makeDataset({ geometry_type: 'POINT' })} canEdit canManageKeys />,
      );
      expect(screen.getByTestId('dataset-write-keys')).toHaveAttribute('data-can-create', 'false');
      unmount();

      canEditMetadata = true;
      render(
        <AccessTab
          dataset={makeDataset({ geometry_type: 'POINT' })}
          canEdit={false}
          canManageKeys
        />,
      );
      expect(screen.getByTestId('dataset-write-keys')).toHaveAttribute('data-can-create', 'true');
    });

    it('keeps the keys of a dataset without a geometry column, but offers no new one', () => {
      render(<AccessTab dataset={makeDataset({ geometry_type: null })} canEdit />);
      expect(screen.getByTestId('dataset-write-keys')).toHaveAttribute('data-can-create', 'false');
    });

    it('is hidden for a dataset without features', () => {
      render(
        <AccessTab
          dataset={makeDataset({ record_type: 'raster_dataset', geometry_type: 'POINT' })}
          canEdit
        />,
      );
      expect(screen.queryByTestId('dataset-write-keys')).not.toBeInTheDocument();
    });
  });

  it('offers no API snippet or export for an unknown record type', () => {
    render(<AccessTab dataset={makeDataset({ record_type: 'hologram_dataset' as RecordType })} />);

    expect(screen.queryByText('Connect with QGIS, Python, or curl')).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Export format' })).not.toBeInTheDocument();
  });
  describe('vector tile service URL', () => {
    const tilesDistribution = {
      id: 'tiles-1',
      record_id: 'rec-1',
      distribution_type: 'vector_tiles',
      format: 'pbf',
      url: '/tiles/data.public_parks/{z}/{x}/{y}.pbf',
      title: 'Vector Tiles',
      description: null,
      protocol: 'XYZ',
      media_type: 'application/vnd.mapbox-vector-tile',
      is_primary: false,
      auto_generated: true,
    };

    beforeEach(() => {
      mockUseDistributions.mockReturnValue({
        data: { distributions: [tilesDistribution], total: 1 },
        isLoading: false,
      } as unknown as ReturnType<typeof useDistributions>);
    });

    it('lists the tile service for a public dataset', () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'public' })} />);
      expect(screen.getByText('Tile Services')).toBeInTheDocument();
    });

    it('shows a public dataset the plain tile URL and no key hint', () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'public', record_type: 'vector_dataset' })} />);
      expect(screen.getByText(/\/tiles\/data\.public_parks\/\{z\}\/\{x\}\/\{y\}\.pbf$/)).toBeInTheDocument();
      expect(screen.queryByText(/In QGIS, add a Vector Tiles connection/)).not.toBeInTheDocument();
    });

    it.each(['internal', 'restricted', 'private'] as const)(
      'lists the tile service with a key placeholder and a QGIS hint for a %s dataset',
      (visibility) => {
        render(<AccessTab dataset={makeDataset({ visibility, record_type: 'vector_dataset' })} />);
        expect(screen.getByText('Tile Services')).toBeInTheDocument();
        expect(
          screen.getByText(/\/tiles\/data\.public_parks\/\{z\}\/\{x\}\/\{y\}\.pbf\?api_key=\{your_key\}$/),
        ).toBeInTheDocument();
        expect(screen.getByText(/In QGIS, add a Vector Tiles connection/)).toBeInTheDocument();
      },
    );

    it('keeps an externally hosted tile service on a non-public dataset', () => {
      mockUseDistributions.mockReturnValue({
        data: {
          distributions: [
            tilesDistribution,
            { ...tilesDistribution, id: 'tiles-2', title: 'Partner Tiles', url: 'https://tiles.example.org/{z}/{x}/{y}.pbf' },
          ],
          total: 2,
        },
        isLoading: false,
      } as unknown as ReturnType<typeof useDistributions>);
      render(<AccessTab dataset={makeDataset({ visibility: 'private' })} />);
      expect(screen.getByText('https://tiles.example.org/{z}/{x}/{y}.pbf')).toBeInTheDocument();
    });

    it('keeps an external tile service even when it uses the same path as GeoLens', () => {
      mockUseDistributions.mockReturnValue({
        data: {
          distributions: [
            { ...tilesDistribution, id: 'tiles-3', title: 'Mirror Tiles', url: 'https://partner.example/api/tiles/data.parks/{z}/{x}/{y}.pbf' },
          ],
          total: 1,
        },
        isLoading: false,
      } as unknown as ReturnType<typeof useDistributions>);
      render(<AccessTab dataset={makeDataset({ visibility: 'private' })} />);
      expect(screen.getByText('https://partner.example/api/tiles/data.parks/{z}/{x}/{y}.pbf')).toBeInTheDocument();
    });

    it('names the endpoints that accept an API key or bearer token', () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'private' })} />);
      expect(screen.getByText(/Downloads, OGC Features and vector tile endpoints accept/)).toBeInTheDocument();
    });
  });

  // Visibility was read-only after import — the only way to publish a
  // private dataset was to re-import it.
  describe('visibility control', () => {
    beforeEach(() => {
      // jsdom has no layout, and Radix's Select scrolls the active item into
      // view when the popup mounts.
      HTMLElement.prototype.scrollIntoView = vi.fn();
      mockListKeywords.mockResolvedValue({
        keywords: [],
        total: 0,
        inherited_audience_gap: false,
      });
    });

    function openVisibilitySelect() {
      fireEvent.keyDown(screen.getByRole('combobox', { name: 'Visibility' }), {
        key: 'ArrowDown',
      });
    }

    it('puts the visibility card above the downloads', () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

      const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
      const visibilityIndex = headings.indexOf('Who can access this dataset');
      const downloadsIndex = headings.indexOf('Downloads and connections');
      expect(visibilityIndex).toBeGreaterThanOrEqual(0);
      expect(downloadsIndex).toBeGreaterThan(visibilityIndex);
    });

    it('renders a read-only badge for viewers and non-owner editors', () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'private' })} />);

      expect(screen.queryByRole('combobox', { name: 'Visibility' })).not.toBeInTheDocument();
      expect(screen.getByText('Private')).toBeInTheDocument();
    });

    function selectVisibility(name: string) {
      openVisibilitySelect();
      fireEvent.click(screen.getByRole('option', { name }));
    }

    function confirmMakePublic() {
      fireEvent.click(screen.getByRole('button', { name: 'Make public' }));
    }

    function selectPublic() {
      selectVisibility('Public');
      confirmMakePublic();
    }

    it('lets an owner or admin move a dataset from private to public', async () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

      selectPublic();

      await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
      expect(mutate.mock.calls[0][0]).toEqual({
        datasetId: 'ds-1',
        data: { visibility: 'public' },
      });
    });

    it('does not offer restricted as a move', () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

      openVisibilitySelect();

      expect(screen.queryByRole('option', { name: 'Restricted' })).not.toBeInTheDocument();
    });

    // The restrict_public_visibility instance setting caps
    // non-admins at non-public. The server enforces it with a 403; this
    // control disables the Public move and explains why.
    it('disables the Public move when the instance restricts public to admins', async () => {
      mockUseCanSetPublic.mockReturnValue(false);
      render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

      expect(
        screen.getByText('Only administrators can make content public on this instance.'),
      ).toBeInTheDocument();

      openVisibilitySelect();
      const publicOption = screen.getByRole('option', { name: 'Public' });
      expect(publicOption).toHaveAttribute('aria-disabled', 'true');

      fireEvent.click(publicOption);
      expect(mutate).not.toHaveBeenCalled();
    });

    it('keeps the Public move and hides the admin-only note when allowed', () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

      expect(
        screen.queryByText('Only administrators can make content public on this instance.'),
      ).not.toBeInTheDocument();

      openVisibilitySelect();
      expect(
        screen.getByRole('option', { name: 'Public' }),
      ).not.toHaveAttribute('aria-disabled', 'true');
    });

    // `internal` is on the ladder. The import pickers deliberately stay at
    // private/public.
    it('offers internal as a move, between private and public', async () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

      openVisibilitySelect();
      expect(screen.getAllByRole('option').map((el) => el.textContent)).toEqual([
        'Private',
        'Internal',
        'Public',
      ]);

      fireEvent.click(screen.getByRole('option', { name: 'Internal' }));

      await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
      expect(mutate.mock.calls[0][0]).toEqual({
        datasetId: 'ds-1',
        data: { visibility: 'internal' },
      });
    });

    // Before #930 an `internal` dataset rendered through the legacy branch, so
    // it showed up twice and could not be moved back to.
    it('treats a stored internal value as current, not legacy', () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'internal' })} canEdit />);

      openVisibilitySelect();

      expect(screen.getAllByRole('option', { name: 'Internal' })).toHaveLength(1);
      expect(screen.getByRole('option', { name: 'Internal' })).not.toHaveAttribute(
        'aria-disabled',
        'true',
      );
    });

    // A one-way exit: a SQL-managed or pre-existing `restricted` dataset keeps
    // displaying what it is, and is never silently coerced to something else.
    it('shows a stored restricted value as the disabled current option', () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'restricted' })} canEdit />);

      expect(screen.getByRole('combobox', { name: 'Visibility' })).toHaveTextContent('Restricted');

      openVisibilitySelect();
      expect(screen.getByRole('option', { name: 'Restricted' })).toHaveAttribute(
        'aria-disabled',
        'true',
      );
      expect(screen.getByRole('option', { name: 'Private' })).not.toHaveAttribute(
        'aria-disabled',
        'true',
      );
      expect(screen.getByRole('option', { name: 'Public' })).not.toHaveAttribute(
        'aria-disabled',
        'true',
      );
    });

    // The backend rejects public → private with a 422 while a public map uses
    // the dataset. #931 owns turning that prose into its own message; what must
    // not happen here is the select snapping back with nothing said.
    it('surfaces a rejected change instead of swallowing it', async () => {
      mutate.mockImplementation((_vars, opts) => opts?.onError?.(new Error('nope')));
      render(<AccessTab dataset={makeDataset({ visibility: 'public' })} canEdit />);

      selectVisibility('Private');

      await waitFor(() => expect(toast.error).toHaveBeenCalled());
    });

    // Inherited keywords get a confirm/diff step before the
    // audience widens past the source they came from.
    describe('inherited-keyword confirm', () => {
      const inheritedProbe = {
        keywords: [
          {
            id: 'kw-1',
            record_id: 'rec-1',
            keyword: 'codename',
            vocabulary_uri: null,
            keyword_type: 'theme',
            inherited: true,
          },
        ],
        total: 1,
        inherited_audience_gap: true,
      };

      it('holds the change behind a dialog naming the inherited keywords', async () => {
        mockListKeywords.mockResolvedValue(inheritedProbe);
        render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

        selectPublic();

        expect(await screen.findByText('Share inherited keywords?')).toBeInTheDocument();
        expect(screen.getByText('codename')).toBeInTheDocument();
        expect(mockListKeywords).toHaveBeenCalledWith('rec-1', {
          audienceVisibility: 'public',
        });
        expect(mutate).not.toHaveBeenCalled();

        fireEvent.click(screen.getByRole('button', { name: 'Change visibility' }));
        await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
        expect(mutate.mock.calls[0][0]).toEqual({
          datasetId: 'ds-1',
          data: { visibility: 'public' },
        });
      });

      it('cancelling the dialog leaves the visibility untouched', async () => {
        mockListKeywords.mockResolvedValue(inheritedProbe);
        render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

        selectPublic();

        expect(await screen.findByText('Share inherited keywords?')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

        await waitFor(() =>
          expect(screen.queryByText('Share inherited keywords?')).not.toBeInTheDocument(),
        );
        expect(mutate).not.toHaveBeenCalled();
      });

      it('a failed probe never blocks the change', async () => {
        mockListKeywords.mockRejectedValue(new Error('boom'));
        render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

        selectPublic();

        await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
      });

      // The probe asks an absolute question, so a NARROWING
      // move (already-public output moving down the ladder) must not be
      // blocked behind a dialog claiming a "wider audience" — that dialog
      // was standing in front of the remediation.
      it('a narrowing move skips the probe and the dialog entirely', async () => {
        mockListKeywords.mockResolvedValue(inheritedProbe);
        render(<AccessTab dataset={makeDataset({ visibility: 'public' })} canEdit />);

        selectVisibility('Internal');

        await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
        expect(mockListKeywords).not.toHaveBeenCalled();
        expect(
          screen.queryByText('Share inherited keywords?'),
        ).not.toBeInTheDocument();
      });

      // inherited_audience_gap is computed server-side over
      // ALL keyword rows; the fetched page only supplies names. A page
      // without the inherited entries must still produce the dialog.
      it('shows the dialog on a gap even when no inherited names are on the page', async () => {
        mockListKeywords.mockResolvedValue({
          keywords: [
            {
              id: 'kw-2',
              record_id: 'rec-1',
              keyword: 'riverine',
              vocabulary_uri: null,
              keyword_type: 'theme',
              inherited: false,
            },
          ],
          total: 150,
          inherited_audience_gap: true,
        });
        render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

        selectPublic();

        expect(await screen.findByText('Share inherited keywords?')).toBeInTheDocument();
        expect(
          screen.getByText(
            'This dataset carries keywords inherited from its source. Review the full keyword list before sharing.',
          ),
        ).toBeInTheDocument();
        expect(mutate).not.toHaveBeenCalled();

        fireEvent.click(screen.getByRole('button', { name: 'Change visibility' }));
        await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
      });

      // Two quick selections leave both probes in flight, and
      // the LAST response to arrive used to write pendingChange — possibly
      // for the earlier, no-longer-intended value. Only the newest selection
      // may produce anything.
      it('a superseded probe response is discarded, even resolving last', async () => {
        vi.mocked(toast.warning).mockClear();
        const resolvers: Array<(v: unknown) => void> = [];
        mockListKeywords.mockImplementation(
          () =>
            new Promise((res) => {
              resolvers.push(res as (v: unknown) => void);
            }) as ReturnType<typeof listKeywords>,
        );
        render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

        // First selection: Internal. Second selection: Public. Both widen.
        selectVisibility('Internal');
        selectPublic();
        await waitFor(() => expect(resolvers).toHaveLength(2));

        // The newest probe resolves FIRST with no gap: direct mutate for
        // public. The stale probe resolves LAST claiming a gap: discarded.
        resolvers[1]({ keywords: [], total: 0, inherited_audience_gap: false });
        await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
        expect(mutate.mock.calls[0][0]).toEqual({
          datasetId: 'ds-1',
          data: { visibility: 'public' },
        });

        resolvers[0](inheritedProbe);
        // Give the stale response a tick to (wrongly) act, then assert it
        // produced nothing: no dialog, no extra mutate.
        await waitFor(() =>
          expect(
            screen.queryByText('Share inherited keywords?'),
          ).not.toBeInTheDocument(),
        );
        expect(mutate).toHaveBeenCalledTimes(1);
      });

      // A superseded FAILED probe must not fire the direct
      // PATCH for its stale value.
      it('a superseded failed probe does not mutate its stale value', async () => {
        const handlers: Array<{ resolve: (v: unknown) => void; reject: (e: unknown) => void }> = [];
        mockListKeywords.mockImplementation(
          () =>
            new Promise((resolve, reject) => {
              handlers.push({ resolve: resolve as (v: unknown) => void, reject });
            }) as ReturnType<typeof listKeywords>,
        );
        render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

        selectVisibility('Internal');
        selectPublic();
        await waitFor(() => expect(handlers).toHaveLength(2));

        handlers[1].resolve({ keywords: [], total: 0, inherited_audience_gap: false });
        await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));

        // The stale probe FAILS after being superseded: without the guard the
        // catch fell through to applyVisibility('internal').
        handlers[0].reject(new Error('boom'));
        await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
        expect(mutate.mock.calls[0][0]).toEqual({
          datasetId: 'ds-1',
          data: { visibility: 'public' },
        });
      });

      // The fallback is only a fallback if the PATCH
      // response's warnings actually reach the user when the probe failed.
      it('surfaces the PATCH warning when the probe failed', async () => {
        mockListKeywords.mockRejectedValue(new Error('boom'));
        mutate.mockImplementation((_vars, opts) =>
          opts?.onSuccess?.({
            metadata_warnings: [
              'Keywords inherited from the source dataset are now visible: codename',
            ],
          }),
        );
        render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

        selectPublic();

        await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
        expect(toast.warning).toHaveBeenCalledWith(
          'Keywords inherited from the source dataset are now visible: codename',
        );
      });

      it('no warning toast when the response carries none', async () => {
        // The toast mocks are module-level and survive the previous test.
        vi.mocked(toast.warning).mockClear();
        mutate.mockImplementation((_vars, opts) =>
          opts?.onSuccess?.({ metadata_warnings: null }),
        );
        render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

        selectPublic();

        await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
        expect(toast.warning).not.toHaveBeenCalled();
      });
    });

    describe('public confirm', () => {
      it.each(['private', 'restricted', 'internal'] as const)(
        'selecting Public from %s opens the dialog without mutating',
        async (from) => {
          render(<AccessTab dataset={makeDataset({ visibility: from })} canEdit />);

          selectVisibility('Public');

          const dialog = await screen.findByRole('alertdialog');
          expect(within(dialog).getByText('Make this dataset public?')).toBeInTheDocument();
          expect(
            within(dialog).getByText(/OGC API, its map tiles, its downloads and its catalog record/),
          ).toBeInTheDocument();
          expect(within(dialog).getByText(/Groups this dataset is shared with keep their access/)).toBeInTheDocument();
          expect(mutate).not.toHaveBeenCalled();
        },
      );

      it('confirming applies visibility public', async () => {
        render(<AccessTab dataset={makeDataset({ visibility: 'internal' })} canEdit />);

        selectPublic();

        await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
        expect(mutate.mock.calls[0][0]).toEqual({
          datasetId: 'ds-1',
          data: { visibility: 'public' },
        });
      });

      it('cancelling leaves the visibility unchanged and the select on the old value', async () => {
        render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

        selectVisibility('Public');
        await screen.findByRole('alertdialog');
        fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

        await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
        expect(mutate).not.toHaveBeenCalled();
        expect(mockListKeywords).not.toHaveBeenCalled();
        expect(screen.getByRole('combobox', { name: 'Visibility' })).toHaveTextContent('Private');
      });

      it.each([
        ['private', 'Internal'],
        ['public', 'Internal'],
        ['public', 'Private'],
      ] as const)('moving %s to %s applies with no dialog', async (from, to) => {
        render(<AccessTab dataset={makeDataset({ visibility: from })} canEdit />);

        openVisibilitySelect();
        fireEvent.click(screen.getByRole('option', { name: to }));

        await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
        expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      });

      it.each([
        ['no gap', { keywords: [], total: 0, inherited_audience_gap: false }],
        [
          'a gap',
          {
            keywords: [
              {
                id: 'kw-1',
                record_id: 'rec-1',
                keyword: 'codename',
                vocabulary_uri: null,
                keyword_type: 'theme',
                inherited: true,
              },
            ],
            total: 1,
            inherited_audience_gap: true,
          },
        ],
      ])(
        'a superseded Internal probe resolving with %s does nothing once Public is chosen',
        async (_label, probe) => {
          let resolveProbe: (v: unknown) => void = () => {};
          mockListKeywords.mockImplementation(
            () =>
              new Promise((res) => {
                resolveProbe = res as (v: unknown) => void;
              }) as ReturnType<typeof listKeywords>,
          );
          render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

          selectVisibility('Internal');
          await waitFor(() => expect(mockListKeywords).toHaveBeenCalledTimes(1));
          selectVisibility('Public');
          await screen.findByText('Make this dataset public?');

          resolveProbe(probe);
          await new Promise((r) => setTimeout(r, 0));

          expect(mutate).not.toHaveBeenCalled();
          expect(screen.queryByText('Share inherited keywords?')).not.toBeInTheDocument();
          expect(screen.getByText('Make this dataset public?')).toBeInTheDocument();

          mockListKeywords.mockResolvedValue({
            keywords: [],
            total: 0,
            inherited_audience_gap: false,
          });
          confirmMakePublic();
          await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
          expect(mutate.mock.calls[0][0]).toEqual({
            datasetId: 'ds-1',
            data: { visibility: 'public' },
          });
        },
      );

      it('asks for the public confirmation first, then the inherited-keywords dialog', async () => {
        mockListKeywords.mockResolvedValue({
          keywords: [
            {
              id: 'kw-1',
              record_id: 'rec-1',
              keyword: 'codename',
              vocabulary_uri: null,
              keyword_type: 'theme',
              inherited: true,
            },
          ],
          total: 1,
          inherited_audience_gap: true,
        });
        render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

        selectVisibility('Public');

        await screen.findByText('Make this dataset public?');
        expect(screen.queryByText('Share inherited keywords?')).not.toBeInTheDocument();
        expect(mockListKeywords).not.toHaveBeenCalled();

        confirmMakePublic();
        expect(await screen.findByText('Share inherited keywords?')).toBeInTheDocument();
        expect(mutate).not.toHaveBeenCalled();

        fireEvent.click(screen.getByRole('button', { name: 'Change visibility' }));
        await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
        expect(mutate.mock.calls[0][0]).toEqual({
          datasetId: 'ds-1',
          data: { visibility: 'public' },
        });
      });
    });

    it('does not fire a mutation when the value is unchanged', () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'public' })} canEdit />);

      selectVisibility('Public');

      expect(mutate).not.toHaveBeenCalled();
    });
  });
});
