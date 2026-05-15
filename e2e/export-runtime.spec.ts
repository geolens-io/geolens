import {
  test,
  expect,
  type APIRequestContext,
  type APIResponse,
} from '@playwright/test';

type BBox = [number, number, number, number];

type SearchFeatureCollection = {
  features?: Array<{ id?: string }>;
};

type DatasetDetail = {
  id: string;
  title: string;
  geometry_type: string | null;
  feature_count: number | null;
  extent_bbox: number[] | null;
  column_info?: Array<{ name?: string }> | null;
};

type GeoJsonGeometry =
  | {
      type: string;
      coordinates?: unknown;
      geometries?: GeoJsonGeometry[];
    }
  | null
  | undefined;

type GeoJsonFeature = {
  type?: string;
  properties?: Record<string, unknown> | null;
  geometry?: GeoJsonGeometry;
};

type GeoJsonFeatureCollection = {
  type: 'FeatureCollection';
  features: GeoJsonFeature[];
};

type WherePredicate = {
  clause: string;
  propertyKey: string;
  evaluate: (properties: Record<string, unknown>) => boolean;
};

type AuditLogEntry = {
  resource_id?: string | null;
  details?: {
    format?: string | null;
    target_crs?: string | null;
    bbox?: string | null;
    where?: string | null;
  } | null;
};

type AuditLogListResponse = {
  logs?: AuditLogEntry[];
  total?: number;
};

const adminUser = process.env.GEOLENS_ADMIN_USERNAME ?? 'admin';
const adminPass = process.env.GEOLENS_ADMIN_PASSWORD ?? 'admin';

function expectAttachment(response: APIResponse, expectedExtension: string): void {
  const contentDisposition = response.headers()['content-disposition'] ?? '';
  expect(contentDisposition.toLowerCase()).toContain('attachment');
  expect(contentDisposition.toLowerCase()).toContain(expectedExtension.toLowerCase());
}

function listZipEntries(buffer: Buffer): string[] {
  const entries: string[] = [];
  const centralFileHeaderSignature = 0x02014b50;
  let offset = 0;

  while (offset <= buffer.length - 46) {
    const signature = buffer.readUInt32LE(offset);
    if (signature !== centralFileHeaderSignature) {
      offset += 1;
      continue;
    }

    const fileNameLength = buffer.readUInt16LE(offset + 28);
    const extraLength = buffer.readUInt16LE(offset + 30);
    const commentLength = buffer.readUInt16LE(offset + 32);
    const nameStart = offset + 46;
    const nameEnd = nameStart + fileNameLength;

    if (nameEnd > buffer.length) {
      break;
    }

    entries.push(buffer.toString('utf8', nameStart, nameEnd));
    offset = nameEnd + extraLength + commentLength;
  }

  return entries;
}

function parseGeoJsonFeatureCollection(body: Buffer): GeoJsonFeatureCollection {
  const payload = JSON.parse(body.toString('utf8')) as {
    type?: string;
    features?: GeoJsonFeature[];
  };

  expect(payload.type).toBe('FeatureCollection');
  expect(Array.isArray(payload.features)).toBeTruthy();

  return {
    type: 'FeatureCollection',
    features: payload.features ?? [],
  };
}

function toBBox(value: number[] | null | undefined): BBox | null {
  if (!Array.isArray(value) || value.length !== 4) {
    return null;
  }

  const [minX, minY, maxX, maxY] = value;
  if (![minX, minY, maxX, maxY].every((part) => Number.isFinite(part))) {
    return null;
  }

  if (minX >= maxX || minY >= maxY) {
    return null;
  }

  return [minX, minY, maxX, maxY];
}

function collectPositions(node: unknown, sink: Array<[number, number]>): void {
  if (!Array.isArray(node)) {
    return;
  }

  if (
    node.length >= 2 &&
    typeof node[0] === 'number' &&
    Number.isFinite(node[0]) &&
    typeof node[1] === 'number' &&
    Number.isFinite(node[1])
  ) {
    sink.push([node[0], node[1]]);
    return;
  }

  for (const child of node) {
    collectPositions(child, sink);
  }
}

function collectGeometryPositions(
  geometry: GeoJsonGeometry,
  sink: Array<[number, number]>,
): void {
  if (!geometry) {
    return;
  }

  if (geometry.type === 'GeometryCollection') {
    for (const child of geometry.geometries ?? []) {
      collectGeometryPositions(child, sink);
    }
    return;
  }

  collectPositions(geometry.coordinates, sink);
}

