---
quick_id: 260502-c19
researched: 2026-05-02
domain: meta-review of `.claude/commands/star-audit.md` slash command
confidence: HIGH (file inspected line-by-line; geolens facts cross-checked against README.md, CLAUDE.md memory, CHANGELOG.md, repo filesystem, git tags)
---

# Quick Task 260502-c19 — Star-audit command review (research)

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Output mode:** Edit `.claude/commands/star-audit.md` in place. One atomic commit. No separate findings doc.
- **Release scope:** Repo-surface readiness — version sync, leftover internal refs, removed-component refs, CHANGELOG hygiene, demo liveness flag, LICENSE match, `.env.example` heuristics, "WIP/Coming soon", stale screenshots.
- **Geolens facts to update:** PostGIS + pgvector + pg_trgm + Titiler. `pg_tileserv` removed v7.0; `pg_featureserv` removed v2.2. 1.0.0 release on 2026-04-01 (versions reset 13.x → 1.0.0). v13.2 latest milestone (2026-04-30). Open-core boundary mentioned briefly.
- **Structure:** Add Subagent F (Public-Release Readiness) as 6th parallel auditor in Phase 2. Add Phase 2.5 release-readiness gate. Update Phase 4 `--write` to include readiness artifacts. Update star-velocity scoring table.

### Claude's Discretion
- Wording of Subagent F prompts and bash blocks
- Phase numbering (keep 2.5 for minimal diff)
- Whether Subagent F BLOCKS or annotates report — recommendation: surface BLOCKERS section if any P0 readiness issue, otherwise weave findings into prioritised plan
- Trim redundant sections opportunistically (no major restructuring)

### Deferred Ideas
- None recorded (out of scope: actually running the audit, README edits, other commands)

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| COMPLETE | Cover star-growth audit dimensions the file misses today | §1 — gap inventory with insertion targets |
| CORRECT | Geolens facts must match the 1.0.0 repo state | §2 — line-by-line factual mismatch table |
| READY | Add public-release readiness checks (Subagent F) | §3 — concrete bash/grep checks per CONTEXT.md decision list |

---

## §1 — Completeness gaps in `.claude/commands/star-audit.md`

The current file (827 lines) covers first-impression, discoverability, trust, community, distribution. It is **silent on several star-friction dimensions that high-converting OSS launches consistently address**. Each finding below: WHAT (gap) / WHERE (slot in current structure) / HOW (one-liner of what to add).

