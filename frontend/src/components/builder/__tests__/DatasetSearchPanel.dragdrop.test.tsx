/**
 * Phase 1040 Plan 04 — DatasetSearchPanel drag-drop contract tests.
 *
 * Verifies that:
 * 1. Dataset rows render a grip handle with aria-label "Drag to add to map".
 * 2. Basemap rows render a grip handle with the same aria-label.
 * 3. useDraggable is called with ids namespaced as `catalog:{datasetId}` for dataset rows.
 * 4. useDraggable is called with ids namespaced as `catalog-basemap:{id}` for basemap rows.
 *
 * Per PATTERNS.md worker-exit risk note: file-level vi.mock for transitive deps
 * (sonner, react-router) are minimized. We spy on useDraggable at file scope so
 * the spy is restored via vi.restoreAllMocks() in afterEach.
 */

import { render, screen, waitFor } from '@/test/test-utils';
import { DatasetSearchPanel } from '../DatasetSearchPanel';
import { searchDatasets } from '@/api/search';
import { DndContext } from '@dnd-kit/core';
import * as dndCore from '@dnd-kit/core';
import type { OGCRecordResponse, RecordType } from '@/types/api';
import type { ReactNode } from 'react';
import type { BasemapEntry } from '@/api/settings';

// ---------------------------------------------------------------------------
// Minimal mocks (pattern mirrors DatasetSearchPanel.test.tsx)
// ---------------------------------------------------------------------------

vi.mock('@/api/search', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/search')>();
  return { ...actual, searchDatasets: vi.fn() };
});

const mockBasemaps: BasemapEntry[] = [
  { id: 'openfreemap-positron', label: 'Positron', url: 'https://example.com/positron', enabled: true, is_preset: true },
  { id: 'openfreemap-dark', label: 'Dark', url: 'https://example.com/dark', enabled: true, is_preset: true },
];

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: vi.fn(() => ({ data: mockBasemaps })),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) =>
      options?.defaultValue ?? key,
    i18n: { language: 'en' },
  }),
}));

const mockSearchDatasets = vi.mocked(searchDatasets);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeRecord(overrides: {
  id: string;
  title: string;
  recordType?: RecordType;
}): OGCRecordResponse {
  return {
    type: 'Feature',
    id: overrides.id,
    geometry: null,
    bbox: null,
    links: [],
    properties: {
      type: 'Feature',
      title: overrides.title,
      description: `${overrides.title} description`,
      keywords: [],
      created: '2026-01-01T00:00:00Z',
      updated: '2026-01-02T00:00:00Z',
      updated_by_display: null,
      never_edited: false,
      crs: 'EPSG:4326',
      geometry_type: 'POLYGON',
      feature_count: 100,
      contacts: null,
      license: null,
      source_organization: 'City GIS',
      quality_detail: null,
      record_status: 'published',
      record_type: overrides.recordType ?? 'vector_dataset',
      has_quicklook: false,
    },
  };
}

function defaultProps() {
  return {
    onAddDataset: vi.fn(),
    onDuplicateRendering: vi.fn(),
    layers: [],
    isAdding: false,
    basemapStyle: 'openfreemap-positron',
    showBasemapLabels: true,
    basemapConfig: null,
    onBasemapChange: vi.fn(),
    onBasemapLabelsChange: vi.fn(),
    onBasemapConfigChange: vi.fn(),
  } satisfies React.ComponentProps<typeof DatasetSearchPanel>;
}

/** Wrap in DndContext so useDraggable / useDndContext hooks have a provider. */
function renderWithDnd(ui: ReactNode) {
  return render(<DndContext>{ui}</DndContext>);
}

