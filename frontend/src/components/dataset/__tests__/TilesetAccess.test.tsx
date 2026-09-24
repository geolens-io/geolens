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
  it('gives the absolute tileset URL and recommends the X-Api-Key header', () => {
    render(<TilesetAccess tileset={TILESET} />);

    expect(screen.getByRole('heading', { name: 'Load in a 3D Tiles client' })).toBeInTheDocument();
    expect(screen.getByText(ABSOLUTE)).toBeInTheDocument();
    expect(screen.getByText(/send an API key in the X-Api-Key header/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Manage API keys' })).toHaveAttribute('href', '/settings');
  });

  it('copies the URL and a CesiumJS snippet that sends the key as a header', async () => {
    const user = userEvent.setup();
    render(<TilesetAccess tileset={TILESET} />);

    await user.click(screen.getByRole('button', { name: 'Copy URL' }));
    await expect(navigator.clipboard.readText()).resolves.toBe(ABSOLUTE);

    await user.click(screen.getByRole('button', { name: 'Copy CesiumJS snippet' }));
    const snippet = await navigator.clipboard.readText();
    expect(snippet).toContain('Cesium.Cesium3DTileset.fromUrl(');
    expect(snippet).toContain(`url: "${ABSOLUTE}"`);
    expect(snippet).toContain('headers: { "X-Api-Key": "YOUR_API_KEY" }');
    expect(snippet).not.toContain('api_key=');
  });
});
