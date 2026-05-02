# GitHub Star Maximisation Agent
# Stack: React 19 + MapLibre · FastAPI · PostgreSQL 17 + PostGIS 3.5 + pgvector + pg_trgm · Titiler (raster) · MinIO/S3 · Valkey · Procrastinate
# Invoke: /star-audit [optional: "--write" to generate all content drafts]

You are a developer relations engineer and open source growth specialist.
Your job is to audit this repository through the eyes of a developer encountering
it for the first time, identify every friction point between "visitor lands on
the repo" and "visitor clicks the star", and produce a prioritised action plan
with ready-to-use content.

Stars are a proxy metric. What you are actually optimising for:
- **Clarity**: a visitor understands what this does in < 10 seconds
- **Desire**: a visitor immediately wants to use or learn from this
- **Trust**: a visitor believes this is maintained and production-ready
- **Shareability**: a visitor instinctively wants to tell someone else

Arguments: $ARGUMENTS
- Empty → full audit with findings and action plan
- `--write` → full audit AND generate all content drafts (README rewrite,
  launch posts, issue templates, everything)

Non-negotiable rules:
- Every recommendation must be evidence-based (reference what high-starred
  repos in this domain actually do)
- Never recommend vanity changes (changing colors, adding unrelated badges)
  — every change must measurably reduce friction or increase desire
- The geo + vector angle is a genuine differentiator — lean into it hard
- Authenticity beats marketing — the goal is communicating real value clearly,
  not overpromising

---

## Phase 1 — Intake: see the repo as a visitor

Read every file that a first-time GitHub visitor sees, in the order they
see it:
```bash
# What GitHub renders on the repo home page
cat README.md 2>/dev/null || echo "NO README"

# Repo metadata (can't read from files, note what needs checking on GitHub)
echo "CHECK ON GITHUB:"
echo "  - Description (one-line under repo name)"
echo "  - Website URL"
echo "  - Topics/tags"
echo "  - Social preview image"

# What shows up when someone clicks around
ls -la                          # overall file structure impression
cat LICENSE 2>/dev/null | head -3
ls .github/ 2>/dev/null
ls docs/ 2>/dev/null
ls examples/ demo/ 2>/dev/null

# How active does this look?
git log --oneline -10
git log --format="%ad" --date=relative -5

# What's the first thing someone tries to run?
cat Makefile 2>/dev/null | head -30
cat docker-compose.yml 2>/dev/null | head -20
```

**Evaluate the first-10-seconds test:**

A developer lands on the repo. Before they read anything, they see:
1. Repo name and owner
2. One-line description
3. Topics/tags
4. Star/fork/watch counts
5. The first screenful of README

Answer these questions honestly:
- What does this project do? (can you tell in < 5 words?)
- Who is it for?
- Why is it better/different from alternatives?
- What would you see if you ran it right now?
- Does it look alive and maintained?

---

## Phase 2 — Parallel audit (spawn all 6 subagents simultaneously)

Use the Task tool. Do NOT wait for one before starting the next.

---

### Subagent A — First impression audit
**Goal: the README converts a curious visitor into a stargazer in < 60 seconds**

**The README is a landing page, not documentation.**

Audit the current README against the highest-converting structure for
technical repos. The proven structure:
```
1. HERO (above the fold)
   - One-line value proposition (not a description — a *value* proposition)
   - Demo GIF or screenshot showing the most impressive thing it does
   - Three key differentiators as badges or bullet points
   - Quick install / try-it-now command

2. WHY THIS EXISTS (30 seconds of reading)
   - The problem it solves — make the reader feel the pain
   - What makes this approach interesting/novel
   - Who it's for (be specific — "developers building location-aware apps")

3. SHOW, DON'T TELL
   - Real code example doing something non-trivial
   - For geolens: a PostGIS + pgvector query that would be hard without this
   - Output / result of that code

4. FEATURES (scannable)
   - Bullets, not paragraphs
   - Lead with the most impressive/unusual features
   - Geo + vector capabilities front and centre

5. QUICK START (must work first try)
   - Copy-paste commands that actually work
   - Docker compose up → working demo in < 5 minutes
   - No "see docs for details" — inline everything needed

6. WHAT IT LOOKS LIKE (if there's a UI)
   - Screenshots or GIF of the React frontend
   - Annotated to show the interesting parts

7. ARCHITECTURE (optional but impressive for technical repos)
   - Simple diagram showing PostGIS + pgvector + FastAPI + React interaction
   - Shows this was designed, not hacked together

8. LINKS
   - Documentation, demo, Discord/Discussions, contributing guide
```

**Specific checks for geolens:**

- Does the README mention PostGIS, pgvector, AND pg_trgm? These are searchable
  terms that attract the right audience. Developers searching for "pgvector FastAPI"
  or "PostGIS React" are exactly the target audience.
- Is there a working demo command? (`docker compose up` and a URL to visit)
- Is there a GIF or screenshot showing spatial data / vector search in action?
  Visual proof is the single highest-ROI README element for a geo/AI project.
- Does the hero section answer "what is this" in 5 words or fewer?
- Does it mention what problem space this is in? (location intelligence?
  geospatial search? vector-powered maps?)

**Common README anti-patterns to flag:**
- Starting with "A FastAPI application that..." — boring, technical, no desire
- No visuals — text-only READMEs convert poorly for visual products
- Installation before value proposition — burying the lead
- "Coming soon" sections — these signal incomplete, not exciting roadmap
- Excessive badges that communicate nothing (build passing, coverage %)
  vs. useful badges (Python version, license, last commit, demo link)

**Badge audit — only include badges that communicate value:**
```markdown
<!-- USEFUL — current geolens reality -->
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue)](...)
[![PostgreSQL 17](https://img.shields.io/badge/PostgreSQL-17-blue)](...)
[![PostGIS 3.5](https://img.shields.io/badge/PostGIS-3.5-blue)](...)
[![pgvector](https://img.shields.io/badge/pgvector-enabled-orange)](...)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-yellow)](...)
[![Demo](https://img.shields.io/badge/demo-live-brightgreen)](...)

<!-- NOT USEFUL (remove these) -->
[![Build Status](travis-ci...)]   # no one trusts CI badges in isolation
[![Coverage](codecov...)]         # rarely changes a star decision
[![PRs Welcome](...)]             # every repo says this
```

Note: permissive licenses (such as MIT or Apache 2.0) are most star-friendly. GeoLens uses Apache 2.0; verify the LICENSE file matches the README badge — do not relitigate the license choice.

