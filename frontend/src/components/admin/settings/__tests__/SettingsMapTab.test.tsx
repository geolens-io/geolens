import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { PMTiles } from 'pmtiles';
import { SettingsMapTab } from '../SettingsMapTab';
import type { BasemapEntry, SettingItem } from '@/api/settings';

/**
 * feat(pmtiles): `isValidTileUrl` in SettingsMapTab.tsx is the client-side
 * mirror of the backend's `validate_tile_url` (backend/app/modules/settings/schemas.py).
 * It gates the "Add" button before a request ever reaches the API, so a
 * self-hoster typing a PMTiles archive URL must not be blocked here even
 * though the backend would accept it.
 *
 * codex review (#1688 P1): a bare PMTiles archive is only renderable as a
 * basemap when it's raster (see basemap-utils.ts). `handleAdd` reads the
 * archive header via `pmtiles`'s `PMTiles` class (mocked globally in
 * src/test/setup.ts, defaulting to a raster tileType) before accepting a
 * bare archive URL, and rejects a vector one with a clear error.
 */
// userEvent.type() reads `{` as the start of a special-key sequence (e.g.
// `{enter}`), so a literal `{` must be escaped as `{{` (a lone `}` types
// literally and needs no escaping).
function escapeUserEventBraces(text: string): string {
  return text.replace(/\{/g, '{{');
}

async function addBasemap(name: string, url: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/name/i), name);
  await user.type(screen.getByLabelText(/tile url/i), escapeUserEventBraces(url));
  await user.click(screen.getByRole('button', { name: /add/i }));
  return user;
}

function renderMapTab(overrides: Partial<Parameters<typeof SettingsMapTab>[0]> = {}) {
  const settings: SettingItem[] = [];
  return render(
    <SettingsMapTab
      settings={settings}
      envOnly={false}
      onSave={vi.fn()}
      onReset={vi.fn()}
      isSaving={false}
      {...overrides}
    />,
  );
}

