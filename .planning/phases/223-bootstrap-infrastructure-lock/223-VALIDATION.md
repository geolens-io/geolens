---
phase: 223
slug: bootstrap-infrastructure-lock
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-25
approved: 2026-04-25
---

# Phase 223 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Phase 223 is pure infrastructure scaffolding — there is no test framework
> in the docs subtree. Validation = build artifact assertions + manual
> Cloudflare dashboard verifications.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | None — Astro/Starlight build is the test harness |
| **Config file** | `docs/astro.config.mjs` (build configuration) |
| **Quick run command** | `cd docs && npm run check` (`astro check`) |
| **Full suite command** | `cd docs && npm run build && bash scripts/verify-build.sh` |
| **Estimated runtime** | ~30s (check) / ~90s (build + assertions) |

---

## Sampling Rate

- **After every task commit:** Run `cd docs && npm run check`
- **After every plan wave:** Run `cd docs && npm run build && bash scripts/verify-build.sh`
- **Before `/gsd-verify-work`:** Full build green + manual CF dashboard checks done
- **Max feedback latency:** ~30s (check) / ~90s (build)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 223-01-* | 01 | 1 | BOOT-01 | — | `docs/` scaffold present with isolated deps | smoke | `cd docs && npm run build` exits 0 | ❌ W0 | ⬜ pending |
| 223-01-* | 01 | 1 | BOOT-02 | — | Astro pinned to `^6.1.x`, `astro check` clean | unit | `cd docs && npm run check` exits 0 | ❌ W0 | ⬜ pending |
| 223-01-* | 01 | 1 | BOOT-03 | T-223-FLAT-URL | No flat `/install` `/admin` `/api` paths in built HTML | smoke | `! grep -E 'href="/(install\|admin\|api)(/\|"\|#)' docs/dist/**/*.html` | ❌ W0 | ⬜ pending |
| 223-01-* | 01 | 1 | BOOT-04 / SEO-05 | T-223-WRONG-CANONICAL | Canonical link in built HTML resolves to docs.getgeolens.com | smoke | `grep 'rel="canonical"' docs/dist/index.html \| grep -F 'https://docs.getgeolens.com'` returns 1 line | ❌ W0 | ⬜ pending |
| 223-02-* | 02 | 2 | DEPLOY-01 | — | `getgeolens-docs` project created in CF Pages dashboard | manual | CF dashboard screenshot | manual | ⬜ pending |
| 223-02-* | 02 | 2 | DEPLOY-02 | T-223-CROSS-CONTAM | Marketing-only push doesn't trigger docs CI; docs-only doesn't trigger marketing | smoke | branch test on PR — only the matching workflow runs in Actions UI | manual via test branch | ⬜ pending |
| 223-02-* | 02 | 2 | DEPLOY-03 | T-223-TLS | TLS valid at `docs.getgeolens.com` | manual | `curl -I https://docs.getgeolens.com` returns 200 + valid cert | manual | ⬜ pending |
| 223-02-* | 02 | 2 | DEPLOY-04 | — | PR preview at `*.pages.dev` URL | manual | open a PR; verify CF Pages preview comment | manual | ⬜ pending |
| 223-01-* | 01 | 1 | MIG-02 | T-223-FLAT-URL | `dist/_redirects` matches expected three-rule pattern for `/install`, `/admin`, `/api` | unit | `diff docs/public/_redirects docs/dist/_redirects` exits 0 AND `grep -c '301$' docs/dist/_redirects` returns 9 | ❌ W0 | ⬜ pending |
| 223-01-* | 01 | 1 | CI-02 | — | `astro check` step present in `docs-ci.yml` | unit | `grep 'astro check' .github/workflows/docs-ci.yml` returns ≥ 1 match | ❌ W0 | ⬜ pending |
| 223-01-* | 01 | 1 | (noindex insurance) | T-223-EARLY-INDEX | `<meta name="robots" content="noindex, nofollow">` in built HTML AND `Disallow: /` in robots.txt | smoke | `grep 'name="robots"' docs/dist/index.html \| grep -F 'noindex'` AND `grep -F 'Disallow: /' docs/dist/robots.txt` | ❌ W0 | ⬜ pending |
| 223-01-* | 01 | 1 | (sitemap) | — | `sitemap-index.xml` generated | smoke | `test -f docs/dist/sitemap-index.xml` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Note:** SEO-06 (GA4 Measurement ID) was **deferred to Phase 228** on 2026-04-25 — see `223-CONTEXT.md` D-19. No GA4 row in this map.

---

## Wave 0 Requirements

- [ ] `docs/` directory scaffold (entire subtree created in this phase — no pre-existing infrastructure to extend)
- [ ] `docs/scripts/verify-build.sh` — single load-bearing build-artifact assertion script wired into CI
- [ ] CF Pages `getgeolens-docs` project created in dashboard BEFORE first `pages-action@v1` deploy runs
- [ ] No test framework install — none needed; build-artifact assertions are the gate

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CF Pages project exists with `rootDirectory: docs` and Build Watch Paths `docs/**` | DEPLOY-01 | Dashboard-only configuration | Screenshot the project Settings → Build & Deploy in phase summary |
| `docs.getgeolens.com` custom domain attached and TLS provisioned | DEPLOY-03 | DNS + cert provisioning is a CF-managed async step (~5min) | After first preview deploy succeeds, attach custom domain in CF dashboard, wait for TLS, then `curl -I https://docs.getgeolens.com`; capture response in phase summary |
| PR preview deploy comment appears on a real PR | DEPLOY-04 | CF Pages comments require a live GitHub App webhook | Open a docs-only PR, confirm CF Pages bot comments with `*.pages.dev` URL |
| Marketing CI is not retriggered when only `docs/**` changes (and vice versa) | DEPLOY-02 | Requires real GitHub Actions UI inspection | After merging Phase 223, push docs-only commit to a branch; in Actions UI verify only `docs-ci.yml` runs. Reverse with marketing-only commit. Capture both workflow runs. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (`scripts/verify-build.sh`)
- [x] Sampling continuity: build runs after every plan wave; no 3 consecutive tasks without `astro check`
- [x] Wave 0 covers all MISSING references (entire docs/ scaffold + verify-build.sh)
- [x] No watch-mode flags (`astro check` and `astro build` both run once-and-exit)
- [x] Feedback latency < 90s (full build)
- [ ] Manual verifications captured with screenshots / curl output in 223-SUMMARY.md *(post-execution gate)*
- [x] `nyquist_compliant: true` set in frontmatter after sign-off

**Approval:** approved 2026-04-25 (gsd-plan-checker — VERIFICATION PASSED)
