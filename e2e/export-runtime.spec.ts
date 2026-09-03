import {
  test,
  expect,
  type APIRequestContext,
  type APIResponse,
} from '@playwright/test';

type BBox = [number, number, number, number];

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

type OwnedDataset = {
  id: string;
  title: string;
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

  if (minX > maxX || minY > maxY) {
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

  if (minX > maxX || minY > maxY) {
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

// fix(review #1792): pads a bbox (or a degenerate single-point bbox) out by
// `epsilon` on every side, guaranteeing a non-degenerate span (the API
// rejects a zero-width/height bbox, per buildInteriorBBox's own comment)
// while staying tight enough to exclude sibling features in a small fixture.
function padBBox(bbox: BBox, epsilon: number): BBox {
  return [bbox[0] - epsilon, bbox[1] - epsilon, bbox[2] + epsilon, bbox[3] + epsilon];
}

function hasProjectedCoordinateSemantics(
  coordinates: Array<[number, number]>,
): boolean {
  return coordinates.some(([x, y]) => Math.abs(x) > 180 || Math.abs(y) > 90);
}

function buildInteriorBBox(extent: BBox): BBox {
  const width = extent[2] - extent[0];
  const height = extent[3] - extent[1];

  // The API deliberately requires a non-degenerate latitude span. Runtime
  // fixtures can contain a single point (or a sub-microdegree extent that
  // collapses when serializeBBox rounds to six decimals), so first pad each
  // axis to a stable envelope around its center.
  const minimumSpan = 0.0001;
  const centerX = (extent[0] + extent[2]) / 2;
  const centerY = (extent[1] + extent[3]) / 2;
  const paddedExtent: BBox = [
    width < minimumSpan ? centerX - minimumSpan / 2 : extent[0],
    height < minimumSpan ? centerY - minimumSpan / 2 : extent[1],
    width < minimumSpan ? centerX + minimumSpan / 2 : extent[2],
    height < minimumSpan ? centerY + minimumSpan / 2 : extent[3],
  ];

  const paddedWidth = paddedExtent[2] - paddedExtent[0];
  const paddedHeight = paddedExtent[3] - paddedExtent[1];

  const insetX = paddedWidth * 0.2;
  const insetY = paddedHeight * 0.2;
  const candidate: BBox = [
    paddedExtent[0] + insetX,
    paddedExtent[1] + insetY,
    paddedExtent[2] - insetX,
    paddedExtent[3] - insetY,
  ];

  if (candidate[0] >= candidate[2] || candidate[1] >= candidate[3]) {
    return paddedExtent;
  }

  return candidate;
}

function serializeBBox(bbox: BBox): string {
  return bbox.map((value) => Number(value.toFixed(6))).join(',');
}

// fix(review #1792 round 5): a number string-interpolated directly (e.g.
// `${threshold}` below) goes through JS's default Number-to-string
// conversion, which switches to scientific notation below 1e-6 or at/above
// 1e21 -- (1e-7).toString() === '1e-7', (1e21).toString() === '1e+21'. The
// backend's -where clause parser (validate_where_clause) reads that `e` as
// a bare SQL identifier, not part of a numeric literal, and rejects the
// clause. Expand scientific notation back to a plain decimal string before
// it reaches a clause. Pure string/digit manipulation on the exact digits
// JS already chose -- never touches the value itself, so it can never round
// (in particular, never rounds above the observed maximum the round-2 fix
// depends on).
function formatNumericLiteral(value: number): string {
  const raw = String(value);
  const match = raw.match(/^(-?)(\d+)(?:\.(\d+))?e([+-]\d+)$/i);
  if (!match) {
    return raw;
  }

  const [, sign, intDigits, fracDigits = '', expStr] = match;
  const exponent = Number(expStr);
  const digits = intDigits + fracDigits;
  // Where the decimal point lands once the exponent shifts it, counted from
  // the start of `digits` (intDigits followed directly by fracDigits).
  const pointPos = intDigits.length + exponent;

  let expanded: string;
  if (pointPos <= 0) {
    // |value| < 1: leading zeros after the point, then the digits.
    expanded = `0.${'0'.repeat(-pointPos)}${digits}`;
  } else if (pointPos >= digits.length) {
    // Large integer: pad the digits out with trailing zeros.
    expanded = digits + '0'.repeat(pointPos - digits.length);
  } else {
    // The point lands inside the digit string.
    expanded = `${digits.slice(0, pointPos)}.${digits.slice(pointPos)}`;
  }

  if (expanded.includes('.')) {
    expanded = expanded.replace(/0+$/, '').replace(/\.$/, '');
  }

  return sign + expanded;
}

function isSqlIdentifier(value: string): boolean {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(value);
}

// fix(review #1792 round 6): JSON.parse loses precision above
// Number.MAX_SAFE_INTEGER -- not just fractional rounding, the parsed
// integer can differ from the true value entirely (9007199254740995
// becomes 9007199254740996, a database value that may not even exist).
// This recovers the EXACT digits the server actually returned for one
// specific property key, straight from the raw response text, without a
// general big-number-safe JSON parser: a targeted regex over the raw
// bytes rather than a reviver over an already-lossy parse.
function extractRawIntegerValues(rawText: string, propertyKey: string): bigint[] {
  const escapedKey = propertyKey.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  // `(?![\d.eE])` requires the digit run to end here -- excludes matching
  // just the integer prefix of a larger float/exponential token (e.g. the
  // "123" in "123.456" or "123e10"), which is not this function's problem
  // to solve (see the floating-column branch in buildWherePredicate).
  const pattern = new RegExp(`"${escapedKey}"\\s*:\\s*(-?\\d+)(?![\\d.eE])`, 'g');
  const values: bigint[] = [];
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(rawText)) !== null) {
    values.push(BigInt(match[1]));
  }
  return values;
}

function buildWherePredicate(
  baseline: GeoJsonFeatureCollection,
  columnInfo: Array<{ name?: string }> | null | undefined,
  baselineRawText?: string,
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

  // fix(#1778): the threshold used to come from the FIRST feature's numeric
  // value, returned on the spot. The seeded runtime fixture inserts
  // value=10,20,30 in that order, so the clause was always `value >= 10` —
  // every seeded row satisfies it, so a `where` param silently dropped
  // (wrong column, inverted operator, ignored entirely) produced the same
  // full result set as a correctly-applied filter. Scan every feature for
  // the first numeric column and use its MAXIMUM observed value instead, so
  // the clause is genuinely selective against the seeded fixture.
  let numericColumn: { columnName: string; propertyKey: string } | null = null;
  let maxValue = -Infinity;

  for (const feature of baseline.features) {
    const properties = feature.properties ?? {};

    for (const [propertyKey, rawValue] of Object.entries(properties)) {
      const columnName = allowedColumns.get(propertyKey.toLowerCase());
      if (!columnName) {
        continue;
      }

      if (typeof rawValue === 'number' && Number.isFinite(rawValue)) {
        if (!numericColumn) {
          numericColumn = { columnName, propertyKey };
        }
        if (numericColumn.propertyKey === propertyKey) {
          maxValue = Math.max(maxValue, rawValue);
        }
        continue;
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

  if (numericColumn) {
    // fix(review #1792 round 2): Number(maxValue.toFixed(6)) can round the
    // observed maximum UP (1.2345678 -> 1.234568), which would make
    // `column >= threshold` exclude the very row that produced the maximum
    // -- the clause would then match nothing. The auto-seeded runtime
    // fixture's values (10/20/30) are integers, so toFixed(6) never
    // triggered this, but the E2E_EXPORT_DATASET_ID escape hatch can point
    // at a dataset with fractional column values. Use the exact observed
    // maximum instead of a rounded one: `value >= value` is always true for
    // the identical float, so the row that produced it can never be
    // excluded by this comparison -- for a value JS's own JSON.parse
    // rendered exactly, which is not guaranteed (see below).
    const { columnName, propertyKey } = numericColumn;

    // fix(review #1792 round 6): `maxValue` came from JSON.parse, which for
    // a BIGINT above Number.MAX_SAFE_INTEGER does not just lose fractional
    // precision -- it can round to a DIFFERENT integer entirely (e.g.
    // 9007199254740995 becomes 9007199254740996), so `maxValue` here may
    // not be a value the database ever returned, and `column >= maxValue`
    // could exclude the true maximal row. A high-precision NUMERIC/float
    // has the same failure mode in miniature (small relative rounding in
    // the low-order digits). Two different margins, because the two cases
    // need different treatment: a BIGINT is a whole number with no value
    // between v-1 and v, so once we know the TRUE integer maximum exactly
    // (recovered from the raw response text, since JSON.parse already threw
    // that away), subtracting exactly 1 is both necessary and sufficient.
    // A float has no such gap to exploit, so a proportional margin below
    // the (still only approximately correct) parsed value is used instead
    // -- 1e-9 relative is far larger than a double's ~1e-15 relative
    // rounding error, so it comfortably covers it without needing the raw
    // text at all.
    //
    // `Number.isInteger` alone cannot tell a BIGINT column from a NUMERIC/
    // float column that currently happens to hold a whole number -- a
    // double this large has no fractional bits left to distinguish them
    // with. Postgres's actual BIGINT range (+/-2^63-1) can, though: a
    // magnitude beyond it cannot possibly be a real BIGINT value, so it is
    // routed to the proportional-margin path instead (e.g. the
    // 1.2345678901234567e20 pin below, which is a whole JS double but far
    // past BIGINT's ~9.22e18 ceiling).
    const BIGINT_MAX_MAGNITUDE = 9223372036854775807; // Postgres bigint upper bound, 2^63 - 1
    let clauseValue: string;
    let evaluateThreshold: number;

    // fix(review #1792 round 7): a raw token that fails the regex's
    // `(?![\d.eE])` lookahead -- e.g. a NUMERIC maximum serialized as
    // "9007199254740995.1", which JSON.parse rounds to the unsafe integer
    // 9007199254740996 -- used to fall through to the `rawValues.length ===
    // 0` branch below and emit that rounded-UP parsed value verbatim. That
    // value can be strictly GREATER than the true maximum, so
    // `column >= clauseValue` could exclude the very row that produced it.
    // Exact BigInt recovery failing means the value was never an exact
    // integer literal in the response text at all, which is exactly the
    // condition the proportional-margin (epsilon) path below exists to
    // handle -- so route there instead of using the unchanged parsed value.
    let exactBigIntThreshold: bigint | null = null;
    if (
      Number.isInteger(maxValue) &&
      !Number.isSafeInteger(maxValue) &&
      Math.abs(maxValue) <= BIGINT_MAX_MAGNITUDE &&
      baselineRawText
    ) {
      const rawValues = extractRawIntegerValues(baselineRawText, propertyKey);
      if (rawValues.length > 0) {
        const trueMax = rawValues.reduce((a, b) => (b > a ? b : a));
        exactBigIntThreshold = trueMax - 1n;
      }
    }

    if (exactBigIntThreshold !== null) {
      clauseValue = exactBigIntThreshold.toString();
      evaluateThreshold = Number(exactBigIntThreshold);
    } else if (Number.isSafeInteger(maxValue)) {
      // A safe integer's JSON round-trip is exact; nothing to correct.
      clauseValue = formatNumericLiteral(maxValue);
      evaluateThreshold = maxValue;
    } else {
      const margin = Math.abs(maxValue) * 1e-9 + Number.EPSILON;
      const safeThreshold = maxValue - margin;
      clauseValue = formatNumericLiteral(safeThreshold);
      evaluateThreshold = safeThreshold;
    }

    return {
      clause: `${columnName} >= ${clauseValue}`,
      propertyKey,
      evaluate: (candidate) => {
        const value = candidate[propertyKey];
        return typeof value === 'number' && Number.isFinite(value) && value >= evaluateThreshold;
      },
    };
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

async function seedRuntimeDataset(
  request: APIRequestContext,
  authHeader: Record<string, string>,
): Promise<OwnedDataset> {
  const title = `E2E Runtime Export ${Date.now()}`;
  const fixture = {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [-100, 30] },
        properties: { name: 'west', value: 10 },
      },
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [-95, 35] },
        properties: { name: 'center', value: 20 },
      },
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [-90, 40] },
        properties: { name: 'east', value: 30 },
      },
    ],
  };

  const uploadResponse = await request.post('/api/ingest/upload', {
    headers: authHeader,
    multipart: {
      file: {
        name: 'runtime-export.geojson',
        mimeType: 'application/geo+json',
        buffer: Buffer.from(JSON.stringify(fixture)),
      },
    },
  });
  if (!uploadResponse.ok()) {
    throw new Error(`Runtime export fixture upload failed (${uploadResponse.status()})`);
  }

  const uploadPayload = (await uploadResponse.json()) as { job_id?: string };
  if (!uploadPayload.job_id) {
    throw new Error('Runtime export fixture upload did not return a job id');
  }

  const commitResponse = await request.post(
    `/api/ingest/commit/${uploadPayload.job_id}`,
    {
      headers: authHeader,
      data: { title },
    },
  );
  if (!commitResponse.ok()) {
    throw new Error(`Runtime export fixture commit failed (${commitResponse.status()})`);
  }

  for (let attempt = 0; attempt < 60; attempt += 1) {
    const jobResponse = await request.get(`/api/jobs/${uploadPayload.job_id}`, {
      headers: authHeader,
    });
    if (jobResponse.ok()) {
      const job = (await jobResponse.json()) as {
        status?: string;
        dataset_id?: string | null;
      };
      if (
        job.dataset_id &&
        ['complete', 'completed', 'succeeded'].includes(job.status ?? '')
      ) {
        return { id: job.dataset_id, title };
      }
      if (['failed', 'error'].includes(job.status ?? '')) {
        throw new Error(`Runtime export fixture ingest failed with status ${job.status}`);
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }

  throw new Error('Runtime export fixture ingest did not complete in time');
}

async function deleteRuntimeDataset(
  request: APIRequestContext,
  authHeader: Record<string, string>,
  dataset: OwnedDataset,
): Promise<void> {
  const response = await request.delete(`/api/datasets/${dataset.id}`, {
    headers: authHeader,
    data: { confirm_title: dataset.title },
  });
  if (!response.ok() && response.status() !== 404) {
    throw new Error(`Runtime export fixture cleanup failed (${response.status()})`);
  }
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
  datasetId: string,
): Promise<{ dataset: DatasetDetail; baseline: GeoJsonFeatureCollection; baselineRawText: string }> {
  async function resolveCandidate(
    datasetId: string,
  ): Promise<{ dataset: DatasetDetail; baseline: GeoJsonFeatureCollection; baselineRawText: string } | null> {
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
    // fix(review #1792 round 6): kept alongside the parsed `baseline` so
    // buildWherePredicate can recover exact BIGINT digits JSON.parse
    // already discarded -- see extractRawIntegerValues.
    const baselineRawText = baselineBody.toString('utf8');

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

    if (!buildWherePredicate(baseline, detail.column_info, baselineRawText)) {
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

    return { dataset: detail, baseline, baselineRawText };
  }

  const resolved = await resolveCandidate(datasetId);
  if (resolved) {
    return resolved;
  }

  throw new Error(
    `Runtime export dataset ${datasetId} did not satisfy format and target_crs semantic preconditions`,
  );
}

// fix(review #1792 round 5): pure-logic pin for formatNumericLiteral,
// independent of any live request -- the two inputs are exactly where
// JS's Number-to-string conversion switches to scientific notation (see
// the function's own comment).
test.describe('formatNumericLiteral', () => {
  test('expands a value just below the small-number scientific-notation threshold', () => {
    expect(String(1e-7)).toBe('1e-7'); // sanity: this is the input JS would otherwise emit as-is
    expect(formatNumericLiteral(1e-7)).toBe('0.0000001');
  });

  test('expands a value at the large-number scientific-notation threshold', () => {
    expect(String(1e21)).toBe('1e+21'); // sanity: this is the input JS would otherwise emit as-is
    expect(formatNumericLiteral(1e21)).toBe('1000000000000000000000');
  });

  test('leaves values JS already renders as plain decimals untouched', () => {
    expect(formatNumericLiteral(1e-6)).toBe('0.000001');
    expect(formatNumericLiteral(1e20)).toBe('100000000000000000000');
    expect(formatNumericLiteral(30)).toBe('30');
    expect(formatNumericLiteral(-1e-7)).toBe('-0.0000001');
  });
});

// fix(review #1792 round 6): pure-logic pin for buildWherePredicate's
// threshold computation, independent of any live request. Covers the two
// precision-loss shapes JSON.parse can introduce: a BIGINT above
// Number.MAX_SAFE_INTEGER (parses to a DIFFERENT integer, not just a
// rounded one) and a high-precision NUMERIC/float whose magnitude is
// beyond even BIGINT's range (so it cannot be recovered exactly from raw
// text the way a BIGINT can -- see buildWherePredicate's own comment for
// why the two need different treatment).
test.describe('buildWherePredicate precision', () => {
  const columnInfo = [{ name: 'value' }];

  function syntheticBaseline(propertyValue: number): GeoJsonFeatureCollection {
    return {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: { value: propertyValue },
          geometry: null,
        },
      ],
    };
  }

  test('an unsafe BIGINT-range integer gets a threshold strictly below the true value', () => {
    // A string, not a number literal: 9007199254740995 written directly in
    // this file's own source would be rounded by the SAME double-precision
    // limit this test exists to work around, before the test ever ran.
    const trueValueText = '9007199254740995';
    const trueValueBigInt = BigInt(trueValueText);

    // What a real response body parses to -- JSON.parse rounds this to a
    // DIFFERENT integer (...996), which is what buildWherePredicate's own
    // scan of `baseline.features` would observe as `maxValue`.
    const parsedValue = JSON.parse(trueValueText) as number;
    expect(Number.isSafeInteger(parsedValue)).toBe(false);
    expect(BigInt(parsedValue)).not.toBe(trueValueBigInt);

    const baselineRawText = `{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"value":${trueValueText}},"geometry":null}]}`;
    const predicate = buildWherePredicate(
      syntheticBaseline(parsedValue),
      columnInfo,
      baselineRawText,
    );

    expect(predicate).toBeTruthy();
    const clauseValueText = predicate!.clause.split('>=')[1].trim();
    // Exact BigInt comparison: this is the whole point of the raw-text
    // recovery, so tolerate no float round-trip here either.
    expect(BigInt(clauseValueText) < trueValueBigInt).toBe(true);
  });

  test('a NUMERIC-like value beyond BIGINT range gets a threshold strictly below the true value', () => {
    const trueValue = 1.2345678901234567e20;
    // Sanity: this is genuinely past what BIGINT (2^63-1 =~ 9.22e18) can
    // hold, and a whole number as far as JS's own double precision can
    // tell -- exactly the case that can't be told apart from a BIGINT by
    // Number.isInteger alone, and needs the magnitude check to route to
    // the proportional-margin path instead of the (inapplicable) BigInt one.
    expect(Number.isInteger(trueValue)).toBe(true);
    expect(Number.isSafeInteger(trueValue)).toBe(false);

    const predicate = buildWherePredicate(syntheticBaseline(trueValue), columnInfo);

    expect(predicate).toBeTruthy();
    const clauseValue = Number(predicate!.clause.split('>=')[1].trim());
    expect(clauseValue).toBeLessThan(trueValue);
  });

  test('a raw decimal token past MAX_SAFE_INTEGER falls back to the epsilon margin, not the rounded parse', () => {
    // fix(review #1792 round 7): a NUMERIC column can genuinely hold a
    // fractional value out here, e.g. "9007199254740995.1" -- the regex in
    // extractRawIntegerValues deliberately excludes this token (its
    // `(?![\d.eE])` lookahead requires the digit run to end cleanly, not
    // run into a `.`), so raw-text recovery finds nothing for it. What
    // JSON.parse itself does to it is the trap: at this magnitude doubles
    // are spaced 2 apart, so parsing silently ROUNDS UP to the next whole
    // double (9007199254740996), which is strictly GREATER than the true
    // value. Emitting that rounded value unchanged as the threshold would
    // make `column >= threshold` exclude the very row that produced it.
    const trueValueText = '9007199254740995.1';
    const trueValue = Number(trueValueText);
    expect(Number.isInteger(trueValue)).toBe(true);
    expect(Number.isSafeInteger(trueValue)).toBe(false);
    // Confirms the rounding actually happened, i.e. this pin exercises the
    // failure mode it claims to: the parsed double is NOT the true value.
    // Comparing as Number would compare two equally-rounded doubles (the
    // ".1" literal and its own truncated integer part land on the SAME
    // double at this magnitude) -- BigInt on the integer-valued `trueValue`
    // is exact, so it correctly shows the parse rounded past the true
    // integer part rather than merely dropping the fraction.
    expect(BigInt(trueValue) > BigInt(trueValueText.split('.')[0])).toBe(true);

    const baselineRawText = `{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"value":${trueValueText}},"geometry":null}]}`;
    const predicate = buildWherePredicate(
      syntheticBaseline(trueValue),
      columnInfo,
      baselineRawText,
    );

    expect(predicate).toBeTruthy();
    const clauseValue = Number(predicate!.clause.split('>=')[1].trim());
    expect(clauseValue).toBeLessThan(trueValue);
  });
});

