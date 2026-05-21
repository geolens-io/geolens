---
created: 2026-05-20T00:00:00Z
title: "v1063 IN-02: StacSearchBody.limit/offset have no Pydantic ge/le constraints"
area: api
phase: 1063
severity: info
source: 1063-REVIEW.md
resolves_phase: 1071
files:
  - backend/app/standards/stac/schemas.py
---

## Finding

`StacSearchBody.limit` and `StacSearchBody.offset` are typed `int` with no
`ge`/`le` bounds. A caller passing `limit=999999` or `offset=-1` would be
accepted by Pydantic and reach the SQLAlchemy layer.

The downstream query already caps results (LIMIT clause), so this is not a
security issue — just an API hygiene gap.

## Solution

Add bounds to the schema:

```python
limit: int = Field(default=10, ge=1, le=1000)
offset: int = Field(default=0, ge=0)
```

## Deferred rationale

Behavior is currently bounded by downstream query logic. Schema-level bounds
are best-practice but not strictly required.