| # | Gap | WHERE it slots | HOW to add |
|---|-----|----------------|------------|
| C1 | **Competitive positioning matrix.** No prompt to enumerate competing tools (other geo-data catalogs, OGC servers, e.g. GeoNetwork, pycsw, Felt, Atlas, ArcGIS Hub) and articulate why a visitor should pick this one. Visitors compare; the README must answer "vs X" implicitly. | Subagent A — add as section after "anti-patterns" (~line 153). | New prompt: "List the 3–5 closest comparable repos and write a one-sentence differentiator for each. If no comparison fits in the README, add a `## Compared to` collapsed section." |
| C2 | **`npm`/`PyPI`/`Docker Hub` install-flow audit.** geolens ships a Python CLI, two SDKs (Python + TS), and a Docker image. The command never asks: do install instructions actually copy-paste cleanly into a fresh terminal? Are package names resolvable? Is `docker pull ghcr.io/...` documented? | New mini-section in Subagent A under "QUICK START" (~line 117). | Add: "Verify every copy-paste install line by running it dry. Confirm package names exist on registry: `npm view @geolens/sdk`, `pip index versions geolens-sdk`, `docker manifest inspect ghcr.io/geolens-io/geolens:latest`." |
| C3 | **First-run video / Loom.** Subagent E mentions "A Loom video" once (~line 532) but it's not in the README structure or scoring table. A 60-second screencap of `docker compose up` → working UI is the single highest-converting visual asset for stack-heavy projects. | Subagent A "WHAT IT LOOKS LIKE" (~line 122) and Phase 3 scoring table (~line 583). | Add row to scoring table: `60s "first run" screencast \| 2h \| +30–50% README-to-clone conversion`. Add to Subagent A: "If no GIF or video exists, recommend recording a 30–60s `docker compose up` → login → upload demo." |
| C4 | **GitHub Sponsors / `FUNDING.yml` as discovery (not just trust).** `FUNDING.yml` is mentioned in Subagent D (~line 411) as a trust signal, but its discovery side-effect (sponsor listings, GitHub recommendations, `❤️ Sponsor` button on every PR) is not surfaced. | Subagent D enhance existing block. | Add: "Beyond trust, `FUNDING.yml` puts the repo in GitHub's sponsor-discovery surfaces and adds a `❤️ Sponsor` button on every PR/issue, increasing per-page conversion." |
| C5 | **GitHub search-result snippet quality.** GitHub search-result cards show: name, description, stars, language, **last 256 chars of README**. The command never audits how the README's first paragraph LOOKS as a snippet. | Subagent B (~line 199, GitHub description block). | Add: "Render the first 200 chars of README and the GitHub description side-by-side. Both should be standalone-readable. Reject if either starts with markup, badges, or boilerplate." |
| C6 | **Star history / momentum chart.** Repos with visible star-history charts (e.g. star-history.com embed in README) get a self-reinforcing "this is taking off" signal. Not mentioned. | Subagent A — badges block (~line 154). | Add: "Embed a star-history chart in the README near the bottom: `![Star History](https://api.star-history.com/svg?repos=geolens-io/geolens&type=Date)`. After 200+ stars this becomes social proof; before then, omit." |
| C7 | **README accessibility / visual quality on mobile + dark mode.** Many devs scroll READMEs on mobile. Hero GIFs that are huge files, screenshots that don't render in dark mode, badges that overflow — all kill conversion. Not addressed. | Subagent A new sub-block after badges. | Add: "Verify README renders cleanly on (a) mobile width (≤ 375px), (b) GitHub dark mode (use `#gh-dark-mode-only` / `#gh-light-mode-only` for theme-specific images), (c) raw text RSS readers (no HTML-only content above the fold)." |
| C8 | **Comparison "where this fits" diagram for crowded categories.** A simple "data lake catalog (✗) — internal data portal (✗) — geo data catalog with semantic search (✓ here)" 2×2 or quadrant aids positioning. | Subagent A architecture section (~line 126). | Add: "Consider a positioning quadrant or a one-line capability matrix vs alternatives." |
| C9 | **Maintainer responsiveness as a public metric.** GitHub now shows a "Median time to respond" insight. Repos optimising for stars should know this metric and pin a recent issue/PR they handled fast. | Subagent C trust block (~line 263). | Add: "Run `gh api repos/:owner/:repo/issues --paginate --jq 'length'` for open vs closed counts. Aim for closed > open. Stale unanswered issues older than 90 days hurt trust — recommend triage pass." |
| C10 | **Internationalisation/locale signal.** Geolens already ships en/es/fr/de (per CHANGELOG); the README never mentions it. i18n support is a quiet trust signal especially for non-US adopters. | Subagent B SEO block (~line 224) and Subagent A features. | Add: "If the project supports multiple locales, mention them in the README features bullet (`🌍 Available in en/es/fr/de`)." |
| C11 | **`good first issue` discoverability test.** Subagent D (~line 376) mentions creating them, but doesn't tell the auditor to actually open `https://github.com/<repo>/labels/good%20first%20issue` and confirm the label has open issues now. | Subagent D extend. | Add bash: `gh issue list --label "good first issue" --state open --json number --jq 'length'`. Flag if 0. |
| C12 | **Awesome-list ROI verification.** Lists awesome-fastapi etc. (~line 247) but doesn't say to read CONTRIBUTING for each list to confirm submission requirements (some require a website, some require >100 stars before accepting). Wasted PR cost. | Subagent B awesome-list block. | Add: "Before drafting the PR, fetch each awesome list's CONTRIBUTING.md and verify the project meets the bar (often: ≥ 100 stars, working demo, license)." |
| C13 | **Twitter/X thread is dated (2025 framing).** The thread template (~line 482–515) says "I've been building" and includes "⭐ if useful" — flagged as anti-pattern in this same file (line 797). Internal contradiction. | Subagent E thread template. | Remove the "⭐ if useful" line. Update tense / drop the "in 2025" framing (see also CORRECT-7). |
| C14 | **Phase 4 `--write` produces drafts that conflict with current repo state.** The `CHANGELOG.md` template (~line 725) and `CONTRIBUTING.md` template (~line 612) would overwrite real, multi-thousand-line files with stubs if blindly applied. No "do not overwrite if file exists with > N lines" guard. | Phase 4 (~line 595). | Add at top of Phase 4: "For each artifact: if a file already exists at the target path, **diff against the existing version and produce a patch**, do not overwrite. Skip generation if the existing file is materially complete." |
| C15 | **No "Do nothing" prompt.** A meta-audit that always finds work to do is suspicious. The command should permit a "the README is fine as-is, ship it" verdict. | Phase 3 prioritised plan (~line 546). | Add to plan template: "If audit finds no changes scoring ≥ Medium impact, the report should state that explicitly and recommend launching the existing README." |

**Insertion summary for §1:** all gaps fit inside existing Subagents A–E or Phase 3/4. No restructuring required beyond the new Subagent F (§3).

---

## §2 — Correctness issues (geolens-specific facts)

Every claim in `.claude/commands/star-audit.md` that names a geolens-specific stack element, version, or release was checked against:
- `/Users/ishiland/Code/geolens/README.md` (current as of 2026-05-02)
- `~/.claude/projects/-Users-ishiland-Code-geolens/memory/MEMORY.md` (auto-memory; project stack section)
- `/Users/ishiland/Code/geolens/CHANGELOG.md` (top of file)
- `/Users/ishiland/Code/geolens/frontend/package.json` (`"version": "1.0.0"`)
- `/Users/ishiland/Code/geolens/backend/pyproject.toml` (`version = "1.0.0"`)
- `git tag --sort=-version:refname` → most recent published: `v13.2`. (Note: `v14.0` and `v13.3` tags exist locally per `git tag` but the public release line is 1.0.0. v13.x tags pre-date the 1.0.0 reset and are historical.)

