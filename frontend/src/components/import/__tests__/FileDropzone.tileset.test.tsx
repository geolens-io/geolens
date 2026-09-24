/** A tileset dropzone describes tileset archives and tags its format as 3D Tiles. */
import { render, screen } from '@/test/test-utils';
import { FileDropzone } from '../FileDropzone';

describe('FileDropzone for tilesets', () => {
  it('describes the archive check and tags .zip as 3D Tiles', () => {
    render(<FileDropzone onFilesAccepted={() => {}} allowedExtensions={['.zip']} tileset />);

    expect(
      screen.getByText('GeoLens checks each archive and reads its tileset.json before anything is stored.'),
    ).toBeInTheDocument();
    expect(screen.getByText('3DT')).toBeInTheDocument();
    expect(screen.queryByText('VEC')).not.toBeInTheDocument();
  });

  it('keeps the geospatial description and kinds otherwise', () => {
    render(<FileDropzone onFilesAccepted={() => {}} allowedExtensions={['.zip', '.tif']} />);

    expect(screen.getByText(/GeoLens will detect geometry, CRS, and schema/)).toBeInTheDocument();
    expect(screen.getByText('VEC')).toBeInTheDocument();
    expect(screen.queryByText('3DT')).not.toBeInTheDocument();
  });
});
