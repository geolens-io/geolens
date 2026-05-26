import type { ReactNode } from 'react';
import { fireEvent, render, screen } from '@/test/test-utils';
import { TerrainControls } from '../TerrainControls';
import type { MapLayerResponse } from '@/types/api';

vi.mock('@/components/ui/select', () => ({
  Select: ({
    value,
    onValueChange,
    children,
  }: {
    value?: string;
    onValueChange: (value: string) => void;
    children: ReactNode;
  }) => (
    <select
      aria-label="DEM source"
      value={value ?? ''}
      onChange={(event) => onValueChange(event.currentTarget.value)}
    >
      {children}
    </select>
  ),
  SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: ReactNode }) => (
    <option value={value}>{children}</option>
  ),
  SelectTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectValue: () => null,
}));

vi.mock('@/components/ui/slider', () => ({
  Slider: ({
    value,
    min,
    max,
    step,
    onValueChange,
    'aria-label': ariaLabel,
  }: {
    value: number[];
    min: number;
    max: number;
    step: number;
    onValueChange: (value: number[]) => void;
    'aria-label': string;
  }) => (
    <input
      aria-label={ariaLabel}
      type="range"
      value={value[0]}
      min={min}
      max={max}
      step={step}
      onChange={(event) => onValueChange([Number(event.currentTarget.value)])}
    />
  ),
}));

function layer(overrides: Partial<MapLayerResponse>): MapLayerResponse {
  return {
    id: overrides.id ?? 'layer-1',
    dataset_id: overrides.dataset_id ?? 'dataset-1',
    dataset_name: overrides.dataset_name ?? 'Dataset',
    dataset_geometry_type: overrides.dataset_geometry_type ?? null,
    dataset_table_name: overrides.dataset_table_name ?? 'dataset',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: overrides.display_name ?? null,
    sort_order: overrides.sort_order ?? 0,
    visible: overrides.visible ?? true,
    opacity: overrides.opacity ?? 1,
    paint: overrides.paint ?? {},
    layout: overrides.layout ?? {},
    filter: overrides.filter ?? null,
    label_config: overrides.label_config ?? null,
    popup_config: overrides.popup_config ?? null,
    style_config: overrides.style_config ?? null,
    layer_type: overrides.layer_type ?? 'raster_geolens',
    dataset_record_type: overrides.dataset_record_type ?? 'raster_dataset',
    show_in_legend: overrides.show_in_legend ?? true,
    is_dem: overrides.is_dem ?? true,
    dem_vertical_units: overrides.dem_vertical_units ?? 'meters',
    ...overrides,
  };
}

describe('TerrainControls', () => {
  it('shows an unavailable state when the map has no DEM raster layers', () => {
    render(
      <TerrainControls
        layers={[layer({ dataset_id: 'vector-1', dataset_record_type: 'vector_dataset', is_dem: false })]}
        value={null}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText('Add a DEM raster layer to enable terrain.')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Enable terrain' })).toBeDisabled();
  });

  it('enables terrain with the first available DEM source', () => {
    const onChange = vi.fn();
    render(
      <TerrainControls
        layers={[layer({ dataset_id: 'dem-1', dataset_name: 'Elevation' })]}
        value={null}
        onChange={onChange}
      />,
    );

    expect(screen.getByText('Elevation surface')).toBeInTheDocument();
    expect(screen.getByText('Selected DEM')).toBeInTheDocument();
    expect(screen.getAllByText('Elevation').length).toBeGreaterThan(0);
    expect(screen.getByText('1 visible DEM layer')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('switch', { name: 'Enable terrain' }));

    expect(onChange).toHaveBeenCalledWith({
      enabled: true,
      source_dataset_id: 'dem-1',
      exaggeration: 1,
    });
  });

  it('filters source options to DEM rasters and writes source changes', () => {
    const onChange = vi.fn();
    render(
      <TerrainControls
        layers={[
          layer({ dataset_id: 'dem-1', dataset_name: 'Elevation A' }),
          layer({ dataset_id: 'vector-1', dataset_name: 'Roads', dataset_record_type: 'vector_dataset', is_dem: false }),
          layer({ dataset_id: 'dem-2', dataset_name: 'Elevation B', dataset_record_type: 'vrt_dataset' }),
        ]}
        value={{ enabled: true, source_dataset_id: 'dem-1', exaggeration: 2 }}
        onChange={onChange}
      />,
    );

    expect(screen.getByText('2 visible DEM layers')).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Roads' })).not.toBeInTheDocument();
    expect(screen.queryByRole('slider', { name: 'Exaggeration' })).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: 'DEM source' }), { target: { value: 'dem-2' } });
    expect(onChange).toHaveBeenCalledWith({
      enabled: true,
      source_dataset_id: 'dem-2',
      exaggeration: 2,
    });
  });

  it('shows vertical unit caveats for missing or non-meter units', () => {
    const { rerender } = render(
      <TerrainControls
        layers={[layer({ dem_vertical_units: null })]}
        value={{ enabled: true, source_dataset_id: 'dataset-1', exaggeration: 1 }}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText('Vertical units are unavailable; terrain scale is approximate.')).toBeInTheDocument();

    rerender(
      <TerrainControls
        layers={[layer({ dem_vertical_units: 'feet' })]}
        value={{ enabled: true, source_dataset_id: 'dataset-1', exaggeration: 1 }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText('Vertical units are feet, not meters; terrain scale is approximate.')).toBeInTheDocument();

    rerender(
      <TerrainControls
        layers={[layer({ dem_vertical_units: 'meters' })]}
        value={{ enabled: true, source_dataset_id: 'dataset-1', exaggeration: 1 }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.queryByText(/terrain scale is approximate/i)).not.toBeInTheDocument();
  });
});
