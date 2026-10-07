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

let mockIsEnterprise = false;
let mockEditionResolved = true;
let mockEditionLoading = false;
vi.mock('@/hooks/use-edition', () => ({
  useEdition: () => ({
    isEnterprise: mockIsEnterprise,
    isResolved: mockEditionResolved,
    isLoading: mockEditionLoading,
  }),
}));

async function clickAndCaptureHref(button: HTMLElement): Promise<string[]> {
  const hrefs: string[] = [];
  const original = Object.getOwnPropertyDescriptor(window, 'location');
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...window.location, set href(v: string) { hrefs.push(v); } },
  });
  try {
    await userEvent.click(button);
    await waitFor(() => expect(hrefs).toHaveLength(1));
  } finally {
    if (original) Object.defineProperty(window, 'location', original);
  }
  return hrefs;
}

describe('OAuthButtons', () => {
  beforeEach(() => {
    mockIsEnterprise = false;
    mockEditionResolved = true;
    mockEditionLoading = false;
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

  // fix(#1852): a 2026-09-04 UX audit flagged "three unlabelled icon
  // buttons" on the login page's SSO row. The compact (2-3 branded
  // providers) layout renders icon-only, with the label carried on
  // aria-label/title instead of visible text — but no test exercised that
  // path, so a regression here would have shipped silently. Locking it in.
  it('gives each icon-only button in the compact (3-provider) layout an accessible name', async () => {
    const { getOAuthProviders } = await import('@/api/auth');
    (getOAuthProviders as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { slug: 'google', display_name: 'Google', provider_type: 'google' },
      { slug: 'microsoft', display_name: 'Microsoft', provider_type: 'microsoft' },
      { slug: 'github', display_name: 'GitHub', provider_type: 'github' },
    ]);

    render(<OAuthButtons />);

    const google = await screen.findByRole('button', { name: /sign in with google/i });
    const microsoft = await screen.findByRole('button', { name: /sign in with microsoft/i });
    const github = await screen.findByRole('button', { name: /sign in with github/i });

    // Icon-only: no visible label text inside the button, only the icon.
    for (const button of [google, microsoft, github]) {
      expect(button).toHaveAttribute('aria-label');
      expect(button.querySelector('span')).not.toBeInTheDocument();
    }
  });

  it('sends SAML providers to the SAML login route and OIDC providers to the OAuth route', async () => {
    mockIsEnterprise = true;
    const { getOAuthProviders } = await import('@/api/auth');
    (getOAuthProviders as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { slug: 'corp-saml', display_name: 'Corp SSO', provider_type: 'saml' },
      { slug: 'corp-oidc', display_name: 'Corp OIDC', provider_type: 'oidc' },
    ]);

    render(<OAuthButtons />);

    const saml = await screen.findByRole('button', { name: /corp sso/i });
    const oidc = await screen.findByRole('button', { name: /corp oidc/i });
    expect(await clickAndCaptureHref(saml)).toEqual(['/api/auth/saml/corp-saml/login']);
    expect(await clickAndCaptureHref(oidc)).toEqual(['/api/auth/oauth/corp-oidc/login']);
  });

  it('hides SAML providers when the runtime is not Enterprise', async () => {
    const { getOAuthProviders } = await import('@/api/auth');
    (getOAuthProviders as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { slug: 'corp-saml', display_name: 'Corp SSO', provider_type: 'saml' },
      { slug: 'corp-oidc', display_name: 'Corp OIDC', provider_type: 'oidc' },
    ]);

    render(<OAuthButtons />);

    await screen.findByRole('button', { name: /corp oidc/i });
    expect(screen.queryByRole('button', { name: /corp sso/i })).not.toBeInTheDocument();
  });

  it('keeps SAML providers when the edition lookup failed', async () => {
    mockEditionResolved = false;
    const { getOAuthProviders } = await import('@/api/auth');
    (getOAuthProviders as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { slug: 'corp-saml', display_name: 'Corp SSO', provider_type: 'saml' },
    ]);

    render(<OAuthButtons />);

    expect(await screen.findByRole('button', { name: /corp sso/i })).toBeInTheDocument();
  });
});
