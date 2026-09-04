import type { ComponentProps } from 'react';
import userEvent from '@testing-library/user-event';
import { fireEvent, render, screen, waitFor } from '@/test/test-utils';
import { checkMapVisibility } from '@/api/maps';
import { ApiError } from '@/api/client';
import { translateApiErrorDetail } from '@/lib/error-map';
import { ShareDialog, generateEmbedCode, buildEmbedSrc } from '@/components/builder/SharePanel';
import {
  useCreateEmbedToken,
  useMapEmbedTokens,
  useRevokeEmbedToken,
  useUpdateEmbedToken,
} from '@/components/builder/hooks/use-embed-tokens';
import { useEdition } from '@/hooks/use-edition';
import { useCanSetPublicVisibility, useTileConfig } from '@/hooks/use-settings';
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

// fix(#1548 review r3): SharePanel now reads the deployment's configured
// public origin for every URL it hands out. Default the mock to the current
// origin so tests written before that change emit byte-identical URLs; the
// tests that care drive a DIFFERENT hostname, which is the whole point.
vi.mock('@/hooks/use-settings', () => ({
  useTileConfig: vi.fn(),
  useCanSetPublicVisibility: vi.fn(),
}));

vi.mock('@/components/builder/hooks/use-embed-tokens', () => ({
  useCreateEmbedToken: vi.fn(),
  useMapEmbedTokens: vi.fn(),
  useUpdateEmbedToken: vi.fn(),
  useRevokeEmbedToken: vi.fn(),
}));

const mockedUseTileConfig = vi.mocked(useTileConfig);
const mockedUseCanSetPublicVisibility = vi.mocked(useCanSetPublicVisibility);
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

// Embed tokens render the "Restrict to domains" control only when an active
// (non-expired) token exists: SharePanel filters on `new Date(expires_at) > now`.
// A hardcoded fixture date becomes a time-bomb (failed once 2026-06-01 rolled
// past the old '2026-06-01T00:00:00Z'). Compute a far-future expiry relative to
// now so the token is always considered active during the test run.
const FUTURE_EMBED_EXPIRES_AT = new Date(
  Date.now() + 365 * 24 * 60 * 60 * 1000,
).toISOString();

