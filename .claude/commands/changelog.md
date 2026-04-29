# /changelog — Generate Changelog & Release Notes

Read git history between two refs (tags, branches, or commits), categorize changes by type and domain, and generate a polished `CHANGELOG.md` entry plus GitHub release notes. Designed for a solo developer shipping an open-core geospatial product to gov/enterprise buyers — the output signals professionalism and active maintenance.

**Usage:**
- `/changelog` — Generate for all commits since the last tag (or all commits if no tags exist)
- `/changelog v1.1.0` — Generate for commits since last tag, labeled as v1.1.0
- `/changelog v1.0.0..v1.1.0` — Generate for a specific range
- `/changelog --unreleased` — Generate an "Unreleased" section without a version number

---

## PHASE 0: DISCOVERY (Serial)

### Step 1: Understand the git state

```bash
# All tags, sorted by version
git tag --list --sort=-version:refname | head -20

# Latest tag
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null)
echo "Latest tag: ${LATEST_TAG:-'(none)'}"

# Current branch
BRANCH=$(git branch --show-current)
echo "Branch: $BRANCH"

# If a version argument was provided, parse the range
# Otherwise: LATEST_TAG..HEAD (or all history if no tags)
```

### Step 2: Gather raw commit data

```bash
# Commits in range with full metadata
# Format: hash | author | date | subject | body
git log ${FROM_REF}..${TO_REF:-HEAD} \
  --pretty=format:"%H|%an|%ai|%s|%b" \
  --no-merges 2>/dev/null

# Also grab merge commits separately (PR merges contain useful context)
git log ${FROM_REF}..${TO_REF:-HEAD} \
  --merges \
  --pretty=format:"%H|%an|%ai|%s|%b" 2>/dev/null

# Diff stats for the range
git diff --stat ${FROM_REF}..${TO_REF:-HEAD} 2>/dev/null

# Files changed summary
git diff --name-only ${FROM_REF}..${TO_REF:-HEAD} 2>/dev/null | sort

# Contributors in range
git log ${FROM_REF}..${TO_REF:-HEAD} --pretty=format:"%an" --no-merges 2>/dev/null | sort -u
```

### Step 3: Read existing changelog format

```bash
# Existing changelog
cat CHANGELOG.md 2>/dev/null | head -80

# Existing release notes format (from GitHub releases if gh CLI available)
gh release list --limit 3 2>/dev/null
gh release view $(git describe --tags --abbrev=0 2>/dev/null) 2>/dev/null
```

If an existing `CHANGELOG.md` exists, match its format exactly. If not, use the standard format defined below.

### Step 4: Read project context

```bash
# Package versions (for version number validation)
grep -i "version" backend/pyproject.toml 2>/dev/null | head -5
cat frontend/package.json 2>/dev/null | python3 -c "import sys,json; print('frontend:', json.load(sys.stdin).get('version','unset'))" 2>/dev/null

# Conventional commit usage (does the project use it?)
git log --oneline -20 2>/dev/null
```

---

## PHASE 1: COMMIT CLASSIFICATION (Serial)

### Categorize every commit

For each commit in the range, classify into exactly one category. Use the commit message first, then fall back to reading the diff if the message is ambiguous.

#### Category definitions

| Category | Icon | Trigger | Examples |
|----------|------|---------|----------|
| **Features** | ✨ | `feat:`, `add`, new endpoint, new component, new capability | New OGC endpoint, new map tool, new AI capability |
| **Fixes** | 🐛 | `fix:`, `bug`, `patch`, `resolve`, `correct` | Query fix, rendering fix, auth fix |
| **Performance** | ⚡ | `perf:`, `optimize`, `speed`, `cache`, `index` | Query optimization, tile caching, index addition |
| **Security** | 🔒 | `security:`, `auth`, `vuln`, `sanitize`, `injection` | Auth fix, input validation, SQL injection prevention |
| **Documentation** | 📚 | `docs:`, `readme`, `guide`, `comment` | README update, API docs, design guide |
| **Standards** | 🌐 | OGC, STAC, DCAT, FAIR, compliance, conformance | OGC endpoint fix, STAC schema update |
| **UI/UX** | 🎨 | `style:`, `ui:`, `ux:`, design, layout, theme, dark mode | Component update, responsive fix, theme change |
| **Infrastructure** | 🏗️ | `ci:`, `build:`, `docker`, `deploy`, migration, config | Docker update, CI pipeline, Alembic migration |
| **Refactor** | ♻️ | `refactor:`, restructure, rename, extract, simplify | Code reorganization, type cleanup |
| **Testing** | 🧪 | `test:`, `spec`, test file changes | New tests, test fixes |
| **Dependencies** | 📦 | `deps:`, `chore(deps)`, package updates, lockfile | Dependency updates, version bumps |
| **Breaking Changes** | 💥 | `BREAKING:`, `!:`, breaking, incompatible | API change, schema change, config change |

