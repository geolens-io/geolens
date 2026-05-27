import type { ComponentProps } from 'react';
import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@/test/test-utils';
import { checkMapVisibility } from '@/api/maps';
import { ShareDialog, generateEmbedCode } from '@/components/builder/SharePanel';
import {
  useCreateEmbedToken,
  useMapEmbedTokens,
  useRevokeEmbedToken,
  useUpdateEmbedToken,
} from '@/components/builder/hooks/use-embed-tokens';
import { useEdition } from '@/hooks/use-edition';
import {
  useCreateShareToken,
  useMapShareToken,
  usePublishMap,
  useRevokeShareToken,
  useUpdateShareToken,
} from '@/hooks/use-maps';

vi.mock('@/hooks/use-edition', () => ({
  useEdition: vi.fn(),
}));

vi.mock('@/api/maps', () => ({
  checkMapVisibility: vi.fn(),
}));

vi.mock('@/hooks/use-maps', () => ({
  usePublishMap: vi.fn(),
  useCreateShareToken: vi.fn(),
  useRevokeShareToken: vi.fn(),
  useMapShareToken: vi.fn(),
  useUpdateShareToken: vi.fn(),
}));

vi.mock('@/components/builder/hooks/use-embed-tokens', () => ({
  useCreateEmbedToken: vi.fn(),
  useMapEmbedTokens: vi.fn(),
  useUpdateEmbedToken: vi.fn(),
  useRevokeEmbedToken: vi.fn(),
}));

const mockedUseEdition = vi.mocked(useEdition);
const mockedCheckMapVisibility = vi.mocked(checkMapVisibility);
const mockedUsePublishMap = vi.mocked(usePublishMap);
const mockedUseCreateShareToken = vi.mocked(useCreateShareToken);
const mockedUseRevokeShareToken = vi.mocked(useRevokeShareToken);
const mockedUseMapShareToken = vi.mocked(useMapShareToken);
const mockedUseUpdateShareToken = vi.mocked(useUpdateShareToken);
const mockedUseCreateEmbedToken = vi.mocked(useCreateEmbedToken);
const mockedUseMapEmbedTokens = vi.mocked(useMapEmbedTokens);
const mockedUseUpdateEmbedToken = vi.mocked(useUpdateEmbedToken);
const mockedUseRevokeEmbedToken = vi.mocked(useRevokeEmbedToken);

function mutationResult(mutateAsync = vi.fn()) {
  return {
    mutateAsync,
    isPending: false,
  } as never;
}

function setup({
  enterprise = false,
  hasShareToken = true,
  hasNonPublic = false,
  hasUnsavedChanges = false,
  saveStatus = hasUnsavedChanges ? 'unsaved' : 'saved',
}: {
  enterprise?: boolean;
  hasShareToken?: boolean;
  hasNonPublic?: boolean;
  hasUnsavedChanges?: boolean;
  saveStatus?: ComponentProps<typeof ShareDialog>['saveStatus'];
} = {}) {
  const createShareToken = vi.fn().mockResolvedValue({
    token: 'share-token',
    share_url: '/m/share-token',
    expires_at: null,
    is_active: true,
  });
  const createEmbedToken = vi.fn().mockResolvedValue({
    id: 'embed-2',
    raw_token: 'raw-token',
    token_hint: 'raw...',
    expires_at: '2026-06-01T00:00:00Z',
    is_active: true,
  });

  mockedUseEdition.mockReturnValue({
    edition: enterprise ? 'enterprise' : 'community',
    features: enterprise ? ['advanced-sharing'] : [],
    isEnterprise: enterprise,
    isLoading: false,
  });
  mockedUsePublishMap.mockReturnValue(mutationResult());
  mockedUseCreateShareToken.mockReturnValue(mutationResult(createShareToken));
  mockedUseRevokeShareToken.mockReturnValue(mutationResult());
  mockedUseUpdateShareToken.mockReturnValue(mutationResult());
  mockedUseCreateEmbedToken.mockReturnValue(mutationResult(createEmbedToken));
  mockedUseUpdateEmbedToken.mockReturnValue(mutationResult());
  mockedUseRevokeEmbedToken.mockReturnValue(mutationResult());
  mockedUseMapShareToken.mockReturnValue({
    data: hasShareToken
      ? {
          token: 'share-token',
          share_url: 'http://test/m/share-token',
          expires_at: null,
          is_active: true,
        }
      : null,
    isLoading: false,
    isError: false,
  } as never);
  mockedUseMapEmbedTokens.mockReturnValue({
    data: {
      tokens: hasShareToken
        ? [
            {
              id: 'embed-1',
              map_id: 'map-1',
              token_hint: 'emb...',
              scoped_dataset_ids: [],
              allowed_origins: ['https://example.com'],
              expires_at: '2026-06-01T00:00:00Z',
              is_active: true,
              use_count: 0,
              created_at: '2026-05-01T00:00:00Z',
            },
          ]
        : [],
      total: hasShareToken ? 1 : 0,
    },
    isLoading: false,
    isError: false,
  } as never);
  mockedCheckMapVisibility.mockResolvedValue({
    has_non_public: hasNonPublic,
    non_public_datasets: hasNonPublic ? ['Private dataset'] : [],
  });

  render(
    <ShareDialog
      mapId="map-1"
      visibility="public"
      open
      onOpenChange={vi.fn()}
      hasUnsavedChanges={hasUnsavedChanges}
      saveStatus={saveStatus}
    />,
  );

  return { createShareToken, createEmbedToken };
}