function setup({
  enterprise = false,
  hasShareToken = true,
  hasNonPublic = false,
  hasUnsavedChanges = false,
  saveStatus = hasUnsavedChanges ? 'unsaved' : 'saved',
  allowedOrigins = ['https://example.com'],
  updateEmbedTokenFn = vi.fn().mockResolvedValue({}),
  updateShareTokenFn = vi.fn().mockResolvedValue({}),
  shareExpires = null,
  createEmbedTokenFn,
  visibility = 'public',
  layers,
  publishMapFn = vi.fn().mockResolvedValue({}),
  publicAppUrl = window.location.origin,
  canSetPublic = true,
  forceActiveEmbedToken = false,
  lockOriginsAfterCreate = null,
}: {
  enterprise?: boolean;
  hasShareToken?: boolean;
  hasNonPublic?: boolean;
  hasUnsavedChanges?: boolean;
  saveStatus?: ComponentProps<typeof ShareDialog>['saveStatus'];
  allowedOrigins?: string[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  updateEmbedTokenFn?: (...args: any[]) => any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  updateShareTokenFn?: (...args: any[]) => any;
  shareExpires?: string | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  createEmbedTokenFn?: (...args: any[]) => any;
  visibility?: ComponentProps<typeof ShareDialog>['visibility'];
  layers?: ComponentProps<typeof ShareDialog>['layers'];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  publishMapFn?: (...args: any[]) => any;
  /** The deployment's configured PUBLIC_APP_URL. null = unconfigured. */
  publicAppUrl?: string | null;
  /** feat(#1691): useCanSetPublicVisibility() — false when the instance
   *  restricts public visibility to admins and the user is not one. */
  canSetPublic?: boolean;
  /** Return an active embed token even when the share link is created at
   *  runtime — the domain-locked branch needs both. */
  forceActiveEmbedToken?: boolean;
  /** Origins that appear on the active token only AFTER one is created here.
   *  Mirrors the real builder sequence — a token is minted unlocked and the
   *  origins are PATCHed on afterwards — and is the only way to reach a
   *  domain-locked PREVIEW, since createEmbed() skips when a token already
   *  exists and the raw token is available only at creation. */
  lockOriginsAfterCreate?: string[] | null;
} = {}) {
  const createShareToken = vi.fn().mockResolvedValue({
    token: 'share-token',
    share_url: '/m/share-token',
    expires_at: null,
    is_active: true,
  });
  let embedTokenCreated = false;
  const createEmbedToken = createEmbedTokenFn ?? vi.fn().mockImplementation(async () => {
    embedTokenCreated = true;
    return {
      id: 'embed-2',
      raw_token: 'raw-token',
      token_hint: 'raw...',
      expires_at: FUTURE_EMBED_EXPIRES_AT,
      is_active: true,
    };
  });

  mockedUseCanSetPublicVisibility.mockReturnValue(canSetPublic);

  mockedUseTileConfig.mockReturnValue({
    data: {
      cdn_base_url: null,
      public_app_url: publicAppUrl,
      public_api_url: publicAppUrl ? `${publicAppUrl}/api` : null,
      public_base_url: null,
      mvt_source_layer_prefix: 'data',
    },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);

  mockedUseEdition.mockReturnValue({
    edition: enterprise ? 'enterprise' : 'community',
    features: enterprise ? ['advanced-sharing'] : [],
    isEnterprise: enterprise,
    isMultiTenant: false,
    isLoading: false,
    isResolved: true,
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockedUsePublishMap.mockReturnValue(mutationResult(publishMapFn as any));
  mockedUseCreateShareToken.mockReturnValue(mutationResult(createShareToken));
  mockedUseRevokeShareToken.mockReturnValue(mutationResult());
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockedUseUpdateShareToken.mockReturnValue(mutationResult(updateShareTokenFn as any));
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockedUseCreateEmbedToken.mockReturnValue(mutationResult(createEmbedToken as any));
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockedUseUpdateEmbedToken.mockReturnValue(mutationResult(updateEmbedTokenFn as any));
  mockedUseRevokeEmbedToken.mockReturnValue(mutationResult());
  mockedUseMapShareToken.mockReturnValue({
    data: hasShareToken
      ? {
          token: 'share-token',
          share_url: 'http://test/m/share-token',
          expires_at: shareExpires,
          is_active: true,
        }
      : null,
    isLoading: false,
    isError: false,
  } as never);
  const embedTokenRow = (origins: string[]) => ({
    id: 'embed-1',
    map_id: 'map-1',
    token_hint: 'emb...',
    scoped_dataset_ids: [],
    allowed_origins: origins,
    expires_at: FUTURE_EMBED_EXPIRES_AT,
    is_active: true,
    use_count: 0,
    created_at: '2026-05-01T00:00:00Z',
  });
  mockedUseMapEmbedTokens.mockImplementation((() => {
    if (lockOriginsAfterCreate && embedTokenCreated) {
      return {
        data: { tokens: [embedTokenRow(lockOriginsAfterCreate)], total: 1 },
        isLoading: false,
        isError: false,
      };
    }
    if (lockOriginsAfterCreate) {
      return { data: { tokens: [], total: 0 }, isLoading: false, isError: false };
    }
    return {
      data: {
        tokens: hasShareToken || forceActiveEmbedToken
          ? [
            {
              id: 'embed-1',
              map_id: 'map-1',
              token_hint: 'emb...',
              scoped_dataset_ids: [],
              allowed_origins: allowedOrigins,
              expires_at: FUTURE_EMBED_EXPIRES_AT,
              is_active: true,
              use_count: 0,
              created_at: '2026-05-01T00:00:00Z',
            },
            ]
          : [],
        total: hasShareToken || forceActiveEmbedToken ? 1 : 0,
      },
      isLoading: false,
      isError: false,
    };
  }) as never);
  mockedCheckMapVisibility.mockResolvedValue({
    has_non_public: hasNonPublic,
    non_public_datasets: hasNonPublic ? ['Private dataset'] : [],
  });

  render(
    <ShareDialog
      mapId="map-1"
      visibility={visibility}
      open
      onOpenChange={vi.fn()}
      hasUnsavedChanges={hasUnsavedChanges}
      saveStatus={saveStatus}
      layers={layers}
    />,
  );

  return { createShareToken, createEmbedToken: createEmbedToken as ReturnType<typeof vi.fn>, updateEmbedTokenFn, updateShareTokenFn, publishMapFn };
}

describe('ShareDialog edition gates', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows fixed expiration presets but hides advanced sharing controls in community', async () => {
    const user = userEvent.setup();
    setup({ enterprise: false });

    await user.click(screen.getByRole('button', { name: /link settings/i }));

    expect(screen.getByText('Expiration')).toBeInTheDocument();
    expect(screen.queryByText('Restrict to domains')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /revoke share link/i })).toBeInTheDocument();

    openExpirationSelect();
    const options = screen.getAllByRole('option').map((option) => option.textContent);
    expect(options).toEqual(['Never', '1 day', '7 days', '30 days', '90 days']);
    expect(options).not.toContain('Custom date…');
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
/*  #1515: embed iframe sandbox attribute                              */
/* ------------------------------------------------------------------ */
//
// Supersedes the M-70 contract this block used to pin. `allow-scripts` alone
// gives the frame an opaque origin, and the emitted snippet could not boot:
// measured end to end, the viewer rendered "Map not found" for a valid share
// token because every /api/ call was cross-origin with `Origin: null`.
//
// The sandbox-escape M-70 feared needs the frame to be same-origin with its
// EMBEDDER, which a third-party embed never is. See the generateEmbedCode
// docstring.
//
// The whole string is asserted, not just the sandbox value: this snippet is
// copied verbatim into other people's pages, so an edit to any part of the
// template should fail here rather than ship.
describe('#1515: embed code sandbox attribute', () => {
  it('emits the exact snippet, sandbox included', () => {
    const code = generateEmbedCode({
      shareToken: 'abc123',
      embedTokenRaw: 'tok-456',
      origin: 'https://geolens.example.com',
    });
    expect(code).toBe(
      '<iframe src="https://geolens.example.com/m/abc123?embed=true&et=tok-456"' +
        ' width="800" height="600" sandbox="allow-scripts allow-same-origin"' +
        ' style="border:none;"></iframe>',
    );
  });

  it('carries allow-same-origin, without which the frame cannot load its own bundle', () => {
    const code = generateEmbedCode({
      shareToken: 'abc123',
      embedTokenRaw: 'tok-456',
      origin: 'https://geolens.example.com',
    });
    expect(code).toContain('sandbox="allow-scripts allow-same-origin"');
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
  it('rendered embed textarea carries the emitted sandbox after creating a raw share token', async () => {
    const user = userEvent.setup();
    setup({ enterprise: false, hasShareToken: false });

    await user.click(screen.getByRole('button', { name: /generate share link/i }));

    const textarea = await screen.findByRole('textbox') as HTMLTextAreaElement;
    expect(textarea).toBeTruthy();
    expect(textarea.value).toContain('sandbox="allow-scripts allow-same-origin"');
  });
});

describe('SHARE-04: buildEmbedSrc shared URL builder', () => {
  it('builds the viewer src with embed=true and et=<token>', () => {
    const src = buildEmbedSrc({
      shareToken: 'abc123',
      embedTokenRaw: 'tok-456',
      origin: 'https://geolens.example.com',
    });
    expect(src).toBe('https://geolens.example.com/m/abc123?embed=true&et=tok-456');
  });

  it('omits et= when no embed token is supplied', () => {
    const src = buildEmbedSrc({ shareToken: 'abc123', embedTokenRaw: '', origin: 'https://x.io' });
    expect(src).toBe('https://x.io/m/abc123?embed=true');
  });

  it('generateEmbedCode wraps the exact buildEmbedSrc output (no drift)', () => {
    const args = { shareToken: 'abc123', embedTokenRaw: 'tok-456', origin: 'https://x.io' };
    expect(generateEmbedCode(args)).toContain(`src="${buildEmbedSrc(args)}"`);
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
    const user = userEvent.setup();
    const { updateEmbedTokenFn } = setup({ enterprise: true, allowedOrigins: [] });
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
    const user = userEvent.setup();
    const { updateEmbedTokenFn } = setup({ enterprise: true, allowedOrigins: [] });
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
    const user = userEvent.setup();
    // Pre-populate with one origin (default allowedOrigins = ['https://example.com'])
    const { updateEmbedTokenFn } = setup({ enterprise: true });
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
    const user = userEvent.setup();
    // Pre-populate with one origin
    const { updateEmbedTokenFn } = setup({ enterprise: true });
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
    const user = userEvent.setup();
    const { updateEmbedTokenFn } = setup({ enterprise: true, allowedOrigins: [] });
    await openChipBlock(user);

    const input = screen.getByRole('textbox', { name: /allowed origin url/i });
    await user.type(input, '*');
    await user.keyboard('{Enter}');

    expect(screen.getByText(/wildcard origin not allowed/i)).toBeInTheDocument();
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
    expect(updateEmbedTokenFn).not.toHaveBeenCalled();
  });

  it('test_chip_input_surfaces_backend_wildcard_422_inline: backend 422 with wildcard message shows same inline error', async () => {
    const user = userEvent.setup();
    const updateEmbedTokenFn = vi.fn().mockRejectedValue(
      new ApiError('Wildcard origin not allowed', 422)
    );
    setup({ enterprise: true, allowedOrigins: [], updateEmbedTokenFn });
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

  /**
   * fix(#1548 review P2): both compose files ship PUBLIC_APP_URL defaulted to
   * localhost, so a self-hoster reached at a real hostname is refused here on a
   * stock install. The refusal exists to replace a silently-empty embed with an
   * actionable message, so routing it to the generic "update failed" toast — the
   * default for any unmapped 422 — would put them back where they started.
   */
  const DOMAIN_LOCK_DETAIL =
    'Domain locking cannot be enforced by this deployment: its public app URL ' +
    'resolves to http://localhost:8080, but this request reached it at ' +
    'https://maps.example.com. An embed shell\'s own API calls carry the ' +
    "shell's origin, so a domain-locked token issued now would load an empty " +
    'map. Set PUBLIC_APP_URL (or the public_app_url setting) to ' +
    'https://maps.example.com and try again.';

  function domainLockRefusal() {
    // Mirrors apiFetch: message is already localized, body carries the detail.
    return new ApiError(
      translateApiErrorDetail(DOMAIN_LOCK_DETAIL, 422),
      422,
      DOMAIN_LOCK_DETAIL,
    );
  }

  it('test_chip_input_surfaces_unenforceable_domain_lock_inline: the refusal names PUBLIC_APP_URL where the operator is looking', async () => {
    const user = userEvent.setup();
    const updateEmbedTokenFn = vi.fn().mockRejectedValue(domainLockRefusal());
    setup({ enterprise: true, allowedOrigins: [], updateEmbedTokenFn });
    await openChipBlock(user);

    const input = screen.getByRole('textbox', { name: /allowed origin url/i });
    await user.type(input, 'https://customer.example.com');
    await user.keyboard('{Enter}');

    await waitFor(() => {
      expect(screen.queryByText('https://customer.example.com')).not.toBeInTheDocument();
    });
    expect(screen.getByText(/PUBLIC_APP_URL/)).toBeInTheDocument();
    expect(screen.getByText(/https:\/\/maps\.example\.com/)).toBeInTheDocument();
    // The whole point: not swallowed by the generic toast.
    expect(vi.mocked(toast.error)).not.toHaveBeenCalled();
  });

  it('test_chip_remove_surfaces_unenforceable_domain_lock_inline: shrinking a lock still writes one, so it gets the same message', async () => {
    const user = userEvent.setup();
    const updateEmbedTokenFn = vi.fn().mockRejectedValue(domainLockRefusal());
    setup({
      enterprise: true,
      allowedOrigins: ['https://example.com', 'https://other.io'],
      updateEmbedTokenFn,
    });
    await openChipBlock(user);

    await user.click(
      screen.getByRole('button', { name: /remove https:\/\/example\.com/i }),
    );

    await waitFor(() => {
      expect(screen.getByText(/PUBLIC_APP_URL/)).toBeInTheDocument();
    });
    expect(vi.mocked(toast.error)).not.toHaveBeenCalled();
  });

  it('test_chip_PATCH_failure_rolls_back: non-422 PATCH failure rolls back chip and surfaces toast', async () => {
    const user = userEvent.setup();
    const updateEmbedTokenFn = vi.fn().mockRejectedValue(
      new ApiError('Internal Server Error', 500)
    );
    setup({ enterprise: true, allowedOrigins: [], updateEmbedTokenFn });
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

/* ------------------------------------------------------------------ */
/*  fix(#1831): the visibility PUT's 400 refusal (map holds non-public  */
/*  dataset layers) used to vanish — the toast key it referenced didn't */
/*  exist in any locale, and the dataset names were read off the        */
/*  already-translated `err.message` instead of the raw `err.body`.     */
/*  Now it renders as a persistent inline message under the visibility  */
/*  control, naming the datasets, and the toggle never leaves its       */
/*  previous value (the mutation only ever applies it on success).      */
/* ------------------------------------------------------------------ */
describe('#1831 publish blocked by non-public datasets', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function nonPublicDatasetsRefusal(datasets = 'Large Lakes') {
    const detail = {
      message: 'Cannot set visibility to public: map contains non-public datasets',
      datasets,
    };
    // Mirrors apiFetch: message is already localized, body carries the raw detail.
    return new ApiError(translateApiErrorDetail(detail, 400), 400, detail);
  }

  it('test_publish_refusal_shows_dataset_names_inline_and_keeps_toggle_private', async () => {
    const user = userEvent.setup();
    const publishMapFn = vi.fn().mockRejectedValue(nonPublicDatasetsRefusal('Large Lakes'));
    setup({ visibility: 'private', publishMapFn });

    await user.click(screen.getByRole('radio', { name: /anyone with the link/i }));
    await user.click(screen.getByRole('button', { name: /^make public$/i }));

    await waitFor(() => {
      expect(screen.getByTestId('share-publish-blocked-error')).toBeInTheDocument();
    });
    expect(screen.getByTestId('share-publish-blocked-error')).toHaveTextContent('Large Lakes');

    // The toggle stays on its previous value — the mutation never resolved,
    // so nothing "snaps back": it never moved in the first place.
    expect(screen.getByRole('radio', { name: /only you/i })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('radio', { name: /anyone with the link/i })).toHaveAttribute(
      'aria-checked',
      'false',
    );
  });

  it('test_publish_refusal_survives_the_confirm_dialog_closing_first', async () => {
    // The confirm AlertDialog closes as soon as "Make public" is clicked
    // (setPendingVisibility(null) runs before the mutation), so the message
    // has to persist somewhere that outlives it — not inside the dialog.
    const user = userEvent.setup();
    const publishMapFn = vi.fn().mockRejectedValue(nonPublicDatasetsRefusal('Large Lakes'));
    setup({ visibility: 'private', publishMapFn });

    await user.click(screen.getByRole('radio', { name: /anyone with the link/i }));
    await user.click(screen.getByRole('button', { name: /^make public$/i }));

    await waitFor(() => {
      expect(
        screen.queryByRole('alertdialog', { name: /make this map public/i }),
      ).not.toBeInTheDocument();
    });
    expect(screen.getByTestId('share-publish-blocked-error')).toBeInTheDocument();
  });

  it('test_publish_success_does_not_show_the_refusal_message', async () => {
    const user = userEvent.setup();
    const publishMapFn = vi.fn().mockResolvedValue({});
    setup({ visibility: 'private', publishMapFn });

    await user.click(screen.getByRole('radio', { name: /anyone with the link/i }));
    await user.click(screen.getByRole('button', { name: /^make public$/i }));

    await waitFor(() => expect(publishMapFn).toHaveBeenCalled());
    expect(screen.queryByTestId('share-publish-blocked-error')).not.toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ */
/*  SHARE-04: Expiration preset Select + Pitfall #6 regression pins    */
/* ------------------------------------------------------------------ */

// Radix Select requires pointer capture / scroll polyfills in JSDOM.
// Use plain function stubs (not vi.fn) so vi.clearAllMocks() in beforeEach
// does not clear their implementations between tests.
Element.prototype.hasPointerCapture = () => false;
Element.prototype.releasePointerCapture = () => undefined;
Element.prototype.scrollIntoView = () => undefined;

/**
 * Open the Link Settings disclosure and return the user-event instance.
 * Reusable helper for SHARE-04 tests (parallel to openChipBlock above).
 */
async function openLinkSettings(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /link settings/i }));
}

/**
 * Open the Radix Select for expiration by clicking the trigger button.
 * Uses fireEvent.click (Radix Select in JSDOM requires synchronous click dispatch).
 * Returns the trigger element.
 */
function openExpirationSelect() {
  const trigger = screen.getByRole('combobox');
  fireEvent.click(trigger);
  return trigger;
}

describe('SHARE-04 expiration presets', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('test_expiration_select_renders_six_options: Select exposes fixed presets and a custom date for Enterprise', async () => {
    const user = userEvent.setup();
    setup({ enterprise: true });

    await openLinkSettings(user);
    openExpirationSelect();

    // After opening the Select, options should be in the DOM
    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(6);
    const labels = options.map((o) => o.textContent);
    expect(labels).toContain('Never');
    expect(labels).toContain('1 day');
    expect(labels).toContain('7 days');
    expect(labels).toContain('30 days');
    expect(labels).toContain('90 days');
    expect(labels).toContain('Custom date…');
  });

  it('test_select_seven_days_preset_fires_updateShareToken: selecting "7 days" sends the server-calculated preset', async () => {
    const user = userEvent.setup();
    const { updateShareTokenFn } = setup({ enterprise: true });

    await openLinkSettings(user);
    openExpirationSelect();
    fireEvent.click(screen.getByRole('option', { name: '7 days' }));

    await waitFor(() => {
      expect(updateShareTokenFn).toHaveBeenCalledOnce();
    });
    expect(updateShareTokenFn).toHaveBeenCalledWith({
      mapId: 'map-1',
      expiresInDays: 7,
    });
  });

  it('test_select_never_preset_clears_expiration: selecting "Never" fires mutateAsync with expiresAt: null', async () => {
    const user = userEvent.setup();
    // Set shareExpires so the Select opens at "30 days" — then switching to "Never" fires onChange
    const thirtyDaysFromNow = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000)
      .toISOString()
      .split('T')[0] + 'T23:59:59.000Z';
    const { updateShareTokenFn } = setup({ enterprise: true, shareExpires: thirtyDaysFromNow });

    await openLinkSettings(user);
    openExpirationSelect();
    // Select starts at "30 days" → clicking "Never" changes value → fires onValueChange
    fireEvent.click(screen.getByRole('option', { name: 'Never' }));

    await waitFor(() => {
      expect(updateShareTokenFn).toHaveBeenCalledOnce();
      expect(updateShareTokenFn).toHaveBeenCalledWith({
        mapId: 'map-1',
        expiresAt: null,
      });
    });
  });

  it('test_select_custom_reveals_date_input: selecting "Custom date…" reveals date Input and Save button without firing mutateAsync', async () => {
    const user = userEvent.setup();
    const { updateShareTokenFn } = setup({ enterprise: true });

    await openLinkSettings(user);
    openExpirationSelect();
    fireEvent.click(screen.getByRole('option', { name: 'Custom date…' }));

    // Date input (type="date") should be visible
    const allInputs = document.querySelectorAll<HTMLInputElement>('input[type="date"]');
    expect(allInputs.length).toBeGreaterThan(0);
    const dateInput = allInputs[0];
    expect(dateInput).toBeInTheDocument();
    // Save button should be visible for custom path
    expect(screen.getByRole('button', { name: /^save$/i })).toBeInTheDocument();
    // updateShareToken should NOT have been called yet
    expect(updateShareTokenFn).not.toHaveBeenCalled();
  });

  it('test_select_pre_populates_to_custom_when_shareExpires_off_preset: shareExpires at T12:00 (off-preset) → Select shows "Custom date…" and date input shows the date', async () => {
    const user = userEvent.setup();
    // shareExpires off every preset (7/30/90d ±1 day) AND at T12:00 (presets use
    // T23:59:59). Computed relative to now (not hardcoded) so it can't drift into a
    // preset window as the calendar advances — a previously hardcoded 2026-06-15
    // started failing once "now" reached 2026-06-07 and the 7-day preset landed
    // within the ±1-day tolerance of it. 45 days is safely between the 30d and 90d
    // presets.
    const offPresetDate = new Date(Date.now() + 45 * 24 * 60 * 60 * 1000)
      .toISOString()
      .split('T')[0];
    setup({ enterprise: true, shareExpires: `${offPresetDate}T12:00:00.000Z` });

    await openLinkSettings(user);

    // The Select trigger should show "Custom date…"
    const trigger = screen.getByRole('combobox');
    expect(trigger).toHaveTextContent(/custom date/i);

    // The date input should be pre-populated with the date portion
    const dateInputs = document.querySelectorAll<HTMLInputElement>('input[type="date"]');
    expect(dateInputs.length).toBeGreaterThan(0);
    expect(dateInputs[0]).toHaveValue(offPresetDate);
  });

  it('test_select_pre_populates_to_seven_days_when_within_preset_window: shareExpires = (now + 7d at T23:59:59Z) → Select shows "7 days"', async () => {
    const user = userEvent.setup();
    // Compute real 7-day preset ISO: now + 7 days at T23:59:59Z
    // detectPreset uses ±1 day tolerance, so this should hit the '7d' bucket
    const sevenDaysIso = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000)
      .toISOString()
      .split('T')[0] + 'T23:59:59.000Z';
    setup({ enterprise: true, shareExpires: sevenDaysIso });

    await openLinkSettings(user);

    // The Select trigger should show "7 days" (detected from shareExpires)
    const trigger = screen.getByRole('combobox');
    expect(trigger).toHaveTextContent('7 days');
  });

  /**
   * Pitfall #6 regression pin (rawShareToken survival).
   *
   * Contract: selecting a preset fires updateShareToken but does NOT touch
   * rawShareToken or embedTokenRaw state. The "Copy Link" button is gated on
   * rawShareToken being non-null — if it survives, the button stays visible.
   */
  it('test_rawShareToken_survives_preset_selection (Pitfall #6 LOAD-BEARING): rawShareToken state unchanged after preset select', async () => {
    const user = userEvent.setup();
    // hasShareToken:false so we generate a fresh raw token via the button click
    setup({ enterprise: true, hasShareToken: false });

    // Generate a share link — this sets rawShareToken='share-token' in state
    await user.click(screen.getByRole('button', { name: /generate share link/i }));

    // Wait until Copy Link is visible (proxy for rawShareToken being non-null)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /copy link/i })).toBeInTheDocument();
    });

    // Now open Link Settings and apply a preset
    await openLinkSettings(user);
    openExpirationSelect();
    fireEvent.click(screen.getByRole('option', { name: '7 days' }));

    // rawShareToken must still be non-null — Copy Link stays visible
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /copy link/i })).toBeInTheDocument();
    });
  });

  /**
   * Pitfall #6 mirror (embedTokenRaw survival).
   *
   * Both rawShareToken and embedTokenRaw are independent of expiration mutations.
   * The embed code textarea is gated on embedTokenRaw being non-null.
   */
  it('test_embedTokenRaw_survives_preset_selection (Pitfall #6 mirror): embedTokenRaw state unchanged after preset select', async () => {
    const user = userEvent.setup();
    // hasNonPublic:true so embedTokenRaw is created during link generation
    setup({ enterprise: true, hasShareToken: false, hasNonPublic: true });

    // Generate a share link — this creates both rawShareToken and embedTokenRaw
    await user.click(screen.getByRole('button', { name: /generate share link/i }));

    // Wait for the embed code textarea to appear (proxy for embedTokenRaw non-null)
    await waitFor(() => {
      const textarea = screen.queryByRole('textbox');
      expect(textarea).toBeInTheDocument();
      expect((textarea as HTMLTextAreaElement).value).toContain('et=raw-token');
    });

    // Open Link Settings and select "30 days" preset
    await openLinkSettings(user);
    openExpirationSelect();
    fireEvent.click(screen.getByRole('option', { name: '30 days' }));

    // embedTokenRaw must still be non-null — embed textarea still shows et=raw-token
    await waitFor(() => {
      const textarea = screen.queryByRole('textbox');
      expect(textarea).toBeInTheDocument();
      expect((textarea as HTMLTextAreaElement).value).toContain('et=raw-token');
    });
  });
});

/* ------------------------------------------------------------------ */
/*  SHARE-03: embed-preview iframe pane                               */
/* ------------------------------------------------------------------ */

/**
 * Helper: click "Generate Share Link" and wait until rawShareToken is set
 * (the "Copy Link" button appearing is the proxy).
 */
async function generateShareLinkAndWait(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /generate share link/i }));
  await waitFor(() => {
    expect(screen.getByRole('button', { name: /copy link/i })).toBeInTheDocument();
  });
}

