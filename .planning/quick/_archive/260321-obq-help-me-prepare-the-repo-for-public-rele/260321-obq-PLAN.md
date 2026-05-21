---
phase: quick-260321-obq
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .gitignore
  - README.md
autonomous: false
requirements: []

must_haves:
  truths:
    - "No internal planning, dev notes, or AI tooling artifacts are tracked in the public repo"
    - "README reflects actual GitHub org URL and current shipped feature set"
    - ".gitignore prevents internal files from being re-added"
  artifacts:
    - path: ".gitignore"
      provides: "Exclusion rules for internal files"
      contains: ".planning"
    - path: "README.md"
      provides: "Public-facing project documentation"
      contains: "Carto-Concepts/geolens"
  key_links:
    - from: ".gitignore"
      to: "git rm --cached"
      via: "files removed from tracking match new ignore rules"
      pattern: "\\.planning|plans/|\\.claude"
---

<objective>
Prepare the GeoLens repository for public release by removing internal development artifacts from git tracking, updating the README to reflect the actual project state, and hardening .gitignore to prevent internal files from being re-committed.

Purpose: The repo currently tracks ~1930 .planning files, .claude worktree files, internal dev notes (prd.md, todo.md, plans/, phase-89-search.md), and has a placeholder GitHub URL in the README. These must be cleaned before making the repo public.

Output: A clean repo state suitable for `git push` to a public GitHub repository.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@README.md
@.gitignore
@LICENSE
@LICENSE-FAQ.md
@docker-compose.yml
</context>

<tasks>

<task type="auto">
  <name>Task 1: Update .gitignore and remove internal files from tracking</name>
  <files>.gitignore</files>
  <action>
1. Add the following entries to .gitignore (append a new "# Internal development" section):

```
# Internal development
.planning/
.claude/
plans/
artifacts/
prd.md
todo.md
phase-*.md

# Stray screenshots
leave-warning-*.png
unsaved-state-*.png
```

2. Remove internal files from git tracking (files stay on disk, just untracked):

```bash
git rm -r --cached .planning/
git rm -r --cached .claude/
git rm -r --cached plans/
git rm --cached prd.md
git rm --cached todo.md
git rm --cached phase-89-search.md
```

Do NOT delete any files from disk. Only remove from git index. The `--cached` flag is critical.

3. Verify no .env files (other than .env.example) are tracked. Currently only `.env.example` and `helm/geolens/templates/secret.yaml` (a Helm template, not actual secrets) are tracked, which is correct.
  </action>
  <verify>
    <automated>git status --short | grep -c "^D " && echo "Deleted from index" || true; git ls-files | grep -cE '\.planning/|\.claude/|plans/|prd\.md|todo\.md|phase-89' | grep -q '^0$' && echo "PASS: no internal files tracked" || echo "FAIL: internal files still tracked"</automated>
  </verify>
  <done>No .planning/, .claude/, plans/, prd.md, todo.md, or phase-89-search.md files appear in `git ls-files`. All files still exist on disk. .gitignore contains rules preventing re-addition.</done>
</task>

<task type="auto">
  <name>Task 2: Update README for public release</name>
  <files>README.md</files>
  <action>
Update README.md with these changes:

1. **Fix GitHub URL**: Replace `YOUR_ORG/geolens` with `Carto-Concepts/geolens` (the actual remote origin).

2. **Update Features list** to reflect the full shipped feature set (v12.3). The current list is outdated. Replace the Features section with:

