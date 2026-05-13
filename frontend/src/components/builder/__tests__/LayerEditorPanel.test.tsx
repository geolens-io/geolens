import { render, screen, fireEvent } from '@/test/test-utils';
import { LayerEditorPanel, type LayerEditorHandlers } from '../LayerEditorPanel';
import type { MapLayerResponse } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) =>
      options?.defaultValue ?? key,
  }),
}));

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: overrides.id ?? 'layer-1',
    dataset_id: overrides.dataset_id ?? 'dataset-1',
    dataset_name: overrides.dataset_name ?? 'Population',
    dataset_geometry_type: overrides.dataset_geometry_type ?? 'POLYGON',
    dataset_table_name: overrides.dataset_table_name ?? 'population',
    dataset_extent_bbox: overrides.dataset_extent_bbox ?? [0, 0, 1, 1],
    dataset_column_info: overrides.dataset_column_info ?? null,
    dataset_feature_count: overrides.dataset_feature_count ?? null,
    dataset_sample_values: overrides.dataset_sample_values ?? null,
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
    layer_type: overrides.layer_type ?? null,
    dataset_record_type: overrides.dataset_record_type ?? 'vector_dataset',
    show_in_legend: overrides.show_in_legend ?? true,
    is_dem: overrides.is_dem ?? false,
    dem_vertical_units: overrides.dem_vertical_units ?? null,
    ...overrides,
  };
}

function makeHandlers(overrides: Partial<LayerEditorHandlers> = {}): LayerEditorHandlers {
  return {
    onTabChange: vi.fn(),
    onPaintChange: vi.fn(),
    onOpacityChange: vi.fn(),
    onFilterChange: vi.fn(),
    onLabelChange: vi.fn(),
    onPopupChange: vi.fn(),
    onStyleConfigChange: vi.fn(),
    onLayoutChange: vi.fn(),
    onRenderModeChange: vi.fn(),
    onRemove: vi.fn(),
    ...overrides,
  };
}

describe('LayerEditorPanel', () => {
  describe('header', () => {
    it('renders the layer name in the header', () => {
      const layer = makeLayer({ dataset_name: 'Population' });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
        />
      );
      expect(screen.getByTestId('layer-editor-header')).toBeInTheDocument();
      expect(screen.getByTestId('layer-editor-header')).toHaveTextContent('Population');
    });

    it('renders the display_name when available instead of dataset_name', () => {
      const layer = makeLayer({ dataset_name: 'Population', display_name: 'My Layer' });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
        />
      );
      expect(screen.getByTestId('layer-editor-header')).toHaveTextContent('My Layer');
      expect(screen.getByTestId('layer-editor-header')).not.toHaveTextContent('Population');
    });

    it('renders close button with aria-label="Close layer editor"', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
        />
      );
      const closeBtn = screen.getByRole('button', { name: 'Close layer editor' });
      expect(closeBtn).toBeInTheDocument();
    });

    it('clicking the close button calls onClose', () => {
      const onClose = vi.fn();
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={onClose}
          handlers={makeHandlers()}
          activeTab={null}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: 'Close layer editor' }));
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe('body slot', () => {
    it('renders data-testid="layer-editor-body"', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
        />
      );
      expect(screen.getByTestId('layer-editor-body')).toBeInTheDocument();
    });

    it('body is empty when enableLegacyTabs=false', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          enableLegacyTabs={false}
        />
      );
      const body = screen.getByTestId('layer-editor-body');
      expect(body).toBeInTheDocument();
      // body should have no children when enableLegacyTabs=false
      expect(body.children).toHaveLength(0);
    });

    it('renders the legacy tab UI when enableLegacyTabs=true (default)', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab="style"
          enableLegacyTabs={true}
        />
      );
      // Legacy tab bar should be present (it renders tablist)
      const body = screen.getByTestId('layer-editor-body');
      expect(body.children.length).toBeGreaterThan(0);
    });
  });

  describe('footer slot', () => {
    it('renders data-testid="layer-editor-footer"', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
        />
      );
      expect(screen.getByTestId('layer-editor-footer')).toBeInTheDocument();
    });
  });

  describe('LayerEditorHandlers interface', () => {
    it('handlers.onRemove is part of the interface (type check via test)', () => {
      const handlers = makeHandlers({ onRemove: vi.fn() });
      // If onRemove is not in the type, TypeScript would fail here.
      // This is primarily a compile-time check, but we verify it's accepted.
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={handlers}
          activeTab={null}
        />
      );
      // Component rendered without errors - onRemove is part of the interface
      expect(screen.getByTestId('layer-editor-header')).toBeInTheDocument();
    });
  });
});
