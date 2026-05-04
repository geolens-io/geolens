import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@/test/test-utils';
import { checkMapVisibility } from '@/api/maps';
import { ShareDialog } from '@/components/builder/SharePanel';
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
}: {
  enterprise?: boolean;
  hasShareToken?: boolean;
  hasNonPublic?: boolean;
} = {}) {
  const createShareToken = vi.fn().mockResolvedValue({
    token: 'share-token',
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
});