describe('SettingsMapTab custom basemap URL validation', () => {
  it('accepts a bare https .pmtiles archive URL (raster header)', async () => {
    renderMapTab();
    await addBasemap('World PMTiles', 'https://example.com/world.pmtiles');

    expect(await screen.findByText('https://example.com/world.pmtiles')).toBeInTheDocument();
    expect(screen.queryByText(/must contain/i)).not.toBeInTheDocument();
  });

  it('accepts a pmtiles://-prefixed archive URL (raster header)', async () => {
    renderMapTab();
    await addBasemap('World PMTiles', 'pmtiles://https://example.com/world.pmtiles');

    expect(await screen.findByText('pmtiles://https://example.com/world.pmtiles')).toBeInTheDocument();
    expect(screen.queryByText(/must contain/i)).not.toBeInTheDocument();
  });

  it('rejects a bare vector PMTiles archive with a clear error instead of adding it', async () => {
    vi.mocked(PMTiles).mockImplementationOnce(function (this: { getHeader: () => Promise<{ tileType: number }> }) {
      this.getHeader = vi.fn().mockResolvedValue({ tileType: 1 }); // TileType.Mvt (vector)
    } as unknown as typeof PMTiles);

    renderMapTab();
    await addBasemap('Vector PMTiles', 'https://example.com/vector.pmtiles');

    expect(await screen.findByText(/vector tiles/i)).toBeInTheDocument();
    expect(screen.queryByText('https://example.com/vector.pmtiles')).not.toBeInTheDocument();
  });

  it('accepts a bare archive when the header read fails (fails open)', async () => {
    vi.mocked(PMTiles).mockImplementationOnce(function (this: { getHeader: () => Promise<{ tileType: number }> }) {
      this.getHeader = vi.fn().mockRejectedValue(new Error('network error'));
    } as unknown as typeof PMTiles);

    renderMapTab();
    await addBasemap('Unreachable header', 'https://example.com/unreachable.pmtiles');

    expect(await screen.findByText('https://example.com/unreachable.pmtiles')).toBeInTheDocument();
    expect(screen.queryByText(/vector tiles/i)).not.toBeInTheDocument();
  });

  it('probes an authenticated archive URL with the API key substituted, not the literal placeholder', async () => {
    vi.mocked(PMTiles).mockImplementationOnce(function (this: { getHeader: () => Promise<{ tileType: number }> }) {
      this.getHeader = vi.fn().mockResolvedValue({ tileType: 1 }); // vector -- only reachable via the substituted URL
    } as unknown as typeof PMTiles);

    const user = userEvent.setup();
    renderMapTab();
    await user.type(screen.getByLabelText(/name/i), 'Authenticated PMTiles');
    await user.type(
      screen.getByLabelText(/tile url/i),
      escapeUserEventBraces('https://example.com/{api_key}/world.pmtiles'),
    );
    await user.type(screen.getByLabelText(/api key/i), 'secret-key');
    await user.click(screen.getByRole('button', { name: /add/i }));

    // The mocked header (tileType: 1, vector) is only returned regardless of
    // which URL PMTiles was constructed with, so the meaningful assertion is
    // on the constructor call argument itself: it must be the substituted
    // URL, never the literal `{api_key}` placeholder.
    expect(await screen.findByText(/vector tiles/i)).toBeInTheDocument();
    const calls = vi.mocked(PMTiles).mock.calls;
    const probedUrl = calls[calls.length - 1]?.[0];
    expect(probedUrl).toBe('https://example.com/secret-key/world.pmtiles');
  });

  it('substitutes every occurrence of the API key placeholder before probing', async () => {
    vi.mocked(PMTiles).mockImplementationOnce(function (this: { getHeader: () => Promise<{ tileType: number }> }) {
      this.getHeader = vi.fn().mockResolvedValue({ tileType: 2 }); // raster
    } as unknown as typeof PMTiles);

    const user = userEvent.setup();
    renderMapTab();
    await user.type(screen.getByLabelText(/name/i), 'Double placeholder');
    await user.type(
      screen.getByLabelText(/tile url/i),
      escapeUserEventBraces('https://example.com/{api_key}/tiles/{api_key}/world.pmtiles'),
    );
    await user.type(screen.getByLabelText(/api key/i), 'secret-key');
    await user.click(screen.getByRole('button', { name: /add/i }));

    await screen.findByText('https://example.com/{api_key}/tiles/{api_key}/world.pmtiles');
    const calls = vi.mocked(PMTiles).mock.calls;
    const probedUrl = calls[calls.length - 1]?.[0];
    expect(probedUrl).toBe('https://example.com/secret-key/tiles/secret-key/world.pmtiles');
  });

  it('still rejects an unrecognized URL shape', async () => {
    renderMapTab();
    await addBasemap('Bad', 'https://example.com/not-a-recognized-shape');

    expect(screen.queryByText('https://example.com/not-a-recognized-shape')).not.toBeInTheDocument();
    expect(screen.getByText(/must contain/i)).toBeInTheDocument();
  });

  it('still accepts an XYZ template URL (pre-existing behavior)', async () => {
    renderMapTab();
    await addBasemap('XYZ', 'https://tiles.example.com/{z}/{x}/{y}.png');

    expect(screen.getByText('https://tiles.example.com/{z}/{x}/{y}.png')).toBeInTheDocument();
    expect(screen.queryByText(/must contain/i)).not.toBeInTheDocument();
  });
});

// fix(#1755): the basemap API key fields are admin secrets, not login
// credentials -- they need the same password-manager opt-out attributes the
// service-token inputs gained in #1750.
describe('SettingsMapTab API key fields opt out of password managers', () => {
  function expectOptedOut(input: HTMLElement) {
    expect(input).toHaveAttribute('autocomplete', 'new-password');
    expect(input).toHaveAttribute('data-1p-ignore');
    expect(input).toHaveAttribute('data-lpignore', 'true');
    expect(input).toHaveAttribute('data-bwignore');
  }

  it('opts out the new-basemap API key field', () => {
    renderMapTab();
    expectOptedOut(screen.getByLabelText(/api key/i));
  });

  it('opts out the API key field on an existing custom basemap', () => {
    const existingBasemap: BasemapEntry = {
      id: 'custom-1',
      label: 'Authenticated Basemap',
      url: 'https://example.com/{api_key}/{z}/{x}/{y}.png',
      enabled: true,
      is_preset: false,
      api_key: 'existing-secret',
    };
    const settings: SettingItem[] = [
      { key: 'basemaps', value: [existingBasemap], source: 'overridden', label: 'basemaps' },
    ];
    render(
      <SettingsMapTab
        settings={settings}
        envOnly={false}
        onSave={vi.fn()}
        onReset={vi.fn()}
        isSaving={false}
      />,
    );

    expectOptedOut(screen.getByPlaceholderText('••••••••'));
  });
});
