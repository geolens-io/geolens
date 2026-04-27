---
status: partial
phase: 216-geolens-cli-mvp
source: [216-VERIFICATION.md]
started: 2026-04-27
updated: 2026-04-27
---

## Current Test

[awaiting human testing]

## Tests

### 1. PyPI publish via publish-cli.yml
expected: After triggering Actions → publish-cli.yml → Run workflow with PYPI_TOKEN secret configured, `pip install geolens` in a clean venv installs the Apache-2.0 package; `geolens --version` prints `geolens <version>` matching the OpenAPI version.
result: [pending]
notes: Deferred user action per CONTEXT.md D-40 / Phase 215 D-16. Workflow scaffold ships in this phase; first publish requires user-managed credentials.

### 2. OS-native keyring backends (macOS Keychain / Windows Credential Manager / Linux Secret Service)
expected: After installing the CLI from the wheel, running `geolens login http://localhost:8001` on macOS and Windows respectively stores the access token in Keychain Access (macOS) / Credential Manager (Windows) under service `geolens` with account `<instance_url>`. Linux desktop with Secret Service stores the same way.
result: [pending]
notes: Round-trip tests use an in-memory mock keyring. Native backends cannot be exercised in CI; require manual cross-platform smoke tests.

### 3. Interactive rich.Progress UI rendering during live publish
expected: Running `geolens publish foo.geojson` interactively against a real instance renders the 4-stage progress bar (uploading, previewing, committing, done) with smooth updates and final dataset URL printed cleanly when stdout is a TTY.
result: [pending]
notes: CliRunner captures stdout as non-TTY, suppressing progress UI per D-21. Manual TTY test is the only way to verify the rich Progress experience.

### 4. Refresh-token retry on a real expiring JWT
expected: After `geolens login` against a live backend with short-lived JWTs (e.g., 60-second expiry), waiting past the access-token TTL and running `geolens whoami` triggers exactly one POST /auth/refresh (visible in backend logs), succeeds transparently, and prints the user's email. If refresh also fails, prints "Session expired — run `geolens login` again" and exits with code 3.
result: [pending]
notes: Round-trip tests use a single long-lived test JWT. Refresh retry path (D-13) is unit-tested with mocks but the live integration loop should be smoke-tested before first customer use.

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
