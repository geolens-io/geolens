import {
  classifyApiError,
  translateApiErrorDetail,
  translateError,
} from '@/lib/error-map';

describe('API error localization boundary', () => {
  it('maps known backend details to stable keys', () => {
    expect(classifyApiError('Dataset not found', 404)).toEqual({
      key: 'errors.datasetNotFound',
    });
    expect(translateError('Dataset not found', 404)).toBe('Dataset not found');
  });

  // fix(#1746): the ArcGIS-worded auth-required refusal (ArcGISTokenError
  // path) previously fell through to the generic 403 "Access denied" because
  // only the WFS/OGC wording of the same refusal was mapped.
  it('maps the ArcGIS-worded auth-required refusal to the same key as the generic one', () => {
    expect(
      classifyApiError(
        'This service requires authentication. Provide a valid ArcGIS token and try again.',
        403,
      ),
    ).toEqual({ key: 'errors.serviceRequiresAuth' });
    expect(
      translateApiErrorDetail(
        'This service requires authentication. Provide a valid ArcGIS token and try again.',
        403,
      ),
    ).toBe('This service requires authentication. Provide an access token and try again.');
  });

  it('does not render unknown backend prose', () => {
    const backendDetail = 'Name is required according to an internal rule';
    const rendered = translateApiErrorDetail(backendDetail, 400);

    expect(rendered).toBe('The request could not be completed. Check your input.');
    expect(rendered).not.toContain(backendDetail);
  });

  it('uses a service fallback for unknown server failures', () => {
    expect(translateApiErrorDetail('SQL connection pool exhausted', 503)).toBe(
      'The service is temporarily unavailable. Try again later.',
    );
  });

  it('localizes storage quotas while preserving and formatting every number', () => {
    expect(
      translateApiErrorDetail(
        'Storage quota exceeded: used 1024 of 2048 bytes (adding 4096 bytes)',
        413,
      ),
    ).toBe(
      'Storage quota exceeded: 1,024 of 2,048 bytes used (adding 4,096 bytes).',
    );
  });

  it('localizes dataset quotas while preserving both counts', () => {
    expect(
      translateApiErrorDetail('Dataset quota exceeded: 5 of 5 datasets used', 422),
    ).toBe('Dataset quota exceeded: 5 of 5 datasets used.');
  });

  it('uses a structured backend code without displaying its English message', () => {
    const detail = {
      code: 'duplicate_source',
      message: 'A dataset from this source URL is already registered',
      existing_title: 'Road closures',
    };

    expect(classifyApiError(detail, 409)).toEqual({
      key: 'errors.duplicateSource',
      values: { title: 'Road closures' },
    });
    expect(translateApiErrorDetail(detail, 409)).toBe(
      'A dataset from this source is already registered (Road closures).',
    );
  });

  it('collapses the refresh door refusal taxonomy to one key per code, regardless of call site', () => {
    // Two different resolvers (service vs. postgis) word refresh_not_applicable
    // differently; both must land on the same user-facing message.
    expect(
      classifyApiError(
        {
          code: 'refresh_not_applicable',
          message: 'This dataset has no remote service origin to refresh from. Replace its data through re-upload instead.',
        },
        409,
      ),
    ).toEqual({ key: 'errors.refreshNotApplicable' });
    expect(
      classifyApiError(
        {
          code: 'refresh_not_applicable',
          message: 'This dataset is not backed by a registered table, so there is nothing to re-measure.',
        },
        409,
      ),
    ).toEqual({ key: 'errors.refreshNotApplicable' });

    expect(
      classifyApiError(
        {
          code: 'dataset_busy',
          message: 'A refresh is already running for this dataset. Wait for it to finish, then try again.',
        },
        409,
      ),
    ).toEqual({ key: 'errors.refreshDatasetBusy' });
  });

  it('maps the STAC door refusal wordings introduced by #1266 (#1332)', () => {
    expect(
      classifyApiError(
        {
          code: 'refresh_not_applicable',
          message: 'This dataset was not imported from a STAC item, so there is no item to re-resolve.',
        },
        409,
      ),
    ).toEqual({ key: 'errors.refreshNotApplicable' });
    expect(
      classifyApiError(
        {
          code: 'origin_unavailable',
          message:
            "This dataset's source binding does not record the STAC item its asset was published in, so GeoLens cannot ask the catalog where that asset is now. Re-import it from the STAC catalog to record one.",
        },
        409,
      ),
    ).toEqual({ key: 'errors.refreshOriginUnavailable' });
    expect(
      classifyApiError(
        {
          code: 'origin_unavailable',
          message:
            "GeoLens cannot tell this dataset's STAC item from another one its stored URL might serve: the binding predates item-identity tracking and the catalog's item URLs carry no identity of their own. Re-import it from the STAC catalog to record one.",
        },
        409,
      ),
    ).toEqual({ key: 'errors.refreshOriginUnavailable' });
    expect(
      classifyApiError(
        {
          code: 'credential_not_applicable',
          message:
            'Refreshing a STAC dataset re-reads a public item document and needs no credential. Send the request without a token.',
        },
        422,
      ),
    ).toEqual({ key: 'errors.refreshCredentialNotApplicable' });
  });

  it('interpolates the dynamic token policy for invalid_service_token without a static key', () => {
    const detail = {
      code: 'invalid_service_token',
      message: 'This service requires a base64url token (letters, digits, "-", "_").',
    };

    expect(classifyApiError(detail, 422)).toEqual({
      key: 'errors.refreshInvalidServiceToken',
      values: { message: detail.message },
    });
    expect(translateApiErrorDetail(detail, 422)).toBe(
      'The token was rejected: This service requires a base64url token (letters, digits, "-", "_").',
    );
  });

  // Lane A2 (service-auth wave): POST /services/arcgis/signin/'s refusal
  // taxonomy (plan 2026-09-01-service-auth-PLAN.md section 3.2).
  it('maps the ArcGIS sign-in refusal taxonomy to distinct static keys', () => {
    expect(
      classifyApiError(
        { code: 'arcgis_signin_rejected', message: 'invalid credentials', field: 'credential' },
        400,
      ),
    ).toEqual({ key: 'errors.arcgisSigninRejected' });

    expect(
      classifyApiError(
        { code: 'arcgis_sso_account', message: 'federated identity', field: 'credential' },
        400,
      ),
    ).toEqual({ key: 'errors.arcgisSsoAccount' });

    expect(
      classifyApiError(
        { code: 'ssrf_refused', message: 'blocked private address', field: 'url' },
        400,
      ),
    ).toEqual({ key: 'errors.arcgisPortalUnreachable' });

    // network_error covers both the 502 (unreachable) and 504 (timeout)
    // cases the endpoint can raise; it reuses the existing generic copy
    // rather than a new key.
    expect(
      classifyApiError({ code: 'network_error', message: 'connection refused', field: 'url' }, 502),
    ).toEqual({ key: 'errors.couldNotReachService' });
    expect(
      classifyApiError({ code: 'network_error', message: 'timed out', field: 'url' }, 504),
    ).toEqual({ key: 'errors.couldNotReachService' });
  });

  it('falls back the ArcGIS sign-in rate limit to the generic 429 key, unmapped by code', () => {
    // rate_limited carries no dedicated entry: the object branch falls
    // through to its message, which in turn falls through to the generic
    // 429 status key — the same path #774 already relies on.
    expect(
      classifyApiError(
        { code: 'rate_limited', message: 'Too many sign-in attempts', field: 'credential' },
        429,
      ),
    ).toEqual({ key: 'errors.rateLimited' });
  });

  it('drops the dynamic SSRF diagnostic suffix from the refresh URL refusal', () => {
    expect(
      translateApiErrorDetail(
        "This dataset's stored source URL is not reachable: DNS resolved to a private address",
        400,
      ),
    ).toBe(
      "This dataset's stored source URL failed a safety check and can't be refreshed automatically. Contact an administrator.",
    );
    // fix(#1332): the STAC door words the same refusal around its item URL.
    expect(
      translateApiErrorDetail(
        "This dataset's stored STAC item URL is not reachable: DNS resolved to a private address",
        400,
      ),
    ).toBe(
      "This dataset's stored source URL failed a safety check and can't be refreshed automatically. Contact an administrator.",
    );
  });

  // fix(#1390): the VRT source-compatibility 422 (`validate_sources` in
  // backend/app/processing/raster/validation.py) returns an array of
  // SourceValidationError objects (source_id/code/message/field/severity),
  // not the Pydantic loc/type/ctx shape below. All 8 VAL codes must map to a
  // per-code string that carries the offending source_id as context.
  it('maps every SourceValidationError code from a VRT validation 422', () => {
    const sourceId = '11111111-1111-1111-1111-111111111111';
    const cases: Array<[string, string]> = [
      ['crs_mismatch', 'errors.sourceValidationCrsMismatch'],
      ['band_count_mismatch', 'errors.sourceValidationBandCountMismatch'],
      ['single_band_required', 'errors.sourceValidationSingleBandRequired'],
      ['dtype_mismatch', 'errors.sourceValidationDtypeMismatch'],
      ['grid_misaligned', 'errors.sourceValidationGridMisaligned'],
      ['nodata_inconsistent', 'errors.sourceValidationNodataInconsistent'],
      ['rotated_raster', 'errors.sourceValidationRotatedRaster'],
      ['unknown_pixel_geometry', 'errors.sourceValidationUnknownPixelGeometry'],
    ];

    for (const [code, key] of cases) {
      const detail = [
        {
          source_id: sourceId,
          code,
          message: 'diagnostic backend prose that should not reach the user',
          field: 'some_field',
          severity: 'error',
        },
      ];

      expect(classifyApiError(detail, 422)).toEqual({
        key,
        values: { source: sourceId },
      });
    }
  });

  it('renders a real-shaped VAL-08 unknown_pixel_geometry 422 with source context', () => {
    const detail = [
      {
        source_id: '22222222-2222-2222-2222-222222222222',
        code: 'unknown_pixel_geometry',
        message:
          'Pixel resolution was never measured for this source; cannot verify it is unrotated and grid-aligned',
        field: 'res_x',
        severity: 'error',
      },
    ];

    expect(translateApiErrorDetail(detail, 422)).toBe(
      "Source 22222222-2222-2222-2222-222222222222's pixel resolution has never been measured, so it can't be verified as unrotated and grid-aligned.",
    );
  });

  it('falls back gracefully for an unrecognized SourceValidationError code', () => {
    const detail = [
      {
        source_id: '33333333-3333-3333-3333-333333333333',
        code: 'some_future_val_check',
        message: 'a VAL check added after this table was written',
        field: 'whatever',
        severity: 'error',
      },
    ];

    expect(classifyApiError(detail, 422)).toEqual({ key: 'errors.validationFailed' });
    const rendered = translateApiErrorDetail(detail, 422);
    expect(rendered).toBe('The submitted values are invalid.');
    expect(rendered).not.toContain('{');
  });

  it('still classifies the Pydantic validation-error array shape as before', () => {
    // Regression guard: the SourceValidationError detection above must not
    // intercept the pre-existing loc/type/ctx shape used by every other
    // FastAPI 422.
    const detail = [{ type: 'missing', loc: ['body', 'title'], msg: 'Field required' }];

    expect(classifyApiError(detail, 422)).toEqual({
      key: 'errors.validationRequired',
      values: { field: 'title' },
    });
  });

  it('localizes FastAPI missing-field validation with field context', () => {
    const detail = [
      { type: 'missing', loc: ['body', 'display_name'], msg: 'Field required' },
    ];

    expect(translateApiErrorDetail(detail, 422)).toBe('display_name is required.');
  });

  it('localizes validation constraints with their numeric limit', () => {
    const detail = [
      {
        type: 'string_too_short',
        loc: ['body', 'name'],
        msg: 'String should have at least 3 characters',
        ctx: { min_length: 3 },
      },
    ];

    expect(translateApiErrorDetail(detail, 422)).toBe(
      'name must contain at least 3 characters.',
    );
  });

  it('does not stringify malformed validation payloads', () => {
    const detail = [{ code: 17, ctx: { limit: 3 } }];
    const rendered = translateApiErrorDetail(detail, 422);

    expect(rendered).toBe('The submitted values are invalid.');
    expect(rendered).not.toContain('{');
    expect(rendered).not.toContain('[');
  });

  // The analysis size gates and the CORS guard are only useful if the limit and
  // the way out survive the localization boundary; before this mapping existed
  // every one of them rendered as "The submitted values are invalid."
  it.each([
    [
      'This dataset is too large for dissolve (the limit is 250,000 features). Filter it to a smaller dataset first.',
      '250,000',
    ],
    [
      'This dataset is too large for buffer (the limit is 500,000 features). Filter it to a smaller dataset first.',
      '500,000',
    ],
  ])('keeps the source-size limit out of the generic 422 bucket', (detail, limit) => {
    const rendered = translateApiErrorDetail(detail, 422);

    expect(rendered).not.toBe('The submitted values are invalid.');
    expect(rendered).toContain(limit);
    expect(rendered).toContain('Filter it to a smaller dataset first.');
  });

  it('keeps the mask-layer cap and both of its escape hatches', () => {
    const rendered = translateApiErrorDetail(
      'The mask layer has too many features to clip with (limit 1,000). Choose a smaller mask layer or draw the mask on the map.',
      422,
    );

    expect(rendered).toContain('1,000');
    expect(rendered).toContain('smaller mask layer');
    expect(rendered).toContain('draw the mask on the map');
  });

  it('explains the CORS wildcard rejection instead of blaming the input', () => {
    const rendered = translateApiErrorDetail(
      "Validation error for 'cors_allowed_origins': Wildcard '*' is not accepted " +
        'because credentialed CORS requires explicit origins. List each origin ' +
        'in full, e.g. https://example.com, https://app.example.com',
      422,
    );

    expect(rendered).not.toBe('The submitted values are invalid.');
    expect(rendered).toContain('Credentialed requests');
  });

  it('fix(#774): maps the four analysis 4xx literals #718 missed', () => {
    expect(
      classifyApiError(
        'An analysis job is already running; wait for it to finish',
        429,
      ),
    ).toEqual({ key: 'errors.analysisJobAlreadyRunning' });
    expect(classifyApiError('Analysis requires a vector dataset', 422)).toEqual({
      key: 'errors.analysisVectorRequired',
    });
    expect(
      classifyApiError('mask_dataset_id must reference a polygon dataset', 422),
    ).toEqual({ key: 'errors.analysisMaskPolygonRequired' });
    expect(
      classifyApiError("Unknown dissolve column: 'wetland_ha'", 422),
    ).toEqual({
      key: 'errors.analysisUnknownDissolveColumn',
      values: { column: 'wetland_ha' },
    });
  });

  // fix(#790): the sandbox advisory lock is shared between analysis previews
  // and AI chat data queries. Unmapped, this 429 collapsed to the generic
  // rate-limit fallback, so a busy chat query refused an analysis preview
  // without ever naming the feature holding the shared budget.
  it('names the other feature when the shared query lock refuses a preview', () => {
    expect(
      classifyApiError('Another data query is already running for this user', 429),
    ).toEqual({ key: 'errors.sharedQueryBusy' });
    const rendered = translateApiErrorDetail(
      'Another data query is already running for this user',
      429,
    );
    expect(rendered).toContain('AI chat');
    expect(rendered).not.toBe('Too many requests. Wait a moment and try again.');
  });

  it('still falls back for an unmapped analysis-shaped message', () => {
    expect(
      translateApiErrorDetail('This dataset is too large for everything', 422),
    ).toBe('The submitted values are invalid.');
  });

  // fix(#931): the backend names the offending maps precisely so a human can go
  // and fix them; unmapped, that list fell through to the generic 422 string.
  it('surfaces the maps a visibility change would strand', () => {
    expect(
      classifyApiError(
        'Cannot restrict visibility: dataset is used in shared maps: Flood Risk, Parcels 2026',
        422,
      ),
    ).toEqual({
      key: 'errors.datasetVisibilityBlockedByMaps',
      values: { maps: 'Flood Risk, Parcels 2026' },
    });
    expect(
      translateApiErrorDetail(
        'Cannot restrict visibility: dataset is used in shared maps: Flood Risk',
        422,
      ),
    ).toContain('Flood Risk');
  });

  // fix(#931 codex r5): `MapCreate.name` is length-bounded and NFC-normalized,
  // nothing more, so a newline in a map name is valid input. Without the `s`
  // flag `.` stopped at it and the whole list fell back to the generic 422 —
  // losing exactly the part that makes the refusal actionable.
  it('surfaces map names that legally contain a newline', () => {
    expect(
      classifyApiError(
        'Cannot restrict visibility: dataset is used in shared maps: Flood\nRisk, Parcels',
        422,
      ),
    ).toEqual({
      key: 'errors.datasetVisibilityBlockedByMaps',
      values: { maps: 'Flood\nRisk, Parcels' },
    });
  });

  it('retains unknown layer names through localized structured validation', () => {
    expect(
      translateApiErrorDetail(
        {
          message: 'Unknown layer name(s) — not found in the uploaded file',
          unknown_layers: ['roads', 'rivers'],
        },
        422,
      ),
    ).toBe('These layers were not found in the uploaded file: roads, rivers.');
  });
  // fix(#1548 review P2): the embed domain-lock refusal. Both compose files
  // ship PUBLIC_APP_URL defaulted to localhost, so a self-hoster reached at a
  // real hostname hits this on a stock install — and its whole value is the
  // remediation. Unmapped it collapses to the generic 422 and the domain lock
  // goes back to failing silently, which is what the refusal exists to stop.
  it('keeps the remediation in the embed domain-lock refusal', () => {
    expect(
      classifyApiError(
        'Domain locking cannot be enforced by this deployment: its public app URL ' +
          'resolves to http://localhost:8080, but this request reached it at ' +
          'https://maps.example.com. An embed shell\'s own API calls carry the ' +
          "shell's origin, so a domain-locked token issued now would load an empty " +
          'map. Set PUBLIC_APP_URL (or the public_app_url setting) to ' +
          'https://maps.example.com and try again.',
        422,
      ),
    ).toEqual({
      key: 'errors.embedDomainLockUnenforceable',
      values: {
        resolved: 'http://localhost:8080',
        origin: 'https://maps.example.com',
      },
    });
  });

  it('names both the configured value and the origin to set', () => {
    const rendered = translateApiErrorDetail(
      'Domain locking cannot be enforced by this deployment: its public app URL ' +
        'resolves to http://localhost:8080, but this request reached it at ' +
        'https://maps.example.com. Set PUBLIC_APP_URL (or the public_app_url ' +
        'setting) to https://maps.example.com and try again.',
      422,
    );
    expect(rendered).toContain('PUBLIC_APP_URL');
    expect(rendered).toContain('http://localhost:8080');
    expect(rendered).toContain('https://maps.example.com');
    // The guard the mapping exists for.
    expect(rendered).not.toBe('The submitted values are invalid.');
  });
});