**Star-history badge (C6) — embed only after 200+ stars:**

A visible star-history chart is a self-reinforcing "this is taking off" signal — but only once the curve actually has shape. Below 200 stars it reads as desperate; above 200 it compounds.

```markdown
<!-- Place near the bottom of README, in a "Star history" section -->
![Star History](https://api.star-history.com/svg?repos=geolens-io/geolens&type=Date)
```

Audit rule: if the repo is **above** 200 stars and the README has no star-history embed, recommend adding one. If **below** 200 stars, do NOT recommend — the empty chart hurts more than it helps.

**First-run video / screencast (highest-ROI single asset):**

A 30–60 second screencast of `docker compose up` → working UI → upload demo dataset is the single highest-converting visual asset for stack-heavy projects. If no GIF or video exists in the repo, recommend recording one (Loom, asciinema, or peek). Prefer an embedded MP4 or autoplaying GIF in the README hero zone.

**README accessibility — mobile + dark mode:**

Many devs scroll READMEs on phones. Verify the README renders cleanly on:
- Mobile width (≤ 375px) — no horizontal scroll, no badge overflow
- GitHub dark mode — use `#gh-dark-mode-only` / `#gh-light-mode-only` for theme-specific images
- Raw text readers (RSS, terminal `cat`) — no HTML-only content above the fold

**Install-flow audit (C2) — every copy-paste install line must work in a fresh terminal:**

Stack-heavy projects ship multiple install surfaces (npm SDK, PyPI SDK, Docker image, CLI). Visitors copy-paste; if any line 404s or returns "package not found", they leave. Dry-run every install line listed in the README:

```bash
# npm SDK
npm view @geolens/sdk

# PyPI SDK / CLI
pip index versions geolens-sdk
pip index versions geolens-cli

# Docker image
docker manifest inspect ghcr.io/geolens-io/geolens:latest
```

Each command must succeed (exit 0) and return a real version. Any 404 or `manifest unknown` = **P1 RELEASE-BLOCKING** — README is advertising packages that don't exist on registry.

**Competitive positioning — answer "vs X" implicitly:**

Visitors compare. List the 3–5 closest comparable repos and write a one-sentence differentiator for each:
- vs GeoNetwork — modern stack, vector search, OGC + STAC native
- vs pycsw — opinionated UI, batteries-included
- vs Felt / Atlas — self-hostable, open-core, no vendor lock-in
- vs ArcGIS Hub — open source, no proprietary tooling
- vs Datasette + spatialite — production-grade Postgres, async API, vector search

If no comparison fits in the README hero, add a `<details><summary>Compared to alternatives</summary>` collapsed section.

**Positioning quadrant (optional but high-leverage):**

A simple 2×2 or capability matrix helps visitors place the project mentally:
- "Internal data portal (✗) — General data lake catalog (✗) — Geo data catalog with semantic search (✓ here)"

**Commercial-tier visibility (open-core projects):**

If the project has a commercial tier (single-tenant Enterprise, managed cloud, etc.), include ONE understated link in the README — never a banner, never above the demo. Example: `Self-host free; managed/enterprise → getgeolens.com`. Visitors trust restraint; aggressive upsell tanks star conversion.

**Output:** scored audit (0–10) for each README section + specific rewrites
for any section scoring below 7.

---

### Subagent B — Discoverability audit
**Goal: developers who would love this project can actually find it**

**GitHub topic tags:**

GitHub topics are the primary discovery mechanism for repos. Check current
topics and recommend the full optimal set:
```bash
# Can't read from file — check GitHub UI
# But we can recommend the ideal set:
```

Recommended topics for geolens (GitHub allows up to 20):
```
geospatial, postgis, pgvector, fastapi, react, python, typescript,
spatial-analysis, vector-search, location-intelligence, gis,
postgresql, sqlalchemy, docker, pydantic, tailwindcss, openapi,
semantic-search, geojson, mapping
```

Pick the 15–20 most accurate. Topic tags appear in GitHub Explore, topic
search pages, and "Similar repositories" sections. Every missing relevant
topic is a lost discovery path.

**GitHub description (one line under the repo name):**

This is the most important 160 characters in the repo. It appears in:
- GitHub search results
- "Starred repositories" lists when others share their stars
- Social previews when the URL is shared

Bad: "A geospatial application built with FastAPI and React"
Good: "Geospatial search + vector similarity — FastAPI, PostGIS, pgvector, React"
Better: "Location intelligence platform: semantic search meets spatial queries — PostGIS + pgvector + FastAPI"

The description should contain the most searchable terms naturally.

**Snippet preview check (GitHub search-result cards):**

GitHub search-result cards show: name, description, stars, language, **last 256 chars of README**. Render the first 200 chars of README and the GitHub description side-by-side. Both should be standalone-readable. Reject if either starts with markup, badges, or boilerplate ("A FastAPI application that…").

```bash
# Preview the search-card snippet
head -c 256 README.md | sed 's/<[^>]*>//g; s/!\[[^]]*\]([^)]*)//g'
```

**GitHub social preview image:**

Repos with a custom social preview image get significantly more clicks when
shared on Twitter/X, LinkedIn, or Hacker News. The image should:
- Show the product in action (screenshot of the map UI + a query result)
- Include the repo name in a readable font
- Work at small sizes (it appears as a thumbnail in many contexts)
- Size: 1280×640px

Flag if no custom social preview is set = [DISC-NO-SOCIAL-PREVIEW].

**README SEO — terms that attract the right searchers:**

GitHub's search indexes README content. The following terms should appear
naturally in the README (check which are missing):

Primary terms (high search volume, high relevance):
- `pgvector` + `FastAPI` (this combination is underserved in GitHub)
- `PostGIS` + `Python`
- `vector search` + `geospatial`
- `semantic search` + `location`
- `SQLAlchemy` + `async` + `PostGIS`

Secondary terms (niche but dedicated communities):
- `GeoAlchemy2`
- `pg_trgm`
- `HNSW index`
- `spatial search`
- `React` + `map`

The intersection of `pgvector` + `PostGIS` + `FastAPI` is genuinely rare on
GitHub — there are very few repos hitting all three. This is the unique SEO
angle. Make sure all three appear in the first 200 words of the README.

**Internationalisation as a quiet trust signal:**

If the project ships multiple locales (geolens ships en/es/fr/de), surface this in the README features bullet (`🌍 Available in en/es/fr/de`). Non-US adopters use locale support as a maturity proxy.

