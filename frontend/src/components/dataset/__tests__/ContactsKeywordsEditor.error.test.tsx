// GAP-034: ContactsEditor / KeywordsEditor previously collapsed a fetch error
// into the empty 'noContacts'/'noKeywords' state (data?.contacts ?? []), which
// silently mislead the editor into thinking the record has none and re-adding
// duplicates. They must now render a distinct error + retry state.
import { render, screen, waitFor } from '@/test/test-utils';
import { ContactsEditor } from '../ContactsEditor';
import { KeywordsEditor } from '../KeywordsEditor';
import { listContacts, listKeywords } from '@/api/records';

vi.mock('@/api/records', () => ({
  listContacts: vi.fn(),
  createContact: vi.fn(),
  deleteContact: vi.fn(),
  listKeywords: vi.fn(),
  createKeyword: vi.fn(),
  deleteKeyword: vi.fn(),
}));

describe('ContactsEditor error state (GAP-034)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('renders a distinct error + retry state on fetch failure (not the empty state)', async () => {
    vi.mocked(listContacts).mockRejectedValue(new Error('Network error'));
    render(<ContactsEditor recordId="rec-1" canEdit />);

    await waitFor(() => {
      expect(screen.getByText('Failed to load contacts.')).toBeInTheDocument();
    });
    // The misleading empty-state copy must NOT be shown on error.
    expect(screen.queryByText('No contacts added yet.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('shows the empty state (not the error) on a successful empty fetch', async () => {
    vi.mocked(listContacts).mockResolvedValue({ contacts: [] } as never);
    render(<ContactsEditor recordId="rec-1" canEdit />);

    await waitFor(() => {
      expect(screen.getByText('No contacts added yet.')).toBeInTheDocument();
    });
    expect(screen.queryByText('Failed to load contacts.')).not.toBeInTheDocument();
  });
});

describe('KeywordsEditor error state (GAP-034)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('renders a distinct error + retry state on fetch failure (not the empty state)', async () => {
    vi.mocked(listKeywords).mockRejectedValue(new Error('Network error'));
    render(<KeywordsEditor recordId="rec-1" canEdit={false} />);

    await waitFor(() => {
      expect(screen.getByText('Failed to load keywords.')).toBeInTheDocument();
    });
    expect(screen.queryByText('No keywords added yet.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });
});