function collectFeatureCollectionPositions(
  featureCollection: GeoJsonFeatureCollection,
): Array<[number, number]> {
  const coordinates: Array<[number, number]> = [];

  for (const feature of featureCollection.features) {
    collectGeometryPositions(feature.geometry, coordinates);
  }

  return coordinates;
}

function computeBBoxFromPositions(
  coordinates: Array<[number, number]>,
): BBox | null {
  if (coordinates.length === 0) {
    return null;
  }

  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;

  for (const [x, y] of coordinates) {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }

  if (minX >= maxX || minY >= maxY) {
    return null;
  }

  return [minX, minY, maxX, maxY];
}

function computeFeatureBBox(feature: GeoJsonFeature): BBox | null {
  const coordinates: Array<[number, number]> = [];
  collectGeometryPositions(feature.geometry, coordinates);
  return computeBBoxFromPositions(coordinates);
}

function intersectsBBox(a: BBox, b: BBox): boolean {
  return !(a[2] < b[0] || a[0] > b[2] || a[3] < b[1] || a[1] > b[3]);
}

function hasProjectedCoordinateSemantics(
  coordinates: Array<[number, number]>,
): boolean {
  return coordinates.some(([x, y]) => Math.abs(x) > 180 || Math.abs(y) > 90);
}

function buildInteriorBBox(extent: BBox): BBox {
  const width = extent[2] - extent[0];
  const height = extent[3] - extent[1];

  if (width <= 0 || height <= 0) {
    return extent;
  }

  const insetX = width * 0.2;
  const insetY = height * 0.2;
  const candidate: BBox = [
    extent[0] + insetX,
    extent[1] + insetY,
    extent[2] - insetX,
    extent[3] - insetY,
  ];

  if (candidate[0] >= candidate[2] || candidate[1] >= candidate[3]) {
    return extent;
  }

  return candidate;
}

function serializeBBox(bbox: BBox): string {
  return bbox.map((value) => Number(value.toFixed(6))).join(',');
}

function isSqlIdentifier(value: string): boolean {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(value);
}

function buildWherePredicate(
  baseline: GeoJsonFeatureCollection,
  columnInfo: Array<{ name?: string }> | null | undefined,
): WherePredicate | null {
  const allowedColumns = new Map<string, string>();
  let nonNullFallback:
    | {
        columnName: string;
        propertyKey: string;
      }
    | null = null;

  for (const column of columnInfo ?? []) {
    if (!column.name || !isSqlIdentifier(column.name)) {
      continue;
    }
    allowedColumns.set(column.name.toLowerCase(), column.name);
  }

  for (const feature of baseline.features) {
    const properties = feature.properties ?? {};

    for (const [propertyKey, rawValue] of Object.entries(properties)) {
      const columnName = allowedColumns.get(propertyKey.toLowerCase());
      if (!columnName) {
        continue;
      }

      if (typeof rawValue === 'number' && Number.isFinite(rawValue)) {
        const threshold = Number(rawValue.toFixed(6));
        return {
          clause: `${columnName} >= ${threshold}`,
          propertyKey,
          evaluate: (candidate) => {
            const value = candidate[propertyKey];
            return typeof value === 'number' && Number.isFinite(value) && value >= threshold;
          },
        };
      }

      if (
        rawValue !== null &&
        rawValue !== undefined &&
        nonNullFallback === null
      ) {
        nonNullFallback = {
          columnName,
          propertyKey,
        };
      }
    }
  }

  if (nonNullFallback) {
    return {
      clause: `${nonNullFallback.columnName} IS NOT NULL`,
      propertyKey: nonNullFallback.propertyKey,
      evaluate: (candidate) =>
        candidate[nonNullFallback.propertyKey] !== null &&
        candidate[nonNullFallback.propertyKey] !== undefined,
    };
  }

  return null;
}

async function loginAsAdmin(request: APIRequestContext): Promise<string> {
  // SP-11: route is now /auth/login (no trailing slash), so the POST body is
  // preserved without a 307 redirect and Playwright doesn't trip on the
  // Docker-internal api:8000 hostname.
  const loginResponse = await request.post('/api/auth/login', {
    form: {
      username: adminUser,
      password: adminPass,
    },
  });

  expect(loginResponse.ok()).toBeTruthy();

  const payload = (await loginResponse.json()) as { access_token?: string };
  expect(payload.access_token).toBeTruthy();
  return payload.access_token as string;
}