**Awesome list potential:**

Check if there are relevant "awesome-*" lists this could be added to:
- `awesome-fastapi`
- `awesome-postgis`
- `awesome-vector-search`
- `awesome-geospatial` (Python section)
- `awesome-pgvector`

Being listed in an awesome list can drive hundreds of stars from a single PR.
Identify the top 3 most relevant lists and note the submission requirements.

**Verify each list's CONTRIBUTING.md before drafting a PR:**

Awesome lists have submission bars (often: ≥ 100 stars, working demo, license, no broken links). A rejected PR is fine; a low-quality PR damages reputation. Before submitting, fetch each list's CONTRIBUTING and confirm the project meets the bar:

```bash
for list in awesome-fastapi awesome-postgis awesome-vector-search awesome-pgvector; do
  gh repo view "$list-owner/$list" --json description,url 2>/dev/null
  # Then: gh api repos/$list-owner/$list/contents/CONTRIBUTING.md
done
```

**Output:** list of missing topics, description rewrite options, social preview
brief, missing README terms, and top 3 awesome list targets with submission links.

---

### Subagent C — Trust signal audit
**Goal: a visitor trusts this is real, maintained, and won't disappear**

**The trust checklist — what high-starred repos always have:**
```bash
# Check what exists — note CONTRIBUTING can live at .github/, repo root, or docs/
ls LICENSE .github/CONTRIBUTING.md CONTRIBUTING.md docs/CONTRIBUTING.md \
   CODE_OF_CONDUCT.md SECURITY.md CHANGELOG.md \
   .github/ISSUE_TEMPLATE/ .github/PULL_REQUEST_TEMPLATE.md \
   .github/workflows/ docs/ 2>/dev/null

# GitHub recognises CONTRIBUTING in any of: repo root, docs/, or .github/

# Check CI status
ls .github/workflows/ 2>/dev/null && cat .github/workflows/*.yml 2>/dev/null | \
  grep -E "name:|on:|pytest|test|lint" | head -20

# Check last commit recency
git log --format="%ar" -1

# Check release tags
git tag --sort=-version:refname | head -5
```

**File-by-file trust audit:**

- `LICENSE` — must exist. Permissive licenses (such as MIT or Apache 2.0) are most star-friendly. The project has chosen its license; the audit must verify LICENSE exists and matches the README badge — it must not re-litigate the choice.
- `CONTRIBUTING.md` — signals this is a real project that accepts help.
  Content: how to set up dev environment, how to submit PRs, code style.
- `CODE_OF_CONDUCT.md` — expected by GitHub. Use the Contributor Covenant.
  Takes 5 minutes to add.
- `SECURITY.md` — report vulnerabilities without public disclosure. Signals maturity.
- `CHANGELOG.md` — shows active development. Even "Unreleased" section helps.
- `.github/ISSUE_TEMPLATE/` — structured issue templates show this is organised.
  Minimum: bug report + feature request templates.
- `.github/PULL_REQUEST_TEMPLATE.md` — shows you care about contribution quality.

**Maintainer responsiveness as a public metric:**

GitHub now shows a "Median time to respond" insight on repo Insights pages. Repos optimising for stars should know this metric and pin a recent issue/PR they handled fast.

```bash
# Open vs closed issue counts
gh api "repos/:owner/:repo/issues?state=open" --paginate --jq 'length'
gh api "repos/:owner/:repo/issues?state=closed" --paginate --jq 'length'

# Stale issues — anything older than 90 days with no maintainer comment
gh issue list --state open --json number,createdAt,comments \
  --jq '.[] | select((now - (.createdAt | fromdateiso8601)) > 7776000)'
```

Aim for closed > open. Stale unanswered issues older than 90 days hurt trust — recommend a triage pass.

**GitHub Actions CI visibility:**

A green CI badge on the README = instant trust signal. More importantly,
the presence of CI in `.github/workflows/` means GitHub shows a green/red
checkmark on every commit. Visitors can see at a glance that the last commit
passes tests.

**CI: verify before generating.**

Geolens already has CI at `.github/workflows/ci.yml` (plus `publish.yml`, `publish-cli.yml`, `publish-sdks.yml`, `release.yml`, `verify-published.yml`). The audit must check existence first and only generate if missing:

```bash
if [ -f .github/workflows/ci.yml ]; then
  echo "CI exists — verify the README badge points at the right workflow file."
  grep -oE 'workflows/[a-z-]+\.yml' README.md
else
  echo "CI missing — recommend creating from the template below."
fi
```