describe('SHARE-03 embed-preview iframe', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('test_preview_pane_collapsed_by_default: Preview toggle visible but iframe NOT in DOM after generating link', async () => {
    const user = userEvent.setup();
    // hasNonPublic:true so embedTokenRaw is created (preview pane requires embedTokenRaw)
    setup({ enterprise: false, hasShareToken: false, hasNonPublic: true });

    await generateShareLinkAndWait(user);

    // Preview disclosure toggle should be visible
    expect(screen.getByRole('button', { name: /preview/i })).toBeInTheDocument();
    // iframe NOT yet in DOM (collapsed by default)
    expect(screen.queryByTestId('share-preview-iframe')).not.toBeInTheDocument();
  });

  it('test_preview_pane_expands_on_click: clicking Preview disclosure reveals the iframe element', async () => {
    const user = userEvent.setup();
    // hasNonPublic:true so embedTokenRaw is set (required for preview pane)
    setup({ enterprise: false, hasShareToken: false, hasNonPublic: true });

    await generateShareLinkAndWait(user);

    const previewToggle = screen.getByRole('button', { name: /preview/i });
    await user.click(previewToggle);

    // iframe appears with data-testid
    await waitFor(() => {
      expect(screen.getByTestId('share-preview-iframe')).toBeInTheDocument();
    });
  });

  // fix(#1515): the preview and the copied snippet must carry the SAME sandbox.
  // While they differed the preview was a preview of a different page, and it
  // showed "Map not found" for a token that was perfectly valid.
  it('test_iframe_sandbox_matches_the_emitted_snippet: preview sandbox === generateEmbedCode sandbox', async () => {
    const user = userEvent.setup();
    setup({ enterprise: false, hasShareToken: false, hasNonPublic: true });

    await generateShareLinkAndWait(user);
    await user.click(screen.getByRole('button', { name: /preview/i }));

    const iframe = await screen.findByTestId('share-preview-iframe');
    expect(iframe.getAttribute('sandbox')).toBe('allow-scripts allow-same-origin');

    const snippet = generateEmbedCode({
      shareToken: 'share-token',
      embedTokenRaw: 'raw-token',
      origin: 'https://geolens.example.com',
    });
    expect(snippet).toContain(`sandbox="${iframe.getAttribute('sandbox')}"`);
  });

  it('test_iframe_title_attribute_set: iframe has title="Map embed preview" (a11y)', async () => {
    const user = userEvent.setup();
    setup({ enterprise: false, hasShareToken: false, hasNonPublic: true });

    await generateShareLinkAndWait(user);
    await user.click(screen.getByRole('button', { name: /preview/i }));

    const iframe = await screen.findByTestId('share-preview-iframe');
    expect(iframe.getAttribute('title')).toBe('Map embed preview');
  });

  it('test_iframe_src_matches_embed_url_shape: src contains embed=true&et=<token>', async () => {
    const user = userEvent.setup();
    setup({ enterprise: false, hasShareToken: false, hasNonPublic: true });

    await generateShareLinkAndWait(user);
    await user.click(screen.getByRole('button', { name: /preview/i }));

    const iframe = await screen.findByTestId('share-preview-iframe') as HTMLIFrameElement;
    expect(iframe.src).toContain('embed=true');
    expect(iframe.src).toContain('et=raw-token');
    expect(iframe.src).toContain('/m/share-token');
  });

  it('test_security_indicator_footer_present: security indicator shows sandbox note below iframe container', async () => {
    const user = userEvent.setup();
    setup({ enterprise: false, hasShareToken: false, hasNonPublic: true });

    await generateShareLinkAndWait(user);
    await user.click(screen.getByRole('button', { name: /preview/i }));

    await waitFor(() => {
      expect(screen.getByTestId('share-preview-iframe')).toBeInTheDocument();
    });

    // Security indicator footer: contains sandbox note text
    expect(
      screen.getByText(/same restricted sandbox as the snippet you copy/i),
    ).toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ */
/*  Pitfall #7: inflightEmbedCreate race guard                        */
/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ */
/*  SHARE-08: Copy Link emits /card URL; embed + Open unchanged        */
/* ------------------------------------------------------------------ */

describe('SHARE-08 Copy Link emits /card URL', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('Copy Link button writes the /card URL to the clipboard (not the /m/ viewer URL)', async () => {
    const user = userEvent.setup();
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: writeTextMock },
      writable: true,
      configurable: true,
    });

    // Generate a share token so rawShareToken = 'share-token'
    setup({ enterprise: false, hasShareToken: false });
    await generateShareLinkAndWait(user);

    await user.click(screen.getByRole('button', { name: /copy link/i }));

    await waitFor(() => {
      expect(writeTextMock).toHaveBeenCalledOnce();
    });
    const [copiedUrl] = writeTextMock.mock.calls[0] as [string];
    // Must match the /card URL shape
    expect(copiedUrl).toMatch(/\/api\/maps\/shared\/[^/]+\/card/);
    // Must NOT be the /m/ viewer URL
    expect(copiedUrl).not.toMatch(/\/m\//);
  });

  it('embed code textarea still contains /m/ and embed=true (embed iframe src unchanged)', async () => {
    const user = userEvent.setup();
    setup({ enterprise: false, hasShareToken: false, hasNonPublic: true });
    await generateShareLinkAndWait(user);

    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    expect(textarea.value).toContain('/m/share-token');
    expect(textarea.value).toContain('embed=true');
  });
});