async function exportDataset(
  request: APIRequestContext,
  authHeader: Record<string, string>,
  datasetId: string,
  query: string,
): Promise<APIResponse> {
  return request.get(`/api/datasets/${datasetId}/export?${query}`, {
    headers: authHeader,
  });
}

async function exportGeoJson(
  request: APIRequestContext,
  authHeader: Record<string, string>,
  datasetId: string,
  queryParts: string[] = [],
): Promise<GeoJsonFeatureCollection> {
  const query = ['format=geojson', ...queryParts].join('&');
  const response = await exportDataset(request, authHeader, datasetId, query);

  if (!response.ok()) {
    const failureBody = await response.text();
    throw new Error(
      `GeoJSON export failed (${response.status()}) for query "${query}": ${failureBody}`,
    );
  }

  expectAttachment(response, '.geojson');

  const body = await response.body();
  expect(body.length).toBeGreaterThan(0);

  return parseGeoJsonFeatureCollection(body);
}

async function resolveRuntimeDataset(
  request: APIRequestContext,
  authHeader: Record<string, string>,
): Promise<{ dataset: DatasetDetail; baseline: GeoJsonFeatureCollection }> {
  async function resolveCandidate(
    datasetId: string,
  ): Promise<{ dataset: DatasetDetail; baseline: GeoJsonFeatureCollection } | null> {
    const detailResponse = await request.get(`/api/datasets/${datasetId}`, {
      headers: authHeader,
    });

    if (!detailResponse.ok()) {
      return null;
    }

    const detail = (await detailResponse.json()) as DatasetDetail;
    if (!detail.geometry_type) {
      return null;
    }

    const baselineResponse = await exportDataset(
      request,
      authHeader,
      detail.id,
      'format=geojson',
    );

    if (!baselineResponse.ok()) {
      return null;
    }

    const baselineBody = await baselineResponse.body();
    if (baselineBody.length === 0) {
      return null;
    }

    const baseline = parseGeoJsonFeatureCollection(baselineBody);
    if (baseline.features.length === 0) {
      return null;
    }

    const baselinePositions = collectFeatureCollectionPositions(baseline);
    if (
      baselinePositions.length === 0 ||
      hasProjectedCoordinateSemantics(baselinePositions)
    ) {
      return null;
    }

    if (
      !toBBox(detail.extent_bbox) &&
      !computeBBoxFromPositions(baselinePositions)
    ) {
      return null;
    }

    if (!buildWherePredicate(baseline, detail.column_info)) {
      return null;
    }

    const projectedResponse = await exportDataset(
      request,
      authHeader,
      detail.id,
      'format=geojson&target_crs=EPSG:3857',
    );

    if (!projectedResponse.ok()) {
      return null;
    }

    const projectedBody = await projectedResponse.body();
    if (projectedBody.length === 0) {
      return null;
    }

    const projected = parseGeoJsonFeatureCollection(projectedBody);
    const projectedPositions = collectFeatureCollectionPositions(projected);
    if (
      projectedPositions.length === 0 ||
      !hasProjectedCoordinateSemantics(projectedPositions)
    ) {
      return null;
    }

    return { dataset: detail, baseline };
  }

  const preferredDatasetId = process.env.E2E_EXPORT_DATASET_ID?.trim();
  if (preferredDatasetId) {
    const preferred = await resolveCandidate(preferredDatasetId);
    if (preferred) {
      return preferred;
    }
    throw new Error(
      `E2E_EXPORT_DATASET_ID=${preferredDatasetId} did not satisfy runtime semantic preconditions`,
    );
  }

  // Trailing slash required — see loginAsAdmin() above for the rationale.
  const searchResponse = await request.get('/api/search/datasets/?limit=10', {
    headers: authHeader,
  });
  expect(searchResponse.ok()).toBeTruthy();

  const searchPayload = (await searchResponse.json()) as SearchFeatureCollection;
  const candidates = searchPayload.features ?? [];
  expect(candidates.length).toBeGreaterThan(0);

  for (const feature of candidates) {
    if (!feature.id) {
      continue;
    }
    const resolved = await resolveCandidate(feature.id);
    if (resolved) {
      return resolved;
    }
  }

  throw new Error(
    'No runtime dataset satisfied format + target_crs semantic preconditions; set E2E_EXPORT_DATASET_ID to a known-good dataset id to skip discovery',
  );
}

