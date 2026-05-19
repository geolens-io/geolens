import { render, screen, fireEvent, within } from '@/test/test-utils';
import { LayerEditorPanel, type LayerEditorHandlers } from '../LayerEditorPanel';
import type { MapLayerResponse } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) => {
      // Resolve the four known tab-label keys so role=tab assertions can find
      // them by their visible English label.
      if (key === 'layerItem.styleTab') return 'Style';
      if (key === 'layerItem.filterTab') return 'Filter';
      if (key === 'layerItem.labelsTab') return 'Labels';
      if (key === 'layerItem.popupTab') return 'Popup';
      return options?.defaultValue ?? key;
    },
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
  });

  describe('LayerEditorHandlers interface', () => {
    it('handlers.onRemove is part of the interface (type check via test)', () => {
      const handlers = makeHandlers({ onRemove: vi.fn() });
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          handlers={handlers}
          onClose={vi.fn()}
          activeTab={null}
        />
      );
      expect(screen.getByTestId('layer-editor-header')).toBeInTheDocument();
    });
  });

  describe('tab body (default scene)', () => {
    it('renders a tablist with Style/Filter/Popup for a vector layer (no Labels tab unless render_mode=symbol)', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
        />
      );
      const tablist = screen.getByRole('tablist');
      expect(within(tablist).getByRole('tab', { name: 'Style' })).toBeInTheDocument();
      expect(within(tablist).getByRole('tab', { name: 'Filter' })).toBeInTheDocument();
      expect(within(tablist).getByRole('tab', { name: 'Popup' })).toBeInTheDocument();
      expect(within(tablist).queryByRole('tab', { name: 'Labels' })).not.toBeInTheDocument();
    });

    it('renders a Labels tab only when style_config.render_mode === "symbol"', () => {
      // Point layer with symbol render mode → Labels tab appears
      const layer = makeLayer({
        dataset_geometry_type: 'POINT',
        style_config: {
          render_mode: 'symbol',
          symbol: { iconImage: 'marker', iconSize: 1 },
        } as import('@/types/api').StyleConfig,
      });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
        />
      );
      const tablist = screen.getByRole('tablist');
      expect(within(tablist).getByRole('tab', { name: 'Labels' })).toBeInTheDocument();
    });

    it('Style tab is the default active tab when activeTab is null', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
        />
      );
      const styleTab = screen.getByRole('tab', { name: 'Style' });
      expect(styleTab).toHaveAttribute('aria-selected', 'true');
    });

    it('Render-as pill strip renders inside the Style tab and active pill has data-active="true"', () => {
      const layer = makeLayer({ dataset_geometry_type: 'POLYGON' });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab="style"
        />
      );
      const activePill = document.querySelector('[data-active="true"]');
      expect(activePill).not.toBeNull();
    });

    it('clicking a non-active render-as pill opens the destructive confirm — does NOT immediately fire onRenderModeChange', () => {
      // Point layer has multiple options (point/symbol/heatmap/cluster).
      const handlers = makeHandlers();
      const layer = makeLayer({ dataset_geometry_type: 'POINT' });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={handlers}
          activeTab="style"
        />
      );
      const pills = document.querySelectorAll('[data-active="false"]');
      if (pills.length === 0) {
        // Single render option for this geometry — skip
        return;
      }
      fireEvent.click(pills[0] as HTMLElement);
      // Switch is destructive — confirm dialog opens, no actual mutation yet.
      expect(handlers.onRenderModeChange).not.toHaveBeenCalled();
      expect(screen.getByRole('alertdialog')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Switch mode' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Keep style' })).toBeInTheDocument();
    });

    it('clicking "Switch mode" in the render-as confirm calls onRenderModeChange', () => {
      const handlers = makeHandlers();
      const layer = makeLayer({ dataset_geometry_type: 'POINT' });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={handlers}
          activeTab="style"
        />
      );
      const pills = document.querySelectorAll('[data-active="false"]');
      if (pills.length === 0) return;
      fireEvent.click(pills[0] as HTMLElement);
      fireEvent.click(screen.getByRole('button', { name: 'Switch mode' }));
      expect(handlers.onRenderModeChange).toHaveBeenCalled();
    });

    it('clicking "Keep style" dismisses the render-as confirm without calling onRenderModeChange', () => {
      const handlers = makeHandlers();
      const layer = makeLayer({ dataset_geometry_type: 'POINT' });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={handlers}
          activeTab="style"
        />
      );
      const pills = document.querySelectorAll('[data-active="false"]');
      if (pills.length === 0) return;
      fireEvent.click(pills[0] as HTMLElement);
      fireEvent.click(screen.getByRole('button', { name: 'Keep style' }));
      expect(handlers.onRenderModeChange).not.toHaveBeenCalled();
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    });

    it('Style tab embeds LayerStyleEditor for a vector layer', () => {
      const layer = makeLayer({ dataset_geometry_type: 'POLYGON' });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab="style"
        />
      );
      expect(screen.getByTestId('layer-style-editor')).toBeInTheDocument();
    });

    it('Style tab embeds RasterLayerControls for a raster layer', () => {
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
          activeTab="style"
        />
      );
      expect(screen.getByTestId('raster-layer-controls')).toBeInTheDocument();
      expect(screen.queryByTestId('layer-style-editor')).not.toBeInTheDocument();
    });

    it('selecting the Filter tab renders the filter editor body', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab="filter"
        />
      );
      expect(screen.getByTestId('layer-filter-editor')).toBeInTheDocument();
    });

    it('selecting the Popup tab renders the popup config editor', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab="popup"
        />
      );
      expect(screen.getByTestId('popup-config-editor')).toBeInTheDocument();
    });

    it('clicking a tab fires handlers.onTabChange with the layer id and tab key', () => {
      const handlers = makeHandlers();
      render(
        <LayerEditorPanel
          layer={makeLayer({ id: 'foo' })}
          onClose={vi.fn()}
          handlers={handlers}
          activeTab="style"
        />
      );
      fireEvent.click(screen.getByRole('tab', { name: 'Filter' }));
      expect(handlers.onTabChange).toHaveBeenCalledWith('foo', 'filter');
    });

    it('Filter tab pip shows a count badge when the filter has conditions', () => {
      const layer = makeLayer({ filter: ['all', ['==', 'a', 1], ['==', 'b', 2]] });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab="style"
        />
      );
      // The Filter tab should contain a "2" pip
      const filterTab = screen.getByRole('tab', { name: /Filter/ });
      expect(filterTab).toHaveTextContent('2');
    });

    it('Popup tab pip is rendered when popup_config.enabled is true', () => {
      const layer = makeLayer({
        popup_config: { enabled: true } as import('@/types/api').PopupConfig,
      });
      const { container } = render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab="style"
        />
      );
      const popupTab = screen.getByRole('tab', { name: /Popup/ });
      // The popup tab should contain a dot element (small rounded primary span)
      const dot = popupTab.querySelector('span.rounded-full');
      expect(dot).not.toBeNull();
      expect(container).toBeTruthy();
    });

    it('Source section is NOT rendered in the panel (moved to row kebab)', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer({ dataset_name: 'My dataset' })}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab="style"
        />
      );
      // No "Source" section header in the panel body — Source moved to StackRow kebab
      expect(screen.queryByText('Source')).not.toBeInTheDocument();
    });

    it('Footer is NOT rendered for the default scene (Delete moved to row kebab)', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab="style"
        />
      );
      expect(screen.queryByTestId('layer-editor-footer')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Delete layer' })).not.toBeInTheDocument();
    });
  });

  describe('editorScene dispatch', () => {
    it('editorScene=default renders the tab body', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          editorScene="default"
        />
      );
      expect(screen.getByRole('tablist')).toBeInTheDocument();
    });

    it('editorScene=undefined renders the tab body (regression)', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
        />
      );
      expect(screen.getByRole('tablist')).toBeInTheDocument();
    });

    it('editorScene=basemap-sublayer renders breadcrumb', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          editorScene="basemap-sublayer"
          breadcrumbPresetName="Positron"
        />
      );
      const breadcrumb = screen.getByRole('button', { name: 'Back to basemap group' });
      expect(breadcrumb).toBeInTheDocument();
      expect(breadcrumb).toHaveTextContent('Basemap · Positron ›');
    });

    it('breadcrumb calls onBreadcrumbClick when clicked', () => {
      const onBreadcrumbClick = vi.fn();
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          editorScene="basemap-sublayer"
          breadcrumbPresetName="Streets"
          onBreadcrumbClick={onBreadcrumbClick}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: 'Back to basemap group' }));
      expect(onBreadcrumbClick).toHaveBeenCalledTimes(1);
    });

    it('non-default editorScene does NOT render the tab body; renders sceneContent instead', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          editorScene="dem"
          sceneContent={<div data-testid="custom-scene">scene</div>}
        />
      );
      expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
      expect(screen.getByTestId('custom-scene')).toBeInTheDocument();
    });

    it('non-default scene WITH sceneFooter renders the footer slot', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          editorScene="basemap-sublayer"
          sceneFooter={<button data-testid="scene-footer-action">Reset</button>}
        />
      );
      expect(screen.getByTestId('layer-editor-footer')).toBeInTheDocument();
      expect(screen.getByTestId('scene-footer-action')).toBeInTheDocument();
    });

    it('non-default scene WITHOUT sceneFooter omits the footer slot', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          editorScene="basemap-sublayer"
        />
      );
      expect(screen.queryByTestId('layer-editor-footer')).not.toBeInTheDocument();
    });

    it('breadcrumb with undefined presetName renders "Basemap · Untitled ›"', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          editorScene="basemap-sublayer"
        />
      );
      const breadcrumb = screen.getByRole('button', { name: 'Back to basemap group' });
      expect(breadcrumb).toHaveTextContent('Basemap · Untitled ›');
    });
  });

  describe('AUD-05/06: header padding, type pill color', () => {
    it('AUD-05: header element has className containing px-4 and py-3', () => {
      render(
        <LayerEditorPanel
          layer={makeLayer()}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
        />
      );
      const header = screen.getByTestId('layer-editor-header');
      expect(header.className).toContain('px-4');
      expect(header.className).toContain('py-3');
    });

    it('AUD-06: vector layer type pill has bg-[var(--type-vector-bg)] class', () => {
      const layer = makeLayer({ dataset_record_type: 'vector_dataset', dataset_geometry_type: 'POLYGON' });
      render(
        <LayerEditorPanel
          layer={layer}
          onClose={vi.fn()}
          handlers={makeHandlers()}
          activeTab={null}
          editorScene="default"
        />
      );
      const pill = document.querySelector('[class*="type-vector-bg"]');
      expect(pill).not.toBeNull();
      expect(pill?.className).toContain('type-vector');
    });

    it('AUD-06: raster layer type pill has bg-[var(--type-raster-bg)] class', () => {
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
          editorScene="default"
        />
      );
      const pill = document.querySelector('[class*="type-raster-bg"]');
      expect(pill).not.toBeNull();
    });
  });
});
