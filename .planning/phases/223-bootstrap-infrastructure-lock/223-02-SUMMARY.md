---
phase: 223-bootstrap-infrastructure-lock
plan: 02
subsystem: infra

tags:
  - github-actions
  - cloudflare-pages
  - ci-cd
  - paths-filter
  - docs-site
  - build-isolation

# Dependency graph
requires:
  - phase: 223-01
    provides: "docs/ subtree with package-lock.json, .nvmrc, wrangler.toml (name=getgeolens-docs), and scripts/verify-build.sh — all referenced by the new docs-ci.yml workflow"
  - phase: external-getgeolens.com
    provides: "Existing CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID GitHub secrets and marketing ci.yml template (D-05)"

provides:
  - "GitHub Actions workflow `.github/workflows/docs-ci.yml` (check → build → verify-build.sh → cloudflare/pages-action@v1) with paths filter on docs/** + self-modification trigger"
  - "Marketing `.github/workflows/ci.yml` patched with symmetric paths-ignore: ['docs/**'] on push and pull_request triggers — minimal +4/-0 diff"
  - "Build isolation between the two Astro projects at the CI layer (T-223-CROSS-CONTAM mitigation, file-side complete)"
  - "Plan-2 file infrastructure ready for first deploy — operator can run the deferred CF Pages dashboard steps any time without further code changes"

