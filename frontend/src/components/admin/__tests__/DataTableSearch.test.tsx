import { act, fireEvent, render, screen } from '@/test/test-utils';
import { DataTableSearch } from '../DataTableSearch';

describe('DataTableSearch debounce', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not report the untouched initial value', () => {
    const onChange = vi.fn();
    render(<DataTableSearch value="" onChange={onChange} debounceMs={300} />);

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(onChange).not.toHaveBeenCalled();
  });

  it('reports a typed value once the delay passes', () => {
    const onChange = vi.fn();
    render(<DataTableSearch value="" onChange={onChange} debounceMs={300} />);

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'abc' } });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith('abc');
  });
});
