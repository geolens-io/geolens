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
  it('replaces a layer name derived from the staged file with the file stem', () => {
    expect(displayLayerName(`${JOB}_significant_month`, 'significant_month.geojson')).toBe('significant_month');
    expect(displayLayerName(`${JOB}_x1y2_significant_month`, 'significant_month.geojson')).toBe('significant_month');
    expect(displayLayerName('significant_month', 'significant_month.geojson')).toBe('significant_month');
  });

  it('keeps a real layer name', () => {
    expect(displayLayerName('roads', 'network.gpkg')).toBe('roads');
    expect(displayLayerName('roads', null)).toBe('roads');
  });
});

describe('ImportPreview layer name', () => {
  it('shows the uploaded file name, not the staged copy name', () => {
    render(<ImportPreview preview={preview(`${JOB}_significant_month`)} />);

    expect(screen.getByText('significant_month')).toBeInTheDocument();
    expect(screen.queryByText(new RegExp(JOB))).not.toBeInTheDocument();
  });
});
