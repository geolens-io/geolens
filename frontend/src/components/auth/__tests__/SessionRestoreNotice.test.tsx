import { render } from '@testing-library/react';
import { act } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { toast } from 'sonner';
import { abortInflightRefresh, ApiError } from '@/api/client';
import { refreshAccessToken } from '@/api/auth';
import { SessionRestoreNotice } from '@/components/auth/SessionRestoreNotice';
import { restoreSession, useSessionRestore } from '@/lib/session-sync';
import { useAuthStore } from '@/stores/auth-store';
import type { UserResponse } from '@/types/api';

vi.mock('@/api/auth', () => ({
  refreshAccessToken: vi.fn(),
  getMe: vi.fn(() => new Promise(() => {})),
  revokeCurrentSession: vi.fn(() => Promise.resolve()),
  logoutSession: vi.fn(() => Promise.resolve()),
}));

vi.mock('sonner', () => ({ toast: { warning: vi.fn(), dismiss: vi.fn() } }));

const user = { id: 'u1', username: 'someone', roles: ['admin'] } as unknown as UserResponse;

function renderNotice() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
  render(
    <QueryClientProvider client={queryClient}>
      <SessionRestoreNotice />
    </QueryClientProvider>,
  );
  return invalidate;
}

/** A reload: the stored user and session id, but no access token in memory. */
function reloaded() {
  useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user, sessionId: 'session-1' });
}

async function restoreRateLimited() {
  vi.mocked(refreshAccessToken).mockRejectedValueOnce(new ApiError('rate limited', 429));
  vi.useFakeTimers();
  try {
    const pending = restoreSession();
    await vi.advanceTimersByTimeAsync(2_000);
    await act(() => pending);
  } finally {
    vi.useRealTimers();
  }
}

describe('SessionRestoreNotice', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    reloaded();
  });

  afterEach(() => {
    abortInflightRefresh();
    useSessionRestore.setState({ failures: 0 });
    useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null, sessionId: null });
  });

  it('stays quiet while the session restores normally', async () => {
    vi.mocked(refreshAccessToken).mockResolvedValueOnce({
      access_token: 'recovered', refresh_token: null, token_type: 'bearer', expires_in: 900,
    });
    renderNotice();

    await act(() => restoreSession());

    expect(toast.warning).not.toHaveBeenCalled();
  });

  it('offers a retry when a reload could not restore the session, and refetches once it does', async () => {
    const invalidate = renderNotice();

    await restoreRateLimited();

    expect(useAuthStore.getState()).toMatchObject({ token: null, user });
    expect(toast.warning).toHaveBeenCalledWith(
      "We couldn't restore your session",
      expect.objectContaining({ id: 'session-restore', duration: Infinity }),
    );
    const action = vi.mocked(toast.warning).mock.calls[0][1]?.action as {
      label: string;
      onClick: () => void;
    };
    expect(action.label).toBe('Try again');

    vi.mocked(refreshAccessToken).mockResolvedValueOnce({
      access_token: 'recovered', refresh_token: null, token_type: 'bearer', expires_in: 900,
    });
    await act(async () => action.onClick());

    await vi.waitFor(() => expect(useAuthStore.getState().token).toBe('recovered'));
    expect(refreshAccessToken).toHaveBeenCalledTimes(2);
    expect(toast.dismiss).toHaveBeenCalledWith('session-restore');
    expect(invalidate).toHaveBeenCalled();
    expect(useSessionRestore.getState().failures).toBe(0);
  });

  it('withdraws the offer when the session ends instead', async () => {
    const invalidate = renderNotice();
    await restoreRateLimited();
    expect(toast.warning).toHaveBeenCalledTimes(1);

    act(() => useAuthStore.getState().logout());

    expect(toast.dismiss).toHaveBeenCalledWith('session-restore');
    expect(invalidate).not.toHaveBeenCalled();
    expect(useSessionRestore.getState().failures).toBe(0);
  });
});