test.describe('Runtime export integrity', () => {
  test.describe.configure({ mode: 'serial' });

  let authHeader: Record<string, string>;
  let dataset: DatasetDetail;
  let baseline: GeoJsonFeatureCollection;
  let baselineExtent: BBox;
  let auditDateFrom: string;
  let lastBboxFilter: string | null = null;
  let lastWhereFilter: string | null = null;

  test.beforeAll(async ({ request }) => {
    const token = await loginAsAdmin(request);
    authHeader = { Authorization: `Bearer ${token}` };
    auditDateFrom = new Date(Date.now() - 5_000).toISOString();

    const runtimeContext = await resolveRuntimeDataset(request, authHeader);
    dataset = runtimeContext.dataset;
    baseline = runtimeContext.baseline;

    const extentFromDataset = toBBox(dataset.extent_bbox);
    const extentFromFeatures = computeBBoxFromPositions(
      collectFeatureCollectionPositions(baseline),
    );

    expect(extentFromDataset ?? extentFromFeatures).toBeTruthy();
    baselineExtent = (extentFromDataset ?? extentFromFeatures) as BBox;
  });

  test('exports gpkg with SQLite payload header', async ({ request }) => {
    const response = await exportDataset(request, authHeader, dataset.id, 'format=gpkg');

    expect(response.ok()).toBeTruthy();
    expectAttachment(response, '.gpkg');

    const body = await response.body();
    expect(body.length).toBeGreaterThan(0);
    expect(body.subarray(0, 16).toString('utf8')).toBe('SQLite format 3\u0000');
  });

  test('exports geojson as a FeatureCollection attachment', async ({ request }) => {
    const featureCollection = await exportGeoJson(request, authHeader, dataset.id);
    expect(featureCollection.type).toBe('FeatureCollection');
    expect(Array.isArray(featureCollection.features)).toBeTruthy();
  });

  test('exports shapefile as zip containing shp/shx/dbf members', async ({ request }) => {
    const response = await exportDataset(request, authHeader, dataset.id, 'format=shp');

    expect(response.ok()).toBeTruthy();
    expectAttachment(response, '.zip');

    const body = await response.body();
    expect(body.length).toBeGreaterThan(0);

    const entries = listZipEntries(body).map((entry) => entry.toLowerCase());

    expect(entries.some((entry) => entry.endsWith('.shp'))).toBeTruthy();
    expect(entries.some((entry) => entry.endsWith('.shx'))).toBeTruthy();
    expect(entries.some((entry) => entry.endsWith('.dbf'))).toBeTruthy();
  });

  test('exports csv with header row', async ({ request }) => {
    const response = await exportDataset(request, authHeader, dataset.id, 'format=csv');

    expect(response.ok()).toBeTruthy();
    expectAttachment(response, '.csv');

    const body = await response.body();
    expect(body.length).toBeGreaterThan(0);

    const text = body.toString('utf8').trim();
    const [header] = text.split(/\r?\n/);

    expect(header).toBeTruthy();
    const columns = header.split(',').map((column) => column.trim());
    expect(columns.length).toBeGreaterThan(0);
    expect(columns.some((column) => column.length > 0)).toBeTruthy();
  });

  test('semantic target_crs=EPSG:3857 reprojection changes coordinate space', async ({
    request,
  }) => {
    const projected = await exportGeoJson(request, authHeader, dataset.id, [
      'target_crs=EPSG:3857',
    ]);

    expect(projected.features.length).toBeGreaterThan(0);

    const baselinePositions = collectFeatureCollectionPositions(baseline);
    const projectedPositions = collectFeatureCollectionPositions(projected);
    expect(baselinePositions.length).toBeGreaterThan(0);
    expect(projectedPositions.length).toBeGreaterThan(0);
    expect(hasProjectedCoordinateSemantics(baselinePositions)).toBeFalsy();
    expect(hasProjectedCoordinateSemantics(projectedPositions)).toBeTruthy();
  });

  test('semantic bbox filter returns an intersecting subset', async ({ request }) => {
    const interiorBBox = buildInteriorBBox(baselineExtent);
    lastBboxFilter = serializeBBox(interiorBBox);
    const bboxParam = encodeURIComponent(lastBboxFilter);
    const filtered = await exportGeoJson(request, authHeader, dataset.id, [
      `bbox=${bboxParam}`,
    ]);

    expect(filtered.features.length).toBeLessThanOrEqual(baseline.features.length);

    for (const feature of filtered.features) {
      const featureBBox = computeFeatureBBox(feature);
      expect(featureBBox).toBeTruthy();
      if (featureBBox) {
        expect(intersectsBBox(featureBBox, interiorBBox)).toBeTruthy();
      }
    }
  });

  test('semantic where filter returns a property-matching subset', async ({ request }) => {
    const predicate = buildWherePredicate(baseline, dataset.column_info);
    expect(predicate).toBeTruthy();
    const predicateValue = predicate as WherePredicate;
    lastWhereFilter = predicateValue.clause;

    const filtered = await exportGeoJson(request, authHeader, dataset.id, [
      `where=${encodeURIComponent(predicateValue.clause)}`,
    ]);

    expect(filtered.features.length).toBeLessThanOrEqual(baseline.features.length);

    for (const feature of filtered.features) {
      const properties = feature.properties ?? {};
      expect(predicateValue.evaluate(properties)).toBeTruthy();
    }
  });

  test('audit dataset.export entries include format and semantic parameters', async ({
    request,
  }) => {
    const auditBbox = lastBboxFilter ?? serializeBBox(buildInteriorBBox(baselineExtent));
    const fallbackPredicate = buildWherePredicate(baseline, dataset.column_info);
    expect(fallbackPredicate).toBeTruthy();
    const auditWhereClause =
      lastWhereFilter ?? (fallbackPredicate as WherePredicate).clause;

    lastBboxFilter = auditBbox;
    lastWhereFilter = auditWhereClause;

    const gpkgResponse = await exportDataset(
      request,
      authHeader,
      dataset.id,
      'format=gpkg',
    );
    expect(gpkgResponse.ok()).toBeTruthy();

    const geojsonTargetCrsResponse = await exportDataset(
      request,
      authHeader,
      dataset.id,
      'format=geojson&target_crs=EPSG:3857',
    );
    expect(geojsonTargetCrsResponse.ok()).toBeTruthy();

    const shpBboxResponse = await exportDataset(
      request,
      authHeader,
      dataset.id,
      `format=shp&bbox=${encodeURIComponent(auditBbox)}`,
    );
    expect(shpBboxResponse.ok()).toBeTruthy();

    const csvWhereResponse = await exportDataset(
      request,
      authHeader,
      dataset.id,
      `format=csv&where=${encodeURIComponent(auditWhereClause)}`,
    );
    expect(csvWhereResponse.ok()).toBeTruthy();

    const auditResponse = await request.get(
      `/api/admin/audit-logs/?action=dataset.export&date_from=${encodeURIComponent(auditDateFrom)}&limit=200`,
      {
        headers: authHeader,
      },
    );

    expect(auditResponse.ok()).toBeTruthy();

    const auditPayload = (await auditResponse.json()) as AuditLogListResponse;
    const datasetExportLogs = (auditPayload.logs ?? []).filter(
      (log) => log.resource_id === dataset.id,
    );

    expect(datasetExportLogs.length).toBeGreaterThan(0);

    const formats = new Set(
      datasetExportLogs
        .map((log) => log.details?.format)
        .filter((value): value is string => typeof value === 'string'),
    );

    expect(formats.has('gpkg')).toBeTruthy();
    expect(formats.has('geojson')).toBeTruthy();
    expect(formats.has('shp')).toBeTruthy();
    expect(formats.has('csv')).toBeTruthy();

    expect(
      datasetExportLogs.some(
        (log) => log.details?.target_crs === 'EPSG:3857',
      ),
    ).toBeTruthy();

    expect(lastBboxFilter).toBeTruthy();
    if (lastBboxFilter) {
      expect(
        datasetExportLogs.some((log) => log.details?.bbox === lastBboxFilter),
      ).toBeTruthy();
    }

    expect(lastWhereFilter).toBeTruthy();
    if (lastWhereFilter) {
      expect(
        datasetExportLogs.some((log) => log.details?.where === lastWhereFilter),
      ).toBeTruthy();
    }
  });
});