/* ------------------------------------------------------------------ */
/*  SHARE-10: 2-weight typography system (font-semibold + font-medium) */
/* ------------------------------------------------------------------ */

describe('SHARE-10 font-weight hierarchy', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('rendered ShareDialog contains font-semibold (section headers) and no font-bold (no third weight)', async () => {
    const user = userEvent.setup();
    // hasShareToken: false so we generate a token, mounting the Share Link + Embed sections
    setup({ enterprise: false, hasShareToken: false, hasNonPublic: true });
    await generateShareLinkAndWait(user);

    // Get the rendered dialog container
    const dialog = document.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();

    // At least one font-semibold element must exist (section headers)
    const semiboldEls = dialog!.querySelectorAll('.font-semibold');
    expect(semiboldEls.length).toBeGreaterThan(0);

    // No font-bold — two-weight system enforced
    const boldEls = dialog!.querySelectorAll('.font-bold');
    expect(boldEls.length).toBe(0);
  });
});

describe('Pitfall #7 inflightEmbedCreate race guard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('test_pitfall_7_inflightEmbedCreate_dedupes_concurrent_calls: two concurrent Generate clicks fire createEmbedToken exactly once', async () => {
    const user = userEvent.setup();

    // Slow-resolving createEmbedToken so the race window is real (50ms).
    // Both clicks arrive while the first promise is still in-flight.
    const slowCreateEmbedToken = vi.fn().mockImplementation(
      () => new Promise<{ id: string; raw_token: string; token_hint: string; expires_at: string; is_active: boolean }>(
        (resolve) => setTimeout(() => resolve({
          id: 'embed-2',
          raw_token: 'raw-token',
          token_hint: 'raw...',
          expires_at: '2026-06-01T00:00:00Z',
          is_active: true,
        }), 50)
      )
    );

    setup({
      enterprise: false,
      hasShareToken: false,
      hasNonPublic: true,
      createEmbedTokenFn: slowCreateEmbedToken,
    });

    const generateBtn = screen.getByRole('button', { name: /generate share link/i });

    // Fire two clicks concurrently — the second arrives while the first is still in-flight.
    // Promise.all ensures both clicks are initiated before either resolves.
    await Promise.all([
      user.click(generateBtn),
      user.click(generateBtn),
    ]);

    // Wait for the token to fully resolve
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /copy link/i })).toBeInTheDocument();
    });

    // KEY ASSERTION: exactly ONE backend POST should have fired despite 2 clicks
    expect(slowCreateEmbedToken).toHaveBeenCalledTimes(1);
  });
});

