import { fireEvent, render, screen } from '@/test/test-utils';
import { useDistributions } from '@/components/dataset/hooks/use-records';
import { useUpdateDataset } from '@/components/dataset/hooks/use-dataset';
import { useTileConfig } from '@/hooks/use-settings';
import { toast } from 'sonner';
import { AccessTab } from '../tabs/AccessTab';
import type { DatasetResponse } from '@/types/api';

vi.mock('@/components/dataset/hooks/use-records', () => ({
  useDistributions: vi.fn(),
}));

vi.mock('@/hooks/use-settings', () => ({
  useTileConfig: vi.fn(),
}));

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useUpdateDataset: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockUseDistributions = vi.mocked(useDistributions);
const mockUseTileConfig = vi.mocked(useTileConfig);
const mockUseUpdateDataset = vi.mocked(useUpdateDataset);
const mutate = vi.fn();

function makeDataset(overrides: Partial<DatasetResponse> = {}): DatasetResponse {
  return {
    id: 'ds-1',
    record_id: 'rec-1',
    table_name: 'public_parks',
    title: 'Parks',
    summary: null,
    srid: 4326,
    geometry_type: null,
    feature_count: 3,
    extent_bbox: null,
    column_info: null,
    license: null,
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
    mutate.mockReset();
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

  it('renders a distribution-backed OGC snippet and csv-only export for table datasets', () => {
    render(<AccessTab dataset={makeDataset()} />);

    expect(screen.getByText('Access via API')).toBeInTheDocument();

    const codeBlock = document.querySelector('pre');
    expect(codeBlock).not.toBeNull();
    expect(codeBlock).toHaveTextContent('https://catalog.example.com/api/collections/ds-1/items?limit=10');
    expect(codeBlock).not.toHaveTextContent('/api/v1/collections/public_parks');
    expect(codeBlock).not.toHaveTextContent('public_parks');

    // fix(#438): DS-08 — the format picker is now a Radix Select; its options
    // only mount when opened. For table datasets CSV is the sole format, so the
    // trigger displays it.
    const select = screen.getByRole('combobox', { name: 'Export format' });
    expect(select).toHaveTextContent('CSV');
  });

  it('hides the API snippet for raster datasets that do not expose OGC features', () => {
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

    expect(screen.queryByText('Access via API')).not.toBeInTheDocument();
  });
  // fix(#927): visibility was read-only after import — the only way to publish a
  // private dataset was to re-import it.
  describe('visibility control', () => {
    beforeEach(() => {
      // jsdom has no layout, and Radix's Select scrolls the active item into
      // view when the popup mounts.
      HTMLElement.prototype.scrollIntoView = vi.fn();
    });

    function openVisibilitySelect() {
      fireEvent.keyDown(screen.getByRole('combobox', { name: 'Visibility' }), {
        key: 'ArrowDown',
      });
    }

    it('renders a read-only badge for viewers and non-owner editors', () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'private' })} />);

      expect(screen.queryByRole('combobox', { name: 'Visibility' })).not.toBeInTheDocument();
      expect(screen.getByText('Private')).toBeInTheDocument();
    });

    it('lets an owner or admin move a dataset from private to public', () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

      openVisibilitySelect();
      fireEvent.click(screen.getByRole('option', { name: 'Public' }));

      expect(mutate).toHaveBeenCalledTimes(1);
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

    // fix(#930): `internal` joined the ladder once its permission branches
    // landed. The import pickers deliberately stay at private/public.
    it('offers internal as a move, between private and public', () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

      openVisibilitySelect();
      expect(screen.getAllByRole('option').map((el) => el.textContent)).toEqual([
        'Private',
        'Internal',
        'Public',
      ]);

      fireEvent.click(screen.getByRole('option', { name: 'Internal' }));

      expect(mutate).toHaveBeenCalledTimes(1);
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
    it('surfaces a rejected change instead of swallowing it', () => {
      mutate.mockImplementation((_vars, opts) => opts?.onError?.(new Error('nope')));
      render(<AccessTab dataset={makeDataset({ visibility: 'public' })} canEdit />);

      openVisibilitySelect();
      fireEvent.click(screen.getByRole('option', { name: 'Private' }));

      expect(toast.error).toHaveBeenCalled();
    });

    it('does not fire a mutation when the value is unchanged', () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'public' })} canEdit />);

      openVisibilitySelect();
      fireEvent.click(screen.getByRole('option', { name: 'Public' }));

      expect(mutate).not.toHaveBeenCalled();
    });
  });
});
