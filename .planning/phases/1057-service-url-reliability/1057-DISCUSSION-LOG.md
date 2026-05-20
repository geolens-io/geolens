# Phase 1057: Service URL Reliability - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-19
**Phase:** 1057-Service URL Reliability
**Areas discussed:** WFS-04 fix strategy, PROBE-05 latency strategy (real root cause), CRS-06 URI coverage scope, CLASS-07 (where to flip + what counts as raster)

---

## Gray Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| WFS-04 fix strategy | Three candidates: (a) abstract→concrete map at -nlt, (b) probe inspects first feature, (c) drop subtype, declare generic geometry column. | ✓ |
| PROBE-05 latency strategy | Orchestrator already short-circuits — real bottleneck is per-layer ogrinfo enrichment. Options: drop, bound, raise concurrency, replace with cheaper HTTP. | ✓ |
| CRS-06 URI coverage scope | Cover URI + URN + HTTPS variants; behavior on unrecognized URIs. | ✓ |
| CLASS-07 — where to flip + what counts as raster | Frontend-only vs backend-classified `kind` field; raster-signal definition. | ✓ |

**User's choice:** All four areas selected for discussion.

---

## WFS-04 — Fix Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| (c) Generic GEOMETRY column | Declare `geometry(Geometry, 4326)` (no subtype). Works for any abstract or mixed type. Loses PostGIS column-level constraint; recovered via `metadata.geometry_type` derived from data. | ✓ (via deferral) |
| (a) Abstract→concrete mapping at -nlt | Pre-ingest lookup: MultiSurface→MULTIPOLYGON, MultiCurve→MULTILINESTRING, etc. Keeps strict column type. Doesn't cover unknown abstract types. | |
| (b) Probe inspects first feature | Extra HTTP round-trip per probe. Most accurate. Collides with PROBE-05 ≤5s budget. | |

**User's choice (free text):** "proceed with your suggestions for all gray areas" — deferred to Claude across all four areas.

**Notes:** Claude's recommendation = (c) Generic GEOMETRY column. Lowest risk against future weird WFS schemas; replacement type-discipline path already exists in `metadata.py:165`.

---

## PROBE-05 — Latency Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| (i) Drop enrichment from probe; lazy-enrich on layer-select | `geometry_type=null` and `feature_count=null` returned for all layers; one ogrinfo call per selected layer at preview time. ≤5s target trivially achievable. Pairs with CLASS-07. | ✓ (via deferral) |
| (ii) Bound to first N layers (e.g., 5) at probe | Partial enrichment up front; rest on demand. | |
| (iii) Raise Semaphore to unlimited + bound wall time | 5s timeout on enrichment phase; return whatever finished. | |
| (iv) Replace per-layer ogrinfo with cheaper HTTP GET | Read geometry from queryables / schema; skip subprocess. More effort, more durable. | |

**User's choice (free text):** Deferred to Claude (part of the same "proceed with your suggestions" response).

**Notes:**
- Diagnostic finding flagged before the question: `detect_service_type` already short-circuits per-probe; the ~60s in the smoke report is enrichment (`ogcapi.py:162-239`), not orchestration. The requirement text in REQUIREMENTS.md ("short-circuit `try_all_probes()`") names the wrong root cause. This is locked into CONTEXT.md `<decisions>` D-04 so planner doesn't follow the misleading hint.
- Claude's recommendation = (i). Simplest implementation, fully achieves acceptance criterion, pairs cleanly with CLASS-07's null→VEC fallback (no probe-response field gymnastics).

---

## CRS-06 — URI/URN Coverage Scope

| Option | Description | Selected |
|--------|-------------|----------|
| All 4 URI/URN forms + fallback to today's behavior on unrecognized | CRS84 + EPSG/0/N + urn:ogc:def:crs:EPSG::N + urn:ogc:def:crs:OGC:1.3:CRS84; HTTPS variants of all. Unrecognized → CRS=null + Override field stays visible. | ✓ (via deferral) |
| Minimum-only (CRS84 + EPSG/0/N) | What REQUIREMENTS.md mandates verbatim. Skips URN forms which are common in older OGC services. | |
| All recognized + hard-fail on unrecognized | No escape hatch for weird URIs. | |
| Default to CRS84 (4326) on unrecognized | Assume OGC default. Silent data corruption risk if source actually publishes a non-4326 CRS. | |

**User's choice (free text):** Deferred to Claude.

**Notes:** Claude's recommendation = all 4 forms + fallback. URN form is common in older GeoServer / pygeoapi / Esri OGC API deployments — covering it costs ~3 lines of code. Hard-fail and silent-4326-assumption both risk worse UX than today.

---

## CLASS-07 — Where to Flip + What Counts as Raster

| Option | Description | Selected |
|--------|-------------|----------|
| Backend-classified `kind` field on `ProbeLayer`; null→VEC unless explicit raster signal | Durable schema field consumed by frontend `ServiceUrlForm.tsx:197`. Raster signals: `geometry_type` contains 'raster', adapter is STAC, layer has `coverage_format` / `bands` / `mediaType: image/*`. | ✓ (via deferral) |
| Frontend-only flip at ServiceUrlForm.tsx:197 | Invert `isVector` rule so null→VEC. One-line change, ships fast. But each frontend re-derives. | |

**User's choice (free text):** Deferred to Claude.

**Notes:** Claude's recommendation = backend `kind` field. The `Layer` schema is already shared across probe consumers; an additive Pydantic field with `Literal['vector', 'raster']` and a `'vector'` default is backward-compat. Future ingest UIs / future audits inherit the classification without re-deriving.

---

## Final Confirmation

| Option | Description | Selected |
|--------|-------------|----------|
| Lock in and write CONTEXT.md | Write `1057-CONTEXT.md` with the four decisions above. | ✓ |
| Discuss one of them more | Open a follow-up. | |
| Replace a decision | Override a specific area's decision. | |

**User's choice:** "Lock in and write CONTEXT.md"

---

## Claude's Discretion

All four gray areas — user deferred via "proceed with your suggestions for all gray areas". Specific recommendations recorded above and locked into CONTEXT.md `<decisions>`. Three smaller discretion items remain (test fixture format, helper module location, telemetry on/off) — recorded in CONTEXT.md `<decisions>` "Claude's Discretion".

## Deferred Ideas

Recorded in CONTEXT.md `<deferred>`. Summary:

- Migrating / retrying previously-failed WFS imports — out of v1013 scope.
- Probe-duration structured-log telemetry — planner discretion.
- WMS / WMTS / TMS adapter support — REQUIREMENTS.md "Out of Scope".
- Backend-side CRS reprojection beyond URI parsing — REQUIREMENTS.md "Out of Scope".
- Background-enrichment-task alternative to D-05 lazy-on-select — D-05 simpler.
- Pre-emptive raster signal expansion (`coverage_format` taxonomy) — defer until needed.