| # | WHAT (mismatch) | WHERE (`star-audit.md` line) | HOW (rewrite) |
|---|-----------------|-------------------------------|----------------|
| F1 | Header stack omits Titiler, MapLibre, Valkey, MinIO, Procrastinate. Says only "React · FastAPI · Postgres · PostGIS · pg_trgm · pgvector". | Line 2 | Replace with: `# Stack: React 19 + MapLibre · FastAPI · PostgreSQL 17 + PostGIS 3.5 + pgvector + pg_trgm · Titiler (raster) · MinIO/S3 · Valkey · Procrastinate` |
| F2 | Hard-coded version "FastAPI 0.110" in example badge. Repo runs Python 3.13, not 3.12 as in line 158. | Lines 158–161 | Replace badges with what README actually uses today (Python 3.13, PostGIS 3.5, PostgreSQL 17, Apache 2.0 license — the README shows `License: Apache 2.0`, NOT MIT). |
| F3 | Recommends "MIT is the most star-friendly". GeoLens is **Apache 2.0** (per `LICENSE` and README badge). Subagent C (~line 286) and Phase 4 sample SECURITY.md/CONTRIBUTING templates assume MIT. | Lines 161, 286 (Subagent C "MIT is the most star-friendly"), implicit in Phase 4 | Either drop the license recommendation entirely (the project has chosen Apache 2.0 and that decision shouldn't be re-litigated by an audit), or rewrite as: "Permissive licenses (MIT or Apache 2.0) are most star-friendly. GeoLens uses Apache 2.0; verify LICENSE file matches the README badge." |
| F4 | Phase 4 generates a CHANGELOG starting at `[0.1.0]` (line 737) with Initial release entries that don't reflect reality. The real CHANGELOG runs back through `[1.0.0] - 2026-04-01` and includes a documented 13.x → 1.0.0 reset (CHANGELOG.md line 8). | Lines 725–747 | Either skip CHANGELOG generation when one exists (see C14 above), or rewrite the example to match Keep a Changelog 1.1.0 (the real CHANGELOG declares 1.1.0, line 5) starting from `[Unreleased]` then `[1.0.0] - 2026-04-01`. |
| F5 | "If no releases exist: recommend creating `v0.1.0` with a proper changelog." (line 338) and "release notes template for v0.1.0" (line 357) — geolens already shipped 1.0.0 on 2026-04-01. The audit must not regress version numbers. | Lines 334–338, 357 | Replace with: "If no releases exist: recommend the next semver-appropriate tag and a Keep-a-Changelog-conformant entry. Detect current version from `frontend/package.json`, `backend/pyproject.toml`, and `git tag --sort=-version:refname | head -1` — recommend going forward from there." |
| F6 | Geolens unique-angle pitch (lines 813–826) overweights pgvector × PostGIS as the differentiator. While true, the **actual** 1.0.0 differentiators per the current README are: (a) one-command Docker setup with themed demo, (b) OGC API Features/Records + STAC compliance for QGIS/ArcGIS interop, (c) raster + vector + VRT mosaics in one catalog, (d) optional AI chat-with-maps. The pgvector/PostGIS combo is a sub-feature, not the headline. | Lines 813–826 ("The geolens unique angle — never dilute this") | Rewrite as: "GeoLens 1.0.0 differentiators: (1) **One-command spatial data catalog** — Docker compose to working UI in 5 minutes, with a themed demo dataset; (2) **OGC- and STAC-native** — works with QGIS/ArcGIS/MapLibre out of the box; (3) **Vector + raster + VRT mosaics** in one catalog; (4) **Semantic + spatial + fuzzy search** (pgvector + pg_trgm + PostGIS); (5) **AI chat with maps** (optional, BYO key). The pgvector × PostGIS angle is a real technical differentiator but is one of several." |
| F7 | "in 2025" timestamp in Subagent E (line 427: "in 2025") and "Tuesday–Thursday, 9–11am US Eastern" (line 454) framing. Today is 2026-05-02. | Line 427 | Drop the year (or update to "in 2026"). The HN timing is fine — leave as-is. |
| F8 | Subagent E HN draft uses pgvector × PostGIS as the headline. Same overweighting as F6. Also says "served by async FastAPI with a React frontend" — true, but the most striking demo-able feature today is the themed demo (`Earth as Seen from Space`, `One Territory, Multiple Official Maps`, etc., per README lines 35–60). | Lines 437–451 | Add an alternative HN draft framed around the themed demo: "Show HN: GeoLens 1.0 — one-command spatial data catalog with a 'Borders, Boundaries & Contested Space' themed demo." Keep the pgvector/PostGIS draft as alternative #2. |
| F9 | dev.to article titles (lines 469–473) and Twitter thread (lines 482–515) all centre on the pgvector + PostGIS combo. Same overweighting. | Lines 469–515 | Add 2 more title options aligned to actual differentiators: "Why we built a self-hosted spatial data catalog (and shipped 1.0 in public)" and "Themed demos as a launch strategy: how GeoLens 1.0 ships with 9 working maps". |
| F10 | Twitter thread (line 514): `⭐ if this is useful to you` — directly violates the anti-pattern listed in this same file at line 797 ("⭐ Star this repo if you find it useful! in the README — desperate, kills trust"). The same logic applies to threads. | Line 514 | Delete that line from the thread template. |
| F11 | Subagent D good-first-issue suggestions (lines 380–387) reference `Add CONTRIBUTING.md` — but `CONTRIBUTING.md` already exists at `.github/CONTRIBUTING.md` (per `ls .github/` on this repo, plus README line 235 linking to it, plus CHANGELOG line 81 noting the consolidation). Recommending it as a good-first-issue would surface stale advice. | Line 387 | Replace `Add CONTRIBUTING.md` with a real geolens-shaped good first issue, e.g. `Document the SRID coordinate convention in the README` (already in the list line 384 — keep), or `Add a ‹Compose-up troubleshooting› section to docs/`, or `Write an example uploading a Shapefile via the Python SDK`. |
| F12 | Subagent C CI block (lines 305–330) recommends adding `.github/workflows/ci.yml`. **CI already exists** at `.github/workflows/ci.yml` (plus `publish.yml`, `publish-cli.yml`, `publish-sdks.yml`, `release.yml`, `verify-published.yml`, per `ls .github/workflows/`). Recommending creating it would generate a duplicate-PR-quality finding. | Lines 305–330 | Reframe as: "Verify CI exists and is green. If `.github/workflows/ci.yml` exists, check the badge in README points at the right workflow file. If not, recommend creating from the template below." |
| F13 | Subagent D (~line 410) recommends adding `FUNDING.yml`. **It already exists** at `.github/FUNDING.yml`. | Line 410 | Reframe as: "If `.github/FUNDING.yml` doesn't exist, add it. If it does, verify the GitHub username/org is current and that the Sponsor button renders on the repo home page." |
| F14 | Subagent C (~line 269) `ls` checklist will mark `CONTRIBUTING.md` as missing — it lives at `.github/CONTRIBUTING.md`, not the repo root, per CHANGELOG entry "Top-level `CONTRIBUTING.md` consolidated into `.github/CONTRIBUTING.md`" (CHANGELOG line 81). | Line 269 | Update the `ls` line: `ls LICENSE .github/CONTRIBUTING.md CONTRIBUTING.md CODE_OF_CONDUCT.md SECURITY.md CHANGELOG.md ...` (check both locations). Add note: "GitHub recognises CONTRIBUTING in any of: repo root, `docs/`, or `.github/`." |
| F15 | Stack header line 2 calls Postgres "Postgres" — README and CHANGELOG consistently use "PostgreSQL 17". Cosmetic but the audit's own header should match the project's voice. | Line 2 | Use `PostgreSQL 17` consistently. |
| F16 | The whole file says nothing about the **open-core boundary** (per CONTEXT.md: single-org free / single-tenant Enterprise paid). README mentions "Enterprise and Security" feature group; an audit aimed at stars should note that paid-tier visibility (a `Pricing` section, `Sponsor` button, or commercial-support callout) is a known star-conversion lever for B2B-flavoured infra repos but should be tasteful. | New micro-section, ideally in Subagent E or new note in Subagent A. | Add a single bullet to Subagent A: "If the project has a commercial tier (open-core), include one understated link in the README (e.g. `Self-host free; managed/enterprise → getgeolens.com`) — never a banner, never above the demo." |
| F17 | Header banner says `# GitHub Star Maximisation Agent` — fine. But the file's own `## DELIVERY` (~line 780) writes the report to `docs-internal/audits/star-audit-{YYYYMMDD}.md`. `docs-internal/` is gitignored (per CHANGELOG line 79: "Internal documentation moved to a gitignored `docs-internal/` directory"). This is correct (audit shouldn't be public), but the path needs to be confirmed-existent before the command tries to write to it. | Line 784 | Add a `mkdir -p docs-internal/audits/` before write, and a comment: "`docs-internal/` is gitignored — audit reports are local-only. If you want to share findings, copy out manually." |

