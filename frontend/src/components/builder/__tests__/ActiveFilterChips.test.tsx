/**
 * MAP-20 — ActiveFilterChips regression tests
 *
 * Verifies:
 * 1. The chip container has max-h-[40vh] + overflow-y-auto so at ≤800px (600px
 *    viewport height) the filter column cannot grow past 240px and collide with
 *    the bottom-left MeasurementPlugin.
 * 2. Zero chips renders null (return null preserved).
 * 3. One chip renders the label and layer name.
 * 4. Clicking X calls onClearFilter with the correct layer id.
 * 5. Source-text negative-control: max-h-[40vh] + overflow-y-auto appear in the
 *    source file (guards against future "CSS cleanup" PRs removing either class).
 *
 * Uses Vite ?raw import for source-text test — same pattern as
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

// ===========================================================================
// Tests
// ===========================================================================

describe('ActiveFilterChips — MAP-20 layout constraints', () => {
  it('MAP-20: outer wrapper has pointer-events-none; inner scroll container has max-h-[40vh] + overflow-y-auto + pointer-events-auto (WR-01 fix)', () => {
    const layer = makeLayer({ filter: HIGHWAY_FILTER });
    const { container } = render(
      <ActiveFilterChips layers={[layer]} onClearFilter={vi.fn()} />,
    );

    // WR-01 structure: outer passthrough wrapper (pointer-events-none) wraps an inner
    // scroll container (pointer-events-auto + overflow classes) so wheel/touch-scroll
    // events reach the inner div while map drag events pass through outer gaps.
    const outerWrapper = container.firstChild as HTMLElement;
    expect(outerWrapper).toHaveClass('pointer-events-none');
    // outer wrapper should NOT carry the scroll classes — those live on the inner div
    expect(outerWrapper).not.toHaveClass('max-h-[40vh]');
    expect(outerWrapper).not.toHaveClass('overflow-y-auto');

    const innerScroll = outerWrapper.firstChild as HTMLElement;
    expect(innerScroll).toHaveClass('pointer-events-auto');
    expect(innerScroll).toHaveClass('max-h-[40vh]');
    expect(innerScroll).toHaveClass('overflow-y-auto');
  });

  it('zero chips renders null (preserves current behavior)', () => {
    const { container } = render(
      <ActiveFilterChips layers={[]} onClearFilter={vi.fn()} />,
    );
    // return null → container is empty
    expect(container.firstChild).toBeNull();
  });

  it('1 chip renders the chip label and the layer name', () => {
    const layer = makeLayer({ dataset_name: 'Roads', filter: HIGHWAY_FILTER });
    render(<ActiveFilterChips layers={[layer]} onClearFilter={vi.fn()} />);

    // Filter label: '== "highway"' → summarized as 'class == "highway"'
    expect(screen.getByText('class == "highway"')).toBeInTheDocument();
    // Layer name rendered uppercase via font-mono tracking-wider class
    expect(screen.getByText(/roads/i)).toBeInTheDocument();
  });

  it('chip X button calls onClearFilter with the layer id', () => {
    const onClearFilter = vi.fn();
    const layer = makeLayer({ id: 'layer-abc', filter: HIGHWAY_FILTER });
    render(<ActiveFilterChips layers={[layer]} onClearFilter={onClearFilter} />);

    const clearBtn = screen.getByRole('button', { name: /clear filter/i });
    fireEvent.click(clearBtn);
    expect(onClearFilter).toHaveBeenCalledTimes(1);
    expect(onClearFilter).toHaveBeenCalledWith('layer-abc');
  });

  it('MAP-20 negative control — max-h-[40vh] and overflow-y-auto appear in source (CSS-cleanup guard)', () => {
    // If a future PR removes one of these classes from ActiveFilterChips.tsx,
    // this test fails — preventing silent regression of the collision avoidance.
    expect(activeFilterChipsSrc).toContain('max-h-[40vh]');
    expect(activeFilterChipsSrc).toContain('overflow-y-auto');
  });
});

// ===========================================================================
// builder-audit #338 FILT-01 / FILT-02 — chip summarizer / canonical-parser fixes
// ===========================================================================

describe('ActiveFilterChips — filter summary (FILT-01 / FILT-02)', () => {
  // FILT-01: every numeric-column comparison the editor builds is wrapped in the
  // nullable-safe ["to-number", ["get", f], fallback] accessor. The chip
  // summarizer previously could not unwrap that and dropped the chip entirely.
  it('FILT-01: renders a chip for a to-number-wrapped numeric comparison (bare)', () => {
    const filter = ['>', ['to-number', ['get', 'population'], -1_000_000_000_000], 5000] as FilterSpecification;
    const layer = makeLayer({ filter });
    render(<ActiveFilterChips layers={[layer]} onClearFilter={vi.fn()} />);
    // Numeric RHS rendered without quotes; field unwrapped from the to-number node.
    expect(screen.getByText('population > 5000')).toBeInTheDocument();
  });

  it('FILT-01: renders a chip for a to-number numeric comparison inside an "all" combinator', () => {
    const filter = [
      'all',
      ['<=', ['to-number', ['get', 'pop'], 1_000_000_000_000], 100],
    ] as FilterSpecification;
    const layer = makeLayer({ filter });
    render(<ActiveFilterChips layers={[layer]} onClearFilter={vi.fn()} />);
    expect(screen.getByText('pop <= 100')).toBeInTheDocument();
  });

  // FILT-02: ["in", value, ["get", f]] is a substring/contains filter. It must be
  // labelled `<field> contains "<value>"`, NOT `<value> in (…)` (the prior dead
  // branch produced the wrong label because the literal-list branch ran first).
  it('FILT-02: labels a substring/contains filter as `<field> contains "<value>"`', () => {
    const filter = ['in', 'Main', ['get', 'name']] as unknown as FilterSpecification;
    const layer = makeLayer({ filter });
    render(<ActiveFilterChips layers={[layer]} onClearFilter={vi.fn()} />);
    expect(screen.getByText('name contains "Main"')).toBeInTheDocument();
  });

  it('renders an in_list chip with a value preview', () => {
    const filter = ['in', ['get', 'kind'], ['literal', ['a', 'b', 'c']]] as unknown as FilterSpecification;
    const layer = makeLayer({ filter });
    render(<ActiveFilterChips layers={[layer]} onClearFilter={vi.fn()} />);
    expect(screen.getByText('kind in (a, b, …)')).toBeInTheDocument();
  });

  it('renders no chip for an opaque/advanced filter', () => {
    const filter = ['case', ['==', ['get', 'x'], 1], true, false] as unknown as FilterSpecification;
    const layer = makeLayer({ filter });
    const { container } = render(<ActiveFilterChips layers={[layer]} onClearFilter={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });
});
