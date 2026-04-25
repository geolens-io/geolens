---
phase: 223-bootstrap-infrastructure-lock
reviewed: 2026-04-25T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - getgeolens.com/docs/package.json
  - getgeolens.com/docs/astro.config.mjs
  - getgeolens.com/docs/wrangler.toml
  - getgeolens.com/docs/scripts/verify-build.sh
  - getgeolens.com/docs/src/content/docs/index.mdx
  - getgeolens.com/docs/src/styles/custom.css
  - getgeolens.com/docs/src/content.config.ts
  - getgeolens.com/docs/public/robots.txt
  - getgeolens.com/docs/public/_redirects
  - getgeolens.com/docs/tsconfig.json
  - getgeolens.com/.github/workflows/docs-ci.yml
  - getgeolens.com/.github/workflows/ci.yml
findings:
  critical: 0
  warning: 1
  info: 1
  total: 2
status: issues_found
---

# Phase 223: Code Review Report

**Reviewed:** 2026-04-25
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

All four "forever-wrong if skipped" invariants are correctly locked in:

- `astro.config.mjs` sets `site: 'https://docs.getgeolens.com'` (D-17)
- Site-wide `<meta name="robots" content="noindex, nofollow">` is injected via Starlight `head` config (D-07)
- `public/robots.txt` ships with `User-agent: *` + `Disallow: /` (defense-in-depth alongside the meta tag, D-08)
- All four sidebar groups in `astro.config.mjs` use the `/guides/` prefix (`guides/quickstart`, `guides/user`, `guides/admin`, `guides/api`) — Phase 224 cannot regress to flat URLs (D-11)
- `_redirects` ships 9 rules (3 paths x 3 variants) for `/install`, `/admin`, `/api` redirecting to `/guides/*` as 301s; `/quickstart` is correctly absent and the comment block explains why marketing owns it (D-14, D-15, D-16)

CI scaffolding is symmetric and bootstrap-race-safe:

- `docs-ci.yml` uses `paths: ['docs/**', '.github/workflows/docs-ci.yml']` (self-modification trigger included, per §7.1)
- `ci.yml` uses `paths-ignore: ['docs/**']` on both `push` and `pull_request` triggers and does NOT ignore its own path (correctly preserves self-edit triggering)
- `cloudflare/pages-action@v1` is pinned (no floating ref); secrets are only referenced via `${{ secrets.* }}` and never echoed
- The wrangler-name guard step (`grep 'name = "getgeolens-docs"' wrangler.toml`) is present in `docs-ci.yml`, mitigating §7.5
- `defaults.run.working-directory: docs` is set at the job level for both jobs, mitigating §7.6 contamination
- `verify-build.sh` is bash-safe (`set -euo pipefail`), executable (`chmod +x` confirmed via filesystem inspection), and runs after `npm run build` in the check-and-build job

Pinned dependencies in `package.json` match plan interfaces (`astro ^6.1.3`, `@astrojs/starlight ^0.38.4`, `@astrojs/sitemap ^3.7.2`, `@astrojs/check ^0.9.8`, `typescript ^5.9.3`); `package-lock.json` is committed (262 KB on disk).

The two issues below are minor robustness concerns in `verify-build.sh`. Neither blocks the phase; both could be tightened opportunistically.

## Warnings

### WR-01: `Disallow: /` assertion uses fixed-string match — would pass on a partial disallow

**File:** `getgeolens.com/docs/scripts/verify-build.sh:35`
**Issue:** The check is `grep -F 'Disallow: /' dist/robots.txt`. Because `-F` is a substring match (no anchors), this passes on lines like `Disallow: /admin`, `Disallow: /private`, etc. — not just on the intended `Disallow: /` (full-site disallow). The check is the load-bearing T-223-EARLY-INDEX gate, and the threat model explicitly states "fails the build if any flat URL appears" / "robots.txt blocks well-behaved crawlers." If a future edit to `robots.txt` accidentally narrows the disallow (e.g. flipping to `Disallow: /draft/`) while keeping the prefix, this gate would silently pass even though the site became indexable.

The exact threat is bounded: Phase 228 deliberately flips the disallow, so a future edit relaxing it is the expected change. But during the bootstrap window the assertion should be precise to its stated contract.

**Fix:** Anchor the pattern so only an exact-line `Disallow: /` matches:

```bash
echo "Asserting Disallow: / present in robots.txt..."
grep -E '^Disallow: /[[:space:]]*$' dist/robots.txt \
  || { echo "FAIL: robots.txt missing exact 'Disallow: /' line"; exit 1; }
```

The `^...$` anchors prevent substring matches; `[[:space:]]*$` tolerates a trailing newline/CRLF without permitting `/admin` etc.

## Info

### IN-01: `expected_301_count` pipeline is fragile if `_redirects` ever loses all 301 lines

**File:** `getgeolens.com/docs/scripts/verify-build.sh:20-24`
**Issue:** The pattern is:

```bash
expected_301_count=$(grep -c '301$' dist/_redirects || echo 0)
if [ "$expected_301_count" -lt 9 ]; then
```

`grep -c` always prints the count to stdout (e.g. `0`, `9`). When the count is 0, grep also exits 1, which triggers `|| echo 0` and appends a second `0`. The captured value becomes `"0\n0"` (two lines). The subsequent `[ "$expected_301_count" -lt 9 ]` then errors with `integer expression expected`, which under `set -e` could terminate with a confusing message instead of the intended `FAIL: expected at least 9 '301' rules` line.

In the success path (9 matches) grep exits 0 and the `|| echo 0` does not fire, so production runs are unaffected. This only manifests if `_redirects` is malformed — i.e. exactly the case the assertion is meant to catch — turning a clear failure message into a shell error. Plan 01's acceptance criteria already require 9 rules, so the practical risk is low.

**Fix:** Drop the redundant `|| echo 0` and let `grep -c` set the variable directly. `grep -c` with `set -e` won't kill the script inside command substitution unless `pipefail` and a pipe are involved — which isn't the case here. A safer form:

```bash
expected_301_count=$(grep -c '301$' dist/_redirects 2>/dev/null) || expected_301_count=0
if [ "$expected_301_count" -lt 9 ]; then
  echo "FAIL: expected at least 9 '301' rules in _redirects, got $expected_301_count"
  exit 1
fi
```

This puts the failure handling on the assignment line (so `expected_301_count` is exactly one integer), keeps the existing FAIL message intact, and matches the style of the other assertions in the script.

---

_Reviewed: 2026-04-25_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
