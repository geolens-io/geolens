/**
 * ActiveFilterChips — collapsible summary pill
 *
 * The active-filter chips collapse to a "Filters (N)" pill by default so they no
 * longer render over the top-left NavigationControl / MapCoordReadout (the
 * reported overlap). Expanding reveals the removable chip list + Clear all.
 *
 * Verifies:
 * 1. Collapsed by default — pill + count show, filter detail is hidden.
 * 2. Expanding reveals the chip label + layer name.
 * 3. Layout: outer wrapper pointer-events-none + ml-12 (clears the zoom
 *    control); inner scroll container pointer-events-auto + max-h-[40vh] +
 *    overflow-y-auto (WR-01).
 * 4. Zero chips renders null.
 * 5. Per-chip X and Clear all call onClearFilter correctly.
 * 6. The filter summarizer (FILT-01 / FILT-02) is unchanged.
 * 7. Source-text negative-control keeps the max-h-[40vh] + overflow-y-auto cap.
 *
 * Uses Vite ?raw import for the source-text test — same pattern as
 * preserve-drawing-buffer.test.ts (no node:fs / @types/node dependency).
 */

import { render, screen, fireEvent } from '@/test/test-utils';
import activeFilterChipsSrc from '../ActiveFilterChips.tsx?raw';
import { ActiveFilterChips } from '../ActiveFilterChips';
import type { MapLayerResponse } from '@/types/api';
import type { FilterSpecification } from 'maplibre-gl';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) =>
      options?.defaultValue ?? key,
    i18n: { language: 'en' },
  }),
}));

// ---------------------------------------------------------------------------
// Fixture helpers
// ---------------------------------------------------------------------------

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: overrides.id ?? 'layer-1',
    dataset_id: overrides.dataset_id ?? 'dataset-1',
    dataset_name: overrides.dataset_name ?? 'Roads',
    dataset_geometry_type: overrides.dataset_geometry_type ?? 'LINESTRING',
    dataset_table_name: overrides.dataset_table_name ?? 'roads',
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

const HIGHWAY_FILTER: FilterSpecification = ['==', ['get', 'class'], 'highway'];

/** Click the summary pill to reveal the chip list. */
function expandFilters() {
  fireEvent.click(
    screen.getByRole('button', { name: /show or hide active filters/i }),
  );
}

// ===========================================================================
// Collapsible pill behaviour
// ===========================================================================

