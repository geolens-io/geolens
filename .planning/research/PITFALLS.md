# DCAT-US 3.0 Pitfalls Research

**Milestone:** v1029 DCAT 3.0

## Pitfalls

- **Profile confusion:** W3C DCAT 3 JSON-LD and DCAT-US 3.0 JSON Schema use different compact field names. Avoid changing existing W3C routes in place.
- **Runtime schema fetches:** Fetching the official schema during requests or tests would make validation flaky and slow. Vendor the schema and record the source commit.
- **Mandatory metadata gaps:** DCAT-US requires dataset `title`, `description`, `identifier`, `publisher`, and `contactPoint`. GeoLens cannot invent valid contact emails for datasets without contacts; validation should surface missing metadata rather than hiding it.
- **Route conflicts:** `/datasets/dcat-us/3.0/` must be registered before dynamic `/{dataset_id}` routes.
- **Access regressions:** New export and validation routes must preserve catalog visibility filtering and per-dataset access checks.
- **OpenAPI drift:** Public validation/export routes require `backend/openapi.json` and SDK refresh.

## Prevention

- Add route-order tests for `/datasets/dcat-us/3.0/`.
- Add anonymous/private visibility tests matching existing DCAT tests.
- Add schema validation tests using the vendored registry.
- Keep compatibility routes and DCAT-US profile routes separate.
