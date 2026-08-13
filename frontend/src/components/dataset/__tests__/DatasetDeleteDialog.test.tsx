import { render, screen } from '@/test/test-utils';
import type { DatasetResponse } from '@/types/api';
import {
  DatasetDeleteDialog,
  deleteDescriptionKey,
  deleteDetachesTable,
} from '../DatasetDeleteDialog';

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

describe('deleteDescriptionKey', () => {
  it('promises survival for a healthy registered table', () => {
    const dataset = makeDataset({ origin: 'postgis', source_health: 'healthy' });
    expect(deleteDescriptionKey(dataset)).toBe('deleteDialog.descriptionRegistered');
  });

  it('drops the survival promise when the source table is missing', () => {
    // The backend detects the absent relation and retires the name instead
    // of preserving anything, so there is nothing to promise.
    const dataset = makeDataset({ origin: 'postgis', source_health: 'missing' });
    expect(deleteDescriptionKey(dataset)).toBe(
      'deleteDialog.descriptionRegisteredMissing',
    );
  });

  it.each(['unknown', 'inaccessible'] as const)(
    'keeps the survival promise when health is %s',
    (source_health) => {
      // Neither says the relation is gone; only `missing` does.
      const dataset = makeDataset({ origin: 'postgis', source_health });
      expect(deleteDescriptionKey(dataset)).toBe('deleteDialog.descriptionRegistered');
    },
  );

  it('ignores health entirely for a dataset GeoLens owns', () => {
    const dataset = makeDataset({ origin: 'upload', source_health: 'missing' });
    expect(deleteDescriptionKey(dataset)).toBe('deleteDialog.description');
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

  it('says the surviving table can be registered again', () => {
    // fix(#1452 review round 2): a detached table goes back to being an
    // unregistered table in the data schema, which /ingest/discover/ lists
    // and any upload-permission user can register — the same exposure it had
    // before its owner registered it. Silence about that is the part the
    // owner cannot act on.
    render(
      <DatasetDeleteDialog
        dataset={makeDataset({ origin: 'postgis' })}
        open
        onOpenChange={() => {}}
      />,
    );

    expect(screen.getByText(/register it again/i)).toBeInTheDocument();
    expect(screen.getByText(/drop the table yourself/i)).toBeInTheDocument();
  });

  it('does not promise intact data when the source table is missing', () => {
    render(
      <DatasetDeleteDialog
        dataset={makeDataset({ origin: 'postgis', source_health: 'missing' })}
        open
        onOpenChange={() => {}}
      />,
    );

    expect(screen.getByText(/nothing left to remove/i)).toBeInTheDocument();
    expect(screen.queryByText(/data intact/i)).not.toBeInTheDocument();
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
