import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { act } from 'react';
import { SessionExpiredDialog } from '@/components/auth/SessionExpiredDialog';
import { notifySessionExpired } from '@/api/client';
import { useAuthStore } from '@/stores/auth-store';

// fix(#628): the global signed-out host — one dismissable prompt when the
// fetch core declares the session dead, sign-in returns to the current route,
// and anonymous-capable routes downgrade silently instead of prompting.

function LoginProbe() {
  const location = useLocation();
  return <div data-testid="login-probe">{(location.state as { from?: string } | null)?.from ?? 'no-from'}</div>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SessionExpiredDialog />
      <Routes>
        <Route path="/login" element={<LoginProbe />} />
        <Route path="*" element={<div />} />
      </Routes>
    </MemoryRouter>,
  );
}

// The client module's notification latch is keyed on the dead refresh token's
// value — give each test a unique one so notify fires.
let deadToken = 0;
function nextDeadToken() {
  deadToken += 1;
  return `dead-refresh-${deadToken}`;
}

describe('SessionExpiredDialog', () => {
  beforeEach(() => {
    useAuthStore.setState({ token: 't', refreshToken: 'r', expiresAt: Date.now() + 120_000 });
    sessionStorage.clear();
  });

  it('shows a single signed-out prompt whose sign-in action returns to the current route', async () => {
    renderAt('/datasets/abc?tab=preview');

    const dead = nextDeadToken();
    act(() => notifySessionExpired(dead));
    // Duplicate notifications (concurrent request failures) stay latched.
    act(() => notifySessionExpired(dead));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText("You've been signed out")).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(screen.getByTestId('login-probe')).toHaveTextContent('/datasets/abc?tab=preview');
    // The OAuth callback reads this key for the SSO round-trip.
    expect(sessionStorage.getItem('geolens-login-redirect')).toBe('/datasets/abc?tab=preview');
  });

  it('is dismissable', async () => {
    renderAt('/datasets/abc');
    act(() => notifySessionExpired(nextDeadToken()));

    await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('downgrades silently on anonymous-capable routes instead of prompting', () => {
    renderAt('/');
    act(() => notifySessionExpired(nextDeadToken()));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    // The session is still cleared — queries refetch anonymously.
    expect(useAuthStore.getState().token).toBeNull();
  });
});