```markdown
## Features

- **Search and Discovery** -- Full-text search, spatial/bbox filtering, semantic search (pgvector)
- **Interactive Maps** -- MapLibre GL previews with vector tile streaming (ST_AsMVT)
- **Raster Support** -- COG/GeoTIFF ingestion, Titiler-powered tile serving, VRT mosaics
- **Map Builder** -- Create and share interactive maps with multiple layers, custom styling, and AI-assisted analysis
- **Multi-Format Export** -- GeoJSON, Shapefile, GeoPackage, CSV, KML
- **Dataset Ingestion** -- Upload Shapefile, GeoJSON, GeoPackage, CSV, GeoTIFF, and VRT files
- **Collections** -- Organize datasets into logical groups
- **OGC API Compliance** -- OGC API - Features and Tiles endpoints
- **Sharing and Embeds** -- Public share links and embeddable map iframes with token-based access
- **Admin Panel** -- User management, audit logging, system configuration
- **Internationalization** -- English, Spanish, French, and Chinese translations
- **JWT and API Key Auth** -- Token-based authentication with API key support for programmatic access
```

3. **Remove marketplace placeholder comments** (AWS and DigitalOcean sections). Replace those sections with a single note:

```markdown
### Cloud Deployment

See [docs/cloud-deployment.md](docs/cloud-deployment.md) for AWS, DigitalOcean, and Kubernetes deployment guides.
Helm charts are included in the `helm/` directory.
```

4. **Add a Contributing section** before the License section:

```markdown
## Contributing

Contributions are welcome. Please open an issue to discuss proposed changes before submitting a pull request.

## Architecture

| Component | Technology |
|-----------|------------|
| Backend | FastAPI (Python), SQLAlchemy, Alembic |
| Frontend | React 19, Vite, TanStack Query, MapLibre GL |
| Database | PostgreSQL + PostGIS + pgvector |
| Raster Tiles | Titiler |
| Object Storage | S3-compatible (MinIO for local dev) |
| Cache | Valkey (Redis-compatible) |
| Reverse Proxy | nginx |
```

5. **Keep** the existing Seed Data section, License section, and LICENSE-FAQ reference as-is (they are well-written).
  </action>
  <verify>
    <automated>grep -q "Carto-Concepts/geolens" README.md && echo "PASS: correct GitHub URL" || echo "FAIL: placeholder URL"; grep -q "YOUR_ORG" README.md && echo "FAIL: placeholder still present" || echo "PASS: no placeholder"; grep -q "Raster Support" README.md && echo "PASS: updated features" || echo "FAIL: features not updated"; grep -q "Contributing" README.md && echo "PASS: contributing section" || echo "FAIL: no contributing section"</automated>
  </verify>
  <done>README contains correct Carto-Concepts/geolens URL, updated feature list matching v12.3 capabilities, cloud deployment reference, architecture table, and contributing section. No placeholder comments remain.</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>Repository cleaned for public release: internal dev files (.planning, .claude, plans, prd.md, todo.md) removed from git tracking, .gitignore updated, README rewritten with current features, correct URLs, and architecture overview.</what-built>
  <how-to-verify>
    1. Run `git ls-files | grep -E '\.planning/|\.claude/|plans/|prd\.md|todo\.md'` -- should return empty
    2. Run `cat README.md` -- review for accuracy and presentation quality
    3. Confirm .planning/ and .claude/ directories still exist on disk (only untracked)
    4. Run `git diff --cached --stat` to review the full set of staged changes
    5. Decide whether to squash commit history before making public (this plan does NOT squash -- that is a destructive operation requiring explicit user decision)
  </how-to-verify>
  <resume-signal>Type "approved" to commit, or describe any issues with the README content or cleanup scope</resume-signal>
</task>

</tasks>

<verification>
- `git ls-files | grep -cE '\.planning/|\.claude/|plans/|prd\.md|todo\.md|phase-89'` returns 0
- `grep -c 'YOUR_ORG' README.md` returns 0
- `grep -c 'Carto-Concepts/geolens' README.md` returns at least 1
- All .planning/ and .claude/ files still exist on disk
</verification>

<success_criteria>
Repository is clean for public release: no internal development artifacts tracked, README accurately represents the project, .gitignore prevents re-introduction of internal files.
</success_criteria>

<output>
After completion, create `.planning/quick/260321-obq-help-me-prepare-the-repo-for-public-rele/260321-obq-SUMMARY.md`
</output>
