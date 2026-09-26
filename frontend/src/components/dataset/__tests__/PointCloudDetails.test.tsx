import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { PointCloudCard } from '../PointCloudCard';
import { PointCloudAccess } from '../PointCloudAccess';
import type { DatasetResponse } from '@/types/api';

const PATH = '/api/datasets/ds-1/copc/attempt-1/data.copc.laz';
const URL = `${window.location.origin}${PATH}`;

describe('PointCloudCard', () => {
  it('shows published file facts and geographic bounds from the dataset response', () => {
    const dataset = {
      srid: 26912,
      extent_bbox: [-112.5, 40.5, -112.4, 40.6],
      z_min: 1200,
      z_max: 1900,
      pointcloud: {
        url: PATH,
        size_bytes: 1048576,
        point_count: 9000,
        point_format: 7,
        vertical_crs: 'NAVD88',
      },
    } as DatasetResponse;
    render(<PointCloudCard dataset={dataset} />);

    expect(screen.getByRole('heading', { name: 'COPC point cloud' })).toBeInTheDocument();
    expect(screen.getByText('9,000')).toBeInTheDocument();
    expect(screen.getByText('EPSG:26912')).toBeInTheDocument();
    expect(screen.getByText('1 MB')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.getByText('(-112.5000, 40.5000) to (-112.4000, 40.6000)')).toBeInTheDocument();
    expect(screen.getByText('1,200 – 1,900')).toBeInTheDocument();
    expect(screen.getByText('NAVD88')).toBeInTheDocument();
  });
});

describe('PointCloudAccess', () => {
  it('offers public QGIS, Potree and copc.js instructions with the versioned URL', async () => {
    const user = userEvent.setup();
    render(<PointCloudAccess url={PATH} visibility="public" />);

    expect(screen.getByText(URL)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Copy COPC URL' }));
    await expect(navigator.clipboard.readText()).resolves.toBe(URL);
    expect(screen.getByText(/Add Point Cloud Layer/)).toHaveTextContent('Protocol: HTTP(S), cloud, etc.');

    await user.click(screen.getByRole('button', { name: 'Potree' }));
    expect(screen.getByText(/Potree\.loadPointCloud/)).toHaveTextContent(URL);
    await user.click(screen.getByRole('button', { name: 'copc.js' }));
    await user.click(screen.getByRole('button', { name: 'Copy client snippet' }));
    const snippet = await navigator.clipboard.readText();
    expect(snippet).toContain(`Copc.create("${URL}")`);
    expect(snippet).not.toContain('YOUR_API_KEY');
    expect(snippet).not.toContain('api_key=');
  });

  it.each(['private', 'internal', 'restricted'] as const)(
    'keeps keys as placeholders for a %s point cloud',
    async (visibility) => {
      const user = userEvent.setup();
      render(<PointCloudAccess url={PATH} visibility={visibility} />);

      expect(screen.getByText(/needs a read-only API key/)).toBeInTheDocument();
      expect(screen.getByText(/X-Api-Key: YOUR_API_KEY/)).toBeInTheDocument();

      await user.click(screen.getByRole('button', { name: 'Potree' }));
      expect(screen.getByText(/cannot send an X-Api-Key header/)).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'Copy client snippet' }));
      expect(await navigator.clipboard.readText()).toContain(`${URL}?api_key=YOUR_API_KEY`);

      await user.click(screen.getByRole('button', { name: 'copc.js' }));
      await user.click(screen.getByRole('button', { name: 'Copy client snippet' }));
      const snippet = await navigator.clipboard.readText();
      expect(snippet).toContain('Range: `bytes=${begin}-${end - 1}`');
      expect(snippet).toContain('"X-Api-Key": "YOUR_API_KEY"');
      expect(snippet).not.toContain('api_key=');
    },
  );
});
