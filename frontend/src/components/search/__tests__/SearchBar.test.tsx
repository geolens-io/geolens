import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { useSearchStore } from '@/stores/search-store';
import { SearchBar } from '../SearchBar';

// Mock the debounce hook to return value immediately
vi.mock('@/hooks/use-debounce', () => ({
  useDebouncedValue: <T,>(value: T) => value,
}));

vi.mock('../SearchTypeahead', () => ({
  SearchTypeahead: () => null,
}));

const initialState = useSearchStore.getState();

describe('SearchBar', () => {
  beforeEach(() => {
    useSearchStore.setState(initialState, true);
  });

  it('renders input with placeholder', () => {
    render(<SearchBar />);

    expect(screen.getByPlaceholderText(/search geospatial/i)).toBeInTheDocument();
  });

  it('accepts typed input', async () => {
    const user = userEvent.setup();
    render(<SearchBar />);

    const input = screen.getByPlaceholderText(/search geospatial/i);
    await user.type(input, 'parks');

    expect(input).toHaveValue('parks');
  });

  it('shows clear button when input has value', async () => {
    const user = userEvent.setup();
    render(<SearchBar />);

    const input = screen.getByPlaceholderText(/search geospatial/i);
    await user.type(input, 'test');

    expect(screen.getByRole('button', { name: /clear search/i })).toBeInTheDocument();
  });

  it('clears input when clear button is clicked', async () => {
    const user = userEvent.setup();
    render(<SearchBar />);

    const input = screen.getByPlaceholderText(/search geospatial/i);
    await user.type(input, 'test');

    const clearButton = screen.getByRole('button', { name: /clear search/i });
    await user.click(clearButton);

    expect(input).toHaveValue('');
  });
});
