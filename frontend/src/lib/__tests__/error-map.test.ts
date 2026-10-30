import {
  classifyApiError,
  describeUploadRefusal,
  translateApiErrorDetail,
} from '@/lib/error-map';

describe('API error localization boundary', () => {
  it.each([
    ['retention_unsupported_relation', 'errors.retentionUnsupportedRelation', 'needs the dataset\'s data in an ordinary table'],
    ['retention_has_children', 'errors.retentionHasChildren', 'other tables inherit from'],
    ['retention_referenced', 'errors.retentionReferenced', 'Remove the foreign key'],
    ['retention_delete_trigger', 'errors.retentionDeleteTrigger', 'delete trigger'],
    ['retention_delete_rule', 'errors.retentionDeleteRule', 'DELETE rule'],
    ['retention_gid_unusable', 'errors.retentionGidUnusable', 'whole-number gid column'],
    ['retention_not_feature_dataset', 'errors.retentionNotFeatureDataset', 'features have geometry'],
    ['retention_column_missing', 'errors.retentionColumnMissing', 'The column seen_at no longer exists'],
    ['retention_column_not_temporal', 'errors.retentionColumnNotTemporal', 'The column seen_at isn\'t a date'],
    ['retention_column_in_use', 'errors.retentionColumnInUse', 'Retention deletes rows by the column seen_at'],
  ])('maps the retention refusal %s to its own message', (code, key, text) => {
    const detail = { code, message: 'English diagnostic', column: 'seen_at' };
    expect(classifyApiError(detail, 422).key).toBe(key);
    expect(translateApiErrorDetail(detail, 422)).toContain(text);
  });

  it('maps known backend details to stable keys', () => {
    expect(classifyApiError('Dataset not found', 404)).toEqual({
      key: 'errors.datasetNotFound',
    });
  });

  it('maps the value label budget refusal to a translated message', () => {
    const detail = 'Value labels for this dataset are over the 1 MB limit.';
    expect(classifyApiError(detail, 422)).toEqual({ key: 'errors.valueLabelsTooLarge' });
    expect(translateApiErrorDetail(detail, 422)).toContain('1 MB');
  });

  it('tells an owner at the dataset key limit to revoke one first', () => {
    const detail = 'This dataset already has 100 active keys. Revoke one to create another.';
    expect(classifyApiError(detail, 409)).toEqual({ key: 'errors.datasetKeyLimit' });
    expect(translateApiErrorDetail(detail, 409)).toBe(
      'This dataset already has 100 active write keys. Revoke one to create another.',
    );
  });

  it('maps the trust-link refusals to their own keys', () => {
    expect(classifyApiError({ code: 'device_trust_link_invalid', message: 'x' }, 404)).toEqual({
      key: 'errors.deviceTrustLinkInvalid',
    });
    expect(classifyApiError({ code: 'device_trust_browser_full', message: 'x' }, 409)).toEqual({
      key: 'errors.deviceTrustBrowserFull',
    });
    expect(classifyApiError({ code: 'device_trust_unavailable', message: 'x' }, 409)).toEqual({
      key: 'errors.deviceTrustUnavailable',
    });
  });

  it('names the way back in when sign-in is throttled for an account', () => {
    const detail = { code: 'login_throttled', message: 'Too many failed sign-ins' };
    expect(classifyApiError(detail, 429)).toEqual({ key: 'errors.loginThrottled' });
    expect(translateApiErrorDetail(detail, 429)).toBe(
      "Too many failed sign-ins for this account. Use a browser you've signed in with before, sign in with SSO, or use an API key for scripts and desktop apps.",
    );
  });

  // The ArcGIS-worded auth-required refusal (ArcGISTokenError
  // path) maps to the same key as the WFS/OGC wording, not the generic 403
  // "Access denied".
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

  const denial = (current: string, requested: string, allowed: string[]) => ({
    code: 'workflow_transition_denied',
    message: `Cannot transition from '${current}' to '${requested}'.`,
    current_stage: current,
    requested_stage: requested,
    allowed_stages: allowed,
  });

  it('names the refused workflow edge and the steps still open to the caller', () => {
    const detail = denial('pending_review', 'published', ['approved', 'draft']);
    expect(classifyApiError(detail, 422)).toEqual({
      key: 'errors.workflowTransitionDenied',
      values: { from: 'pending_review', to: 'published', allowed: 'approved, draft' },
    });
    expect(translateApiErrorDetail(detail, 422)).toContain('“pending_review” to “published”');
    expect(translateApiErrorDetail(detail, 422)).toContain('approved, draft');
  });

  it("reads stage names holding quotes, the edge delimiter or a line break", () => {
    expect(
      classifyApiError(denial("a' to 'b", 'pub\nlished', ['reviewer\'s "ok"']), 422),
    ).toEqual({
      key: 'errors.workflowTransitionDenied',
      values: { from: "a' to 'b", to: 'pub\nlished', allowed: 'reviewer\'s "ok"' },
    });
  });

  it('says so when no workflow step is open to the caller', () => {
    expect(classifyApiError(denial('draft', 'published', []), 422)).toEqual({
      key: 'errors.workflowTransitionDeniedNoneAllowed',
      values: { from: 'draft', to: 'published' },
    });
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

    expect(
      classifyApiError(
        {
          code: 'review_superseded',
          message: 'The dataset changed after this replacement was held. Upload the file again.',
        },
        409,
      ),
    ).toEqual({ key: 'errors.refreshReviewSuperseded' });
  });

  // The re-upload commit door returns the SAME `origin_changed`
  // code as the refresh door with different copy, so the two must land on
  // different keys — a shared key would tell a user replacing a file that a
  // refresh was queued.
  it('maps the re-upload door origin_changed apart from the refresh one', () => {
    expect(
      classifyApiError(
        {
          code: 'origin_changed',
          message:
            "This dataset's source changed after this replacement was staged, so nothing was queued. Re-check the dataset's source and start the replacement again.",
          origin_kind: 'service',
          expected_origin_kind: 'upload',
        },
        409,
      ),
    ).toEqual({ key: 'errors.reuploadOriginChanged' });

    expect(
      classifyApiError(
        {
          code: 'origin_changed',
          message:
            "This dataset's source changed while the refresh was being queued, so it was not started. Check the new source and try again.",
        },
        409,
      ),
    ).toEqual({ key: 'errors.refreshOriginChanged' });
  });

  // Keyed on the code, so a reworded server sentence still maps.
  it('maps the re-upload geometry-loss refusal by its code', () => {
    expect(
      classifyApiError(
        {
          code: 'geometry_loss',
          message: 'Some future wording of the same refusal.',
        },
        422,
      ),
    ).toEqual({ key: 'errors.reuploadGeometryLoss' });
  });

  // A plain 422 detail string, so without the matcher it lands on
  // the generic "values are invalid" and the code the user typed is lost.
  it('maps the commit doors srid_override refusal and keeps the code', () => {
    expect(
      classifyApiError(
        'srid_override 99999 is not a known coordinate system: neither PROJ nor PostGIS spatial_ref_sys has that EPSG code. Use an assigned code, or omit srid_override to keep the source CRS.',
        422,
      ),
    ).toEqual({ key: 'errors.unknownSridOverride', values: { srid: '99999' } });
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

  // POST /services/arcgis/signin/'s refusal taxonomy.
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

  it('maps the unrecognized-service probe refusal to its own key', () => {
    expect(
      classifyApiError(
        "Couldn't detect service type. Supported: WFS, ArcGIS Feature Service, and OGC API Features",
        400,
      ),
    ).toEqual({ key: 'errors.serviceNotRecognized' });
  });

  it('falls back the ArcGIS sign-in rate limit to the generic 429 key, unmapped by code', () => {
    // rate_limited carries no dedicated entry: the object branch falls
    // through to its message, which in turn falls through to the generic
    // 429 status key, the same path #774 already relies on.
    expect(
      classifyApiError(
        { code: 'rate_limited', message: 'Too many sign-in attempts', field: 'credential' },
        429,
      ),
    ).toEqual({ key: 'errors.rateLimited' });
  });

  // The limiter's own message names the ArcGIS account, not GeoLens or the
  // portal (the limit is keyed on the target account: three attempts per
  // fifteen minutes per ArcGIS account shared across all GeoLens users,
  // plus three per GeoLens user and portal). The fallback below does not
  // read the message text for this code, so this rewording changes
  // nothing here, and this test pins that.
  it('still falls back a reworded rate_limited message to the generic 429 key', () => {
    expect(
      classifyApiError(
        {
          code: 'rate_limited',
          message: 'Too many sign-in attempts for that ArcGIS account. Wait fifteen minutes before trying again. ArcGIS locks an account after five failed attempts, so GeoLens stops short of that on purpose.',
          field: 'credential',
        },
        429,
      ),
    ).toEqual({ key: 'errors.rateLimited' });
  });

  // arcgis_signin_in_progress replaced a 429 rate_limited response for the
  // same-account-concurrency case (one ArcGIS sign-in per account at a
  // time, distinct from the attempt-count limiter above).
  it('maps arcgis_signin_in_progress to its own key', () => {
    expect(
      classifyApiError(
        {
          code: 'arcgis_signin_in_progress',
          message: 'A sign-in to that ArcGIS account is already in progress. Wait for it to finish before trying again.',
          field: 'credential',
        },
        409,
      ),
    ).toEqual({ key: 'errors.arcgisSigninInProgress' });
  });

  // arcgis_portal_not_https is a 422 with the SAME structured
  // {code, message, field} shape as the rest of this taxonomy, not
  // FastAPI's list-shaped validation 422 handled by validationDescriptor,
  // so it must be caught in the object branch rather than falling through
  // to a generic validation message.
  it('maps arcgis_portal_not_https to its own key rather than the generic validation fallback', () => {
    expect(
      classifyApiError(
        {
          code: 'arcgis_portal_not_https',
          message: 'the portal or its token service must use https',
          field: 'url',
        },
        422,
      ),
    ).toEqual({ key: 'errors.arcgisPortalNotHttps' });
  });

  it('maps credential_over_http to its own key', () => {
    expect(
      classifyApiError(
        {
          code: 'credential_over_http',
          message: 'This service address uses plain HTTP.',
          field: 'url',
        },
        422,
      ),
    ).toEqual({ key: 'errors.credentialOverHttp' });
  });

  // The sixth and
  // final caller-facing code (backend/app/modules/catalog/sources/
  // arcgis_signin.py, HOST_INVALID), a 422 for a portal hostname that
  // cannot be canonicalized, anchored to the same field: 'url' as
  // arcgis_portal_not_https above.
  it('maps arcgis_portal_host_invalid to its own key rather than the generic validation fallback', () => {
    expect(
      classifyApiError(
        {
          code: 'arcgis_portal_host_invalid',
          message: 'That portal address is not a usable hostname.',
          field: 'url',
        },
        422,
      ),
    ).toEqual({ key: 'errors.arcgisPortalHostInvalid' });
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
    // The STAC door words the same refusal around its item URL.
    expect(
      translateApiErrorDetail(
        "This dataset's stored STAC item URL is not reachable: DNS resolved to a private address",
        400,
      ),
    ).toBe(
      "This dataset's stored source URL failed a safety check and can't be refreshed automatically. Contact an administrator.",
    );
  });

  // The VRT source-compatibility 422 (`validate_sources` in
  // backend/app/processing/raster/validation.py) returns an array of
  // SourceValidationError objects (source_id/code/message/field/severity),
  // not the Pydantic loc/type/ctx shape below. Every VAL code must map to a
  // per-code string that carries the offending source_id as context.
  it('maps every SourceValidationError code from a VRT validation 422', () => {
    const sourceId = '11111111-1111-1111-1111-111111111111';
    const cases: Array<[string, string]> = [
      ['crs_mismatch', 'errors.sourceValidationCrsMismatch'],
      ['crs_unverified', 'errors.sourceValidationCrsUnverified'],
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

  // The STAC import door reuses pydantic's own HttpUrl parsing inside a
  // field validator (`_validate_stac_http_url` in stac_router.py) to reject
  // an item whose data asset is an `s3://` (or other non-http) URL. That
  // raises pydantic-core's own `url_scheme` error type rather than the
  // generic `value_error` a raised ValueError would produce; unmapped it
  // fell through to the field-name-only "has an invalid value" message and
  // hid that the concrete, fixable problem is the scheme.
  it('names the scheme problem for a pydantic url_scheme validation error, not the generic field message', () => {
    const detail = [
      {
        type: 'url_scheme',
        loc: ['body', 'items', 0, 'data_asset_href'],
        msg: "URL scheme should be 'http' or 'https'",
        ctx: { expected_schemes: "'http' or 'https'" },
      },
    ];

    expect(classifyApiError(detail, 422)).toEqual({
      key: 'errors.validationUrlSchemeInvalid',
      values: { field: 'items.0.data_asset_href' },
    });
    const rendered = translateApiErrorDetail(detail, 422);
    expect(rendered).toBe('items.0.data_asset_href must be an http or https address.');
    expect(rendered).not.toBe('The submitted values are invalid.');
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

  it('maps the four analysis 4xx literals the first mapping pass missed', () => {
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

  // The sandbox advisory lock is shared between analysis previews
  // and AI chat data queries. Unmapped, this 429 collapses to the generic
  // rate-limit fallback, so a busy chat query refuses an analysis preview
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

  // The backend names the offending maps precisely so a human can go
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

  it('surfaces the maps an unpublish would strand', () => {
    expect(
      classifyApiError(
        'Cannot unpublish: dataset is used in shared maps: Flood Risk, Parcels 2026',
        422,
      ),
    ).toEqual({
      key: 'errors.datasetUnpublishBlockedByMaps',
      values: { maps: 'Flood Risk, Parcels 2026' },
    });
    expect(
      translateApiErrorDetail(
        'Cannot unpublish: dataset is used in shared maps: Flood Risk',
        422,
      ),
    ).toContain('Flood Risk');
  });

  // `MapCreate.name` is length-bounded and NFC-normalized,
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
  // The embed domain-lock refusal. Both compose files
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

describe('describeUploadRefusal', () => {
  it('shows an unmapped 422 string detail verbatim, the way a stored job failure reason already does', () => {
    const detail = 'Archive contains a path outside the tileset root: ../secrets.txt';

    expect(describeUploadRefusal(detail, 422)).toBe(detail);
  });

  it('shows an unmapped 400 string detail verbatim, such as the extension refusal', () => {
    const detail = "File extension '.exe' not allowed. Allowed: ['.zip', '.geojson']";

    expect(describeUploadRefusal(detail, 400)).toBe(detail);
  });

  it('still translates a 422 string this table already recognizes', () => {
    expect(
      describeUploadRefusal('Dataset quota exceeded: 5 of 5 datasets used', 422),
    ).toBe('Dataset quota exceeded: 5 of 5 datasets used.');
  });

  it('translates a Pydantic validation array rather than rendering it', () => {
    const detail = [{ loc: ['body', 'name'], type: 'missing' }];

    const rendered = describeUploadRefusal(detail, 422);

    expect(rendered).not.toBe(detail);
    expect(typeof rendered).toBe('string');
    expect(rendered).toContain('name');
  });

  it('translates a structured {code, message} refusal rather than rendering the message', () => {
    const detail = { code: 'geometry_loss', message: 'Replacing this file would drop its geometry column.' };

    expect(describeUploadRefusal(detail, 422)).not.toBe(detail.message);
  });

  it('does not render an unmapped string outside 400 and 422', () => {
    expect(describeUploadRefusal('Some unmapped 409 detail', 409)).toBe(
      "The request conflicts with the resource's current state.",
    );
  });

  it('interpolates both values for a size refusal that knows the actual size', () => {
    const detail = {
      code: 'file_size_exceeded',
      message: 'File size (2.0 MB) exceeds the maximum allowed (1 MB).',
      size_mb: 2.0,
      limit_mb: 1,
    };

    expect(translateApiErrorDetail(detail, 422)).not.toContain('{{');
  });

  it('interpolates the kind for a .laz sent without the point cloud kind', () => {
    const detail = {
      code: 'pointcloud_kind_required',
      message: 'A .laz file holds a point cloud. Upload it as a new dataset with kind=pointcloud.',
      file_type: 'pointcloud',
    };

    expect(translateApiErrorDetail(detail, 422)).toBe(detail.message);
  });

  it('interpolates the limit for a size refusal aborted mid-stream, with no actual size', () => {
    const detail = {
      code: 'file_size_limit_exceeded',
      message: 'File size exceeds maximum allowed (1 MB).',
      limit_mb: 1,
    };

    expect(translateApiErrorDetail(detail, 413)).not.toContain('{{');
  });

  it.each([
    [
      "This VRT would reach people who cannot see all of its source datasets. Narrow the VRT's visibility or use sources its audience can see.",
      422,
      'A VRT dataset would reach people',
    ],
    ["A group named 'Planning' already exists", 409, 'A group named "Planning" already exists'],
    ['Group not found', 404, 'Group not found'],
  ])('gives the group refusal %j a readable message', (detail, status, text) => {
    expect(translateApiErrorDetail(detail, status)).toContain(text);
  });
});

describe('story write refusals', () => {
  it.each([
    [{ code: 'scenes_unreadable', message: 'x' }, 409, "Some scenes were saved by a newer version of GeoLens and can't be published here."],
    [{ code: 'visibility_unsupported', message: "Stories can't be published as restricted yet." }, 409, "Stories can't be published with this visibility yet."],
    ['Another change to this story is in progress. Retry shortly.', 409, 'Another change to this story is in progress. Try again in a moment.'],
    ["This story was saved by a newer version of GeoLens and can't be changed here.", 409, "This story was saved by a newer version of GeoLens and can't be changed here."],
    ['Story not found', 404, 'Story not found.'],
    [{ code: 'story_image_too_large', message: 'JPEG images can be at most 15,000 pixels on a side.' }, 413, 'This image is too large. Upload a file under 50 MB with fewer pixels.'],
    [{ code: 'story_image_unsupported', message: 'x' }, 415, 'Only PNG, JPEG and WebP images can be uploaded.'],
    [{ code: 'story_image_unreadable', message: 'x' }, 400, "The file isn't a readable image."],
    [{ code: 'story_image_busy', message: 'x' }, 503, 'Other images are being processed. Try again in a moment.'],
    [{ code: 'story_image_missing', message: 'x' }, 422, 'No image was sent. Choose a file and try again.'],
    [{ code: 'story_asset_limit', message: 'x' }, 409, 'This story already holds its most images: 200, or 250 MB of them.'],
    [{ code: 'story_asset_owner_limit', message: 'x' }, 409, 'Your stories already hold the most image storage an admin allows. Remove images from your stories, or ask an admin to raise the limit.'],
    [{ code: 'story_assets_not_found', message: 'x', asset_ids: [] }, 422, "Some images in this story weren't found. Remove those image blocks and save again."],
  ])('localizes %j', (detail, status, expected) => {
    expect(translateApiErrorDetail(detail, status)).toBe(expected);
  });
});
