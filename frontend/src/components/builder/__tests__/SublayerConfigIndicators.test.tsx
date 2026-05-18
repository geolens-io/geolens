import { render, screen } from '@/test/test-utils';
import { SublayerConfigIndicators } from '../SublayerConfigIndicators';
import type { MapLayerResponse } from '@/types/api';

// Mock react-i18next to surface defaultValue strings — mirrors StackRow.test.tsx.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) => {
      if (options?.defaultValue !== undefined) {
        return options.defaultValue as string;
      }
      return key;
    },
  }),
}));

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'dataset-1',
    dataset_name: 'Test layer',
    dataset_geometry_type: 'POLYGON',
    dataset_table_name: 'test_table',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: null,
    ...overrides,
  } as MapLayerResponse;
}

describe('SublayerConfigIndicators', () => {
  it('renders nothing when layer is null', () => {
    const { container } = render(<SublayerConfigIndicators layer={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when layer has no config conditions met', () => {
    const layer = makeLayer({
      label_config: null,
      filter: null,
      paint: { 'fill-color': '#ff0000' }, // scalar — not data-driven
      opacity: 1,
    });
    const { container } = render(<SublayerConfigIndicators layer={layer} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders a labels badge when label_config has a column', () => {
    const layer = makeLayer({
      label_config: { column: 'name' },
    });
    render(<SublayerConfigIndicators layer={layer} />);
    expect(screen.getByText('Labels enabled')).toBeInTheDocument();
  });

  it('renders a filter badge when filter is a non-empty array', () => {
    const layer = makeLayer({
      // FilterSpecification typed as unknown — array literal is acceptable
      filter: ['==', ['get', 'foo'], 1] as unknown as MapLayerResponse['filter'],
    });
    render(<SublayerConfigIndicators layer={layer} />);
    expect(screen.getByText('Filter applied')).toBeInTheDocument();
  });

  it('renders a data-driven badge when any paint value is an expression (array)', () => {
    const layer = makeLayer({
      paint: { 'fill-color': ['get', 'color'] },
    });
    render(<SublayerConfigIndicators layer={layer} />);
    expect(screen.getByText('Data-driven style')).toBeInTheDocument();
  });

  it('renders an opacity-modified badge when opacity !== 1', () => {
    const layer = makeLayer({ opacity: 0.5 });
    render(<SublayerConfigIndicators layer={layer} />);
    expect(screen.getByText('Opacity adjusted')).toBeInTheDocument();
  });

  it('renders 4 badges when all conditions are met (max-render cap respected)', () => {
    const layer = makeLayer({
      label_config: { column: 'name' },
      filter: ['==', ['get', 'foo'], 1] as unknown as MapLayerResponse['filter'],
      paint: { 'fill-color': ['get', 'color'] },
      opacity: 0.5,
    });
    const { container } = render(<SublayerConfigIndicators layer={layer} />);
    expect(screen.getByText('Labels enabled')).toBeInTheDocument();
    expect(screen.getByText('Filter applied')).toBeInTheDocument();
    expect(screen.getByText('Data-driven style')).toBeInTheDocument();
    expect(screen.getByText('Opacity adjusted')).toBeInTheDocument();
    // Strip the wrapper div + count children
    const wrapper = container.firstElementChild as HTMLElement | null;
    expect(wrapper).not.toBeNull();
    expect(wrapper?.children.length).toBe(4);
  });

  it('exposes each badge label via an sr-only span (accessible name)', () => {
    const layer = makeLayer({
      label_config: { column: 'name' },
    });
    render(<SublayerConfigIndicators layer={layer} />);
    const srSpan = screen.getByText('Labels enabled');
    expect(srSpan.className).toContain('sr-only');
  });
});