---

## §3 — Public-Release Readiness checks (Subagent F design)

Per CONTEXT.md decision §4: add **Subagent F: Public-Release Readiness** as the 6th parallel auditor, plus a **Phase 2.5 release-readiness gate** that synthesises Subagent F output.

The checks below are designed to run as bash inside the Subagent F prompt block, mirroring the style of the existing Subagent A–E bash blocks. Each maps to a CONTEXT.md decision-list bullet.

### Subagent F — Public-Release Readiness — checks

#### F.1 Version sync (CONTEXT bullet 1)

Detect the canonical version, then verify all surfaces agree.

```bash
# Discover canonical version sources
echo "=== Version sources ==="
GIT_TAG=$(git tag --sort=-version:refname | head -1)
PKG_FE=$(grep -E '"version"' frontend/package.json 2>/dev/null | head -1 | sed -E 's/.*"version"[ :]*"([^"]+)".*/\1/')
PKG_BE=$(grep -E '^version' backend/pyproject.toml 2>/dev/null | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
CHG_TOP=$(grep -E '^## \[[0-9]' CHANGELOG.md 2>/dev/null | head -1 | sed -E 's/.*\[([0-9][^]]+)\].*/\1/')
README_BADGE=$(grep -oE 'badge/[a-z]+-[0-9][0-9.]+' README.md 2>/dev/null | head -5)

echo "git tag: $GIT_TAG"
echo "frontend/package.json: $PKG_FE"
echo "backend/pyproject.toml: $PKG_BE"
echo "CHANGELOG top entry: $CHG_TOP"
echo "README version-ish badges: $README_BADGE"

# Check Docker image tag references in README
grep -nE 'ghcr\.io/[^ ]+:[0-9][^ ]*|geolens-io/[^:]+:[0-9][^ ]*' README.md docker-compose.yml 2>/dev/null
```