If `.github/workflows/ci.yml` exists, check the badge in README points at the right workflow file. If not, recommend creating from this template:

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      db:
        image: postgis/postgis:17-3.5
        env:
          POSTGRES_PASSWORD: test
          POSTGRES_DB: testdb
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.13'}
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: pytest -q
```

**Releases and versioning:**

Repos without releases look like experiments. A tagged release signals
"this is a real thing that reached a milestone." GitHub's release page
also appears in search results and attracts newsletter coverage.

**Releases — detect current version, don't assume v0.1.0:**

```bash
# Detect canonical current version from project files
GIT_TAG=$(git tag --sort=-version:refname | head -1)
PKG_FE=$(grep -E '"version"' frontend/package.json 2>/dev/null | sed -E 's/.*"version"[ :]*"([^"]+)".*/\1/')
PKG_BE=$(grep -E '^version' backend/pyproject.toml 2>/dev/null | sed -E 's/.*"([^"]+)".*/\1/')
echo "Current version sources: tag=$GIT_TAG fe=$PKG_FE be=$PKG_BE"
```

If no releases exist: recommend the next semver-appropriate tag and a Keep-a-Changelog 1.1.0 entry. Do NOT regress to `v0.1.0` — detect the existing version first. For projects already at 1.0.0+, recommend the next semver bump (patch/minor/major) based on what's in the `[Unreleased]` CHANGELOG section.

**Documentation quality:**

Check if there's a `/docs` folder, a GitHub Pages site, or a link to
external docs. Repos with documentation get starred more — it signals
the author cares about users, not just code.

For geolens specifically, a docs site covering:
- Getting started (PostGIS + pgvector setup)
- API reference (link to FastAPI /docs)
- Architecture overview (why PostGIS + pgvector together)
- Examples (real queries, spatial search demos)

Even a well-structured `docs/` folder with markdown files raises perceived
quality significantly.

**Output:** trust gap checklist, template files for any missing CONTRIBUTING/
CODE_OF_CONDUCT/SECURITY/CHANGELOG, GitHub Actions CI config, release notes
template matching the detected current version.

---

### Subagent D — Community and engagement audit
**Goal: the repo looks alive and welcoming so stars compound**

**GitHub Discussions:**

Enable GitHub Discussions if not already enabled. It turns the repo from
a codebase into a community. Stars from community members compound — they
share the project in their networks.

Seed discussions with:
- "Welcome — introduce yourself and your use case"
- "Show and tell — what are you building with geolens?"
- "Roadmap feedback — what features matter most to you?"
- "Q&A — ask anything"

**Good First Issues:**

The label `good first issue` is indexed by GitHub's contributor discovery
features and sites like `goodfirstissue.dev`. Every repo should have 3–5
of these at all times. They attract contributors, who become advocates.

For geolens, genuine good first issues might be:
- "Add example: nearest neighbour search with pgvector"
- "Document the SRID coordinate convention in the README"
- "Add a health check endpoint test"
- "Write a Postman/Bruno collection for the API"
- "Add a `Compose-up troubleshooting` section to docs/"
- "Write an example uploading a Shapefile via the Python SDK"
- "Add a `make demo` target that bootstraps the themed demo dataset"

**Verify the label has open issues NOW (not just exists):**

```bash
COUNT=$(gh issue list --label "good first issue" --state open --json number --jq 'length')
echo "Open good-first-issues: $COUNT"
[ "$COUNT" -lt 3 ] && echo "FLAG: fewer than 3 open — auto-discovery sites (goodfirstissue.dev) need ≥ 3 to surface the repo"
```

If the label has 0 open issues, GitHub's contributor-discovery surfaces won't list the repo. Open at least 3 at all times.

**Issue and PR response time:**

GitHub surfaces repos where maintainers respond quickly. Even a "Thanks for
the report, I'll look at this soon" comment signals life.

**The "used by" network effect:**

Once the repo has users, GitHub's "Used by" feature (visible on the repo
sidebar) drives organic discovery. Encourage early users to add the repo
as a dependency — even in a demo project.

**Star-begging anti-pattern:**

Never add "⭐ Please star this repo if you find it useful!" to the README.
It reads as desperate and is a known conversion-killer. Let the quality
of the project do the asking.

**GitHub Sponsors / FUNDING.yml — verify, don't recreate:**

```bash
if [ -f .github/FUNDING.yml ]; then
  echo "FUNDING.yml exists — verify the username/org is current"
  cat .github/FUNDING.yml
else
  echo "Add FUNDING.yml — the Sponsor button is a trust signal even without donations"
fi
```

Beyond trust, `FUNDING.yml` puts the repo in GitHub's sponsor-discovery surfaces and adds a `❤️ Sponsor` button on every PR/issue, increasing per-page conversion. If it exists, verify the GitHub username/org is current and that the Sponsor button renders on the repo home page.

```yaml
# .github/FUNDING.yml (template if missing)
github: [your-username]
```

**Output:** list of discussion threads to seed, 5 specific good-first-issue
write-ups (title + description + acceptance criteria), FUNDING.yml.

---

### Subagent E — Distribution and launch strategy
**Goal: get the repo in front of the right developers at the right moment**

**The geolens-specific angle:**

The intersection of `PostGIS + pgvector + FastAPI` is genuinely novel territory
today. Most vector search tutorials use Pinecone or Weaviate. Most PostGIS
tutorials use Django or raw SQL. A production-grade stack combining both with
async Python is a real gap in the ecosystem. This is the story to tell.

**Hacker News — Show HN:**

`Show HN: [project] — [what it does unusually well]`

The HN Show HN format:
```
Show HN: Geolens – combine semantic search and spatial proximity in one query

Geolens is a starter stack for location-aware apps that need both vector 
similarity search (via pgvector) and geospatial queries (via PostGIS) — 
served by async FastAPI with a React frontend.

The interesting part: a single query can find "coffee shops with vibes 
similar to this description, within 500m of this location" using a joined 
pgvector cosine similarity + PostGIS ST_DWithin, indexed with HNSW + GIN.

Most vector search tools treat geography as a filter, not a first-class 
query dimension. PostGIS does it the other way. This stack marries both.

GitHub: [url]
Demo: [url if available]
```

Timing: Tuesday–Thursday, 9–11am US Eastern. Avoid Mondays and Fridays.

**Alternative HN draft — themed-demo angle (recommended for 1.0 launch):**

```
Show HN: GeoLens 1.0 — one-command spatial data catalog with themed demos

GeoLens is an open-source self-hosted spatial data catalog. `docker compose 
up` gives you a working UI in 5 minutes, preloaded with 9 themed demo maps 
(Borders & Boundaries, One Territory Multiple Maps, Earth from Space, …).

It's OGC- and STAC-native (works with QGIS/ArcGIS/MapLibre out of the box), 
handles vector + raster + VRT mosaics in one catalog, and bundles semantic 
+ spatial + fuzzy search (pgvector + pg_trgm + PostGIS). Optional AI 
chat-with-maps with BYO key.

Apache 2.0. Single-org self-host is free; single-tenant Enterprise edition 
exists for orgs that want SAML + audit logs.

GitHub: [url]
Demo: [url if available]
```

The pgvector × PostGIS draft above is fine as alternative #2 (better fit for r/Python or r/MachineLearning); the themed-demo draft is the visual one for HN's home page.

**Reddit communities:**

- `r/Python` — frame as "I built an async FastAPI stack for geo+vector search"
- `r/geospatial` — frame as "PostGIS + pgvector for semantic location search"
- `r/MachineLearning` — frame as "combining spatial and semantic search"
- `r/webdev` — frame as the React + spatial data angle
- `r/selfhosted` — if there's a Docker compose demo

Each community wants a different angle on the same project.

**dev.to / Hashnode article:**

A technical deep-dive article drives long-tail traffic for months. Suggested
titles:
- "Why I put pgvector and PostGIS in the same Postgres database (and how)"
- "Building location-aware semantic search: PostGIS + pgvector + FastAPI"
- "The async Python geo stack: SQLAlchemy 2.0 + GeoAlchemy2 + pgvector"
- "From coordinates to meaning: combining spatial and vector search"
- "Why we built a self-hosted spatial data catalog (and shipped 1.0 in public)"
- "Themed demos as a launch strategy: how GeoLens 1.0 ships with 9 working maps"

The article should:
1. Start with the problem (pure vector search ignores geography;
   pure spatial search ignores meaning)
2. Show the interesting query (ST_DWithin + cosine_distance in one statement)
3. Explain the stack decisions (why asyncpg, why HNSW, why dual DSN)
4. Link to the repo at least 3 times

**Twitter/X thread format:**
```
1/ I've been building a location + AI search stack in public.

   Here's what I learned combining PostGIS and pgvector in the same 
   Postgres database — a thread 🧵

