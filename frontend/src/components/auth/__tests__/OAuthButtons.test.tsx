import { render, screen, waitFor } from '@/test/test-utils';
import { OAuthButtons } from '../OAuthButtons';

vi.mock('@/api/auth', () => ({
  getOAuthProviders: vi.fn().mockResolvedValue([
    { slug: 'github', display_name: 'GitHub', provider_type: 'github' },
  ]),
}));

describe('OAuthButtons', () => {
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
