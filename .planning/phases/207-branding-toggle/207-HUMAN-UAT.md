---
status: partial
phase: 207-branding-toggle
source: [207-VERIFICATION.md]
started: 2026-03-26T19:45:00Z
updated: 2026-03-26T19:45:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Enterprise tab visibility in browser
expected: Log in as admin with GEOLENS_EDITION=enterprise, navigate to /admin/settings — "Appearance" item appears between "Map" and "Permissions" with a paintbrush icon.
result: [pending]

### 2. Toggle round-trip with persistence
expected: In enterprise mode, open Appearance tab, toggle "Show Powered by GeoLens badge" off, navigate away and back — switch remains off, footer badge disappears immediately without page reload.
result: [pending]

### 3. Community mode badge always visible
expected: In community mode (GEOLENS_EDITION=community), footer badge is visible on main app, Appearance sidebar item is absent.
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
