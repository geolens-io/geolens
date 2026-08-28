import { fireEvent, render, screen, waitFor } from '@/test/test-utils';
import {
  useDistributions,
  useSetPrimaryDistribution,
} from '@/components/dataset/hooks/use-records';
import { useUpdateDataset } from '@/components/dataset/hooks/use-dataset';
import { useCanSetPublicVisibility, useTileConfig } from '@/hooks/use-settings';
import { listKeywords } from '@/api/records';
import { toast } from 'sonner';
import { AccessTab } from '../tabs/AccessTab';
import type { DatasetResponse } from '@/types/api';

vi.mock('@/components/dataset/hooks/use-records', () => ({
  useDistributions: vi.fn(),
  // feat(#1395): DistributionsList calls this unconditionally; AccessTab's
  // own tests don't exercise the set-primary control, so a stable no-op
  // mutate is enough to keep it from throwing.
  useSetPrimaryDistribution: vi.fn(),
}));

// feat(#1070): the visibility change probes the keywords endpoint for
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

    it('lets an owner or admin move a dataset from private to public', async () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'private' })} canEdit />);

      openVisibilitySelect();
      fireEvent.click(screen.getByRole('option', { name: 'Public' }));

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

    // feat(#1691): the restrict_public_visibility instance setting caps
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

    // fix(#930): `internal` joined the ladder once its permission branches
    // landed. The import pickers deliberately stay at private/public.
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

      openVisibilitySelect();
      fireEvent.click(screen.getByRole('option', { name: 'Private' }));

      await waitFor(() => expect(toast.error).toHaveBeenCalled());
    });

    // feat(#1070): inherited keywords get a confirm/diff step before the
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

        openVisibilitySelect();
        fireEvent.click(screen.getByRole('option', { name: 'Public' }));

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

        openVisibilitySelect();
        fireEvent.click(screen.getByRole('option', { name: 'Public' }));

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

        openVisibilitySelect();
        fireEvent.click(screen.getByRole('option', { name: 'Public' }));

        await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
      });

      // fix(#1178 r3): the probe asks an absolute question, so a NARROWING
      // move (already-public output moving down the ladder) must not be
      // blocked behind a dialog claiming a "wider audience" — that dialog
      // was standing in front of the remediation.
      it('a narrowing move skips the probe and the dialog entirely', async () => {
        mockListKeywords.mockResolvedValue(inheritedProbe);
        render(<AccessTab dataset={makeDataset({ visibility: 'public' })} canEdit />);

        openVisibilitySelect();
        fireEvent.click(screen.getByRole('option', { name: 'Internal' }));

        await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
        expect(mockListKeywords).not.toHaveBeenCalled();
        expect(
          screen.queryByText('Share inherited keywords?'),
        ).not.toBeInTheDocument();
      });

      // fix(#1178 r3): inherited_audience_gap is computed server-side over
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

        openVisibilitySelect();
        fireEvent.click(screen.getByRole('option', { name: 'Public' }));

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

      // fix(#1178 r4): two quick selections leave both probes in flight, and
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
        openVisibilitySelect();
        fireEvent.click(screen.getByRole('option', { name: 'Internal' }));
        openVisibilitySelect();
        fireEvent.click(screen.getByRole('option', { name: 'Public' }));
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

      // fix(#1178 r4): a superseded FAILED probe must not fire the direct
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

        openVisibilitySelect();
        fireEvent.click(screen.getByRole('option', { name: 'Internal' }));
        openVisibilitySelect();
        fireEvent.click(screen.getByRole('option', { name: 'Public' }));
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

      // fix(#1178 review): the fallback is only a fallback if the PATCH
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

        openVisibilitySelect();
        fireEvent.click(screen.getByRole('option', { name: 'Public' }));

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

        openVisibilitySelect();
        fireEvent.click(screen.getByRole('option', { name: 'Public' }));

        await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
        expect(toast.warning).not.toHaveBeenCalled();
      });
    });

    it('does not fire a mutation when the value is unchanged', () => {
      render(<AccessTab dataset={makeDataset({ visibility: 'public' })} canEdit />);

      openVisibilitySelect();
      fireEvent.click(screen.getByRole('option', { name: 'Public' }));

      expect(mutate).not.toHaveBeenCalled();
    });
  });
});