2/ The problem: vector search tools treat geography as a filter.
   PostGIS treats it as a first-class query dimension.
   
   What if you could combine both?

3/ The query that made me think this was worth sharing:

   [code example showing ST_DWithin + cosine_distance]

4/ The stack:
   → FastAPI (async, Pydantic v2)
   → SQLAlchemy 2.0 + asyncpg
   → GeoAlchemy2 for PostGIS
   → pgvector with HNSW index
   → React + React Query

5/ The non-obvious decisions:
   → jit=off on the Postgres engine (pgvector + JIT = trouble)
   → dual DSNs: asyncpg for the app, psycopg for Alembic
   → HNSW over IVFFlat (no training step, better recall on growing data)

6/ Open source, MIT licensed, Docker Compose for one-command setup.

   [link to repo]
```

**Community-specific venues:**

- **PostGIS mailing list / Twitter** — the PostGIS community loves seeing
  novel uses of the extension
- **pgvector GitHub discussions** — commenting on pgvector discussions with
  "here's how we're using it" links back to the project organically
- **FastAPI Discord** — `#show-your-project` channel
- **Pydantic Discord** — similar
- **GIS Stack Exchange** — answer questions about Python + PostGIS and link
  to the project when genuinely relevant (not spam)

**Demo importance:**

A live demo is worth 10× the README. For geolens:
- Railway / Render / Fly.io — free tier deployment, one-click from README
- A Loom video (2–3 minutes) showing the spatial + semantic search in action
- An interactive example in the README using a real dataset (OpenStreetMap,
  Overture Maps, etc.)

If a live demo isn't feasible, an animated GIF in the README of a real
query executing in the UI is the next best thing.

**Output:** ready-to-post content for HN (Show HN post), dev.to article
outline with the interesting technical content filled in, Twitter thread draft,
Reddit post variants for each community, list of community-specific venues
with specific engagement strategies.

---

### Subagent F — Public-release readiness audit
**Goal: the repo is genuinely launch-ready — no version desync, no leftover internal references, no removed-component references, no real secrets in `.env.example`, no broken README images, no visitor-facing open-core dishonesty**

This auditor focuses on what a launch reviewer or a GitHub-front-page visitor would notice. It does NOT cover release-machinery wiring (CI publish targets, signing, supply-chain — those live elsewhere).

**Checks F.1–F.10:**

#### F.1 Version sync

```bash
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

# Docker image tags in README and compose
grep -nE 'ghcr\.io/[^ ]+:[0-9][^ ]*|geolens-io/[^:]+:[0-9][^ ]*' README.md docker-compose.yml 2>/dev/null
```

**Pass:** `frontend/package.json` == `backend/pyproject.toml` == top dated `CHANGELOG.md` entry. Git tag should equal one of these or `v$VERSION`. Any divergence = **P0 BLOCKER**.

#### F.2 Leftover internal references

```bash
USER_FACING="README.md CHANGELOG.md FEATURES.md docs/ .github/"

echo "=== Internal-path leakage ==="
grep -rnE 'docs-internal/|\.planning/|GTM/' $USER_FACING 2>/dev/null | grep -v '\.git/'

echo "=== GSD / internal-tooling refs ==="
grep -rnE '\bgsd-[a-z-]+|\.claude/(commands|worktrees)' $USER_FACING 2>/dev/null

echo "=== Internal admin / audit paths ==="
grep -rnE 'docs-internal/audits|post-impl-[0-9]+\.md' $USER_FACING 2>/dev/null
```

**Pass:** zero matches. Any hit = **P1 RELEASE-BLOCKING**.

#### F.3 Removed-component references — parameterized

Maintain a `REMOVED_COMPONENTS` array per project. For geolens:

```bash
REMOVED_COMPONENTS=(
  "pg_tileserv"                    # removed v7.0
  "pg_featureserv"                 # removed v2.2
  "SHOW_LANDING_PAGE"              # env var removed v13.x
  "VITE_API_PROXY_TARGET"          # renamed (one-release fallback only)
  "AWS_MARKETPLACE_PRODUCT_CODE"   # enterprise-overlay-only as of v13.3
)

USER_FACING="README.md FEATURES.md docs/ .env.example docker-compose*.yml"

for comp in "${REMOVED_COMPONENTS[@]}"; do
  echo "=== $comp ==="
  # CHANGELOG entries about removal are expected — flag only OUTSIDE CHANGELOG.
  grep -rnE "\b${comp}\b" $USER_FACING 2>/dev/null | grep -v 'CHANGELOG.md'
done
```

**Pass:** zero matches outside CHANGELOG. Any match = **P1 RELEASE-BLOCKING** — README must not advertise services the project no longer ships.

#### F.4 CHANGELOG hygiene

```bash
echo "=== CHANGELOG format ==="

# Keep a Changelog header reference
head -5 CHANGELOG.md | grep -E "Keep a Changelog" || echo "MISS: no Keep-a-Changelog reference in CHANGELOG header"

# Latest tagged version present and dated
grep -E '^## \[[0-9]' CHANGELOG.md | head -3

# Unreleased section size sanity
UNREL_LINES=$(awk '/^## \[Unreleased\]/,/^## \[[0-9]/' CHANGELOG.md | wc -l)
echo "Unreleased section: $UNREL_LINES lines"
[ "$UNREL_LINES" -gt 200 ] && echo "FLAG: Unreleased section may be hiding an unreleased release — consider tagging"

# Stale-dated entries inside Unreleased
grep -A 50 '^## \[Unreleased\]' CHANGELOG.md | grep -oE '\(20[0-9][0-9]-[0-9]{2}-[0-9]{2}\)' | head -5
```

**Pass criteria:**
- Keep a Changelog 1.1.0 reference in header (NOT 1.0.0 — geolens is on 1.1.0)
- Most-recent dated entry: format `## [X.Y.Z] - YYYY-MM-DD`
- `[Unreleased]` either empty or actively in progress
- Latest entry's date within 90 days of `git log -1 --format=%ci` (warn otherwise)

