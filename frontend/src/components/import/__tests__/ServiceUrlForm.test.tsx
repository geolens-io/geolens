/**
 * fix(#1746): ServiceUrlForm regression tests.
 *
 * Two findings pinned here:
 * - Finding 4: the service-token field is a request-only credential, not a
 *   login password, so it must opt every password manager out explicitly
 *   (autoComplete="off" alone does not stop Chrome from offering to save it).
 * - Finding 8: the layer picker must be keyed by layer_id, not layer.name —
 *   two ArcGIS sublayers can share a display name (e.g. two sublayers both
 *   titled REC_PassiveConservedAccessScore), and a name-keyed list would
 *   collapse or misroute the duplicates.
 */
import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { ServiceUrlForm } from '../ServiceUrlForm';
import type { ProbeResponse } from '@/types/api';
import { ApiError } from '@/api/client';

const mockProbeService = vi.fn();
const mockPreviewServiceLayer = vi.fn();
const mockCommitImport = vi.fn();
const mockArcgisSignin = vi.fn();

vi.mock('@/api/ingest', () => ({
  probeService: (...args: unknown[]) => mockProbeService(...args),
  previewServiceLayer: (...args: unknown[]) => mockPreviewServiceLayer(...args),
  commitImport: (...args: unknown[]) => mockCommitImport(...args),
  arcgisSignin: (...args: unknown[]) => mockArcgisSignin(...args),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? key,
  }),
}));

vi.mock('../ImportPreview', () => ({
  ImportPreview: () => <div data-testid="import-preview" />,
}));

vi.mock('../ImportMetadataForm', () => ({
  ImportMetadataForm: () => <div data-testid="import-metadata-form" />,
}));

vi.mock('../JobProgress', () => ({
  JobProgress: () => <div data-testid="job-progress" />,
}));

beforeEach(() => {
  vi.clearAllMocks();
});

// Radix Select needs these in jsdom.
beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
});

const DUPLICATE_NAME_PROBE: ProbeResponse = {
  service_type: 'arcgis',
  url: 'https://example.test/arcgis/rest/services/Rec/FeatureServer',
  selected_layer_id: null,
  layers: [
    {
      name: 'REC_PassiveConservedAccessScore',
      title: 'REC_PassiveConservedAccessScore',
      geometry_type: 'Polygon',
      feature_count: 10,
      layer_type: 'Feature Layer',
      layer_id: 15,
      object_id_field: 'OBJECTID',
      kind: 'vector',
    },
    {
      name: 'REC_PassiveConservedAccessScore',
      title: 'REC_PassiveConservedAccessScore',
      geometry_type: 'Polygon',
      feature_count: 20,
      layer_type: 'Feature Layer',
      layer_id: 17,
      object_id_field: 'OBJECTID',
      kind: 'vector',
    },
  ],
};

async function connectToDuplicateNameService() {
  const user = userEvent.setup();
  render(<ServiceUrlForm />);

  await user.type(
    screen.getByPlaceholderText('serviceUrl.placeholder'),
    'https://example.test/arcgis/rest/services/Rec/FeatureServer',
  );
  await user.click(screen.getByRole('button', { name: 'Probe →' }));

  await waitFor(() => {
    expect(mockProbeService).toHaveBeenCalled();
  });

  const layerButtons = await waitFor(() => {
    const buttons = screen
      .getAllByRole('button')
      .filter((btn) => btn.textContent?.includes('REC_PassiveConservedAccessScore'));
    expect(buttons).toHaveLength(2);
    return buttons;
  });

  return { user, layerButtons };
}

describe('ServiceUrlForm token input', () => {
  it('opts every password manager out of the service token field', () => {
    render(<ServiceUrlForm />);
    const input = screen.getByLabelText('serviceUrl.tokenLabel');

    expect(input).toHaveAttribute('type', 'password');
    expect(input).toHaveAttribute('autocomplete', 'new-password');
    expect(input).toHaveAttribute('data-1p-ignore');
    expect(input).toHaveAttribute('data-lpignore', 'true');
    expect(input).toHaveAttribute('data-bwignore');
  });
});