**Pass criteria:** `frontend/package.json` version == `backend/pyproject.toml` version == top dated `CHANGELOG.md` version. Git tag should equal one of these (or be a prefix `v$VER`). Flag any divergence as P0 BLOCKER.

#### F.2 Leftover internal references (CONTEXT bullet 2)

```bash
# User-facing files: README, top-level docs/, CHANGELOG, .github/
USER_FACING="README.md CHANGELOG.md FEATURES.md docs/ .github/"

echo "=== Internal-path leakage ==="
grep -rnE 'docs-internal/|\.planning/|GTM/' $USER_FACING 2>/dev/null | grep -v '\.git/'

echo "=== GSD / internal-tooling refs ==="
grep -rnE '\bgsd-[a-z-]+|\.claude/(commands|worktrees)' $USER_FACING 2>/dev/null

echo "=== Internal admin / audit paths ==="
grep -rnE 'docs-internal/audits|post-impl-[0-9]+\.md' $USER_FACING 2>/dev/null
```

**Pass criteria:** zero matches. Any hit = P1 (release-blocking; a public visitor must not see internal-tooling references).

#### F.3 Removed-component reference detection (CONTEXT bullet 3) — parameterized

Parameterise the list of removed components per project. For geolens, derive from CLAUDE.md memory: `pg_tileserv` (removed v7.0), `pg_featureserv` (removed v2.2). Generalisable: maintain a `REMOVED_COMPONENTS` array in the prompt, project-overridable.

```bash
# Project-specific removed components — override per repo
REMOVED_COMPONENTS=(
  "pg_tileserv"
  "pg_featureserv"
  "SHOW_LANDING_PAGE"          # env var removed v13.x
  "VITE_API_PROXY_TARGET"      # renamed (one-release fallback only)
  "AWS_MARKETPLACE_PRODUCT_CODE" # enterprise-overlay-only as of v13.3
)

USER_FACING="README.md CHANGELOG.md FEATURES.md docs/ .env.example docker-compose*.yml"

for comp in "${REMOVED_COMPONENTS[@]}"; do
  echo "=== $comp ==="
  # CHANGELOG can reference removed components in the Removed/Changed entries — that's expected.
  # Only flag user-facing docs OUTSIDE CHANGELOG.
  grep -rnE "\b${comp}\b" $USER_FACING 2>/dev/null | grep -v 'CHANGELOG.md'
done
```

**Pass criteria:** zero matches outside CHANGELOG. Each match = P1 (release-blocking — README must not advertise services the project no longer ships).

#### F.4 CHANGELOG hygiene (CONTEXT bullet 4)

```bash
echo "=== CHANGELOG format check ==="

# Keep a Changelog header
head -5 CHANGELOG.md | grep -E "Keep a Changelog" || echo "MISS: no Keep-a-Changelog reference in CHANGELOG header"

# Latest tagged version present and dated (YYYY-MM-DD)
grep -E '^## \[[0-9]' CHANGELOG.md | head -3

# Unreleased section sanity
awk '/^## \[Unreleased\]/,/^## \[[0-9]/' CHANGELOG.md | wc -l
# If > 200 lines, the unreleased section may be hiding an unreleased release — recommend tagging.

# Stale-dated unreleased: Unreleased section containing a date older than the latest tag's date
grep -A 50 '^## \[Unreleased\]' CHANGELOG.md | grep -oE '\(20[0-9][0-9]-[0-9]{2}-[0-9]{2}\)' | head -5
```

**Pass criteria:**
- Keep a Changelog reference in header: required.
- Most-recent dated entry has format `## [X.Y.Z] - YYYY-MM-DD`.
- `[Unreleased]` either empty or actively in progress (warn if has entries dated > 30 days ago — those should be tagged).
- Latest entry's date should be within 90 days of `git log -1 --format=%ci` (warn otherwise).