#### Domain classification

Also classify each commit by the GeoLens domain it primarily affects:

| Domain | Trigger (file paths and keywords) |
|--------|-----------------------------------|
| **Catalog & Search** | `backend/app/modules/catalog/search/`, `backend/app/modules/catalog/datasets/`, `backend/app/modules/catalog/collections/`, `backend/app/processing/embeddings/` |
| **Map & Visualization** | `backend/app/modules/catalog/maps/`, `backend/app/processing/tiles/`, `backend/app/processing/raster/`, `frontend/src/components/map/`, `frontend/src/components/builder/` |
| **Data Ingestion** | `backend/app/processing/ingest/`, `backend/app/processing/export/` |
| **Standards (OGC/STAC/DCAT)** | `backend/app/standards/ogc/`, `backend/app/standards/stac/`, `backend/app/standards/dcat/` |
| **Auth & Admin** | `backend/app/modules/auth/`, `backend/app/modules/admin/`, `backend/app/modules/audit/` |
| **AI** | `backend/app/processing/ai/` |
| **Frontend** | `frontend/src/` (when not map-specific) |
| **Infrastructure** | `docker-compose*`, `Dockerfile*`, `alembic/`, `.github/`, deployment configs |
| **Core** | `backend/app/core/`, `backend/app/core/db/`, `backend/app/modules/settings/`, cross-cutting changes |

When a commit touches multiple domains, assign the primary domain (largest diff) and note secondary domains.

#### Ambiguous commit resolution

If a commit message is terse or unclear:

```bash
# Read the actual diff to understand the change
git show --stat $COMMIT_HASH
git show --no-stat $COMMIT_HASH | head -80
```

Classify based on what the code change actually does, not what the message says. A commit with message "update" that adds a new API endpoint is a Feature, not a Chore.

### Merge and deduplicate

- If a merge commit and its constituent commits both appear, keep the individual commits and drop the merge (unless the merge message adds unique context like a PR description).
- If multiple commits clearly represent one logical change (e.g., "add feature X" + "fix typo in feature X" + "lint fix for feature X"), merge them into a single changelog entry attributed to the first commit.
- Squash fixup commits (`fixup!`, `squash!`, `amend`) into their parent.

---

## PHASE 2: CHANGELOG GENERATION (Serial)

### Determine version number

If the user provided a version number, use it. Otherwise:

```bash
# Infer from the latest tag using semver
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null)

# Determine bump level from commit categories:
# - Any BREAKING CHANGE → major bump
# - Any Feature → minor bump
# - Only Fixes/Perf/Docs → patch bump
```

If `--unreleased` was specified, use "Unreleased" as the version.

### Generate the changelog entry

**Format:**

```markdown
## [VERSION] — YYYY-MM-DD

SUMMARY_PARAGRAPH

### ✨ Features

- **Domain:** Description of the change. ([`abcdef1`](commit_url))
- **Domain:** Description of the change. ([`abcdef2`](commit_url))

### 🐛 Fixes

- **Domain:** Description of the fix. ([`abcdef3`](commit_url))

### ⚡ Performance

- **Domain:** Description of the optimization. ([`abcdef4`](commit_url))

### 🔒 Security

- **Domain:** Description of the security fix. ([`abcdef5`](commit_url))

### 🌐 Standards

- **Domain:** Description of the standards change. ([`abcdef6`](commit_url))

### 🎨 UI/UX

- **Domain:** Description of the UI change. ([`abcdef7`](commit_url))

### 🏗️ Infrastructure

- **Domain:** Description of the infra change. ([`abcdef8`](commit_url))

### 💥 Breaking Changes

- **Domain:** Description of what broke and migration path. ([`abcdef9`](commit_url))
```

#### Writing rules

**Summary paragraph:** 2–4 sentences capturing the release theme. What would a government GIS team care about? Lead with the most impactful change, mention standards/compliance improvements, note any breaking changes. This paragraph is what appears on the GitHub release and what people read first.

