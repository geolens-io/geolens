---
created: 2026-05-20T00:00:00Z
title: "IN-01: _revalidate_redirect does not handle HTTP 305 (Use Proxy)"
area: security
phase: 1061
resolves_phase: 1070
severity: info
source: 1061-REVIEW.md
files:
  - backend/app/modules/catalog/sources/security.py
---

## Finding

Phase 1061 REVIEW.md IN-01 (informational, not a blocker).

`_revalidate_redirect` in `backend/app/modules/catalog/sources/security.py:81`
checks `response.status_code not in (301, 302, 303, 307, 308)`. HTTP 305
("Use Proxy") is omitted. 305 is deprecated in RFC 7231 and modern HTTP
clients (including httpx) do not follow it, so the current omission poses
no practical risk.

## Options

Either document the omission with a comment, or add 305 to the tuple for
completeness:

```python
if response.status_code not in (301, 302, 303, 305, 307, 308):
    return
```

## Deferred Rationale

No practical risk — httpx does not follow 305 redirects. Deferred from
Phase 1061 per review scope (info-only findings deferred to pending todos).
