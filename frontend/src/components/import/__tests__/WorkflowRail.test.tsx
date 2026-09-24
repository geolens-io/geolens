/** The upload rail names every kind an upload can become, 3D Tiles tilesets included. */
import { render, screen } from '@/test/test-utils';
import { WorkflowRail } from '../WorkflowRail';

describe('WorkflowRail', () => {
  it('lists 3D Tiles with its tag alongside vector, raster and tabular data', () => {
    render(<WorkflowRail mode="upload" phase="idle" />);

    for (const label of ['Vector', 'Raster', 'Tabular', '3D Tiles']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText('3DT')).toBeInTheDocument();
    expect(screen.getByText(/unpacked and served as is to 3D Tiles clients/)).toBeInTheDocument();
  });
});
