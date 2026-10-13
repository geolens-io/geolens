import { render, screen, waitFor } from '@/test/test-utils';
import { MemoryRouter, Routes, Route } from 'react-router';
import userEvent from '@testing-library/user-event';

vi.mock('sonner', () => ({
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

vi.mock('@/api/auth', () => ({
  rememberThisBrowser: vi.fn(),
}));

import { toast } from 'sonner';
import { rememberThisBrowser } from '@/api/auth';
import { TrustBrowserPage } from '../TrustBrowserPage';

const mockedRemember = vi.mocked(rememberThisBrowser);

function renderAt(url: string) {
  function Wrapper({ children: _children }: { children: React.ReactNode }) {
    return (
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/login/trust" element={<TrustBrowserPage />} />
          <Route path="/login" element={<div>LOGIN PAGE</div>} />
        </Routes>
      </MemoryRouter>
    );
  }
  return render(<TrustBrowserPage />, { wrapper: Wrapper });
}

describe('TrustBrowserPage', () => {
  beforeEach(() => vi.clearAllMocks());

  it('redeems the link only when the button is pressed, then returns to sign-in', async () => {
    mockedRemember.mockResolvedValue(undefined);
    renderAt('/login/trust?token=abc123');

    const button = await screen.findByRole('button', { name: 'Remember this browser' });
    expect(mockedRemember).not.toHaveBeenCalled();

    await userEvent.click(button);
    await waitFor(() => expect(mockedRemember).toHaveBeenCalledWith('abc123'));
    expect(toast.success).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('LOGIN PAGE')).toBeInTheDocument();
  });

  it('shows the refusal and stays on the page', async () => {
    mockedRemember.mockRejectedValue(new Error('This link is invalid'));
    renderAt('/login/trust?token=abc123');

    await userEvent.click(await screen.findByRole('button', { name: 'Remember this browser' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('This link is invalid');
    expect(screen.queryByText('LOGIN PAGE')).not.toBeInTheDocument();
  });

  it('offers no button when the link has no token', async () => {
    renderAt('/login/trust');
    expect(await screen.findByText(/missing its code/)).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