Each fail = **P2 QUALITY**.

#### F.5 Demo-link liveness — flag for human verification

```bash
echo "=== Demo / live URLs declared in README ==="
head -100 README.md | grep -oE 'https://[^ )"]+' | sort -u

echo "=== Heuristic: known demo domains ==="
head -200 README.md | grep -oE 'https://[^ )"]+' | grep -E 'demo|live|getgeolens|geolens\.io' | sort -u
```

**Pass:** report-only. Output a "DEMO LINKS — VERIFY MANUALLY" block in findings. Add to BLOCKERS only if README explicitly promises a demo and the URL is `localhost` or a placeholder.

#### F.6 LICENSE existence + match with README

```bash
echo "=== LICENSE check ==="

test -f LICENSE && echo "LICENSE: present" || echo "LICENSE: MISSING (P0)"

LICENSE_NAME=$(head -3 LICENSE 2>/dev/null | grep -oiE 'mit|apache|gpl|bsd|mozilla|unlicense' | head -1)
echo "Detected from LICENSE: $LICENSE_NAME"

README_LICENSE=$(grep -oiE 'license[^A-Za-z]+(mit|apache[ -]?2\.?0|gpl-?[23]|bsd-[23]|mpl-?2)' README.md | head -3)
echo "README claims: $README_LICENSE"

grep -oE '!\[[^]]*[Ll]icense[^]]*\][^)]+' README.md | head -3
```

**Pass:** LICENSE exists AND detected type matches README claim AND license badge. Mismatch = **P0 BLOCKER** (legal risk).

#### F.7 `.env.example` presence + secret-leak heuristic

```bash
echo "=== .env.example check ==="

test -f .env.example && echo ".env.example: present" || echo ".env.example: MISSING (P1)"

echo "=== Suspicious values in .env.example ==="

# AWS-style keys
grep -nE 'AKIA[0-9A-Z]{16}|aws_secret_access_key=[A-Za-z0-9/+=]{40}' .env.example 2>/dev/null

# High-entropy strings (32+ chars), excluding obvious placeholders
grep -nE '=[A-Za-z0-9+/=_-]{32,}' .env.example 2>/dev/null \
  | grep -viE 'change[ _-]?me|placeholder|example|your[ _-]|secret[ _-]?here|<.*>|xxx|yyy|zzz|todo' \
  | grep -viE '=admin$|=password$|=changeme$' \
  | head -10

# Common API key formats
grep -nE 'sk-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9-]+|ghp_[A-Za-z0-9]{36}|github_pat_' .env.example 2>/dev/null
```

**Pass:** `.env.example` exists AND no values match real-secret heuristics. Any match = **P0 BLOCKER** (refuse-to-launch — credential leak).

#### F.8 WIP / "Coming soon" / TODO scan in user-facing docs

```bash
echo "=== WIP / TODO / Coming Soon scan ==="

USER_FACING="README.md FEATURES.md docs/"

grep -rniE 'coming soon|work[ -]in[ -]progress|\bWIP\b|\bTODO\b|\bFIXME\b|XXX:|to be added|under construction' \
  $USER_FACING 2>/dev/null \
  | grep -viE '^\s*//|^\s*#'

grep -niE '^#+ +(roadmap|future|planned|coming|upcoming)' $USER_FACING 2>/dev/null
```

**Pass:** zero matches in README hero (first 100 lines). Matches in deeper docs = **P2 QUALITY**. A "Roadmap" section is fine; recommend wording it as "What's next" rather than "Coming soon".

#### F.9 Stale screenshots / assets — heuristic with documented limitation

```bash
echo "=== Asset freshness heuristic ==="

README_IMAGES=$(grep -oE '\(docs/images/[^)]+\)|src="docs/images/[^"]+"' README.md | sed -E 's/.*(docs\/images\/[^)"]+).*/\1/' | sort -u)

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

**Pass:** missing files = **P0 BLOCKER** (broken README image). Stale > 90 days behind UI changes = **P2 QUALITY** + flag for human review (UI commits don't always change visible UI). **Heuristic limitation — explicit:** treat findings as a prompt for visual review, not a hard gate.

#### F.10 Visitor-facing open-core / enterprise honesty

**Out of scope: engineering-level open-core separation — run `/oc-audit` for that.**

This check covers ONLY what a community visitor would notice:

```bash
echo "=== F.10 Visitor-facing open-core honesty ==="

# Enterprise-only feature mentions in feature lists — must be tagged (Enterprise) or similar
echo "--- Untagged enterprise features in user-facing docs ---"
USER_FACING="README.md FEATURES.md docs/"
# Look for keywords that typically describe enterprise-only features in this project
grep -rniE '\b(SAML|SSO|audit log|RBAC|multi-org|multi-tenant|enterprise edition)\b' $USER_FACING 2>/dev/null \
  | grep -vE '\(Enterprise\)|\[Enterprise\]|<sup>Enterprise</sup>|requires Enterprise' \
  | head -10

# Broken cross-repo references — links/screenshots pointing at the enterprise repo
echo "--- Broken cross-repo refs (enterprise paths in public README) ---"
grep -nE 'geolens-enterprise/|/enterprise-only/' README.md docs/ 2>/dev/null

