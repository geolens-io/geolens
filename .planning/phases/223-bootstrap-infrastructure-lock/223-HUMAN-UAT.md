---
status: partial
phase: 223-bootstrap-infrastructure-lock
source: [223-VERIFICATION.md]
started: 2026-04-25T19:35:00Z
updated: 2026-04-25T19:35:00Z
---

## Current Test

[awaiting human testing — operator chose to develop docs locally first; resume when ready to deploy]

## Tests

### 1. Create CF Pages project `getgeolens-docs` in the Cloudflare dashboard
requirement: DEPLOY-01
expected: Project exists at https://dash.cloudflare.com/?to=/:account/pages/view/getgeolens-docs with rootDirectory=docs and Build Watch Paths=docs/**
why_human: CF Pages project creation with rootDirectory + Build Watch Paths is dashboard-only; `wrangler pages project create` does not support rootDirectory per CF docs. Reuses existing CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID per D-05; no new secrets needed.
resume_step: 223-02-SUMMARY.md Deferred Verification Step 1-2
result: [pending]

### 2. Verify CI workflow path-filter isolation via probe PRs
requirement: DEPLOY-02
expected: GitHub Actions UI shows — docs-only commit triggers ONLY 'Docs CI' (not 'CI'); marketing-only commit triggers ONLY 'CI' (not 'Docs CI'); mixed PR triggers both
why_human: Path-filter symmetry can only be observed against a live GitHub Actions trigger. Static analysis confirms the YAML is correct, but the runtime behavior must be observed. Open two probe PRs as described in 223-02-SUMMARY.md Deferred Verification Step 6.
resume_step: 223-02-SUMMARY.md Deferred Verification Step 6
result: [pending]

### 3. Verify TLS at custom domain after attaching docs.getgeolens.com
requirement: DEPLOY-03
expected: `curl -I https://docs.getgeolens.com` returns HTTP/2 200 with valid TLS chain (no -k flag needed; curl exits 0)
why_human: Custom domain attachment is dashboard-only; TLS is provisioned by CF Universal SSL (~3-5 min after attach). DNS for docs.getgeolens.com does not currently resolve (NXDOMAIN), confirming the custom domain has not been attached yet.
resume_step: 223-02-SUMMARY.md Deferred Verification Steps 4-5
result: [pending]

### 4. Confirm Cloudflare Pages bot preview comment on docs-only PR
requirement: DEPLOY-04
expected: Within ~2 minutes of the deploy job finishing, the PR receives an automated comment from the cloudflare-pages bot with a clickable https://<sha>.getgeolens-docs.pages.dev URL
why_human: PR preview comments are emitted only after a real deploy fires from a real PR. Workflow has `permissions.pull-requests: write` on the deploy job (file-side prerequisite met).
resume_step: 223-02-SUMMARY.md Deferred Verification Step 7
result: [pending]

### 5. Production noindex insurance still active after live deploy
requirement: T-223-EARLY-INDEX (production)
expected: `curl -s https://docs.getgeolens.com/robots.txt` contains `Disallow: /` AND `curl -s https://docs.getgeolens.com/` contains `<meta name="robots" content="noindex, nofollow">`
why_human: Local dist/ artifact has both gates verified (verify-build.sh exits 0). Production validation requires the live deploy to confirm the artifact reached the edge intact. Phase 228 will spot-check this when flipping the noindex/Disallow flags together.
resume_step: 223-02-SUMMARY.md Deferred Verification Step 5 spot checks
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps
