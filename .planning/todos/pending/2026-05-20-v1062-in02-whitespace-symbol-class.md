---
created: 2026-05-20T00:00:00Z
title: "v1062 IN-02: validate_password_complexity treats whitespace as a symbol class"
area: security
phase: 1062
severity: info
source: 1062-REVIEW.md
resolves_phase: 1071
files:
  - backend/app/modules/auth/password.py
---

## Finding

`validate_password_complexity` counts any non-alphanumeric character as the
"symbols" class, including whitespace. A 12-character password like
`Aaaaaaaaaaa1 ` (11 lowercase + 1 digit + trailing space) satisfies the
3-of-4 class requirement but is functionally weaker than intended.

## Solution

Tighten the symbol class to a defined character set (e.g., `string.punctuation`)
or explicitly exclude whitespace:

```python
SYMBOL_CLASS = set(string.punctuation) - set(string.whitespace)
```

## Deferred rationale

Edge case — a passing password with this shape is rare in practice, and the
existing 12-character minimum already provides reasonable entropy. Tighten
when convenient.