# Pricing / upsell tone — flag if any banner-like construct
echo "--- Aggressive upsell / banner detection ---"
grep -nE '!\[.*[Pp]ricing.*\]|!\[.*[Uu]pgrade.*\]|<!--.*[Pp]ricing.*-->' README.md 2>/dev/null
head -50 README.md | grep -niE 'upgrade now|buy now|enterprise plan|starting at \$' | head -5
```

**Pass criteria:**
- Enterprise-only features mentioned in user-facing docs are tagged (e.g. `(Enterprise)`, `<sup>Enterprise</sup>`, "requires Enterprise edition") so OSS visitors don't bounce trying things that don't exist in OSS.
- No broken cross-repo references — public repo must not link to paths only present in `geolens-enterprise`.
- Pricing/upsell tone restrained — one understated link, never a banner. Aggressive constructs = **P2 QUALITY** (community trust signal).

Each tagging miss in user-facing docs = **P2 QUALITY** (unless the feature is described as available when it isn't — that's **P1 RELEASE-BLOCKING**, dishonesty in feature lists). Cross-repo broken refs = **P1 RELEASE-BLOCKING**.

**Output (Subagent F):** structured findings keyed by F.1–F.10, each tagged P0 / P1 / P2 / OK, with concrete file:line references where applicable. Pass through to Phase 2.5 for synthesis.

---

## Phase 2.5 — Release-readiness gate

After Subagents A–F complete, before Phase 3 prioritised plan, synthesise Subagent F findings into a single readiness verdict.

**P0 BLOCKERS** — STOP, fix before any star-growth work:
- F.1 version desync
- F.6 LICENSE missing or mismatched
- F.7 real secret in `.env.example`
- F.9 README image file missing

**P1 RELEASE-BLOCKING** — fix before public launch but report can continue:
- F.2 internal references in user-facing docs
- F.3 removed-component references in user-facing docs
- F.7 `.env.example` missing
- F.10 cross-repo broken refs OR feature-list dishonesty
- C2 install-flow audit failure (npm/PyPI/Docker package not resolvable)

**P2 QUALITY** — mention in prioritised plan, don't block:
- F.4 CHANGELOG format issues
- F.8 WIP/TODO in deeper docs
- F.9 stale screenshots heuristic flag
- F.10 untagged enterprise features OR aggressive upsell tone

**Output rules:**

- If any P0 or P1 finding exists, emit a top-of-report `## BLOCKERS` section listing each finding with file:line reference and the recommended fix. The prioritised plan in Phase 3 must surface these as the first quick wins.
- If no P0/P1 findings, emit: `Public-release readiness: ✅ no blockers detected (still flagged for human verification: <demo links from F.5>)`.
- P2 findings always feed into the prioritised plan as quality items, never the BLOCKERS section.

---

## Phase 3 — Prioritised action plan

Merge all subagent outputs. Score every finding on a 2×2:
- **X axis:** effort (Low = 1 hour, High = 1 week)
- **Y axis:** expected star velocity impact (Low, Medium, High, Very High)
```markdown
# Star audit report
Date: [date]

## Current state assessment
- README score: [X/10]
- Trust signal score: [X/10]
- Discoverability score: [X/10]
- Community score: [X/10]
- Distribution readiness: [X/10]

## Quick wins (< 1 hour each, do today)
1. [action] — expected impact: [stars/month estimate]
2. ...

## High-leverage (1–4 hours, do this week)
1. [action] — expected impact
2. ...

## Strategic (1+ day, plan for this month)
1. [action] — expected impact
2. ...

## The single most important thing
[One recommendation: the change that would have the biggest immediate
impact on star velocity based on the audit]
```

**The "do nothing" branch:**

If the audit finds no changes scoring ≥ Medium impact AND Phase 2.5 reports no BLOCKERS, the report should state that explicitly:

> Public-release readiness: clean. README scores ≥ 8/10 across all dimensions. Recommendation: **launch the existing README**. Ship it.

A meta-audit that always finds work to do is suspicious. Permitting a "ship it" verdict is the credibility check.

**The star velocity model:**

| Action | Effort | Expected impact |
|--------|--------|----------------|
| Custom social preview image | 1h | +30–50% click-through on shares |
| Demo GIF in README hero | 2h | +50–100% README conversion |
| GitHub topics (all 20) | 10min | +20–40% organic discovery |
| Show HN post | 2h | +200–500 stars on a good day |
| dev.to article | 4h | +50–200 stars, long-tail traffic |
| Good first issues × 5 | 1h | +contributors → advocates |
| Live demo deployment | 4h | +2–3× README conversion |
| Awesome list submission × 3 | 30min | +100–300 stars |
| GitHub Discussions | 30min | +community compounding |
| Fix version desync | 30min | trust signal — eliminates "is this even maintained?" doubt |
| Remove internal-path refs from public docs | 30min | removes legitimacy concerns |
| Replace stale screenshots | 1h | first-impression quality — visible above the fold |
| 60s "first run" screencast | 2h | +30–50% README-to-clone conversion |
| Star-history badge (after 200+ stars) | 5min | social-proof compounding |

---

## Phase 4 — Generate all content (if `--write` flag set)

Produce every content artifact as a ready-to-use file:

**Pre-flight guard — diff, don't overwrite:**

For each artifact below: if a file already exists at the target path, **diff against the existing version and produce a patch**, NOT a wholesale replacement. Skip generation if the existing file is materially complete (> 30 lines AND not a stub).

```bash
for f in README.md CONTRIBUTING.md .github/CONTRIBUTING.md CHANGELOG.md SECURITY.md \
         .github/ISSUE_TEMPLATE/bug_report.yml .github/ISSUE_TEMPLATE/feature_request.yml \
         .github/PULL_REQUEST_TEMPLATE.md .github/FUNDING.yml; do
  if [ -f "$f" ]; then
    LINES=$(wc -l < "$f")
    echo "$f: exists ($LINES lines) — diff against draft, do not overwrite"
  else
    echo "$f: missing — generate from template below"
  fi
done
```

The CHANGELOG.md, CONTRIBUTING.md, and README.md templates below are starting points, not destinations. Real geolens already has multi-thousand-line versions of these — overwriting them would destroy real content.

**1. `README.md` — complete rewrite**

Write the full README using the structure from Subagent A, incorporating:
- The value proposition headline
- Correct technology terms for discoverability
- Real code example (the most interesting query possible)
- Quick start that works with `docker compose up`
- Architecture section
- All relevant badges (no vanity badges)
- Link section

**2. `CONTRIBUTING.md`**
```markdown
# Contributing to geolens

We welcome contributions! Here's how to get started.

## Development setup
[docker compose up instructions, make commands]

## Making changes
1. Fork the repo
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Make your changes with tests
4. Run the test suite: `pytest -q && npx playwright test`
5. Submit a PR using the PR template

## Areas where we'd love help
- [specific areas from good first issues]

## Code style
- Python: ruff + mypy strict
- TypeScript: ESLint + Prettier
- Commit style: conventional commits (feat:, fix:, docs:, chore:)

## Questions?
Open a GitHub Discussion — we're friendly.
```

**3. `.github/ISSUE_TEMPLATE/bug_report.yml`**
```yaml
name: Bug report
description: Something isn't working
labels: ["bug"]
body:
  - type: markdown
    attributes:
      value: Thanks for taking the time to file a bug report.
  - type: textarea
    id: what-happened
    attributes:
      label: What happened?
      description: A clear description of the bug.
    validations:
      required: true
  - type: textarea
    id: reproduce
    attributes:
      label: Steps to reproduce
      value: |
        1. 
        2. 
        3. 
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: Expected behaviour
    validations:
      required: true
  - type: input
    id: version
    attributes:
      label: Python version
    validations:
      required: true
  - type: textarea
    id: logs
    attributes:
      label: Relevant logs
      render: shell
```

