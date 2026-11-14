/** NewVersionBanner shows only when the server reports a different, non-empty version. */
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { NewVersionBanner } from '../NewVersionBanner';
import { apiFetch } from '@/api/client';

vi.mock('@/api/client', () => ({ apiFetch: vi.fn() }));

const fetchMock = vi.mocked(apiFetch);

function renderBanner() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <NewVersionBanner />
    </QueryClientProvider>,
  );
}

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { value: state, configurable: true });
  document.dispatchEvent(new Event('visibilitychange', { bubbles: true }));
}

describe('NewVersionBanner', () => {
  beforeEach(() => {
    vi.stubGlobal('__APP_VERSION__', '1.0.0');
    fetchMock.mockReset();
  });
  afterEach(() => vi.unstubAllGlobals());

  it('shows when the server version differs', async () => {
    fetchMock.mockResolvedValue({ version: '1.1.0' });
    renderBanner();
    expect(await screen.findByRole('status')).toHaveTextContent(/new version/i);
  });

  it.each([
    ['equal', { version: '1.0.0' }],
    ['missing', {}],
    ['empty', { version: '' }],
    ['null', { version: null }],
  ])('stays hidden when the server version is %s', async (_n, body) => {
    fetchMock.mockResolvedValue(body);
    renderBanner();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('stays hidden when the bundle has no version', async () => {
    vi.stubGlobal('__APP_VERSION__', '');
    fetchMock.mockResolvedValue({ version: '1.1.0' });
    renderBanner();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('stays hidden when the request fails', async () => {
    fetchMock.mockRejectedValue(new Error('down'));
    renderBanner();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('reloads on demand and hides on dismiss', async () => {
    fetchMock.mockResolvedValue({ version: '1.1.0' });
    const reload = vi.fn();
    vi.stubGlobal('location', { ...window.location, reload });
    renderBanner();
    await screen.findByRole('status');
    fireEvent.click(screen.getByRole('button', { name: /reload/i }));
    expect(reload).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(screen.queryByRole('status')).toBeNull();
  });

  it.each([
    ['1.4.0-rc.1', '1.4.0rc1', false],
    ['1.4.0-rc.1', '1.4.0rc2', true],
    ['1.31.0', '1.31.1', true],
  ])('bundle %s vs server %s shows banner: %s', async (bundle, server, shown) => {
    vi.stubGlobal('__APP_VERSION__', bundle);
    fetchMock.mockResolvedValue({ version: server });
    renderBanner();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    if (shown) expect(await screen.findByRole('status')).toBeInTheDocument();
    else expect(screen.queryByRole('status')).toBeNull();
  });

  it('re-checks on visibility only after the stale window and re-prompts for a newer version', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    try {
      fetchMock.mockResolvedValue({ version: '1.1.0' });
      renderBanner();
      await screen.findByRole('status');
      fireEvent.click(screen.getByRole('button', { name: /close/i }));
      fetchMock.mockResolvedValue({ version: '1.2.0' });
      const calls = fetchMock.mock.calls.length;

      act(() => setVisibility('visible'));
      await new Promise((r) => setTimeout(r, 50));
      expect(fetchMock.mock.calls.length).toBe(calls);

      vi.setSystemTime(Date.now() + 61_000);
      act(() => setVisibility('visible'));
      await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(calls));
      expect(await screen.findByRole('status')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