describe('P2-01 explicit create-embed-token for public-only embeds', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('offers a Create embed token button on a fully-public map with no embed token, and creates one', async () => {
    const user = userEvent.setup();
    const createEmbedToken = vi.fn().mockResolvedValue({
      id: 'embed-new',
      raw_token: 'raw-token',
      token_hint: 'raw...',
      expires_at: FUTURE_EMBED_EXPIRES_AT,
      is_active: true,
    });

    mockedUseEdition.mockReturnValue({
      edition: 'enterprise',
      features: ['advanced-sharing'],
      isEnterprise: true,
      isMultiTenant: false,
      isLoading: false,
      isResolved: true,
    });
    mockedUsePublishMap.mockReturnValue(mutationResult());
    mockedUseCreateShareToken.mockReturnValue(mutationResult(
      vi.fn().mockResolvedValue({ token: 'share-token', share_url: '/m/share-token', expires_at: null, is_active: true }),
    ));
    mockedUseRevokeShareToken.mockReturnValue(mutationResult());
    mockedUseUpdateShareToken.mockReturnValue(mutationResult());
    mockedUseCreateEmbedToken.mockReturnValue(mutationResult(createEmbedToken));
    mockedUseUpdateEmbedToken.mockReturnValue(mutationResult());
    mockedUseRevokeEmbedToken.mockReturnValue(mutationResult());
    // Share token exists (so rawShareToken hint present), but there are NO embed tokens.
    mockedUseMapShareToken.mockReturnValue({
      data: { token: 'share-token', share_url: 'http://test/m/share-token', expires_at: null, is_active: true },
      isLoading: false,
      isError: false,
    } as never);
    mockedUseMapEmbedTokens.mockReturnValue({
      data: { tokens: [], total: 0 },
      isLoading: false,
      isError: false,
    } as never);
    mockedCheckMapVisibility.mockResolvedValue({ has_non_public: false, non_public_datasets: [] });

    render(
      <ShareDialog mapId="map-1" visibility="public" open onOpenChange={vi.fn()} />,
    );

    // Regenerate the link to obtain a raw share token so the embed section renders.
    await user.click(await screen.findByRole('button', { name: /regenerate link/i }));

    const createBtn = await screen.findByRole('button', { name: /create embed token/i });
    await user.click(createBtn);

    await waitFor(() => {
      expect(createEmbedToken).toHaveBeenCalledWith({ mapId: 'map-1' });
    });
  });
});

