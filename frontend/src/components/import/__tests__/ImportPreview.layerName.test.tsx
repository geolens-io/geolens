import { render, screen } from '@/test/test-utils';
import { ImportPreview } from '../ImportPreview';
import { displayLayerName } from '../utils';
import type { FilePreviewResponse } from '@/types/api';

const JOB = '8155d4a8-0de1-4a52-9d6c-0123456f5f10';

function preview(layerName: string): FilePreviewResponse {
  return {
    job_id: JOB,
    source_filename: 'significant_month.geojson',
    columns: [],
    crs: 4326,
    geometry_type: 'Point',
    feature_count: 3,
    sample_rows: [],
    layer_name: layerName,
  } as FilePreviewResponse;
}

describe('displayLayerName', () => {
  it('replaces a layer name carrying the job id prefix with the file stem', () => {
    expect(displayLayerName(`${JOB}_significant_month`, JOB, 'significant_month.geojson')).toBe('significant_month');
    expect(displayLayerName(`${JOB}_x1y2_significant_month`, JOB, 'significant_month.geojson')).toBe('significant_month');
  });

  it('keeps real layer names, including ones that end with the file stem', () => {
    expect(displayLayerName('roads', JOB, 'network.gpkg')).toBe('roads');
    expect(displayLayerName('roads', JOB, null)).toBe('roads');
    expect(displayLayerName('primary_roads', JOB, 'roads.gpkg')).toBe('primary_roads');
    expect(displayLayerName('secondary_roads', JOB, 'roads.gpkg')).toBe('secondary_roads');
  });
});

describe('ImportPreview layer name', () => {
  it('shows the uploaded file name, not the staged copy name', () => {
    render(<ImportPreview preview={preview(`${JOB}_significant_month`)} />);

    expect(screen.getByText('significant_month')).toBeInTheDocument();
    expect(screen.queryByText(new RegExp(JOB))).not.toBeInTheDocument();
  });
});

describe('ImportPreview heading', () => {
  it('names a file preview by default', () => {
    render(<ImportPreview preview={preview('roads')} />);
    expect(screen.getByRole('heading', { name: 'File preview' })).toBeInTheDocument();
  });

  it('names a service preview for service imports', () => {
    render(<ImportPreview preview={preview('roads')} source="service" />);
    expect(screen.getByRole('heading', { name: 'Service preview' })).toBeInTheDocument();
  });
});
