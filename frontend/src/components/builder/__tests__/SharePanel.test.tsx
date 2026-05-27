import type { ComponentProps } from 'react';
import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@/test/test-utils';
import { checkMapVisibility } from '@/api/maps';
import { ApiError } from '@/api/client';
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
import { toast } from 'sonner';

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

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

/* ------------------------------------------------------------------ */
/*  SHARE-02 / SHARE-06: chip-based allowed-origins input             */
/* ------------------------------------------------------------------ */

/**
 * Helper: open Link Settings and enable the Restrict to domains switch.
 * Returns the user-event instance.
 */
async function openChipBlock(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /link settings/i }));
  const restrictSwitch = screen.getByRole('switch', { name: /restrict to domains/i });
  // Only click if not already checked (existing origins may pre-enable it)
  if (restrictSwitch.getAttribute('aria-checked') !== 'true') {
    await user.click(restrictSwitch);
  }
}

describe('SHARE-02 chip-based allowed-origins input', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('test_chip_input_adds_canonical_chip_on_enter: typing a URL and pressing Enter renders chip in canonical form', async () => {
    const updateEmbedTokenFn = vi.fn().mockResolvedValue({});
    mockedUseUpdateEmbedToken.mockReturnValue(mutationResult(updateEmbedTokenFn));
    // No pre-existing allowed_origins so chip block starts empty
    mockedUseMapEmbedTokens.mockReturnValue({
      data: {
        tokens: [
          {
            id: 'embed-1',
            map_id: 'map-1',
            token_hint: 'emb...',
            scoped_dataset_ids: [],
            allowed_origins: [],
            expires_at: '2026-06-01T00:00:00Z',
            is_active: true,
            use_count: 0,
            created_at: '2026-05-01T00:00:00Z',
          },
        ],
        total: 1,
      },
      isLoading: false,
      isError: false,
    } as never);

    const user = userEvent.setup();
    setup({ enterprise: true });
    await openChipBlock(user);

    const input = screen.getByRole('textbox', { name: /allowed origin url/i });
    await user.type(input, 'Example.com');
    await user.keyboard('{Enter}');

    // Chip with canonical form should appear
    expect(screen.getByText('https://example.com')).toBeInTheDocument();
    // Input should be cleared
    expect(input).toHaveValue('');
    // PATCH should fire with canonical origin
    await waitFor(() => {
      expect(updateEmbedTokenFn).toHaveBeenCalledOnce();
      expect(updateEmbedTokenFn).toHaveBeenCalledWith({
        mapId: 'map-1',
        tokenId: 'embed-1',
        allowedOrigins: ['https://example.com'],
      });
    });
  });

  it('test_chip_input_adds_chip_on_comma: trailing comma triggers add', async () => {
    const updateEmbedTokenFn = vi.fn().mockResolvedValue({});
    mockedUseUpdateEmbedToken.mockReturnValue(mutationResult(updateEmbedTokenFn));
    mockedUseMapEmbedTokens.mockReturnValue({
      data: {
        tokens: [
          {
            id: 'embed-1',
            map_id: 'map-1',
            token_hint: 'emb...',
            scoped_dataset_ids: [],
            allowed_origins: [],
            expires_at: '2026-06-01T00:00:00Z',
            is_active: true,
            use_count: 0,
            created_at: '2026-05-01T00:00:00Z',
          },
        ],
        total: 1,
      },
      isLoading: false,
      isError: false,
    } as never);

    const user = userEvent.setup();
    setup({ enterprise: true });
    await openChipBlock(user);

    const input = screen.getByRole('textbox', { name: /allowed origin url/i });
    // Type the URL then a comma — the comma triggers the add
    await user.type(input, 'https://other.io,');

    expect(screen.getByText('https://other.io')).toBeInTheDocument();
    await waitFor(() => {
      expect(updateEmbedTokenFn).toHaveBeenCalledOnce();
    });
  });

  it('test_chip_remove_X_button_fires_patch: clicking remove X removes chip and fires PATCH', async () => {
    const updateEmbedTokenFn = vi.fn().mockResolvedValue({});
    mockedUseUpdateEmbedToken.mockReturnValue(mutationResult(updateEmbedTokenFn));
    // Pre-populate with one origin
    mockedUseMapEmbedTokens.mockReturnValue({
      data: {
        tokens: [
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
        ],
        total: 1,
      },
      isLoading: false,
      isError: false,
    } as never);

    const user = userEvent.setup();
    setup({ enterprise: true });
    await openChipBlock(user);

    // Chip should be visible
    expect(screen.getByText('https://example.com')).toBeInTheDocument();

    // Click the remove button
    const removeBtn = screen.getByRole('button', { name: /remove https:\/\/example\.com/i });
    await user.click(removeBtn);

    expect(screen.queryByText('https://example.com')).not.toBeInTheDocument();
    await waitFor(() => {
      expect(updateEmbedTokenFn).toHaveBeenCalledOnce();
      expect(updateEmbedTokenFn).toHaveBeenCalledWith({
        mapId: 'map-1',
        tokenId: 'embed-1',
        allowedOrigins: null,
      });
    });
  });

  it('test_chip_input_dedupes_canonical_form: adding a duplicate canonical origin is silently discarded', async () => {
    const updateEmbedTokenFn = vi.fn().mockResolvedValue({});
    mockedUseUpdateEmbedToken.mockReturnValue(mutationResult(updateEmbedTokenFn));
    mockedUseMapEmbedTokens.mockReturnValue({
      data: {
        tokens: [
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
        ],
        total: 1,
      },
      isLoading: false,
      isError: false,
    } as never);

    const user = userEvent.setup();
    setup({ enterprise: true });
    await openChipBlock(user);

    // 1 chip from pre-populated origins
    expect(screen.getAllByRole('listitem')).toHaveLength(1);

    const input = screen.getByRole('textbox', { name: /allowed origin url/i });
    await user.type(input, 'HTTPS://Example.com/');
    await user.keyboard('{Enter}');

    // Still 1 chip, no mutation fired
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
    expect(updateEmbedTokenFn).not.toHaveBeenCalled();
  });

  it('test_chip_input_rejects_wildcard_inline: wildcard shows inline error, no chip, no PATCH', async () => {
    const updateEmbedTokenFn = vi.fn().mockResolvedValue({});
    mockedUseUpdateEmbedToken.mockReturnValue(mutationResult(updateEmbedTokenFn));
    mockedUseMapEmbedTokens.mockReturnValue({
      data: {
        tokens: [
          {
            id: 'embed-1',
            map_id: 'map-1',
            token_hint: 'emb...',
            scoped_dataset_ids: [],
            allowed_origins: [],
            expires_at: '2026-06-01T00:00:00Z',
            is_active: true,
            use_count: 0,
            created_at: '2026-05-01T00:00:00Z',
          },
        ],
        total: 1,
      },
      isLoading: false,
      isError: false,
    } as never);

    const user = userEvent.setup();
    setup({ enterprise: true });
    await openChipBlock(user);

    const input = screen.getByRole('textbox', { name: /allowed origin url/i });
    await user.type(input, '*');
    await user.keyboard('{Enter}');

    expect(screen.getByText(/wildcard origin not allowed/i)).toBeInTheDocument();
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
    expect(updateEmbedTokenFn).not.toHaveBeenCalled();
  });

  it('test_chip_input_surfaces_backend_wildcard_422_inline: backend 422 with wildcard message shows same inline error', async () => {
    const updateEmbedTokenFn = vi.fn().mockRejectedValue(
      new ApiError('Wildcard origin not allowed', 422)
    );
    mockedUseUpdateEmbedToken.mockReturnValue(mutationResult(updateEmbedTokenFn));
    mockedUseMapEmbedTokens.mockReturnValue({
      data: {
        tokens: [
          {
            id: 'embed-1',
            map_id: 'map-1',
            token_hint: 'emb...',
            scoped_dataset_ids: [],
            allowed_origins: [],
            expires_at: '2026-06-01T00:00:00Z',
            is_active: true,
            use_count: 0,
            created_at: '2026-05-01T00:00:00Z',
          },
        ],
        total: 1,
      },
      isLoading: false,
      isError: false,
    } as never);

    const user = userEvent.setup();
    setup({ enterprise: true });
    await openChipBlock(user);

    const input = screen.getByRole('textbox', { name: /allowed origin url/i });
    await user.type(input, 'https://valid.com');
    await user.keyboard('{Enter}');

    // Optimistic chip appears, then rollback happens after rejection
    await waitFor(() => {
      expect(screen.queryByText('https://valid.com')).not.toBeInTheDocument();
    });
    // Same inline error as frontend wildcard rejection
    expect(screen.getByText(/wildcard origin not allowed/i)).toBeInTheDocument();
  });

  it('test_chip_PATCH_failure_rolls_back: non-422 PATCH failure rolls back chip and surfaces toast', async () => {
    const updateEmbedTokenFn = vi.fn().mockRejectedValue(
      new ApiError('Internal Server Error', 500)
    );
    mockedUseUpdateEmbedToken.mockReturnValue(mutationResult(updateEmbedTokenFn));
    mockedUseMapEmbedTokens.mockReturnValue({
      data: {
        tokens: [
          {
            id: 'embed-1',
            map_id: 'map-1',
            token_hint: 'emb...',
            scoped_dataset_ids: [],
            allowed_origins: [],
            expires_at: '2026-06-01T00:00:00Z',
            is_active: true,
            use_count: 0,
            created_at: '2026-05-01T00:00:00Z',
          },
        ],
        total: 1,
      },
      isLoading: false,
      isError: false,
    } as never);

    const user = userEvent.setup();
    setup({ enterprise: true });
    await openChipBlock(user);

    const input = screen.getByRole('textbox', { name: /allowed origin url/i });
    await user.type(input, 'https://test.com');
    await user.keyboard('{Enter}');

    // Chip should be rolled back after error
    await waitFor(() => {
      expect(screen.queryByText('https://test.com')).not.toBeInTheDocument();
    });
    // Toast with updateFailed key
    expect(vi.mocked(toast.error)).toHaveBeenCalled();
  });
});
