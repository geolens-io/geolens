---
created: 2026-05-20T00:00:00Z
title: "v1063 IN-01: _sanitize_authorization_token 8-char minimum undocumented"
area: documentation
phase: 1063
severity: info
source: 1063-REVIEW.md
resolves_phase: 1071
files:
  - backend/app/processing/ingest/ogr.py
---

## Finding

`_sanitize_authorization_token` (SEC-FU-04) raises `ValueError` for tokens
shorter than 8 characters. The 8-character floor is not documented in the
docstring; a caller passing a legitimately short tracking token (some
ArcGIS deployments) hits an unhelpful error.

## Solution

Add the 8-char minimum to the docstring and explain the rationale (defense
against accidentally-truncated tokens).

## Deferred rationale

Documentation-only. No known production caller passes a token shorter than 8
characters today.
