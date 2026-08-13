import { render, screen } from '@/test/test-utils';
import type { DatasetResponse } from '@/types/api';
import { DatasetDeleteDialog, deleteDetachesTable } from '../DatasetDeleteDialog';

function makeDataset(overrides: Partial<DatasetResponse> = {}): DatasetResponse {
  return {
    id: 'ds-1',
    title: 'Parcels',
    origin: 'upload',
    ...overrides,
  } as DatasetResponse;
}

describe('deleteDetachesTable', () => {
  it('detaches a registered PostGIS table', () => {
    expect(deleteDetachesTable(makeDataset({ origin: 'postgis' }))).toBe(true);
  });

  it.each(['upload', 'service', 'stac', 'created'] as const)(
    'drops a %s dataset — GeoLens created that table',
    (origin) => {
      expect(deleteDetachesTable(makeDataset({ origin }))).toBe(false);
    },
  );

  it('drops a managed postgis table', () => {
    // The analysis materialize path CTAS's its output and registers it, so it
    // reads as postgis but is GeoLens's to drop.
    const dataset = makeDataset({
      origin: 'postgis',
      origin_ref: { kind: 'postgis', table_name: 'data.buffer_out', managed: true },
    });
    expect(deleteDetachesTable(dataset)).toBe(false);
  });

  it('detaches when the ref carries no managed key', () => {
    // Registrations from before #1452 stored no key at all.
    const dataset = makeDataset({
      origin: 'postgis',
      origin_ref: { kind: 'postgis', table_name: 'data.parcels' },
    });
    expect(deleteDetachesTable(dataset)).toBe(true);
  });
});

describe('DatasetDeleteDialog copy', () => {
  it('promises the table survives for a registered dataset', () => {
    render(
      <DatasetDeleteDialog
        dataset={makeDataset({ origin: 'postgis' })}
        open
        onOpenChange={() => {}}
      />,
    );

    expect(screen.getByText(/stays in the database/i)).toBeInTheDocument();
    expect(screen.queryByText(/including all spatial data/i)).not.toBeInTheDocument();
  });

  it('still warns that the data goes for an uploaded dataset', () => {
    render(
      <DatasetDeleteDialog
        dataset={makeDataset({ origin: 'upload' })}
        open
        onOpenChange={() => {}}
      />,
    );

    expect(screen.getByText(/including all spatial data/i)).toBeInTheDocument();
    expect(screen.queryByText(/stays in the database/i)).not.toBeInTheDocument();
  });
});