test.describe('Runtime export integrity', () => {
  test.describe.configure({ mode: 'serial' });

  let authHeader: Record<string, string>;
  let dataset: DatasetDetail;
  let baseline: GeoJsonFeatureCollection;
  let baselineRawText: string;
  let baselineExtent: BBox;
  let auditDateFrom: string;
  let lastBboxFilter: string | null = null;
  let lastWhereFilter: string | null = null;
  let ownedDataset: OwnedDataset | null = null;

  test.beforeAll(async ({ request }) => {
    // fix(review #1792 round 3): seedRuntimeDataset's own ingest-and-poll
    // loop can run for up to 60s (its `for (let attempt = 0; attempt < 60;
    // attempt += 1)` below), which is Playwright's default hook timeout
    // with nothing left over for the login and resolveRuntimeDataset calls
    // this hook also makes. Give this hook real margin.
    test.setTimeout(120_000);

    const token = await loginAsAdmin(request);
    authHeader = { Authorization: `Bearer ${token}` };
    auditDateFrom = new Date(Date.now() - 5_000).toISOString();

    const preferredDatasetId = process.env.E2E_EXPORT_DATASET_ID?.trim();
    if (!preferredDatasetId) {
      ownedDataset = await seedRuntimeDataset(request, authHeader);
    }
    const runtimeDatasetId = preferredDatasetId ?? ownedDataset?.id;
    if (!runtimeDatasetId) {
      throw new Error('Runtime export fixture setup did not produce a dataset id');
    }

    const runtimeContext = await resolveRuntimeDataset(
      request,
      authHeader,
      runtimeDatasetId,
    );
    dataset = runtimeContext.dataset;
    baseline = runtimeContext.baseline;
    baselineRawText = runtimeContext.baselineRawText;

    const extentFromDataset = toBBox(dataset.extent_bbox);
    const extentFromFeatures = computeBBoxFromPositions(
      collectFeatureCollectionPositions(baseline),
    );

    expect(extentFromDataset ?? extentFromFeatures).toBeTruthy();
    baselineExtent = (extentFromDataset ?? extentFromFeatures) as BBox;
  });

  test.afterAll(async ({ request }) => {
    if (ownedDataset) {
      await deleteRuntimeDataset(request, authHeader, ownedDataset);
    }
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
    // fix(review #1792): shrinking the dataset's OWN reported extent by 20%
    // does not guarantee any feature falls inside the shrunk box. For an
    // externally supplied dataset (the E2E_EXPORT_DATASET_ID escape hatch
    // above) with a sparse or corner-clustered distribution, the interior
    // inset can legitimately contain nothing, and the toBeGreaterThan(0)
    // assertion below would then flag a healthy filter as broken. Build the
    // bbox around one OBSERVED feature's own coordinates instead -- taken
    // from `baseline`, the already-fetched unfiltered export -- padded by a
    // small epsilon, so the request is guaranteed to intersect at least that
    // feature regardless of dataset topology. This works identically for
    // `ownedDataset` and for E2E_EXPORT_DATASET_ID.
    // fix(review #1792 round 7): `baseline.features[0]` assumed the FIRST
    // feature has computable geometry, but resolveCandidate only checks
    // that SOME feature across the whole collection contributes a position
    // (collectFeatureCollectionPositions skips null/empty geometry per
    // feature without failing the collection) -- a custom dataset via
    // E2E_EXPORT_DATASET_ID can have a null-geometry row first and still
    // pass that check. Select the first feature computeFeatureBBox()
    // actually succeeds on instead of assuming index 0 is it.
    const observedFeature = baseline.features.find(
      (feature) => computeFeatureBBox(feature) !== null,
    );
    expect(
      observedFeature,
      'no feature in the baseline export has a computable geometry to build a bbox around',
    ).toBeTruthy();
    const observedBBox = computeFeatureBBox(observedFeature!) as BBox;
    const targetBBox = padBBox(observedBBox, 0.0001);

    lastBboxFilter = serializeBBox(targetBBox);
    const bboxParam = encodeURIComponent(lastBboxFilter);
    const filtered = await exportGeoJson(request, authHeader, dataset.id, [
      `bbox=${bboxParam}`,
    ]);

    // fix(#1778): neither assertion below required a non-empty result, so a
    // regression that made the bbox filter match nothing (inverted operator,
    // wrong column, an SRID mismatch) passed this test — the `for` loop
    // simply never ran. `toBeGreaterThan(0)` now holds unconditionally: the
    // bbox above is built to contain the observed feature.
    expect(filtered.features.length).toBeGreaterThan(0);
    expect(filtered.features.length).toBeLessThanOrEqual(baseline.features.length);

    // The observed feature itself must come back. Matched by geometry
    // rather than an id: both this call and `baseline` come from the same
    // GeoJSON export endpoint with no reprojection, so coordinates are
    // byte-identical, and the export response does not carry a stable
    // feature id to match on instead.
    const observedGeometryJson = JSON.stringify(observedFeature.geometry);
    const containsObserved = filtered.features.some(
      (feature) => JSON.stringify(feature.geometry) === observedGeometryJson,
    );
    expect(containsObserved).toBe(true);

    if (ownedDataset) {
      // Against the auto-seeded runtime fixture (west/center/east, spaced
      // ~5 degrees apart) a 0.0001-degree pad around one point never reaches
      // its neighbors -- pin the exact count rather than just "at least 1".
      expect(filtered.features.length).toBe(1);
    }

    for (const feature of filtered.features) {
      const featureBBox = computeFeatureBBox(feature);
      expect(featureBBox).toBeTruthy();
      if (featureBBox) {
        expect(intersectsBBox(featureBBox, targetBBox)).toBeTruthy();
      }
    }
  });

  test('semantic where filter returns a property-matching subset', async ({ request }) => {
    const predicate = buildWherePredicate(baseline, dataset.column_info, baselineRawText);
    expect(predicate).toBeTruthy();
    const predicateValue = predicate as WherePredicate;
    lastWhereFilter = predicateValue.clause;

    const filtered = await exportGeoJson(request, authHeader, dataset.id, [
      `where=${encodeURIComponent(predicateValue.clause)}`,
    ]);

    // fix(#1778): same empty-result gap as the bbox test above.
    // buildWherePredicate's threshold is now the column's MAXIMUM observed
    // value (see its comment), so the row that produced that maximum always
    // satisfies `>=` — the result is never empty.
    expect(filtered.features.length).toBeGreaterThan(0);
    expect(filtered.features.length).toBeLessThanOrEqual(baseline.features.length);
    if (ownedDataset) {
      // Against the auto-seeded runtime fixture, value=10/20/30 are
      // distinct, so `value >= 30` is satisfied by exactly one feature —
      // pin the exact count rather than just "fewer than all".
      expect(filtered.features.length).toBe(1);
    }

    for (const feature of filtered.features) {
      const properties = feature.properties ?? {};
      expect(predicateValue.evaluate(properties)).toBeTruthy();
    }
  });

  test('audit dataset.export entries include format and semantic parameters', async ({
    request,
  }) => {
    const auditBbox = lastBboxFilter ?? serializeBBox(buildInteriorBBox(baselineExtent));
    const fallbackPredicate = buildWherePredicate(baseline, dataset.column_info, baselineRawText);
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