describe('ShareDialog edition gates', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('hides advanced sharing controls in community', async () => {
    const user = userEvent.setup();
    setup({ enterprise: false });

    await user.click(screen.getByRole('button', { name: /link settings/i }));

    expect(screen.queryByText('Expiration')).not.toBeInTheDocument();
    expect(screen.queryByText('Restrict to domains')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /revoke share link/i })).toBeInTheDocument();
  });

  it('keeps community share-link generation basic', async () => {
    const user = userEvent.setup();
    const { createShareToken, createEmbedToken } = setup({
      enterprise: false,
      hasShareToken: false,
      hasNonPublic: true,
    });

    await user.click(screen.getByRole('button', { name: /generate share link/i }));

    await waitFor(() => {
      expect(createShareToken).toHaveBeenCalledWith({ mapId: 'map-1' });
    });
    expect(createEmbedToken).toHaveBeenCalledWith({
      mapId: 'map-1',
      allowedOrigins: undefined,
    });
  });

  it('shows advanced sharing controls in enterprise', async () => {
    const user = userEvent.setup();
    setup({ enterprise: true });

    await user.click(screen.getByRole('button', { name: /link settings/i }));

    expect(screen.getByText('Expiration')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: /restrict to domains/i })).toBeInTheDocument();
  });

  it('warns when share output is behind unsaved builder changes', () => {
    setup({ hasUnsavedChanges: true, saveStatus: 'unsaved' });

    expect(screen.getByTestId('share-output-save-state')).toHaveTextContent(
      'Unsaved changes are only in the builder preview',
    );
  });

  it('does not expose copy/open actions when only a stored token hint is available', () => {
    setup({ hasShareToken: true });

    expect(screen.getByText(/full share link is only shown when it is created/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /copy link/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^open$/i })).not.toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ */
/*  SEC-07 / M-70: embed iframe sandbox attribute                      */
/* ------------------------------------------------------------------ */
//
// Pins the v13.13 closure of M-70. The combination of `allow-scripts` +
// `allow-same-origin` neutralizes the iframe sandbox (MDN-documented
// anti-pattern) — embed iframes loaded by external sites would have
// access to cookies/localStorage of the GeoLens deployment, defeating
// share-token isolation.
describe('SEC-07: embed code sandbox attribute', () => {
  it('uses allow-scripts only, no allow-same-origin', () => {
    const code = generateEmbedCode({
      shareToken: 'abc123',
      embedTokenRaw: 'tok-456',
      origin: 'https://geolens.example.com',
    });
    expect(code).toContain('sandbox="allow-scripts"');
    expect(code).not.toContain('allow-same-origin');
  });

  it('returns empty string when shareToken is missing', () => {
    const code = generateEmbedCode({
      shareToken: '',
      embedTokenRaw: '',
      origin: 'https://geolens.example.com',
    });
    expect(code).toBe('');
  });

  it('includes et=<token> when embedTokenRaw is provided', () => {
    const code = generateEmbedCode({
      shareToken: 'abc123',
      embedTokenRaw: 'tok-456',
      origin: 'https://geolens.example.com',
    });
    expect(code).toContain('et=tok-456');
  });

  it('omits et= param when embedTokenRaw is empty', () => {
    const code = generateEmbedCode({
      shareToken: 'abc123',
      embedTokenRaw: '',
      origin: 'https://geolens.example.com',
    });
    expect(code).not.toContain('et=');
  });

  // DOM-level assertion: render ShareDialog and read the embed-code textarea
  // value. Substitutes for the deferred Playwright MCP UAT — confirms the
  // sandbox value reaches the rendered DOM exactly as the unit-tested pure
  // function emits it (no later string-rewriting in the component layer).
  it('rendered embed textarea contains sandbox="allow-scripts" only after creating a raw share token', async () => {
    const user = userEvent.setup();
    setup({ enterprise: false, hasShareToken: false });

    await user.click(screen.getByRole('button', { name: /generate share link/i }));

    const textarea = await screen.findByRole('textbox') as HTMLTextAreaElement;
    expect(textarea).toBeTruthy();
    expect(textarea.value).toContain('sandbox="allow-scripts"');
    expect(textarea.value).not.toContain('allow-same-origin');
  });
});
