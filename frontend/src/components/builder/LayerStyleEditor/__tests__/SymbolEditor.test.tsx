import { render, screen, fireEvent } from '@/test/test-utils';
import { SymbolEditor } from '../SymbolEditor';
import type { BaseStyleEditorProps } from '../types';
import type { MapLayerResponse } from '@/types/api';

// Radix Select uses ResizeObserver internally
(globalThis as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
Element.prototype.hasPointerCapture = vi.fn(() => false);
Element.prototype.releasePointerCapture = vi.fn();
Element.prototype.scrollIntoView = vi.fn();

const icons = [
  { id: 'builtin:marker', name: 'Marker', slug: 'marker', media_type: 'image/svg+xml', url: '/x', sprite_id: 'marker', size_bytes: 1, builtin: true },
  { id: 'builtin:star', name: 'Star', slug: 'star', media_type: 'image/svg+xml', url: '/x', sprite_id: 'star', size_bytes: 1, builtin: true },
];

vi.mock('@/hooks/use-maps', () => ({
  useMapIcons: () => ({ data: { icons } }),
  useUploadMapIcon: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

function makeLayer(sampleValues: unknown[]): MapLayerResponse {
  return {
    id: 'layer-symbol',
    dataset_id: 'ds',
    dataset_name: 'ds',
    dataset_geometry_type: 'Point',
    dataset_table_name: 'tbl',
    dataset_extent_bbox: null,
    dataset_column_info: [{ name: 'kind', type: 'text' }],
    dataset_feature_count: null,
    dataset_sample_values: { kind: sampleValues },
    display_name: 'Symbols',
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    style_config: null,
  } as unknown as MapLayerResponse;
}

function makeProps(layer: MapLayerResponse, overrides: Partial<BaseStyleEditorProps> = {}): BaseStyleEditorProps {
  return {
    layer,
    paint: {},
    isDataDriven: false,
    builderConfig: {},
    styleConfig: null,
    symbolConfig: { iconImage: 'marker', iconSize: 1, iconRotation: 0, iconAnchor: 'center', categoryColumn: 'kind' },
    isPolygon: false,
    numericColumns: [],
    currentHeightCol: '',
    strokeEnabled: true,
    fillEnabled: true,
    onPaintChange: vi.fn(),
    onLayoutChange: vi.fn(),
    onPaintProp: vi.fn(),
    onToggleFill: vi.fn(),
    onToggleStroke: vi.fn(),
    onHeatmapPaintChange: vi.fn(),
    onSymbolConfigChange: vi.fn(),
    onBuilderChange: vi.fn(),
    onFillPatternChange: vi.fn(),
    t: ((key: string, opts?: Record<string, unknown>) => {
      if (key === 'style.symbol.categoryIcon') return `Icon for ${opts?.value}`;
      if (key === 'style.symbol.unknownIcon') return `No icon named ${opts?.icon}`;
      if (key === 'style.symbol.sampledValues') return 'Sampled values';
      if (key.startsWith('style.symbol.anchorOption.')) return `anchor:${key.split('.').pop()}`;
      return key;
    }) as BaseStyleEditorProps['t'],
    ...overrides,
  };
}

describe('SymbolEditor — category mapping (fix #920)', () => {
  it('renders every sampled value the backend returned, not the first six', () => {
    const values = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j'];
    render(<SymbolEditor {...makeProps(makeLayer(values))} />);
    for (const v of values) {
      expect(screen.getByRole('textbox', { name: `Icon for ${v}` })).toBeInTheDocument();
    }
    expect(screen.getByText('Sampled values')).toBeInTheDocument();
  });

  it('flags an icon that does not resolve and leaves known ones alone', () => {
    render(
      <SymbolEditor
        {...makeProps(makeLayer(['a', 'b']), {
          symbolConfig: {
            iconImage: 'marker',
            categoryColumn: 'kind',
            categories: [{ value: 'a', icon: 'markr' }, { value: 'b', icon: 'star' }],
          },
        })}
      />,
    );
    expect(screen.getByText('No icon named markr')).toBeInTheDocument();
    expect(screen.queryByText('No icon named star')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Icon for a' })).toHaveAttribute('aria-invalid', 'true');
  });

  it('drops the entry instead of storing an empty icon when a row is cleared', () => {
    const onSymbolConfigChange = vi.fn();
    render(
      <SymbolEditor
        {...makeProps(makeLayer(['a', 'b']), {
          onSymbolConfigChange,
          symbolConfig: {
            iconImage: 'marker',
            categoryColumn: 'kind',
            categories: [{ value: 'a', icon: 'star' }],
          },
        })}
      />,
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'Icon for a' }), { target: { value: '' } });
    expect(onSymbolConfigChange).toHaveBeenCalledWith({ categories: [], categoryColumn: 'kind' });
  });

  it('shows the fallback for a legacy empty-icon entry rather than flagging it', () => {
    render(
      <SymbolEditor
        {...makeProps(makeLayer(['a']), {
          symbolConfig: {
            iconImage: 'star',
            categoryColumn: 'kind',
            // Shape a map saved by the previous handler could hold.
            categories: [{ value: 'a', icon: '' }],
          },
        })}
      />,
    );
    expect(screen.getByRole('textbox', { name: 'Icon for a' })).toHaveValue('star');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('accepts a fully qualified sprite id the renderer resolves', () => {
    render(
      <SymbolEditor
        {...makeProps(makeLayer(['a']), {
          symbolConfig: {
            iconImage: 'marker',
            categoryColumn: 'kind',
            categories: [{ value: 'a', icon: 'geolens:star' }],
          },
        })}
      />,
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('translates the anchor options instead of rendering raw tokens', () => {
    render(<SymbolEditor {...makeProps(makeLayer(['a']))} />);
    expect(screen.getByText('anchor:center')).toBeInTheDocument();
  });
});