describe('ServiceUrlForm layer picker with a shared layer name', () => {
  it('renders both same-named layers as distinct, independently selectable rows', async () => {
    mockProbeService.mockResolvedValue(DUPLICATE_NAME_PROBE);
    const { layerButtons } = await connectToDuplicateNameService();

    expect(layerButtons).toHaveLength(2);
  });

  it('routes the first duplicate-named row to its own layer_id', async () => {
    mockProbeService.mockResolvedValue(DUPLICATE_NAME_PROBE);
    mockPreviewServiceLayer.mockResolvedValue({
      job_id: 'job-1',
      source_filename: null,
      columns: [],
      crs: 4326,
      geometry_type: 'Polygon',
      feature_count: 10,
      sample_rows: [],
      layer_name: 'REC_PassiveConservedAccessScore',
      layers: null,
    });

    const { user, layerButtons } = await connectToDuplicateNameService();
    await user.click(layerButtons[0]);

    await waitFor(() =>
      expect(mockPreviewServiceLayer).toHaveBeenCalledWith(
        expect.objectContaining({ layer_id: 15 }),
      ),
    );
  });

  it('routes the second duplicate-named row to its own layer_id', async () => {
    mockProbeService.mockResolvedValue(DUPLICATE_NAME_PROBE);
    mockPreviewServiceLayer.mockResolvedValue({
      job_id: 'job-2',
      source_filename: null,
      columns: [],
      crs: 4326,
      geometry_type: 'Polygon',
      feature_count: 20,
      sample_rows: [],
      layer_name: 'REC_PassiveConservedAccessScore',
      layers: null,
    });

    const { user, layerButtons } = await connectToDuplicateNameService();
    await user.click(layerButtons[1]);

    await waitFor(() =>
      expect(mockPreviewServiceLayer).toHaveBeenCalledWith(
        expect.objectContaining({ layer_id: 17 }),
      ),
    );
  });
});

/**
 * Lane A2 (service-auth wave): ArcGIS auth method select. An ArcGIS-shaped
 * URL (matching /(FeatureServer|MapServer)/, mirroring the backend adapter's
 * own detection) swaps the plain optional token field for a three-way
 * Authentication select: no authentication, sign in, or paste a token.
 */
const ARCGIS_URL = 'https://services6.arcgis.com/abcd1234/arcgis/rest/services/Foo/FeatureServer';

async function typeArcGisUrl(user: ReturnType<typeof userEvent.setup>) {
  render(<ServiceUrlForm />);
  await user.type(screen.getByPlaceholderText('serviceUrl.placeholder'), ARCGIS_URL);
  return user;
}

async function chooseAuthMethod(user: ReturnType<typeof userEvent.setup>, optionName: string) {
  await user.click(screen.getByRole('combobox', { name: 'Authentication' }));
  await user.click(await screen.findByRole('option', { name: optionName }));
}

describe('ServiceUrlForm ArcGIS auth method select', () => {
  it('discards a pasted token when switching to Sign in and back', async () => {
    const user = await typeArcGisUrl(userEvent.setup());

    await chooseAuthMethod(user, 'Paste a token or API key');
    const tokenInput = screen.getByLabelText('Token or API key');
    await user.type(tokenInput, 'my-pasted-token');
    expect(tokenInput).toHaveValue('my-pasted-token');

    await chooseAuthMethod(user, 'Sign in with username and password');
    await chooseAuthMethod(user, 'Paste a token or API key');

    expect(screen.getByLabelText('Token or API key')).toHaveValue('');
  });

  it('discards sign-in fields when switching to Paste a token', async () => {
    const user = await typeArcGisUrl(userEvent.setup());

    await chooseAuthMethod(user, 'Sign in with username and password');
    await user.type(screen.getByLabelText('Username'), 'alice');
    await user.type(screen.getByLabelText('Password'), 'hunter2');

    await chooseAuthMethod(user, 'Paste a token or API key');
    await chooseAuthMethod(user, 'Sign in with username and password');

    expect(screen.getByLabelText('Username')).toHaveValue('');
    expect(screen.getByLabelText('Password')).toHaveValue('');
  });

  // codex review #1757 P1: a token entered for one origin (ArcGIS or not)
  // must not survive the service URL being edited to point at a different
  // origin, since handleConnect forwards whatever is in the token field.
  it('clears a pasted ArcGIS token when the service URL is edited to a different origin', async () => {
    const user = await typeArcGisUrl(userEvent.setup());

    await chooseAuthMethod(user, 'Paste a token or API key');
    await user.type(screen.getByLabelText('Token or API key'), 'stale-token');
    expect(screen.getByLabelText('Token or API key')).toHaveValue('stale-token');

    const urlInput = screen.getByPlaceholderText('serviceUrl.placeholder');
    await user.clear(urlInput);
    await user.type(
      urlInput,
      'https://services7.arcgis.com/other-org/arcgis/rest/services/Bar/FeatureServer',
    );

    // The method select itself resets to "no authentication" on the origin
    // change; re-selecting Token proves the underlying state, not just the
    // visible field, was cleared.
    await chooseAuthMethod(user, 'Paste a token or API key');
    expect(screen.getByLabelText('Token or API key')).toHaveValue('');
  });

  it('clears a token pasted for a non-ArcGIS URL once the URL is edited into an ArcGIS one', async () => {
    const user = userEvent.setup();
    render(<ServiceUrlForm />);

    const urlInput = screen.getByPlaceholderText('serviceUrl.placeholder');
    await user.type(urlInput, 'https://example.test/wfs');
    await user.type(screen.getByLabelText('serviceUrl.tokenLabel'), 'stale-wfs-token');

    await user.clear(urlInput);
    await user.type(urlInput, ARCGIS_URL);

    // The plain token field and the ArcGIS token-method field are the same
    // underlying state; it must not carry the WFS-typed value across.
    await chooseAuthMethod(user, 'Paste a token or API key');
    expect(screen.getByLabelText('Token or API key')).toHaveValue('');
  });

  it('keeps the sign-in method and its fields when only the path changes within the same origin', async () => {
    const user = await typeArcGisUrl(userEvent.setup());

    await chooseAuthMethod(user, 'Sign in with username and password');
    await user.type(screen.getByLabelText('Username'), 'alice');

    const urlInput = screen.getByPlaceholderText('serviceUrl.placeholder');
    // Same origin (services6.arcgis.com), different FeatureServer path.
    await user.type(urlInput, '/1');

    expect(screen.getByRole('combobox', { name: 'Authentication' })).toHaveTextContent(
      'Sign in with username and password',
    );
    expect(screen.getByLabelText('Username')).toHaveValue('alice');
  });
});