describe('ActiveFilterChips — collapsible summary pill', () => {
  it('collapses by default: shows the pill + count, hides the filter detail', () => {
    const layer = makeLayer({ filter: HIGHWAY_FILTER });
    render(<ActiveFilterChips layers={[layer]} onClearFilter={vi.fn()} />);

    expect(
      screen.getByRole('button', { name: /show or hide active filters/i }),
    ).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('1')).toBeInTheDocument();
    // Filter detail is not rendered until expanded.
    expect(screen.queryByText('class == "highway"')).not.toBeInTheDocument();
  });

  it('expands to reveal the chip label and layer name', () => {
    const layer = makeLayer({ dataset_name: 'Roads', filter: HIGHWAY_FILTER });
    render(<ActiveFilterChips layers={[layer]} onClearFilter={vi.fn()} />);

    expandFilters();
    expect(screen.getByText('class == "highway"')).toBeInTheDocument();
    expect(screen.getByText(/roads/i)).toBeInTheDocument();
  });

  it('layout: outer pointer-events-none + ml-12 (clears zoom control); inner has the scroll cap (WR-01)', () => {
    const layer = makeLayer({ filter: HIGHWAY_FILTER });
    const { container } = render(
      <ActiveFilterChips layers={[layer]} onClearFilter={vi.fn()} />,
    );

    const outerWrapper = container.firstChild as HTMLElement;
    expect(outerWrapper).toHaveClass('pointer-events-none');
    // ml-12 offsets the pill clear of the top-left NavigationControl.
    expect(outerWrapper).toHaveClass('ml-12');
    expect(outerWrapper).not.toHaveClass('max-h-[40vh]');
    expect(outerWrapper).not.toHaveClass('overflow-y-auto');

    const innerScroll = outerWrapper.firstChild as HTMLElement;
    expect(innerScroll).toHaveClass('pointer-events-auto');
    expect(innerScroll).toHaveClass('max-h-[40vh]');
    expect(innerScroll).toHaveClass('overflow-y-auto');
  });

  it('zero chips renders null', () => {
    const { container } = render(
      <ActiveFilterChips layers={[]} onClearFilter={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('chip X calls onClearFilter with the layer id (after expand)', () => {
    const onClearFilter = vi.fn();
    const layer = makeLayer({ id: 'layer-abc', filter: HIGHWAY_FILTER });
    render(<ActiveFilterChips layers={[layer]} onClearFilter={onClearFilter} />);

    expandFilters();
    fireEvent.click(screen.getByRole('button', { name: /clear filter/i }));
    expect(onClearFilter).toHaveBeenCalledTimes(1);
    expect(onClearFilter).toHaveBeenCalledWith('layer-abc');
  });

  it('Clear all clears every active filter (shown only for 2+)', () => {
    const onClearFilter = vi.fn();
    const layers = [
      makeLayer({ id: 'a', dataset_name: 'Roads', filter: HIGHWAY_FILTER }),
      makeLayer({
        id: 'b',
        dataset_name: 'Rails',
        filter: ['==', ['get', 'kind'], 'rail'] as FilterSpecification,
      }),
    ];
    render(<ActiveFilterChips layers={layers} onClearFilter={onClearFilter} />);

    expandFilters();
    fireEvent.click(screen.getByRole('button', { name: /clear all/i }));
    expect(onClearFilter).toHaveBeenCalledTimes(2);
    expect(onClearFilter).toHaveBeenCalledWith('a');
    expect(onClearFilter).toHaveBeenCalledWith('b');
  });

  it('Clear all is not shown for a single filter', () => {
    const layer = makeLayer({ filter: HIGHWAY_FILTER });
    render(<ActiveFilterChips layers={[layer]} onClearFilter={vi.fn()} />);

    expandFilters();
    expect(
      screen.queryByRole('button', { name: /clear all/i }),
    ).not.toBeInTheDocument();
  });

  it('negative control — max-h-[40vh] and overflow-y-auto remain in source (scroll-cap guard)', () => {
    expect(activeFilterChipsSrc).toContain('max-h-[40vh]');
    expect(activeFilterChipsSrc).toContain('overflow-y-auto');
  });
});

// ===========================================================================
// builder-audit #338 FILT-01 / FILT-02 — chip summarizer / canonical-parser
// ===========================================================================

describe('ActiveFilterChips — filter summary (FILT-01 / FILT-02)', () => {
  function renderExpanded(layer: MapLayerResponse) {
    const utils = render(
      <ActiveFilterChips layers={[layer]} onClearFilter={vi.fn()} />,
    );
    expandFilters();
    return utils;
  }

  // FILT-01: every numeric-column comparison the editor builds is wrapped in the
  // nullable-safe ["to-number", ["get", f], fallback] accessor. The chip
  // summarizer previously could not unwrap that and dropped the chip entirely.
  it('FILT-01: renders a chip for a to-number-wrapped numeric comparison (bare)', () => {
    const filter = ['>', ['to-number', ['get', 'population'], -1_000_000_000_000], 5000] as FilterSpecification;
    renderExpanded(makeLayer({ filter }));
    expect(screen.getByText('population > 5000')).toBeInTheDocument();
  });

  it('FILT-01: renders a chip for a to-number numeric comparison inside an "all" combinator', () => {
    const filter = [
      'all',
      ['<=', ['to-number', ['get', 'pop'], 1_000_000_000_000], 100],
    ] as FilterSpecification;
    renderExpanded(makeLayer({ filter }));
    expect(screen.getByText('pop <= 100')).toBeInTheDocument();
  });

  // FILT-02: ["in", value, ["get", f]] is a substring/contains filter. It must be
  // labelled `<field> contains "<value>"`, NOT `<value> in (…)`.
  it('FILT-02: labels a substring/contains filter as `<field> contains "<value>"`', () => {
    const filter = ['in', 'Main', ['get', 'name']] as unknown as FilterSpecification;
    renderExpanded(makeLayer({ filter }));
    expect(screen.getByText('name contains "Main"')).toBeInTheDocument();
  });

  it('renders an in_list chip with a value preview', () => {
    const filter = ['in', ['get', 'kind'], ['literal', ['a', 'b', 'c']]] as unknown as FilterSpecification;
    renderExpanded(makeLayer({ filter }));
    expect(screen.getByText('kind in (a, b, …)')).toBeInTheDocument();
  });

  it('renders no chip (pill absent) for an opaque/advanced filter', () => {
    const filter = ['case', ['==', ['get', 'x'], 1], true, false] as unknown as FilterSpecification;
    const { container } = render(
      <ActiveFilterChips layers={[makeLayer({ filter })]} onClearFilter={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