**Individual entries:**
- Write from the user's perspective, not the developer's
- Bad: "Refactored the tile service to use ST_AsMVTGeom"
- Good: "Vector tile generation now simplifies geometry per zoom level, reducing tile sizes by ~60% at low zooms"
- Bad: "Fixed bug in search query"
- Good: "Fixed a bug where searching for short terms (< 3 characters) returned no results due to trigram index minimum length"
- Include the domain tag in bold for scanability
- Link to the commit hash (short hash, linked to the repository URL)
- Keep each entry to one line (two max for complex changes)
- Breaking changes must include migration guidance

**Category ordering:** Features → Fixes → Performance → Security → Standards → UI/UX → Infrastructure → Breaking Changes. Omit empty categories.

**Entry ordering within categories:** Most impactful first, not chronological. The reader is scanning for what matters.

### Detect the repository URL

```bash
git remote get-url origin 2>/dev/null
# Parse into GitHub/GitLab URL base for commit links
# e.g., git@github.com:user/geolens.git → https://github.com/user/geolens
```

If the remote URL can't be parsed, use relative commit references (`abcdef1`) without links.

---

## PHASE 3: RELEASE NOTES GENERATION (Serial)

Generate GitHub Release Notes — a separate artifact from the changelog, optimized for the GitHub Releases page.

**Format:**

```markdown
SUMMARY_PARAGRAPH

## Highlights

- HIGHLIGHT_1 (most impactful feature or fix)
- HIGHLIGHT_2
- HIGHLIGHT_3

## What's Changed

### ✨ Features
- Description ([`hash`](url))

### 🐛 Fixes
- Description ([`hash`](url))

### ⚡ Performance
- Description ([`hash`](url))

(... remaining categories ...)

## 💥 Breaking Changes

BREAKING_CHANGE_DESCRIPTION_WITH_MIGRATION_GUIDE

## Upgrade Guide

STEP_BY_STEP_UPGRADE_INSTRUCTIONS_IF_NEEDED

---

**Full Changelog:** [`PREV_TAG...VERSION`](compare_url)
```

#### Release notes specific rules

- **Highlights section:** Pick the 3–5 most impactful changes. These are what someone scanning GitHub releases will read. Frame for the target audience (gov GIS teams, enterprise evaluators).
- **Upgrade Guide:** Only include if there are breaking changes or migration steps (Alembic migrations, config changes, env var changes). If none, omit the section.
- **Full Changelog link:** Link to the GitHub compare view between tags.
- **Shorter than the changelog** — the release notes are a summary. Collapse minor fixes and infra changes into a single line each if there are many.

---

## PHASE 4: STATS & METADATA (Serial)

Generate release statistics:

```bash
# Commit count
COMMIT_COUNT=$(git log ${FROM_REF}..${TO_REF:-HEAD} --oneline --no-merges 2>/dev/null | wc -l)

# Files changed
FILES_CHANGED=$(git diff --name-only ${FROM_REF}..${TO_REF:-HEAD} 2>/dev/null | wc -l)

# Insertions and deletions
git diff --shortstat ${FROM_REF}..${TO_REF:-HEAD} 2>/dev/null

# Contributors
CONTRIBUTORS=$(git log ${FROM_REF}..${TO_REF:-HEAD} --pretty=format:"%an" --no-merges 2>/dev/null | sort -u)

# Time span
FIRST_COMMIT_DATE=$(git log ${FROM_REF}..${TO_REF:-HEAD} --pretty=format:"%ai" --reverse 2>/dev/null | head -1)
LAST_COMMIT_DATE=$(git log ${FROM_REF}..${TO_REF:-HEAD} --pretty=format:"%ai" 2>/dev/null | head -1)

# Category breakdown
echo "Features: N | Fixes: N | Perf: N | Security: N | Standards: N | UI: N | Infra: N | Breaking: N"
```

---

## PHASE 5: DELIVERY (Interactive)

### Write the changelog entry

**If `CHANGELOG.md` exists:**

Read the existing file and prepend the new entry after the header, before the previous version entry. Maintain the existing format.

```bash
# Existing header pattern
head -5 CHANGELOG.md
```

Insert the new entry in the correct position — after the file header/title, before the previous release entry.

**If `CHANGELOG.md` does not exist:**

Create it with this structure:

```markdown
# Changelog

All notable changes to GeoLens are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [VERSION] — YYYY-MM-DD

(... generated entry ...)
```

### Write the release notes

Write to: `/tmp/release-notes-VERSION.md` (ephemeral — used for `gh release create`)

### Present both outputs

Show the generated changelog entry and release notes, then ask:

```
📋 Changelog entry (for CHANGELOG.md):
---
(preview)
---

📝 Release notes (for GitHub Release):
---
(preview)
---

📊 Release stats:
- N commits, N files changed, +N/-N lines
- Contributors: name1, name2
- Period: YYYY-MM-DD to YYYY-MM-DD
- Categories: N features, N fixes, N perf, ...

Actions:
1. Write changelog to CHANGELOG.md
2. Write changelog + create git tag
3. Write changelog + create git tag + push tag
4. Write changelog + create GitHub release (gh release create)
5. Preview only — don't write anything
```

### Execute chosen action

**Option 1:** Write `CHANGELOG.md` only.

**Option 2:** Write `CHANGELOG.md`, commit it, create an annotated tag:
```bash
git add CHANGELOG.md
git commit -m "docs: update changelog for VERSION"
git tag -a VERSION -m "Release VERSION"
```

**Option 3:** Option 2 + push:
```bash
git push origin $BRANCH
git push origin VERSION
```

**Option 4:** Option 3 + create GitHub release:
```bash
gh release create VERSION \
  --title "VERSION" \
  --notes-file /tmp/release-notes-VERSION.md \
  --target $BRANCH
```

If `gh` is not installed, output the release notes and the manual URL:
```
gh CLI not found. Create release manually:
https://github.com/<owner>/<repo>/releases/new?tag=VERSION

Release notes have been saved to /tmp/release-notes-VERSION.md
```

### Version bumping (optional)

If the user chose to tag, offer to bump version references:

```bash
# Find version strings in the project
grep -rn "version.*=\|\"version\":" backend/pyproject.toml frontend/package.json 2>/dev/null
```

```
Bump version references to VERSION?
- backend/pyproject.toml: "X.Y.Z" → "VERSION"
- frontend/package.json: "X.Y.Z" → "VERSION"
[y/n]
```

If yes, update the files and amend the changelog commit:
```bash
# Update versions
# ... (sed or python-based replacement)
git add backend/pyproject.toml frontend/package.json
git commit --amend --no-edit
# Re-tag if needed
git tag -f -a VERSION -m "Release VERSION"
```

---

## EDGE CASES

### No conventional commits

If the project doesn't use conventional commit prefixes (`feat:`, `fix:`, etc.):
- Classify based on diff content, not commit message
- Read each commit's changed files and diff to determine the category
- Note in the output that commit message conventions would improve future changelog generation

### Very large ranges (100+ commits)

If the range contains more than 100 commits:
- Group minor changes more aggressively (e.g., "Various bug fixes in the search module" instead of listing 15 individual search fixes)
- Keep individual entries for features, breaking changes, and security fixes
- Summarize infra/deps/refactor into single-line aggregates
- Add a "Full commit list" collapsed section at the bottom

### No tags exist

If the repository has no tags:
- Use the full history from the initial commit
- Suggest v1.0.0 as the first tag (per GTM evaluation recommendation)
- Note: "This appears to be the first release. Consider tagging v1.0.0 to establish a versioning baseline."

### Pre-release / release candidate

If the version contains `-rc`, `-beta`, `-alpha`:
- Mark the release as a pre-release in GitHub (`gh release create --prerelease`)
- Add a banner at the top: "⚠️ This is a pre-release. APIs and features may change before the stable release."

---

## CHANGELOG QUALITY RULES

### DO

- Lead with what matters to the user, not what was hard to build
- Use active voice ("Added", "Fixed", "Improved", not "was added", "has been fixed")
- Include the domain tag for every entry — readers scan by domain
- Quantify improvements where possible ("~60% smaller tiles", "3x faster search")
- Link every entry to its commit
- Include migration guidance for every breaking change
- Keep the summary paragraph under 4 sentences

### DO NOT

- List every commit verbatim — aggregate related changes
- Include merge commits, fixup commits, or "lint fix" commits as separate entries
- Use developer jargon without context ("Fixed N+1 query" → "Fixed slow loading when viewing dataset details")
- Include internal-only changes that users can't observe (unless they affect deployment)
- Editorialize ("Finally fixed the annoying bug...") — keep it professional
- Include commit hashes in the summary paragraph — only in individual entries
- Generate entries for changes that were introduced AND reverted within the same range

---

## WHAT NOT TO FLAG

- **Non-conventional commit messages** — Many projects don't use conventional commits. Classify by diff, not message format.
- **Merge commits** — Skip them unless they contain unique PR description context.
- **Lockfile-only commits** — Aggregate into "Updated dependencies" unless a specific dependency update is notable (security fix, major version bump).
- **CI-only changes** — Aggregate into a single "CI/CD improvements" entry unless a specific change affects users (e.g., new release pipeline).
- **Whitespace/formatting commits** — Skip entirely unless they're part of a larger change.