describe('ServiceUrlForm ArcGIS sign-in', () => {
  async function fillSigninForm(user: ReturnType<typeof userEvent.setup>) {
    await chooseAuthMethod(user, 'Sign in with username and password');
    await user.type(screen.getByLabelText('Portal URL'), 'https://myorg.maps.arcgis.com');
    await user.type(screen.getByLabelText('Username'), 'alice');
    await user.type(screen.getByLabelText('Password'), 'hunter2');
  }

  it('disables the Sign in button while the request is in flight', async () => {
    const user = await typeArcGisUrl(userEvent.setup());
    let resolveSignin: (value: { token: string; expires_at: string }) => void = () => {};
    mockArcgisSignin.mockReturnValue(
      new Promise((resolve) => {
        resolveSignin = resolve;
      }),
    );
    await fillSigninForm(user);

    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Signing in...' })).toBeDisabled();
    });

    resolveSignin({ token: 'minted-token', expires_at: '2026-09-01T13:00:00Z' });

    // The request has settled — the button is out of its loading state.
    // (It stays disabled once settled, but now because the password field
    // was cleared on success, a separate, already-covered behavior below.)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    });
  });

  it('clears the password and fills the token field on a successful sign-in', async () => {
    const user = await typeArcGisUrl(userEvent.setup());
    mockArcgisSignin.mockResolvedValue({
      token: 'minted-token',
      expires_at: '2026-09-01T13:00:00Z',
    });
    await fillSigninForm(user);

    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => {
      expect(screen.getByLabelText('Token or API key')).toHaveValue('minted-token');
    });
    expect(screen.getByLabelText('Password')).toHaveValue('');
  });

  it('clears the password and shows the rejection anchored to the credential block on a failed sign-in', async () => {
    const user = await typeArcGisUrl(userEvent.setup());
    mockArcgisSignin.mockRejectedValue(
      new ApiError(
        'ArcGIS did not accept that sign-in. Check the username and password, including capitalization. Too many failed attempts also lock an ArcGIS account temporarily.',
        400,
        { code: 'arcgis_signin_rejected', message: 'invalid credentials', field: 'credential' },
      ),
    );
    await fillSigninForm(user);

    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => {
      expect(screen.getByText(/ArcGIS did not accept that sign-in/)).toBeInTheDocument();
    });
    expect(screen.getByLabelText('Password')).toHaveValue('');
    expect(screen.queryByLabelText('Token or API key')).not.toBeInTheDocument();
  });

  it('disables the Authentication select while a sign-in request is in flight', async () => {
    const user = await typeArcGisUrl(userEvent.setup());
    mockArcgisSignin.mockReturnValue(new Promise(() => {}));
    await fillSigninForm(user);

    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: 'Authentication' })).toBeDisabled();
    });
  });

  // codex review #1757 P1: the Authentication select disables itself while a
  // request is in flight, which already closes the method-switch route to
  // this race. The service URL field stays editable, though, so this
  // exercises the same generation guard through the one avenue still open:
  // editing the URL to a different origin invalidates the pending request's
  // generation, so its late response must not resurrect a token or expiry
  // the user already backed away from.
  it('ignores a late sign-in response after the URL origin changes mid-flight', async () => {
    const user = await typeArcGisUrl(userEvent.setup());
    let resolveSignin: (value: { token: string; expires_at: string }) => void = () => {};
    mockArcgisSignin.mockReturnValue(
      new Promise((resolve) => {
        resolveSignin = resolve;
      }),
    );
    await fillSigninForm(user);
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    const urlInput = screen.getByPlaceholderText('serviceUrl.placeholder');
    await user.clear(urlInput);
    await user.type(
      urlInput,
      'https://services7.arcgis.com/other-org/arcgis/rest/services/Bar/FeatureServer',
    );

    resolveSignin({ token: 'late-token', expires_at: '2026-09-01T13:00:00Z' });

    // Give the resolved promise's .then a turn, then re-select Sign in and
    // confirm no minted-token field appeared: the stale response must not
    // have populated the token this generation's callers would forward.
    await chooseAuthMethod(user, 'Sign in with username and password');
    await waitFor(() => {
      expect(screen.queryByLabelText('Token or API key')).not.toBeInTheDocument();
    });
  });
});