affects:
  - 223 (phase closure — file-task portion of DEPLOY-01..04 in place; live-deploy verification deferred)
  - 224 (BRAND-01..04, SHELL-01..05, SEARCH-01..03 — all docs-only edits will route through docs-ci.yml without triggering marketing CI once that workflow runs in production)
  - 225 (API-01..05 — same docs-ci.yml gate)
  - 226-227 (content phases — depend on the path-filter symmetry to avoid cross-contaminating builds)
  - 228 (SEO go-live — robots.txt + noindex flip, GA4 install, sitemap submission; this plan's deploy verification belongs to the same trip back to the CF Pages dashboard)

# Tech tracking
tech-stack:
  added:
    - "cloudflare/pages-action@v1 (deprecated but mirrored from marketing per D-01; lockstep migration to wrangler-action@v3 deferred)"
    - "GitHub Actions paths/paths-ignore filter pattern (symmetric pair across two workflows in one repo, per D-02 / RESEARCH §3.5 / §7.4)"
  patterns:
    - "Two-workflow build isolation: docs-ci.yml watches docs/**, ci.yml ignores docs/** — neither cross-triggers on single-subtree commits, both run on mixed-subtree PRs"
    - "Self-modification trigger: each workflow includes its own file path in paths: so workflow edits run themselves (per RESEARCH §7.1)"
    - "Wrangler-name guard step: `grep 'name = \"getgeolens-docs\"' wrangler.toml` runs early in CI as cheap insurance against the projectName-vs-wrangler-toml drift pitfall (§7.5)"
    - "verify-build.sh wired into CI as a hard gate — Plan 01's load-bearing assertions now fail the build, not just local diff"

key-files:
  created:
    - "/Users/ishiland/Code/getgeolens.com/.github/workflows/docs-ci.yml (60 lines; getgeolens.com@8726935)"
  modified:
    - "/Users/ishiland/Code/getgeolens.com/.github/workflows/ci.yml (+4/-0; getgeolens.com@836076d)"

key-decisions:
  - "Mirror marketing's `cloudflare/pages-action@v1` despite deprecation (D-01) — coordinated migration to wrangler-action@v3 is a future cross-repo task requiring user re-decision"
  - "Reuse existing CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID GitHub secrets (D-05) — no new secrets minted, narrowing the secret-leak surface"
  - "Path-filter symmetry only — neither workflow lists the OTHER workflow's path in its filter (RESEARCH §3.5 + §7.1). Self-edits to either workflow still trigger that workflow as a sanity check"
  - "Deploy verification (CF Pages project creation, custom domain attachment, TLS, probe PRs) deferred to operator. Workflow files exist on disk and are syntactically valid but UNDEPLOYED. Operator chose to develop docs locally first."

patterns-established:
  - "Pattern 1: Per-workstream CI workflow with path-filter isolation in a single repo — replicable for any future subtree (e.g. /examples, /storybook) without moving repos"
  - "Pattern 2: External-repo planning artifact tracking — Plan 02's code commits live in /Users/ishiland/Code/getgeolens.com (separate repo); planning commits live in /Users/ishiland/Code/geolens. Each commit message references the other repo's hash for traceability"
  - "Pattern 3: Honest-state SUMMARY — when human-action checkpoints are deferred, the summary must distinguish file-task completion from live-verification deferral so /gsd-progress and /gsd-audit-uat surface the gap"

requirements-completed:
  - CI-02

requirements-deferred:
  - DEPLOY-01
  - DEPLOY-02
  - DEPLOY-03
  - DEPLOY-04

# Metrics
duration: ~10min (Tasks 1-2 prior session ~5 min; finalization session ~5 min)
completed: 2026-04-25
---

# Phase 223 Plan 02: Deploy & Production Cutover Summary

**Docs CI workflow + symmetric paths-ignore patch shipped to getgeolens.com repo; Cloudflare Pages dashboard work + custom domain TLS + build-isolation probe PRs deferred — operator chose to develop docs locally first, will return to deploy when ready.**

## Status: Partial — File Tasks Complete, Live-Deploy Verification Deferred

**File-task portion (Tasks 1 + 2): COMPLETE.** Two commits in `/Users/ishiland/Code/getgeolens.com`:
- `8726935` — `feat(docs-ci): add Docs CI workflow with check, build, verify, deploy`
- `836076d` — `fix(ci): add symmetric paths-ignore docs/** to marketing CI`

**Live-deploy portion (Task 3 / DEPLOY-01..04): DEFERRED.** No CF Pages project created, no custom domain attached, no TLS verification, no probe PRs run. Operator decision: develop docs locally first, deploy later.

The phase is **not** fully closed. The `Deferred Verification` section below preserves the exact resume steps so this can be picked up at any time without re-deriving them.

## Performance

- **Plan started:** 2026-04-25T18:09:56Z (Tasks 1-2 prior session)
- **File tasks completed:** 2026-04-25T18:14:54Z (last code commit on getgeolens.com)
- **Finalization (this commit):** 2026-04-25T19:14:18Z
- **Duration (file tasks):** ~5 min
- **Duration (incl. checkpoint resolution):** ~1h 5min wall-clock; ~10 min active execution
- **Tasks attempted:** 3
- **Tasks complete (file-side):** 2 of 3
- **Tasks deferred:** 1 of 3 (Task 3 — operator action)
- **Files created (implementation repo):** 1 (docs-ci.yml)
- **Files modified (implementation repo):** 1 (ci.yml)
- **Files modified (planning repo):** 4 (this SUMMARY.md, STATE.md, ROADMAP.md, REQUIREMENTS.md)

## What Shipped

### `getgeolens.com/.github/workflows/docs-ci.yml` (created — getgeolens.com@8726935)

60-line workflow file with two jobs (`check-and-build` → `deploy`). Triggers on `push` to `main` and on `pull_request`, both filtered with:

```yaml
paths:
  - 'docs/**'
  - '.github/workflows/docs-ci.yml'
```

Self-modification trigger included per RESEARCH §7.1. `defaults.run.working-directory: docs` set at job level on BOTH jobs (RESEARCH §7.6) — `npm install` and all subsequent steps run inside `docs/`, never at repo root.

Pipeline:
1. `actions/checkout@v4`
2. `actions/setup-node@v4` with `node-version-file: docs/.nvmrc` and `cache-dependency-path: docs/package-lock.json`
3. `npm ci`
4. `grep 'name = "getgeolens-docs"' wrangler.toml` — wrangler-name guard step (pitfall §7.5)
5. `npx astro check` — **CI-02 satisfied**
6. `npm run build`
7. `bash scripts/verify-build.sh` — wires Plan 01's load-bearing assertion gate into CI
8. `cloudflare/pages-action@v1` with `projectName: getgeolens-docs`, `directory: docs/dist`, reusing `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` secrets per D-05

No a11y, no GA4, no wrangler-action — Phase 228 / D-19 boundaries respected.

### `getgeolens.com/.github/workflows/ci.yml` (patched — getgeolens.com@836076d)

Minimal +4/-0 diff: `paths-ignore: ['docs/**']` added under both `on.push` and `on.pull_request`. All original jobs/steps (`check-and-build`, `Accessibility scan`, `deploy`, marketing's `cloudflare/pages-action@v1` with `projectName: getgeolens-com`) preserved unchanged.

Path-filter dry-run reasoning (validated by static analysis only — no live PRs run):
- **docs-only commit** (e.g. `docs/foo.mdx`) → docs-ci `paths` matches → docs-ci runs; ci `paths-ignore` matches all → ci skipped ✓
- **marketing-only commit** (e.g. `src/index.astro`) → docs-ci `paths` does not match → docs-ci skipped; ci `paths-ignore` does not cover all changed files → ci runs ✓
- **mixed commit** (e.g. `docs/foo.mdx` + `src/index.astro`) → docs-ci runs; ci runs (paths-ignore only skips when ALL files match) ✓

`paths-ignore` does NOT include `'.github/workflows/ci.yml'` per RESEARCH §3.5 — self-edits to the marketing workflow still trigger marketing CI as a pre-merge sanity check.

## Task Commits

| Task | Name | Implementation repo | Planning repo (state) | Status |
|---|---|---|---|---|
| 1 | Create `.github/workflows/docs-ci.yml` | getgeolens.com@`8726935` (feat) | geolens@`fcc72f16` (state) | ✓ complete |
| 2 | Patch `ci.yml` with paths-ignore: ['docs/**'] | getgeolens.com@`836076d` (fix) | geolens@`9484593c` (state) | ✓ complete |
| 3 | CF Pages dashboard + custom domain + TLS + probe PRs | — | — | **DEFERRED — operator developing locally; will run deferred steps later** |

**Plan finalization commit (this SUMMARY.md + STATE.md + ROADMAP.md + REQUIREMENTS.md):** to follow this commit in the planning repo.

## Files Created/Modified

### Implementation repo (`/Users/ishiland/Code/getgeolens.com`)

- **created** `.github/workflows/docs-ci.yml` — 60 lines, two jobs, paths filter on `docs/**` + workflow self-trigger, wires `npx astro check` (CI-02) + `bash scripts/verify-build.sh` (Plan 01 gate) + `cloudflare/pages-action@v1` (D-01 mirror with D-05 secret reuse)
- **modified** `.github/workflows/ci.yml` — +4/-0: `paths-ignore: ['docs/**']` added under push and pull_request

### Planning repo (`/Users/ishiland/Code/geolens`)

- **modified** `.planning/phases/223-bootstrap-infrastructure-lock/223-02-SUMMARY.md` — this file (created in finalization commit)
- **modified** `.planning/STATE.md` — plan counter advanced (1 → 2 of 2 with deferred-deploy caveat), last_activity refreshed
- **modified** `.planning/ROADMAP.md` — Plan 02 checkbox flipped to `[x]` with deferred-deploy note; phase progress table row updated
- **modified** `.planning/REQUIREMENTS.md` — CI-02 traceability row → Complete; DEPLOY-01..04 traceability rows → Partial (deferred)

## Requirements Coverage

### Complete

- **CI-02** — `npx astro check` runs as a step in `docs-ci.yml`. Validated by reading the committed file at `/Users/ishiland/Code/getgeolens.com/.github/workflows/docs-ci.yml` line 30 (`- run: npx astro check`). Will execute on first GitHub Actions trigger; no live verification required for the workflow-file artifact itself.

### Deferred (file infrastructure ready, live deploy not yet executed)

- **DEPLOY-01** — Second Cloudflare Pages project. Workflow file references `projectName: getgeolens-docs`; CF Pages dashboard project with `rootDirectory: docs` and `Build Watch Paths: docs/**` does NOT yet exist. **What's still needed:** create the project in the CF dashboard. Resume step 1 in Deferred Verification section.
- **DEPLOY-02** — Path-filter build isolation. File-side complete: docs-ci.yml `paths` and ci.yml `paths-ignore` are both committed. **What's still needed:** open two probe PRs (docs-only, marketing-only) and confirm in GitHub Actions UI that only the corresponding workflow runs in each. Resume step 6 in Deferred Verification section.
- **DEPLOY-03** — Custom domain `docs.getgeolens.com` with TLS. **What's still needed:** dashboard custom-domain attachment + `curl -I https://docs.getgeolens.com` returning HTTP/2 200 without `-k`. Resume steps 4–5 in Deferred Verification section.
- **DEPLOY-04** — PR preview deploys via `*.pages.dev` bot comments. **What's still needed:** open a docs-only PR after the CF Pages project exists; confirm bot comment with `*.pages.dev` URL appears. Resume step 7 in Deferred Verification section.

## Threat Mitigations

| Threat | Disposition | Status |
|--------|-------------|--------|
| **T-223-CROSS-CONTAM (Plan 02 portion)** | mitigate | **File-side complete.** docs-ci.yml has `defaults.run.working-directory: docs` at job level; ci.yml has symmetric paths-ignore. Static analysis confirms the filter logic. **Live-PR validation deferred** — Step 6 of Deferred Verification will close this loop with two probe PRs. |
| **T-223-TLS** | mitigate | **DEFERRED — live deploy required.** No CF Pages project, no custom domain, no `curl -I` evidence yet. Resume step 5 of Deferred Verification. |
| **T-223-SECRETS** | mitigate | **Partial.** D-05 honored: workflow files reference existing `secrets.CLOUDFLARE_API_TOKEN` + `secrets.CLOUDFLARE_ACCOUNT_ID`; no new secrets minted. `cloudflare/pages-action@v1` is pinned to `@v1` (not floating tag) per supply-chain hygiene. Live secret-resolution will be observed when the workflow runs for the first time after Step 3 of Deferred Verification. |
| **T-223-EARLY-INDEX (production check)** | mitigate | **Plan 01 portion validated locally** (build artifact `verify-build.sh` asserts noindex meta + `Disallow: /` in robots.txt, both present in `dist/`). **Production validation DEFERRED** — Step 5 of Deferred Verification spot-checks the live URL. |

## Deviations from Plan

None. Tasks 1 and 2 executed exactly as specified by the plan's `<action>` blocks. Task 3 was a `checkpoint:human-action` by design — deferring it is operator choice, not a deviation from plan structure. The plan's checkpoint pattern explicitly handles this case.

## Issues Encountered

- **None during file-task execution.** YAML parsed cleanly first try; the wrangler-name guard step matched on first try; the `git diff .github/workflows/ci.yml` showed exactly the +4/-0 minimal patch the plan specified.
- **Auto-fix attempt counter at finalization:** zero. No code changes needed beyond what the plan prescribed.
- **`gsd-sdk query roadmap.update-plan-progress 223` returned `updated: false, reason: "no matching checkbox found"`** — this is a known SDK quirk: the handler regex matches `(-\s*\[\s*\]\s*(?:Plan\s+\d+|plan\s+\d+|\*\*Plan))` but ROADMAP.md's listing format is `- [ ] 223-02-PLAN.md — ...` which doesn't include the literal word "Plan" before a digit. Worked around by editing the ROADMAP.md checkbox + Progress Table row directly. Not a deviation — purely a tracking-tool quirk for an unrelated handler.
- **`gsd-sdk query state.advance-plan` returned `Cannot parse Current Plan or Total Plans from STATE.md`** — STATE.md uses YAML frontmatter (`progress.completed_plans` / `progress.total_plans`) not "Current Plan: N" prose lines. Worked around by editing STATE.md directly. Not a deviation.

## Deferred Verification (Operator Action Required Before Phase 228 Ships)

**This section preserves the exact resume steps from the original Task 3 checkpoint. When the operator returns to deploy, run these in order. Each step has the exact command or dashboard click — no re-derivation needed.**

### Step 1 — Create the CF Pages project (must happen BEFORE next push to main)

Open https://dash.cloudflare.com/?to=/:account/pages → Create a project → Connect to Git → select `getgeolens.com` repo → Begin setup. Set:
- **Project name:** `getgeolens-docs` (MUST match `wrangler.toml` `name` field — workflow's `grep` guard will fail otherwise)
- **Production branch:** `main`
- **Framework preset:** Astro
- **Build command:** `npm run build`
- **Build output directory:** `dist`
- **Root directory (advanced):** `docs`
- **Environment variables:** none

Save and Deploy. The first deploy may fail if `docs/` isn't on `main` yet — that's expected; the project just needs to exist before `pages-action@v1` first invokes.

### Step 2 — Configure Build Watch Paths (DEPLOY-01)

In the CF dashboard → `getgeolens-docs` project → Settings → Build & Deploy → Build Watch Paths:
- Set: `docs/**`

Capture screenshot of the project Settings page showing `rootDirectory: docs` and `Build Watch Paths: docs/**` for the future phase summary update.

### Step 3 — Trigger first deploy

Push a commit on `main` that touches `docs/**` (or merge an open PR). In https://github.com/<owner>/getgeolens.com/actions, verify:
- "Docs CI" workflow runs
- "CI" workflow does NOT run (D-02 path-filter validation)
- `check-and-build` job: green (~60-90s)
- `deploy` job: green (~30-60s)

Smoke test:
```sh
curl -I https://getgeolens-docs.pages.dev
```
Expected: HTTP/2 200, valid TLS, `content-type: text/html`. If 404, project name mismatch.

### Step 4 — Attach custom domain (DEPLOY-03)

CF dashboard → `getgeolens-docs` → Custom domains → Set up a custom domain → enter `docs.getgeolens.com` → Continue. CF auto-creates the CNAME in the existing `getgeolens.com` zone (apex already on Cloudflare). Wait 3–5 min for TLS. If TLS hangs >15 min, delete + recreate the custom domain attachment.

Capture screenshot of the Custom domains page showing `docs.getgeolens.com` Active with valid TLS.

### Step 5 — Verify TLS at custom domain (T-223-TLS, D-06)

```sh
curl -I https://docs.getgeolens.com
```
MUST return HTTP/2 200 without `-k` flag (no `-k` = TLS validation on; exit 0 = chain valid).

Save curl output. Additional spot checks:
```sh
curl -s https://docs.getgeolens.com/robots.txt | grep "Disallow: /"
curl -s https://docs.getgeolens.com/ | grep 'name="robots"'
curl -I https://docs.getgeolens.com/install
```
Expected: robots.txt `Disallow: /` present (T-223-EARLY-INDEX still active in production); index page contains `<meta name="robots" content="noindex, nofollow">`; `/install` returns HTTP 301 to `/guides/install` (MIG-02 working at edge).

### Step 6 — Build-isolation probe PRs (DEPLOY-02 / T-223-CROSS-CONTAM live validation)

```sh
cd /Users/ishiland/Code/getgeolens.com
git checkout -b test/docs-only-trigger
echo "# test" >> docs/README.md
git add docs/README.md && git commit -m "test: docs-only commit"
git push origin test/docs-only-trigger
gh pr create --title "test: docs-only trigger" --body "Verifying DEPLOY-02 path-filter isolation"
```
Verify in GitHub Actions UI: "Docs CI" runs ✓, "CI" does NOT run ✗.

```sh
git checkout main && git pull
git checkout -b test/marketing-only-trigger
echo "<!-- test -->" >> README.md
git add README.md && git commit -m "test: marketing-only commit"
git push origin test/marketing-only-trigger
gh pr create --title "test: marketing-only trigger" --body "Verifying DEPLOY-02 reverse path-filter"
```
Verify: "CI" runs ✓, "Docs CI" does NOT run ✗.

Capture screenshots of both Actions UI views. Close (don't merge) both probe PRs.

### Step 7 — Verify PR preview comment (DEPLOY-04)

The docs-only test PR from Step 6 should receive a CF Pages bot comment with a `*.pages.dev` preview URL within ~2 min of the deploy job finishing. Confirm the comment appears. If absent, check that `permissions.pull-requests: write` is on the deploy job (it is — line 41 of docs-ci.yml).

Capture screenshot of the PR with the bot comment.

### Resume signal

Once Steps 1-7 are complete, append a follow-up section to this SUMMARY.md (or write a `223-02-DEPLOY-VERIFICATION.md` companion) flipping DEPLOY-01..04 from Deferred to Complete, and update REQUIREMENTS.md traceability rows. The implementation-repo workflow files do NOT need any further changes.

## Hand-off

**Local development is unblocked today.** The operator can:
```sh
cd /Users/ishiland/Code/getgeolens.com/docs
npm run dev
```
and iterate on docs content (Phase 224 brand + shell + search work) without needing a live deploy. The workflow file exists locally; pushing it does not break anything (it just won't deploy successfully until Step 1–2 run).

**Phase 224 can build on the scaffold.** All Plan 01 + Plan 02 file artifacts are in place: pinned deps, working `npm run build`, locked `/guides/` URL structure, brand-color placeholder in `custom.css`, sidebar groups stubbed in `astro.config.mjs`, verify-build.sh as the local gate. Phase 224's BRAND-01 / BRAND-02 / SHELL-01..05 / SEARCH-01..03 work can begin immediately.

**Deploy can happen anytime.** No blocking dependency between Phase 224 content work and the deferred Step 1–7. Operator returns to the CF Pages dashboard whenever ready; until then the docs site lives only locally and on GitHub (in branch state — not deployed).

**Phase 228 must close the loop.** SEO-03 (sitemap submission to GSC) and the noindex flip require a live URL. Phase 228 cannot ship until Step 1–7 complete. This is the latest acceptable date for the deferred deploy.

## Self-Check: PARTIAL — File-Task Acceptance PASSED, Live-Deploy Acceptance DEFERRED

### File-Task Acceptance: PASSED

```
$ git -C /Users/ishiland/Code/getgeolens.com show --stat 8726935 | head -2
commit 87269355f89327ea6cbe7dba12b9a4f9a360f1c0
Author: Ian Shiland <ishiland@gmail.com>
✓ FOUND: getgeolens.com@8726935

$ git -C /Users/ishiland/Code/getgeolens.com show --stat 836076d | head -2
commit 836076d2e45fc3b162aca422e6fb4a8f8bdc41a4
Author: Ian Shiland <ishiland@gmail.com>
✓ FOUND: getgeolens.com@836076d

$ test -f /Users/ishiland/Code/getgeolens.com/.github/workflows/docs-ci.yml && echo FOUND
FOUND

$ test -f /Users/ishiland/Code/getgeolens.com/.github/workflows/ci.yml && echo FOUND
FOUND

$ python3 -c "import yaml; yaml.safe_load(open('/Users/ishiland/Code/getgeolens.com/.github/workflows/docs-ci.yml'))" && echo "docs-ci.yml ✓"
docs-ci.yml ✓

$ python3 -c "import yaml; yaml.safe_load(open('/Users/ishiland/Code/getgeolens.com/.github/workflows/ci.yml'))" && echo "ci.yml ✓"
ci.yml ✓
```

All file-task acceptance criteria from the plan's `<acceptance_criteria>` blocks for Tasks 1 and 2 are satisfied on disk. CI-02 is satisfied (the `npx astro check` step is present in docs-ci.yml).

### Live-Deploy Acceptance: DEFERRED (NOT FAILED)

The plan's success criteria #1, #3, #4, #5, #6, #7, #8 require a live deploy that has not been executed. They are not failing — they are pending the operator's return to the CF Pages dashboard (Steps 1–7 above).

```
$ curl -I https://docs.getgeolens.com
DEFERRED — site not yet deployed at custom domain.

$ # CF Pages project exists?
DEFERRED — to be created in Step 1.

$ # Build-isolation probe PRs run?
DEFERRED — to be opened in Step 6.

$ # CF Pages bot preview comment?
DEFERRED — depends on Step 1 + Step 6.
```

Self-check honest summary: **the file-task work is complete and committed; the deploy-verification work is preserved as a clearly-scoped resume-able set of steps**. The /gsd-progress and /gsd-audit-uat tooling will surface DEPLOY-01..04 as partial/deferred — that is the intended state.

---
*Phase: 223-bootstrap-infrastructure-lock*
*Plan 02 finalized (file tasks): 2026-04-25*
*Deploy verification: deferred to operator; resume steps preserved above*