Each fail = P2 (CHANGELOG quality is a trust signal but rarely blocks launch).

#### F.5 Demo-link liveness (CONTEXT bullet 5) — flag for human verification

Filesystem can't curl reliably (sandboxing, networking). Detect demo links in README and report them for manual verification.

```bash
echo "=== Demo / live URLs declared in README ==="
# Pull all https:// URLs from the first 100 lines of README (the hero/demo zone)
head -100 README.md | grep -oE 'https://[^ )"]+' | sort -u

# Heuristic: known demo domains
head -200 README.md | grep -oE 'https://[^ )"]+' | grep -E 'demo|live|getgeolens|geolens\.io' | sort -u
```

**Pass criteria:** report-only. Output a "DEMO LINKS — VERIFY MANUALLY" block in the Subagent F findings. Add to BLOCKERS only if README explicitly promises a demo and the URL is `localhost` or a placeholder.

#### F.6 LICENSE existence + match with README claim (CONTEXT bullet 6)

```bash
echo "=== LICENSE check ==="

# LICENSE must exist
test -f LICENSE && echo "LICENSE: present" || echo "LICENSE: MISSING (P0)"

# Detect license type from LICENSE file (heuristic)
LICENSE_NAME=$(head -3 LICENSE 2>/dev/null | grep -oiE 'mit|apache|gpl|bsd|mozilla|unlicense' | head -1)
echo "Detected from LICENSE: $LICENSE_NAME"

# Detect what README claims
README_LICENSE=$(grep -oiE 'license[^A-Za-z]+(mit|apache[ -]?2\.?0|gpl-?[23]|bsd-[23]|mpl-?2)' README.md | head -3)
echo "README claims: $README_LICENSE"

# Detect license badge
grep -oE '!\[[^]]*[Ll]icense[^]]*\][^)]+' README.md | head -3
```

**Pass criteria:** LICENSE exists AND its detected type matches the README claim AND the README badge. Mismatch = P0 BLOCKER (legal risk).

#### F.7 `.env.example` presence + secret-leak heuristic (CONTEXT bullet 7)

```bash
echo "=== .env.example check ==="

test -f .env.example && echo ".env.example: present" || echo ".env.example: MISSING (P1)"

# Detect values that look like real secrets, not placeholders
# Real secrets: long base64-ish strings, AWS keys, API tokens with non-trivial entropy
echo "=== Suspicious values in .env.example ==="

# AWS-style keys
grep -nE 'AKIA[0-9A-Z]{16}|aws_secret_access_key=[A-Za-z0-9/+=]{40}' .env.example 2>/dev/null

# Generic high-entropy strings (32+ chars, mixed case + digits, no spaces, not obvious placeholders)
grep -nE '=[A-Za-z0-9+/=_-]{32,}' .env.example 2>/dev/null \
  | grep -viE 'change[ _-]?me|placeholder|example|your[ _-]|secret[ _-]?here|<.*>|xxx|yyy|zzz|todo' \
  | grep -viE '=admin$|=password$|=changeme$' \
  | head -10

# Common API key formats
grep -nE 'sk-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9-]+|ghp_[A-Za-z0-9]{36}|github_pat_' .env.example 2>/dev/null
```

**Pass criteria:** `.env.example` exists AND no values match real-secret heuristics. Any match = P0 BLOCKER (refuse-to-launch — credential leak).

#### F.8 WIP / "Coming soon" / TODO scan in user-facing docs (CONTEXT bullet 8)

```bash
echo "=== WIP / TODO / Coming Soon scan ==="

USER_FACING="README.md FEATURES.md docs/"

# Strict pattern — exclude code blocks (heuristic: lines starting with whitespace + #)
grep -rniE 'coming soon|work[ -]in[ -]progress|\bWIP\b|\bTODO\b|\bFIXME\b|XXX:|to be added|under construction' \
  $USER_FACING 2>/dev/null \
  | grep -viE '^\s*//|^\s*#'  # exclude code-block-style comments

# Roadmap sections — softer signal but still flag
grep -niE '^#+ +(roadmap|future|planned|coming|upcoming)' $USER_FACING 2>/dev/null
```

**Pass criteria:** zero matches in README hero (first 100 lines). Matches in deeper docs = P2. Roadmap section by itself is fine; recommend wording it as "What's next" rather than "Coming soon".

#### F.9 Stale screenshots/assets — heuristic with documented limitation

