import { render, screen } from '@/test/test-utils';
import { changeTestLanguage } from '@/test/i18n';
import type { OGCRecordResponse } from '@/types/api';
import { SearchResultCard } from '../SearchResultCard';

vi.mock('@/components/maps/hooks/use-quicklook', () => ({
  useQuicklook: vi.fn(() => ({ url: null, status: 'idle' })),
}));

function featureWithCount(
  count: number,
  recordType: OGCRecordResponse['properties']['record_type'] = 'vector_dataset',
): OGCRecordResponse {
  return {
    type: 'Feature',
    id: 'dataset-large-count',
    time: {},
    geometry: { type: 'Polygon', coordinates: [] },
    properties: {
      type: 'dataset',
      title: 'Large count dataset',
      description: '',
      keywords: [],
      created: '2026-03-01T00:00:00Z',
      updated: '2026-03-02T00:00:00Z',
      updated_by_display: 'editor-user',
      never_edited: false,
      record_type: recordType,
      themes: [],
      time: {},
      source_freshness: 'unknown',
      source_health: 'unknown',
      has_quicklook: false,
      crs: 'EPSG:4326',
      geometry_type: 'Polygon',
      feature_count: count,
      contacts: [],
      license: 'proprietary',
      quality_detail: null,
    },
    links: [],
  };
}

// Search.json now formats counts with the locale's number formatter. The card
// and its table thumbnail tile share those strings; plural selection still uses
// the raw count while the displayed value is locale-grouped. These tests cover
// the German, French and table-tile cases the search.json suite does not.
describe('SearchResultCard locale digit grouping', () => {
  afterEach(async () => {
    await changeTestLanguage('en');
  });

  it('groups English feature counts and keeps the singular form', () => {
    const { unmount } = render(<SearchResultCard feature={featureWithCount(32_186)} />);
    expect(screen.getByTestId('dataset-card-specs')).toHaveTextContent('32,186 features');
    expect(screen.getByTestId('dataset-card-specs')).not.toHaveTextContent('32186 features');
    unmount();

    render(<SearchResultCard feature={featureWithCount(1)} />);
    expect(screen.getByTestId('dataset-card-specs')).toHaveTextContent('1 feature');
    expect(screen.getByTestId('dataset-card-specs')).not.toHaveTextContent('1 features');
  });

  it('groups row counts in the table thumbnail tile', () => {
    render(<SearchResultCard feature={featureWithCount(22_314, 'table')} />);
    const tile = screen.getAllByText(/22,314 rows/i).find((el) => el.className.includes('tabular-nums'));
    expect(tile).toBeInTheDocument();
  });

  it('groups counts with German dot separators', async () => {
    await changeTestLanguage('de');
    render(<SearchResultCard feature={featureWithCount(32_186)} />);
    expect(screen.getByTestId('dataset-card-specs')).toHaveTextContent('32.186 Features');
  });

  it('groups counts with a French space separator', async () => {
    await changeTestLanguage('fr');
    render(<SearchResultCard feature={featureWithCount(32_186)} />);
    // jsdom normalizes U+202F (narrow no-break space) to a plain space in
    // textContent, so compare after collapsing all spacing.
    expect(screen.getByTestId('dataset-card-specs').textContent?.replace(/\s+/g, ' '))
      .toContain('32 186 entités');
  });
});
