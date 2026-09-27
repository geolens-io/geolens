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

  it('marks a finished table workflow complete and describes the nonspatial result', () => {
    render(<WorkflowRail mode="upload" phase="tracking" outcome="complete" completedKinds={['table']} />);

    expect(screen.getByText(/Rows and schema are ready to query and reuse/)).toBeInTheDocument();
    expect(screen.getByText('Import & catalog').parentElement).toHaveTextContent('✓');
    expect(screen.getByText('COPC point cloud')).toBeInTheDocument();
  });

  it('marks a mixed failure as needing attention', () => {
    render(<WorkflowRail mode="upload" phase="tracking" outcome="partial" completedKinds={['table']} />);

    expect(screen.getByText('Needs attention')).toBeInTheDocument();
    expect(screen.getByText(/Some imports failed or were cancelled/)).toBeInTheDocument();
  });
});