```bash
echo "=== Asset freshness heuristic ==="

# Find images referenced in README
README_IMAGES=$(grep -oE '\(docs/images/[^)]+\)|src="docs/images/[^"]+"' README.md | sed -E 's/.*(docs\/images\/[^)"]+).*/\1/' | sort -u)

# Find UI source last-modified time (frontend/src/**.tsx,jsx,css)
LATEST_UI_COMMIT=$(git log -1 --format=%ct -- 'frontend/src/**' 2>/dev/null)
LATEST_UI_DATE=$(git log -1 --format=%ci -- 'frontend/src/**' 2>/dev/null)
echo "Latest UI commit: $LATEST_UI_DATE"

for img in $README_IMAGES; do
  if [ -f "$img" ]; then
    IMG_COMMIT=$(git log -1 --format=%ct -- "$img" 2>/dev/null)
    IMG_DATE=$(git log -1 --format=%ci -- "$img" 2>/dev/null)
    if [ -n "$IMG_COMMIT" ] && [ -n "$LATEST_UI_COMMIT" ] && [ "$IMG_COMMIT" -lt "$LATEST_UI_COMMIT" ]; then
      AGE_DAYS=$(( ($LATEST_UI_COMMIT - $IMG_COMMIT) / 86400 ))
      echo "STALE? $img (last touched $IMG_DATE — $AGE_DAYS days behind latest UI change)"
    fi
  else
    echo "MISSING: $img (referenced in README, file not found)"
  fi
done
```

