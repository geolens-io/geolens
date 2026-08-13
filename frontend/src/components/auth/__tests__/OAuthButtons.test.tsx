import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { OAuthButtons } from '../OAuthButtons';

const mockAwaitPendingLogout = vi.fn<() => Promise<void>>();

vi.mock('@/api/auth', () => ({
  getOAuthProviders: vi.fn().mockResolvedValue([
    { slug: 'github', display_name: 'GitHub', provider_type: 'github' },
  ]),
  awaitPendingLogout: () => mockAwaitPendingLogout(),
}));

describe('OAuthButtons', () => {
  beforeEach(() => {
    mockAwaitPendingLogout.mockReset();
    mockAwaitPendingLogout.mockResolvedValue(undefined);
  });

  // fix(#1446): OAuth is a second sign-in entry point. A logout dispatched
  // moments earlier revokes every refresh token and deletes the cookies, so a
  // fast callback could install the new session only for the older logout to
  // revoke it. Password login already waits; this path must too.
  it('waits for a pending logout before redirecting to the provider', async () => {
    let releaseLogout: () => void = () => {};
    mockAwaitPendingLogout.mockReturnValue(
      new Promise<void>((resolve) => {
        releaseLogout = resolve;
      }),
    );
    const hrefs: string[] = [];
    const original = Object.getOwnPropertyDescriptor(window, 'location');
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, set href(v: string) { hrefs.push(v); } },
    });

    try {
      render(<OAuthButtons />);
      const button = await screen.findByRole('button', { name: /sign in with github/i });
      await userEvent.click(button);

      expect(mockAwaitPendingLogout).toHaveBeenCalledTimes(1);
      expect(hrefs).toEqual([]);

      releaseLogout();
      await waitFor(() => expect(hrefs).toEqual(['/api/auth/oauth/github/login']));
    } finally {
      if (original) Object.defineProperty(window, 'location', original);
    }
  });

  it('renders a GitHub button with the GitHub mark icon and localized label', async () => {
    render(<OAuthButtons />);

    const button = await screen.findByRole('button', {
      name: /sign in with github/i,
    });
    expect(button).toBeInTheDocument();

    // The GitHub mark SVG should be present inside the button
    const svg = button.querySelector('svg');
    expect(svg).toBeInTheDocument();
  });

  it('renders a Google button without regressing when provider_type is google', async () => {
    const { getOAuthProviders } = await import('@/api/auth');
    (getOAuthProviders as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { slug: 'google', display_name: 'Google', provider_type: 'google' },
    ]);

    render(<OAuthButtons />);

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /sign in with google/i }),
      ).toBeInTheDocument();
    });
  });
});
