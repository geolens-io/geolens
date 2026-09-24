import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { TilesetAccess } from '../TilesetAccess';
import type { TilesetMetadata } from '@/types/api';

const TILESET: TilesetMetadata = {
  url: '/api/datasets/ds-1/tiles3d/tileset.json',
  size_bytes: 1024,
  version: '1.0',
  geometric_error: 70,
  bounding_volume: 'region',
};

const ABSOLUTE = `${window.location.origin}/api/datasets/ds-1/tiles3d/tileset.json`;

describe('TilesetAccess', () => {
  it('gives the absolute tileset URL and asks for a read-only key on every non-public tileset', () => {
    render(<TilesetAccess tileset={TILESET} visibility="internal" />);

    expect(screen.getByRole('heading', { name: 'Load in a 3D Tiles client' })).toBeInTheDocument();
    expect(screen.getByText(ABSOLUTE)).toBeInTheDocument();
    expect(
      screen.getByText(/Internal, restricted and private tilesets all need an API key in the X-Api-Key header\. Use a read-only key/),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Manage API keys' })).toHaveAttribute('href', '/settings');
  });

  it.each(['internal', 'restricted', 'private'] as const)(
    'copies the URL and a CesiumJS snippet that sends the key as a header for a %s tileset',
    async (visibility) => {
      const user = userEvent.setup();
      render(<TilesetAccess tileset={TILESET} visibility={visibility} />);

      await user.click(screen.getByRole('button', { name: 'Copy URL' }));
      await expect(navigator.clipboard.readText()).resolves.toBe(ABSOLUTE);

      await user.click(screen.getByRole('button', { name: 'Copy CesiumJS snippet' }));
      const snippet = await navigator.clipboard.readText();
      expect(snippet).toContain('Cesium.Cesium3DTileset.fromUrl(');
      expect(snippet).toContain(`url: "${ABSOLUTE}"`);
      expect(snippet).toContain('headers: { "X-Api-Key": "YOUR_API_KEY" }');
      expect(snippet).not.toContain('api_key=');
    },
  );

  it('copies a snippet without a key header for a public tileset', async () => {
    const user = userEvent.setup();
    render(<TilesetAccess tileset={TILESET} visibility="public" />);

    await user.click(screen.getByRole('button', { name: 'Copy CesiumJS snippet' }));
    const snippet = await navigator.clipboard.readText();
    expect(snippet).toContain(`url: "${ABSOLUTE}"`);
    expect(snippet).not.toContain('X-Api-Key');
    expect(snippet).not.toContain('api_key=');
  });

  it('wraps the snippet so a narrow screen needs no scroll region', () => {
    render(<TilesetAccess tileset={TILESET} visibility="private" />);

    expect(screen.getByText(/Cesium3DTileset\.fromUrl/).closest('pre')).toHaveClass('whitespace-pre-wrap');
  });
});