**Pass criteria:** missing files = P0 (broken README image). Stale > 90 days behind UI changes = P2 + flag for human review (could be fine if UI didn't visibly change). Document the limitation explicitly: "This check is heuristic — UI commits don't always change the visible UI. Treat findings as a prompt for visual review, not as a hard gate."

### Phase 2.5 — Release-readiness gate

After Subagents A–F complete, before Phase 3 prioritised plan:

```markdown
## Phase 2.5 — Release-readiness gate

Synthesise Subagent F findings into a single readiness verdict:

- **P0 BLOCKERS** (any of these = STOP, fix before any star-growth work):
  - F.1 version desync
  - F.6 LICENSE missing or mismatched
  - F.7 real secret in `.env.example`
  - F.9 README image file missing

- **P1 RELEASE-BLOCKING** (fix before public launch but report can continue):
  - F.2 internal references in user-facing docs
  - F.3 removed-component references in user-facing docs
  - F.7 `.env.example` missing

- **P2 QUALITY** (mention in prioritised plan, don't block):
  - F.4 CHANGELOG format issues
  - F.8 WIP/TODO in deeper docs
  - F.9 stale screenshots heuristic flag

Output a top-of-report `## BLOCKERS` section if any P0 or P1 findings exist.
Otherwise, output: `Public-release readiness: ✅ no blockers detected (still flagged for human verification: <demo links from F.5>)`.
```

### Phase 4 (`--write`) additions

Add to the end of Phase 4 artifact list:

- **13. `RELEASE-READINESS.md`** — local checklist file capturing the F.1–F.9 outcomes, machine-readable so a future re-run can diff. (Write to `docs-internal/audits/release-readiness-{YYYYMMDD}.md` since `docs-internal/` is gitignored.)

### Star-velocity scoring table additions

Append to the table (~line 583):

| Action | Effort | Expected impact |
|--------|--------|----------------|
| Fix version desync | 30min | trust signal — eliminates "is this even maintained?" doubt |
| Remove internal-path refs from public docs | 30min | removes legitimacy concerns |
| Replace stale screenshots | 1h | first-impression quality — visible above the fold |
| 60s "first run" screencast | 2h | +30–50% README-to-clone conversion |
| Star-history badge (after 200+ stars) | 5min | social-proof compounding |

---

## Recommended insertion points in `star-audit.md`

For the planner — exact line targets so edits cluster minimally:

| Edit | File:line | Change type |
|------|-----------|-------------|
| Header stack | `star-audit.md:2` | Replace single line (F1, F15) |
| Subagent A badges | `star-audit.md:155–168` | Replace example badges with current geolens reality (F2, F3) |
| Subagent A "WHAT IT LOOKS LIKE" | After `star-audit.md:124` | Add C3 (first-run screencast), C7 (mobile/dark-mode) |
| Subagent A architecture | After `star-audit.md:131` | Add C1 (competitive matrix), C8 (positioning quadrant) |
| Subagent A new commercial bullet | New, before `star-audit.md:132` | Add F16 (open-core link guidance) |
| Subagent B GitHub-description | `star-audit.md:199–210` | Add C5 (snippet preview check) |
| Subagent B SEO terms | `star-audit.md:224–245` | Add C10 (i18n signal) |
| Subagent B awesome lists | `star-audit.md:247–256` | Add C12 (verify list CONTRIBUTING before submitting) |
| Subagent C `ls` checklist | `star-audit.md:269` | Update for `.github/CONTRIBUTING.md` location (F14) |
| Subagent C MIT recommendation | `star-audit.md:286` | Soften / make license-agnostic (F3) |
| Subagent C CI block | `star-audit.md:305–330` | Reframe to verify-first, generate-only-if-missing (F12) |
| Subagent C release suggestion | `star-audit.md:334–338, 357` | Replace `v0.1.0` with version-detection logic (F5) |
| Subagent C trust block | After `star-audit.md:300` | Add C9 (maintainer responsiveness) |
| Subagent D good-first-issues | `star-audit.md:380–387` | Replace `Add CONTRIBUTING.md` (F11), add C11 (verify label has issues) |
| Subagent D FUNDING.yml | `star-audit.md:407–414` | Add discovery side-effect (C4), reframe as verify-not-create (F13) |
| Subagent E "in 2025" | `star-audit.md:427` | Drop year (F7) |
| Subagent E HN draft | `star-audit.md:437–451` | Add themed-demo-led alt draft (F8) |
| Subagent E dev.to titles | `star-audit.md:469–473` | Add 2 more title options (F9) |
| Subagent E Twitter thread | `star-audit.md:514` | Delete `⭐ if useful` line (F10, C13) |
| **NEW Subagent F** | After `star-audit.md:543` (end of Subagent E) | Insert full Subagent F block with §3.F.1–F.9 |
| **NEW Phase 2.5** | After Subagent F, before `star-audit.md:546` (start of Phase 3) | Insert release-readiness gate |
| Phase 3 scoring table | `star-audit.md:583–591` | Append rows from §3 "Star-velocity scoring table additions" |
| Phase 3 plan template | `star-audit.md:551–577` | Add C15 ("do nothing if README is fine") branch |
| Phase 4 guard | Top of Phase 4 (~`star-audit.md:597`) | Add C14 (diff-not-overwrite for existing files) |
| Phase 4 CHANGELOG template | `star-audit.md:725–747` | Skip-if-exists OR rewrite to match actual format (F4) |
| Phase 4 new artifact #13 | After `star-audit.md:776` | Add `RELEASE-READINESS.md` artifact |
| Geolens unique angle | `star-audit.md:813–826` | Rewrite to broader 1.0.0 differentiator list (F6) |
| DELIVERY block | `star-audit.md:780–789` | Add `mkdir -p docs-internal/audits/` and gitignore note (F17) |

---

## Sources

### Primary (HIGH confidence — repo state)
- `/Users/ishiland/Code/geolens/.claude/commands/star-audit.md` (full file, 827 lines)
- `/Users/ishiland/Code/geolens/README.md` (current — Apache 2.0, Python 3.13, PostgreSQL 17, PostGIS 3.5, Titiler, Valkey, MinIO, themed demo)
- `/Users/ishiland/Code/geolens/CHANGELOG.md` (Keep a Changelog 1.1.0; `[1.0.0] - 2026-04-01`; `docs-internal/` consolidation; `.github/CONTRIBUTING.md` consolidation)
- `~/.claude/projects/-Users-ishiland-Code-geolens/memory/MEMORY.md` (project stack — pg_tileserv removed v7.0, pg_featureserv removed v2.2; milestone chronology including v13.2 latest; open-core boundary)
- `frontend/package.json`, `backend/pyproject.toml` — both at `1.0.0`
- `git tag --sort=-version:refname` — `v14.0`, `v13.3`, `v13.2`, `v13.1`, `v13.0` are in-tree historical tags; the public release line is `1.0.0`

### Secondary (MEDIUM confidence — community references)
- [Open Source launch checklist 2026 — LaunchTry](https://launchtry.com/resources/launch-checklist/open-source) — license, repo structure, CI/CD, docs
- [Open source GitHub repository pre-launch checklist — binbash/Medium](https://medium.com/binbash-inc/open-source-github-repository-pre-launch-checklist-4a52dbbe4af1)
- [GitHub Star Growth: 9 Levers That Compound in 2026 — DEV](https://dev.to/iris1031/github-star-growth-9-levers-that-compound-in-2026-15d) — source for "make project legible in seconds; sequence launches; convert spikes into evergreen discovery"
- [How to crush your Hacker News launch — DEV](https://dev.to/dfarrell/how-to-crush-your-hacker-news-launch-10jk) — Show HN title clarity
- [Starting an Open Source Project — Open Source Guides](https://opensource.guide/starting-a-project/) — repo hygiene checklist
- [How to launch a dev tool on Hacker News — markepear.dev](https://www.markepear.dev/blog/dev-tool-hacker-news-launch) — README > landing page for technical products
- [Pre-launch sanity gist — PurpleBooth](https://gist.github.com/PurpleBooth/6f1ba788bf70fb501439) — primetime-ready repo checklist
- [GitHub Topics docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics) — already cited in current command, kept

### Canonical
- [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) — geolens uses 1.1.0, not 1.0.0 as in current command line 730
- [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html)

## Metadata

**Confidence breakdown:**
- §1 (gaps): MEDIUM-HIGH — gaps cross-checked against multiple launch checklists; a few are judgement calls (e.g. C6 star-history badge timing)
- §2 (correctness): HIGH — every line:line claim verified against repo state today
- §3 (readiness checks): HIGH for the bash patterns; LOW-MEDIUM for impact claims (e.g. F.9 stale-screenshot heuristic explicitly flagged as brittle in §3)

**Research date:** 2026-05-02
**Valid until:** 2026-06-01 — geolens repo state moves fast; re-verify §2 if planner runs more than ~30 days from now
