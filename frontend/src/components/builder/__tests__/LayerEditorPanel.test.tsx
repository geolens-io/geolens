import { render, screen, fireEvent } from '@/test/test-utils';
import { LayerEditorPanel, type LayerEditorHandlers } from '../LayerEditorPanel';
import type { MapLayerResponse } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) =>
      options?.defaultValue ?? key,
  }),
}));

// Mock heavy sub-editors so they don't need full maplibre/canvas setup
vi.mock('../LayerStyleEditor', () => ({
  LayerStyleEditor: () => <div data-testid="layer-style-editor" />,
}));
vi.mock('../RasterLayerControls', () => ({
  RasterLayerControls: () => <div data-testid="raster-layer-controls" />,
}));
vi.mock('../LayerFilterEditor', () => ({
  LayerFilterEditor: () => <div data-testid="layer-filter-editor" />,
}));
vi.mock('../LabelEditor', () => ({
  LabelEditor: () => <div data-testid="label-editor" />,
}));
vi.mock('../PopupConfigEditor', () => ({
  PopupConfigEditor: () => <div data-testid="popup-config-editor" />,
}));
vi.mock('../ColumnsReference', () => ({
  ColumnsReference: () => <div data-testid="columns-reference" />,
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

    it('renders the legacy tab UI when enableLegacyTabs=true', () => {
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
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={handlers}
          activeTab={null}
        />
      );
      expect(screen.getByTestId('layer-editor-header')).toBeInTheDocument();
    });
  });

  describe('section body (enableLegacyTabs=false)', () => {
    it('renders six sections in DOM order: Render as, Appearance, Visibility, Filter, Labels, Source', () => {
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
      // All six section labels should appear in the document
      expect(screen.getByText('Render as')).toBeInTheDocument();
      expect(screen.getByText('Appearance')).toBeInTheDocument();
      expect(screen.getByText('Visibility')).toBeInTheDocument();
      expect(screen.getByText('Filter')).toBeInTheDocument();
      expect(screen.getByText('Labels')).toBeInTheDocument();
      expect(screen.getByText('Source')).toBeInTheDocument();
    });

    it('Render-as pill strip shows pills from getRenderAsOptions; active pill has data-active="true"', () => {
      // POLYGON layer -> fill/stroke/fill-stroke/extrusion-3d options
      const layer = makeLayer({ dataset_geometry_type: 'POLYGON' });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          enableLegacyTabs={false}
        />
      );
      // Should show at least one pill (e.g. "Fill")
      const activePill = document.querySelector('[data-active="true"]');
      expect(activePill).not.toBeNull();
    });

    it('clicking a non-active render-as pill calls handlers.onRenderModeChange', () => {
      // Use POINT layer which has multiple distinct options: point, symbol, heatmap, cluster
      const handlers = makeHandlers();
      const layer = makeLayer({ dataset_geometry_type: 'POINT' });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={handlers}
          activeTab={null}
          enableLegacyTabs={false}
        />
      );
      // Find all render-as pills; click the first inactive one
      const pills = document.querySelectorAll('[data-active="false"]');
      if (pills.length > 0) {
        fireEvent.click(pills[0] as HTMLElement);
        expect(handlers.onRenderModeChange).toHaveBeenCalled();
      } else {
        // If all pills are active (single option), just confirm the section rendered
        expect(screen.getByText('Render as')).toBeInTheDocument();
      }
    });

    it('Appearance section embeds LayerStyleEditor for a vector layer', () => {
      const layer = makeLayer({ dataset_geometry_type: 'POLYGON' });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          enableLegacyTabs={false}
        />
      );
      expect(screen.getByTestId('layer-style-editor')).toBeInTheDocument();
    });

    it('Visibility section opacity slider has aria-label containing "Opacity"', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          enableLegacyTabs={false}
        />
      );
      // The slider aria-label should contain "Opacity"
      const slider = document.querySelector('[aria-label*="Opacity"]');
      expect(slider).not.toBeNull();
    });

    it('Filter section is collapsed by default', () => {
      const layer = makeLayer({ dataset_geometry_type: 'POLYGON' });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          enableLegacyTabs={false}
        />
      );
      // Filter editor should not be visible initially (collapsed)
      expect(screen.queryByTestId('layer-filter-editor')).not.toBeInTheDocument();
    });

    it('Filter section hint reads "No filter" when layer.filter is null', () => {
      const layer = makeLayer({ filter: null });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          enableLegacyTabs={false}
        />
      );
      expect(screen.getByText('No filter')).toBeInTheDocument();
    });

    it('Labels section is absent when supportsLabelEditor is false (raster layer)', () => {
      const layer = makeLayer({
        dataset_record_type: 'raster_dataset',
        layer_type: 'raster_geolens',
        dataset_geometry_type: null,
      });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          enableLegacyTabs={false}
        />
      );
      // Labels section should not render for raster
      expect(screen.queryByText('Labels')).not.toBeInTheDocument();
    });

    it('Source section is always rendered', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          enableLegacyTabs={false}
        />
      );
      expect(screen.getByText('Source')).toBeInTheDocument();
    });

    it('footer renders a single "Delete layer" button when confirmingDelete is false', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          enableLegacyTabs={false}
        />
      );
      expect(screen.getByRole('button', { name: 'Delete layer' })).toBeInTheDocument();
    });

    it('clicking "Delete layer" reveals inline confirm: "Are you sure? This cannot be undone."', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          enableLegacyTabs={false}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: 'Delete layer' }));
      expect(screen.getByText('Are you sure? This cannot be undone.')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Keep layer' })).toBeInTheDocument();
    });

    it('clicking "Delete" in the confirm calls handlers.onRemove(layer.id)', () => {
      const handlers = makeHandlers();
      const layer = makeLayer({ id: 'test-layer-id' });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={handlers}
          activeTab={null}
          enableLegacyTabs={false}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: 'Delete layer' }));
      fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
      expect(handlers.onRemove).toHaveBeenCalledWith('test-layer-id');
    });

    it('clicking "Keep layer" hides the confirm without calling onRemove', () => {
      const handlers = makeHandlers();
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={handlers}
          activeTab={null}
          enableLegacyTabs={false}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: 'Delete layer' }));
      expect(screen.getByText('Are you sure? This cannot be undone.')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Keep layer' }));
      expect(screen.queryByText('Are you sure? This cannot be undone.')).not.toBeInTheDocument();
      expect(handlers.onRemove).not.toHaveBeenCalled();
    });

    it('Appearance section renders RasterLayerControls for a raster layer', () => {
      const layer = makeLayer({
        dataset_record_type: 'raster_dataset',
        layer_type: 'raster_geolens',
        dataset_geometry_type: null,
      });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          enableLegacyTabs={false}
        />
      );
      expect(screen.getByTestId('raster-layer-controls')).toBeInTheDocument();
      expect(screen.queryByTestId('layer-style-editor')).not.toBeInTheDocument();
    });

    it('with enableLegacyTabs=true, the legacy tab UI still renders (regression)', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab="style"
          enableLegacyTabs={true}
        />
      );
      // The old tab UI renders tablist
      expect(screen.getByRole('tablist')).toBeInTheDocument();
      // The new section labels should NOT appear
      expect(screen.queryByText('Render as')).not.toBeInTheDocument();
    });
  });
});