/* ------------------------------------------------------------------ */
/*  fix(#778): confirm visibility changes that cross the public        */
/*  boundary before mutating                                           */
/* ------------------------------------------------------------------ */

describe('fix(#778) public-boundary visibility confirmation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const privateLayer = {
    id: 'layer-1',
    dataset_id: 'ds-1',
    dataset_name: 'Secret parcels',
    display_name: null,
    dataset_visibility: 'private',
    dataset_status: 'published',
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;

  it('private→public opens the confirm dialog and only mutates on confirm', async () => {
    const user = userEvent.setup();
    const { publishMapFn } = setup({
      visibility: 'private',
      hasShareToken: false,
      layers: [privateLayer],
    });

    await user.click(screen.getByRole('radio', { name: /anyone with the link/i }));

    // Dialog is open, nothing has mutated yet.
    const dialog = await screen.findByRole('alertdialog');
    expect(publishMapFn).not.toHaveBeenCalled();
    // The audience-hidden layer list is surfaced inside the dialog body,
    // computed against the TARGET (public) visibility.
    expect(screen.getByTestId('share-confirm-audience-hidden-warning')).toHaveTextContent(
      'Secret parcels',
    );
    expect(dialog).toHaveTextContent(/make this map public\?/i);

    await user.click(screen.getByRole('button', { name: /^make public$/i }));

    await waitFor(() => {
      expect(publishMapFn).toHaveBeenCalledOnce();
    });
    expect(publishMapFn).toHaveBeenCalledWith({ id: 'map-1', visibility: 'public' });
  });

  it('cancelling the private→public confirm fires no mutation and keeps the old selection', async () => {
    const user = userEvent.setup();
    const { publishMapFn } = setup({ visibility: 'private', hasShareToken: false });

    await user.click(screen.getByRole('radio', { name: /anyone with the link/i }));
    await screen.findByRole('alertdialog');

    await user.click(screen.getByRole('button', { name: /^cancel$/i }));

    await waitFor(() => {
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    });
    expect(publishMapFn).not.toHaveBeenCalled();
    // Checked state never flipped — the map is still private.
    expect(screen.getByRole('radio', { name: /only you/i })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    expect(screen.getByRole('radio', { name: /anyone with the link/i })).toHaveAttribute(
      'aria-checked',
      'false',
    );
  });

  it('leaving public warns that existing share links stop working, with a destructive confirm', async () => {
    const user = userEvent.setup();
    const { publishMapFn } = setup({ visibility: 'public' });

    await user.click(screen.getByRole('radio', { name: /only you/i }));

    const dialog = await screen.findByRole('alertdialog');
    expect(publishMapFn).not.toHaveBeenCalled();
    expect(dialog).toHaveTextContent(/share links and embed codes will stop working/i);

    await user.click(screen.getByRole('button', { name: /stop public sharing/i }));

    await waitFor(() => {
      expect(publishMapFn).toHaveBeenCalledOnce();
    });
    expect(publishMapFn).toHaveBeenCalledWith({ id: 'map-1', visibility: 'private' });
  });

  it('a non-boundary change (private→internal) mutates immediately without a dialog', async () => {
    const user = userEvent.setup();
    const { publishMapFn } = setup({ visibility: 'private', hasShareToken: false });

    await user.click(screen.getByRole('radio', { name: /all team members/i }));

    await waitFor(() => {
      expect(publishMapFn).toHaveBeenCalledOnce();
    });
    expect(publishMapFn).toHaveBeenCalledWith({ id: 'map-1', visibility: 'internal' });
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  // feat(#1691): the restrict_public_visibility instance setting caps
  // non-admins at non-public. The server enforces it with a 403; the panel
  // disables the choice and swaps its description for the admin-only note.
  it('disables the Public choice when the instance restricts public to admins', () => {
    setup({ visibility: 'private', hasShareToken: false, canSetPublic: false });

    const publicRadio = screen.getByRole('radio', {
      name: /only administrators can make content public/i,
    });
    expect(publicRadio).toBeDisabled();
    // The other choices stay usable.
    expect(screen.getByRole('radio', { name: /only you/i })).toBeEnabled();
    expect(screen.getByRole('radio', { name: /all team members/i })).toBeEnabled();
  });
});

/* ------------------------------------------------------------------ */
/*  #1548 review r3: shareable URLs come from PUBLIC_APP_URL           */
/* ------------------------------------------------------------------ */

/**
 * A snippet is copied so a CUSTOMER can paste it on THEIR site, and a share
 * link is pasted into Slack. Building either from `window.location.origin`
 * means an operator who administers GeoLens over an internal hostname hands out
 * a URL that will not resolve for anyone else — a bug that exists with or
 * without domain locking.
 *
 * It also silently breaks a domain-locked embed: the shell's own API calls
 * carry the shell's origin, and the backend recognizes only the CONFIGURED
 * origin as first-party, so a snippet built from a different-but-real hostname
 * loads and then returns no layers.
 *
 * `PUBLIC_APP_URL` here is deliberately NOT the current origin, so a builder
 * that ignored it would fail every assertion below.
 */
describe('#1548 r3 shareable URLs use the configured public origin', () => {
  const CONFIGURED = 'https://maps.example.com';

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('builds the embed snippet from PUBLIC_APP_URL, not the admin hostname', async () => {
    const user = userEvent.setup();
    setup({ hasShareToken: false, hasNonPublic: true, publicAppUrl: CONFIGURED });
    await generateShareLinkAndWait(user);

    const textarea = (await screen.findByRole('textbox')) as HTMLTextAreaElement;
    expect(textarea.value).toContain(`src="${CONFIGURED}/m/share-token`);
    expect(textarea.value).not.toContain(window.location.origin);
  });

  /**
   * fix(#1548 review r5): the snippet and the preview deliberately DIVERGE on
   * origin, and asserting them together is the clearest statement of the rule.
   * Same map, same token, same moment — the snippet names the host the customer
   * will open, the preview names the host this browser just reached.
   */
  it('splits the snippet and the preview by who opens each', async () => {
    const user = userEvent.setup();
    setup({ hasShareToken: false, hasNonPublic: true, publicAppUrl: CONFIGURED });
    await generateShareLinkAndWait(user);

    const textarea = (await screen.findByRole('textbox')) as HTMLTextAreaElement;
    expect(textarea.value).toContain(`src="${CONFIGURED}/m/share-token`);

    await user.click(screen.getByRole('button', { name: /preview/i }));
    const iframe = (await screen.findByTestId(
      'share-preview-iframe',
    )) as HTMLIFrameElement;
    expect(iframe.src).toContain(`${window.location.origin}/m/share-token`);
    expect(iframe.src).not.toContain(CONFIGURED);
  });

  it('copies a share link on the configured origin', async () => {
    // userEvent.setup() installs its own clipboard stub, so the spy has to be
    // planted AFTER it — the existing SHARE-08 test does the same.
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      writable: true,
      configurable: true,
    });
    setup({ hasShareToken: false, publicAppUrl: CONFIGURED });
    await generateShareLinkAndWait(user);

    await user.click(screen.getByRole('button', { name: /copy link/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    expect(writeText.mock.calls[0][0]).toBe(
      `${CONFIGURED}/api/maps/shared/share-token/card`,
    );
  });

  /**
   * fix(#1548 review r4): the regression guard.
   *
   * Both compose files inject `${PUBLIC_APP_URL:-http://localhost:8080}`, so
   * the DEFAULT install reports a non-null, perfectly good-looking localhost
   * value. Trusting it hands every such deployment a share link and an embed
   * snippet pointing at localhost — which nobody but the admin can open, and
   * which worked fine before any of this. `publicAppUrl` here is deliberately
   * the shipped default while the browser is elsewhere.
   */
  describe('the shipped localhost default is treated as unconfigured', () => {
    const COMPOSE_DEFAULT = 'http://localhost:8080';
    // jsdom serves these tests from http://localhost:3000, which is itself
    // loopback — and a localhost PUBLIC_APP_URL is CORRECT for a localhost
    // install, so the trust check rightly accepts it there. Pretend the browser
    // reached GeoLens at a real hostname, which is the deployment this is about.
    const SERVED_AT = 'https://maps.example.com';

    // `origin` is non-configurable on jsdom's Location, so the whole object is
    // swapped rather than the one property.
    const realLocation = window.location;

    beforeEach(() => {
      Object.defineProperty(window, 'location', {
        value: { ...realLocation, origin: SERVED_AT },
        writable: true,
        configurable: true,
      });
    });

    afterEach(() => {
      Object.defineProperty(window, 'location', {
        value: realLocation,
        writable: true,
        configurable: true,
      });
    });

    it('copies a share link on the serving origin, not localhost', async () => {
      const user = userEvent.setup();
      const writeText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText },
        writable: true,
        configurable: true,
      });
      setup({ hasShareToken: false, publicAppUrl: COMPOSE_DEFAULT });
      await generateShareLinkAndWait(user);

      await user.click(screen.getByRole('button', { name: /copy link/i }));
      await waitFor(() => expect(writeText).toHaveBeenCalled());
      expect(writeText.mock.calls[0][0]).toBe(
        `${SERVED_AT}/api/maps/shared/share-token/card`,
      );
      expect(writeText.mock.calls[0][0]).not.toContain(COMPOSE_DEFAULT);
    });

    it('still emits an unrestricted embed snippet, on the serving origin', async () => {
      const user = userEvent.setup();
      setup({
        hasShareToken: false,
        hasNonPublic: true,
        allowedOrigins: [],
        publicAppUrl: COMPOSE_DEFAULT,
      });
      await generateShareLinkAndWait(user);

      const textarea = (await screen.findByRole('textbox')) as HTMLTextAreaElement;
      expect(textarea.value).toContain(`src="${SERVED_AT}/m/share-token`);
      expect(textarea.value).not.toContain(COMPOSE_DEFAULT);
    });

    it('withholds a DOMAIN-LOCKED snippet, because that one cannot degrade', async () => {
      // An unrestricted embed served from a non-canonical origin still draws.
      // A locked one does not: its own API calls would carry an origin the
      // backend will not accept, and the map comes up empty saying nothing.
      const user = userEvent.setup();
      setup({
        enterprise: true,
        hasShareToken: false,
        hasNonPublic: true,
        forceActiveEmbedToken: true,
        allowedOrigins: ['https://customer.example.com'],
        publicAppUrl: COMPOSE_DEFAULT,
      });
      await generateShareLinkAndWait(user);

      expect(await screen.findByText(/PUBLIC_APP_URL/)).toBeInTheDocument();
    });
  });

  /**
   * fix(#1548 review r6): you genuinely cannot preview a domain-locked embed
   * from a host the lock does not permit — that is the feature working. Saying
   * so beats rendering a map with no layers in it and letting the operator
   * conclude the embed is broken.
   */
  describe('suppresses the locked preview with no trustworthy public origin', () => {
    // The shipped-default row needs the browser somewhere other than loopback:
    // on a genuine localhost install a localhost PUBLIC_APP_URL is correct.
    const realLocation = window.location;
    beforeEach(() => {
      Object.defineProperty(window, 'location', {
        value: { ...realLocation, origin: 'https://maps.example.com' },
        writable: true,
        configurable: true,
      });
    });
    afterEach(() => {
      Object.defineProperty(window, 'location', {
        value: realLocation,
        writable: true,
        configurable: true,
      });
    });

    it.each([
      ['nothing is configured', null],
      ['the config is the shipped localhost default', 'http://localhost:8080'],
      ['the config is malformed', 'not-a-url'],
    ])('when %s', async (_label, publicAppUrl) => {
      const user = userEvent.setup();
      setup({
        enterprise: true,
        hasShareToken: false,
        hasNonPublic: true,
        lockOriginsAfterCreate: ['https://customer.example.com'],
        publicAppUrl,
      });
      await generateShareLinkAndWait(user);

      expect(
        screen.queryByRole('button', { name: /preview/i }),
      ).not.toBeInTheDocument();
      expect(screen.queryByTestId('share-preview-iframe')).not.toBeInTheDocument();
      // The preview explains itself in its own words — the snippet above it is
      // withheld too and also names PUBLIC_APP_URL, so match the preview copy.
      expect(await screen.findByText(/only be previewed from/i)).toBeInTheDocument();
      expect(screen.getAllByText(/PUBLIC_APP_URL/).length).toBeGreaterThan(0);
    });
  });

  it('keeps previewing an UNLOCKED embed on the shipped localhost default', async () => {
    // The regression guard for the case above: suppression is about the LOCK,
    // not about the configuration alone. An unrestricted preview still loads.
    const user = userEvent.setup();
    setup({
      hasShareToken: false,
      hasNonPublic: true,
      allowedOrigins: [],
      publicAppUrl: 'http://localhost:8080',
    });
    await generateShareLinkAndWait(user);
    await user.click(screen.getByRole('button', { name: /preview/i }));

    const iframe = (await screen.findByTestId(
      'share-preview-iframe',
    )) as HTMLIFrameElement;
    expect(iframe.src).toContain(`${window.location.origin}/m/share-token`);
  });

  it('withholds a domain-locked snippet when nothing is configured', async () => {
    const user = userEvent.setup();
    setup({
      enterprise: true,
      hasShareToken: false,
      hasNonPublic: true,
      forceActiveEmbedToken: true,
      allowedOrigins: ['https://customer.example.com'],
      publicAppUrl: null,
    });
    await generateShareLinkAndWait(user);

    expect(await screen.findByText(/PUBLIC_APP_URL/)).toBeInTheDocument();
  });

  it('keeps the local Open affordance working without a configured URL', async () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    const user = userEvent.setup();
    setup({ hasShareToken: false, hasNonPublic: true, publicAppUrl: null });
    await generateShareLinkAndWait(user);

    await user.click(screen.getByRole('button', { name: /^open$/i }));
    expect(openSpy).toHaveBeenCalledWith(
      `${window.location.origin}/m/share-token`,
      '_blank',
    );
    openSpy.mockRestore();
  });

  /**
   * fix(#1548 review r5): the split-horizon deployment.
   *
   * A public hostname routed externally and unreachable from the internal admin
   * network is a normal setup, not a misconfiguration. The copied link must
   * still name the public host — the customer is not on this network — but
   * anything THIS browser opens has to name the host this browser reached, or
   * an admin can use GeoLens normally and yet cannot open the share they just
   * created.
   */
  describe('split-horizon: the public host is not reachable from here', () => {
    const PUBLIC_HOST = 'https://maps.example.com';

    it('opens the viewer on the current origin, not the public one', async () => {
      const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
      const user = userEvent.setup();
      setup({ hasShareToken: false, hasNonPublic: true, publicAppUrl: PUBLIC_HOST });
      await generateShareLinkAndWait(user);

      await user.click(screen.getByRole('button', { name: /^open$/i }));
      expect(openSpy).toHaveBeenCalledWith(
        `${window.location.origin}/m/share-token`,
        '_blank',
      );
      expect(openSpy.mock.calls[0][0]).not.toContain(PUBLIC_HOST);
      openSpy.mockRestore();
    });

    it('previews from the current origin, not the public one', async () => {
      const user = userEvent.setup();
      setup({ hasShareToken: false, hasNonPublic: true, publicAppUrl: PUBLIC_HOST });
      await generateShareLinkAndWait(user);
      await user.click(screen.getByRole('button', { name: /preview/i }));

      const iframe = (await screen.findByTestId(
        'share-preview-iframe',
      )) as HTMLIFrameElement;
      // An iframe pointed at a host this browser cannot resolve renders
      // nothing, which is strictly worse than previewing from the serving host.
      expect(iframe.src).toContain(`${window.location.origin}/m/share-token`);
      expect(iframe.src).not.toContain(PUBLIC_HOST);
    });

    /**
     * fix(#1548 review r7): a domain-locked preview has no answer here at all.
     * Its API calls must carry the configured origin, and `frame-ancestors`
     * then judges THIS dialog as the parent against that same origin — which
     * the admin's hostname is not. The browser blocks the frame before a single
     * API call runs, so the honest move is not to render it.
     */
    it('suppresses a DOMAIN-LOCKED preview rather than loading a blocked frame', async () => {
      const user = userEvent.setup();
      setup({
        enterprise: true,
        hasShareToken: false,
        hasNonPublic: true,
        lockOriginsAfterCreate: ['https://customer.example.com'],
        publicAppUrl: PUBLIC_HOST,
      });
      await generateShareLinkAndWait(user);

      expect(
        screen.queryByRole('button', { name: /preview/i }),
      ).not.toBeInTheDocument();
      expect(screen.queryByTestId('share-preview-iframe')).not.toBeInTheDocument();
      expect(
        await screen.findByText(/restricted to specific domains/i),
      ).toBeInTheDocument();
    });

    it('leaves the copy-snippet path fully working while the preview is refused', async () => {
      // What the admin actually came here to do. The snippet still names the
      // public host, which is where the customer will load it from.
      const user = userEvent.setup();
      const writeText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText },
        writable: true,
        configurable: true,
      });
      setup({
        enterprise: true,
        hasShareToken: false,
        hasNonPublic: true,
        lockOriginsAfterCreate: ['https://customer.example.com'],
        publicAppUrl: PUBLIC_HOST,
      });
      await generateShareLinkAndWait(user);

      const textarea = (await screen.findByRole('textbox')) as HTMLTextAreaElement;
      expect(textarea.value).toContain(`src="${PUBLIC_HOST}/m/share-token`);

      await user.click(screen.getByTitle(/copy embed code/i));
      await waitFor(() => expect(writeText).toHaveBeenCalled());
      expect(writeText.mock.calls[0][0]).toContain(PUBLIC_HOST);
    });

    it('previews the locked embed once the admin IS on the configured origin', async () => {
      // The regression guard: suppression is about the two origins DIFFERING,
      // not about the embed being locked. Same host, and the preview returns.
      const user = userEvent.setup();
      setup({
        enterprise: true,
        hasShareToken: false,
        hasNonPublic: true,
        lockOriginsAfterCreate: ['https://customer.example.com'],
        publicAppUrl: window.location.origin,
      });
      await generateShareLinkAndWait(user);
      await user.click(screen.getByRole('button', { name: /preview/i }));

      const iframe = (await screen.findByTestId(
        'share-preview-iframe',
      )) as HTMLIFrameElement;
      expect(iframe.src).toContain(`${window.location.origin}/m/share-token`);
    });

    it('still copies a link on the public host, because the customer opens that', async () => {
      const user = userEvent.setup();
      const writeText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText },
        writable: true,
        configurable: true,
      });
      setup({ hasShareToken: false, publicAppUrl: PUBLIC_HOST });
      await generateShareLinkAndWait(user);

      await user.click(screen.getByRole('button', { name: /copy link/i }));
      await waitFor(() => expect(writeText).toHaveBeenCalled());
      expect(writeText.mock.calls[0][0]).toBe(
        `${PUBLIC_HOST}/api/maps/shared/share-token/card`,
      );
    });
  });
});
