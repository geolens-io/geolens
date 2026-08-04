// feat(#1070): keywords copied from the analysis source carry an "inherited"
// marker, and an audience gap (readers who cannot open that source) surfaces
// as a hint line for the editor.
import { render, screen, waitFor } from '@/test/test-utils';
import { KeywordsEditor } from '../KeywordsEditor';
import { listKeywords } from '@/api/records';
import type { KeywordListResponse } from '@/types/api';

vi.mock('@/api/records', () => ({
  listContacts: vi.fn(),
  createContact: vi.fn(),
  deleteContact: vi.fn(),
  listKeywords: vi.fn(),
  createKeyword: vi.fn(),
  deleteKeyword: vi.fn(),
}));

function keywordList(overrides?: Partial<KeywordListResponse>): KeywordListResponse {
  return {
    keywords: [
      {
        id: 'kw-1',
        record_id: 'rec-1',
        keyword: 'codename',
        vocabulary_uri: null,
        keyword_type: 'theme',
        inherited: true,
      },
      {
        id: 'kw-2',
        record_id: 'rec-1',
        keyword: 'riverine',
        vocabulary_uri: null,
        keyword_type: 'theme',
        inherited: false,
      },
    ],
    total: 2,
    inherited_audience_gap: false,
    ...overrides,
  };
}

describe('KeywordsEditor inherited marker (feat #1070)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('marks inherited keywords and leaves authored ones unmarked', async () => {
    vi.mocked(listKeywords).mockResolvedValue(keywordList());
    render(<KeywordsEditor recordId="rec-1" canEdit />);

    await waitFor(() => {
      expect(screen.getByText('codename')).toBeInTheDocument();
    });
    expect(screen.getByText('riverine')).toBeInTheDocument();
    // Exactly one marker: the copied keyword's badge, not the authored one's.
    expect(screen.getAllByText('inherited')).toHaveLength(1);
    expect(screen.getByTitle('Copied from the dataset this one was derived from'))
      .toBeInTheDocument();
  });

  it('shows the audience-gap hint to editors only when the gap exists', async () => {
    vi.mocked(listKeywords).mockResolvedValue(
      keywordList({ inherited_audience_gap: true }),
    );
    render(<KeywordsEditor recordId="rec-1" canEdit />);

    await waitFor(() => {
      expect(
        screen.getByText(
          'Some keywords were inherited from a source dataset that not every reader here can open.',
        ),
      ).toBeInTheDocument();
    });
  });

  it('renders no marker or hint when nothing was inherited', async () => {
    vi.mocked(listKeywords).mockResolvedValue(
      keywordList({
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
        total: 1,
      }),
    );
    render(<KeywordsEditor recordId="rec-1" canEdit />);

    await waitFor(() => {
      expect(screen.getByText('riverine')).toBeInTheDocument();
    });
    expect(screen.queryByText('inherited')).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        'Some keywords were inherited from a source dataset that not every reader here can open.',
      ),
    ).not.toBeInTheDocument();
  });
});
