# DCAT-US 3.0 Architecture Research

**Milestone:** v1029 DCAT 3.0

## Integration Points

- `backend/app/standards/dcat/service.py` remains the W3C DCAT 3 serializer.
- New DCAT-US behavior should live under `backend/app/standards/dcat_us/`.
- `backend/app/modules/catalog/datasets/api/router_export.py` owns export routes and should call the new serializer/validator with the same visibility-filtered query shape used by existing DCAT routes.
- `backend/tests/test_dcat.py` is the closest test analog and should gain DCAT-US focused coverage or a sibling test module.
- `backend/openapi.json` and generated SDKs must refresh if new public routes are included in OpenAPI.

## Recommended Build Order

1. Define requirements and roadmap.
2. Add the DCAT-US serializer and validator package with vendored schemas.
3. Add catalog/dataset/validation routes using existing visibility and access helpers.
4. Add focused tests for schema validity, invalid metadata reports, route behavior, and access control.
5. Refresh OpenAPI/SDK artifacts if route schema changes are public.
6. Run backend gates and Playwright MCP against the running API.

## Compatibility Rules

- Do not change the shape of existing `/datasets/dcat/` or `/{dataset_id}/dcat/` output in this milestone.
- Use explicit DCAT-US 3.0 route names for federal-profile consumers.
- Keep dataset ID access checks before serialization.
- Keep list route visibility filtering through `apply_visibility_filter`.