const datasetResponse = {
  type: 'FeatureCollection' as const,
  numberMatched: 1,
  numberReturned: 1,
  features: [makeRecord({ id: 'rec-1', title: 'Test Dataset', recordType: 'vector_dataset' })],
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DatasetSearchPanel — drag-drop wiring (Phase 1040 Plan 04)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearchDatasets.mockResolvedValue(datasetResponse);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('dataset row renders a grip handle with aria-label "Drag to add to map"', async () => {
    renderWithDnd(<DatasetSearchPanel {...defaultProps()} />);

    // Wait for search results to load
    await waitFor(() => {
      expect(screen.getByText('Test Dataset')).toBeInTheDocument();
    });

    // Grip handle must have the correct aria-label for keyboard discoverability
    const handles = screen.getAllByLabelText('Drag to add to map');
    expect(handles.length).toBeGreaterThanOrEqual(1);
    expect(handles[0]).toBeInTheDocument();
  });

  it('useDraggable is called with id namespaced as catalog:{datasetId} for dataset rows', async () => {
    // Spy on the real useDraggable so we can inspect call arguments
    const useDraggableSpy = vi.spyOn(dndCore, 'useDraggable');

    renderWithDnd(<DatasetSearchPanel {...defaultProps()} />);

    await waitFor(() => {
      expect(screen.getByText('Test Dataset')).toBeInTheDocument();
    });

    // At least one call should have an id matching catalog:rec-1
    const calls = useDraggableSpy.mock.calls;
    const datasetCall = calls.find((args) => {
      const id = String(args[0]?.id ?? '');
      return id === 'catalog:rec-1';
    });
    expect(datasetCall).toBeDefined();
  });

  it('dataset draggable data has source=catalog and correct datasetId', async () => {
    const useDraggableSpy = vi.spyOn(dndCore, 'useDraggable');

    renderWithDnd(<DatasetSearchPanel {...defaultProps()} />);

    await waitFor(() => {
      expect(screen.getByText('Test Dataset')).toBeInTheDocument();
    });

    const calls = useDraggableSpy.mock.calls;
    const datasetCall = calls.find((args) => String(args[0]?.id ?? '').startsWith('catalog:'));
    expect(datasetCall).toBeDefined();
    const data = datasetCall![0].data as { source: string; datasetId: string; recordType: string };
    expect(data.source).toBe('catalog');
    expect(data.datasetId).toBe('rec-1');
    expect(data.recordType).toBe('vector_dataset');
  });

  it('useDraggable is called with id namespaced as catalog-basemap:{id} for basemap rows', async () => {
    const useDraggableSpy = vi.spyOn(dndCore, 'useDraggable');

    renderWithDnd(<DatasetSearchPanel {...defaultProps()} />);

    // Switch to the Basemap tab
    const basemapTab = await screen.findByRole('radio', { name: 'Basemap' });
    basemapTab.click();

    await waitFor(() => {
      expect(screen.getByText('Positron')).toBeInTheDocument();
    });

    const calls = useDraggableSpy.mock.calls;
    // At least one call must use the catalog-basemap: prefix (blank + positron + dark are all rendered)
    const basemapCalls = calls.filter((args) => {
      const id = String(args[0]?.id ?? '');
      return id.startsWith('catalog-basemap:');
    });
    expect(basemapCalls.length).toBeGreaterThanOrEqual(1);
    // Positron must be among them (catalog-basemap:openfreemap-positron)
    const positronCall = calls.find((args) =>
      String(args[0]?.id ?? '') === 'catalog-basemap:openfreemap-positron',
    );
    expect(positronCall).toBeDefined();
  });

  it('basemap draggable data has source=catalog and recordType=basemap', async () => {
    const useDraggableSpy = vi.spyOn(dndCore, 'useDraggable');

    renderWithDnd(<DatasetSearchPanel {...defaultProps()} />);

    const basemapTab = await screen.findByRole('radio', { name: 'Basemap' });
    basemapTab.click();

    await waitFor(() => {
      expect(screen.getByText('Positron')).toBeInTheDocument();
    });

    const calls = useDraggableSpy.mock.calls;
    const basemapCall = calls.find((args) =>
      String(args[0]?.id ?? '').startsWith('catalog-basemap:'),
    );
    expect(basemapCall).toBeDefined();
    const data = basemapCall![0].data as { source: string; recordType: string };
    expect(data.source).toBe('catalog');
    expect(data.recordType).toBe('basemap');
  });

  it('basemap row grip handle has aria-label "Drag to add to map"', async () => {
    renderWithDnd(<DatasetSearchPanel {...defaultProps()} />);

    const basemapTab = await screen.findByRole('radio', { name: 'Basemap' });
    basemapTab.click();

    await waitFor(() => {
      expect(screen.getByText('Positron')).toBeInTheDocument();
    });

    const handles = screen.getAllByLabelText('Drag to add to map');
    expect(handles.length).toBeGreaterThanOrEqual(1);
  });
});