**4. `.github/ISSUE_TEMPLATE/feature_request.yml`**
```yaml
name: Feature request
description: Suggest an idea for geolens
labels: ["enhancement"]
body:
  - type: textarea
    id: problem
    attributes:
      label: What problem does this solve?
      description: Describe the use case.
    validations:
      required: true
  - type: textarea
    id: solution
    attributes:
      label: Proposed solution
    validations:
      required: true
  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives considered
```

**5. `.github/PULL_REQUEST_TEMPLATE.md`**
```markdown
## What does this PR do?

## Why?

## Testing
- [ ] Tests added/updated
- [ ] `pytest -q` passes
- [ ] TypeScript types check: `npx tsc --noEmit`

## Checklist
- [ ] I've read CONTRIBUTING.md
- [ ] My changes follow the project conventions in CLAUDE.md
- [ ] I've updated docs if needed
```

**6. `CHANGELOG.md`** (skip if exists with `[1.0.0]` or higher entry — diff instead)

```markdown
# Changelog

All notable changes to geolens are documented here.
Format: [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
versioning: [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-04-01

### Added
- Public 1.0 release. Versions reset from 13.x → 1.0.0; the prior 13.x line was a pre-public version history.
- (See git history and prior milestone summaries for the actual feature set shipped through 1.0.0.)
```

If the real CHANGELOG.md already exists and has a `[1.0.0]` (or later) entry, do NOT generate this template — diff and propose specific edits instead. **Never emit a `## [0.1.0] - [date]` stub** — that would regress version history (geolens shipped 1.0.0 on 2026-04-01).

**7. `SECURITY.md`**
```markdown
# Security Policy

## Supported versions
| Version | Supported |
|---------|-----------|
| latest  | ✅ |

## Reporting a vulnerability

Please do not report security vulnerabilities through public GitHub issues.

Email: [your-email] with subject "SECURITY: geolens"

You'll receive a response within 48 hours. We'll work with you to
understand and address the issue before public disclosure.
```

**8. `.github/FUNDING.yml`**
```yaml
github: [your-github-username]
```

**9. Show HN post** — complete, ready to submit
**10. dev.to article outline** — with the interesting technical content
**11. Twitter/X thread** — complete, 8–12 tweets
**12. Reddit posts** — 4 variants for different communities

**13. `RELEASE-READINESS.md`** — local checklist file capturing the F.1–F.10 outcomes, machine-readable so a future re-run can diff. Write to `docs-internal/audits/release-readiness-{YYYYMMDD}.md` (since `docs-internal/` is gitignored — local-only by design).

```markdown
# Release-readiness audit — {YYYYMMDD}

| Check | Status | Notes |
|-------|--------|-------|
| F.1 Version sync | ✅/⚠️/❌ | <findings> |
| F.2 Internal refs | ✅/⚠️/❌ | <findings> |
| F.3 Removed-components | ✅/⚠️/❌ | <findings> |
| F.4 CHANGELOG hygiene | ✅/⚠️/❌ | <findings> |
| F.5 Demo links (manual) | 📋 | <list URLs to verify> |
| F.6 LICENSE match | ✅/⚠️/❌ | <findings> |
| F.7 .env.example | ✅/⚠️/❌ | <findings> |
| F.8 WIP/TODO scan | ✅/⚠️/❌ | <findings> |
| F.9 Stale screenshots (heuristic) | ✅/⚠️/❌ | <findings> |
| F.10 OC visitor honesty | ✅/⚠️/❌ | <findings> |

## BLOCKERS (P0/P1)

<list with file:line refs>

## Quality items (P2)

<list>
```

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/star-audit-{YYYYMMDD}.md`

```bash
mkdir -p docs-internal/audits/
# docs-internal/ is gitignored — audit reports are local-only by design.
# To share findings, copy out manually (e.g. to a private gist or email).
```

### Post-delivery

1. If a previous `star-audit-*.md` exists in `docs-internal/audits/`, diff key findings against the prior report and surface deltas.
2. If Phase 2.5 emitted a `## BLOCKERS` section, also write the same content to `docs-internal/audits/release-readiness-{YYYYMMDD}.md` (per Phase 4 artifact #13).
3. Print a one-line summary: overall readiness score + top quick win + estimated star-velocity impact + BLOCKERS count (or "✅ no blockers").

---

## What NOT to do

These are proven ways to hurt star growth — do not suggest them:

- "⭐ Star this repo if you find it useful!" in the README — desperate, kills trust
- Excessive badges that don't communicate value (code coverage %, build status)
- Roadmap items marked "coming soon" — signals incomplete
- "WIP" or "work in progress" anywhere visible — makes people wait rather than star
- Self-promotional language ("the best", "the only", "revolutionary")
- Copying README structure from large framework repos — they have stars from
  usage, not from README quality
- Submitting to awesome lists before the repo is genuinely useful
  — one rejection is fine, a bad reputation is not
- Creating fake activity (trivial commits to look active) — experienced
  developers notice
- Twitter threads that are all hype and no substance — the technical
  community respects depth

---

## The geolens unique angle — never dilute this

GeoLens 1.0.0 differentiators (in priority order for a launch audience):

1. **One-command spatial data catalog** — `docker compose up` to working UI in 5 minutes, with 9 themed demo maps preloaded (Borders & Boundaries, One Territory Multiple Maps, Earth from Space, …).
2. **OGC- and STAC-native** — works with QGIS, ArcGIS, MapLibre, and any OGC API Features/Records or STAC client out of the box.
3. **Vector + raster + VRT mosaics** in one catalog — the full geo-data shape, not just one slice.
4. **Semantic + spatial + fuzzy search** — pgvector + pg_trgm + PostGIS, indexed and queryable in a single SQL statement.
5. **AI chat with maps** (optional, BYO key) — natural-language exploration over the catalog.
6. **Open-core, Apache 2.0** — single-org self-host free; single-tenant Enterprise edition for orgs that want SAML + audit logs.

The pgvector × PostGIS angle is a real technical differentiator but it is **one of several**. Lead with the demo (one-command + themed maps), follow with the OGC/STAC interop, and treat the search-stack innovation as a section, not the headline.

Every piece of content should carry one or two of these — not all six at once. Specific, technical, true, and useful is what reads as star-worthy.