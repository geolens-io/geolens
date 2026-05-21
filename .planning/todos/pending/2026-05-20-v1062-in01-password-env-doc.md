---
created: 2026-05-20T00:00:00Z
title: "v1062 IN-01: .env.example missing PASSWORD_MIN_LENGTH / PASSWORD_REQUIRE_CLASSES documentation"
area: documentation
phase: 1062
severity: info
source: 1062-REVIEW.md
files:
  - .env.example
---

## Finding

Phase 1062 SEC-S16 (v1014) shipped configurable password complexity via
`PASSWORD_MIN_LENGTH` and `PASSWORD_REQUIRE_CLASSES` environment variables, but
`.env.example` was not updated. New operators reading the file have no signal
that these knobs exist.

## Solution

Add documented entries to `.env.example` near the existing auth settings:

```env
# Password complexity (Phase 1062 SEC-S16). Defaults shown.
# PASSWORD_MIN_LENGTH=12
# PASSWORD_REQUIRE_CLASSES=3   # of 4: lowercase, uppercase, digits, symbols
```

## Deferred rationale

Documentation-only. Defaults are sane; operators only need this when tightening
or loosening complexity for their environment.
