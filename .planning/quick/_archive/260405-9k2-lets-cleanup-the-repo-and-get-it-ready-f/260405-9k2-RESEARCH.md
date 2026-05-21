# Quick Task 260405-9k2: Cleanup Repo for Public Release - Research

**Researched:** 2026-04-05
**Domain:** Git history rewrite, open-source release hygiene
**Confidence:** HIGH

## Summary

The GeoLens repo needs history rewriting to purge `.planning/` (1,974 commits, 13MB), selective purging of internal docs from `docs/` (tracked despite gitignore), deletion of 72 stray screenshots, and .gitignore updates for `.agents/`, `.codex/`, `.claude/worktrees/`. The recommended tool is `git-filter-repo` — it needs to be installed via `brew install git-filter-repo`. There are 27 tags and one remote (`origin` on GitHub) that will be affected.

**Primary recommendation:** Use `git-filter-repo` with `--invert-paths` to strip `.planning/`, internal docs, and other artifacts in a single pass, then force-push. All tags will be deleted (fresh start for public release).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Rewrite git history to purge all .planning/ files from all commits (not just untrack)
- Force push required — user is aware and accepts this
- Delete all ~70 PNG screenshots in repo root — they are dev artifacts, already gitignored
- Commit the 15 currently modified files as a separate commit BEFORE starting cleanup work
- Audit existing public docs for internal references
- Review docs/ directory: public docs (install-guide, admin-guide, configuration-reference, upgrade-guide, cloud-deployment, database-design) should be tracked; internal-only docs (audits/, handoffs, UX plans, dep-audit, sec-audit, GTM/, decisions/) should stay gitignored
- .agents/ and .codex/ directories should be added to .gitignore
- DELETE ALL 27 TAGS and start fresh — no tags carried into public release

### Deferred Ideas (OUT OF SCOPE)
None specified.
</user_constraints>

## Standard Stack

### git-filter-repo vs BFG Repo-Cleaner

| Tool | Best For | Limitation |
|------|----------|------------|
| **git-filter-repo** (recommended) | Directory/path purging, complex filtering | Requires Python 3.5+ |
| BFG Repo-Cleaner | Large blob removal (files by size/name) | Cannot filter by path/directory — only by filename pattern |

**BFG cannot do what we need.** BFG operates on blob names (filenames), not paths. It cannot target `.planning/` as a directory path — it would match any file named `planning` anywhere. `git-filter-repo` is the correct tool for path-based filtering. [VERIFIED: BFG README states "BFG does not currently support filtering by path" — this is a well-known limitation]

**Installation:**
```bash
brew install git-filter-repo
```
[VERIFIED: brew availability confirmed on this machine]

**Neither git-filter-repo nor BFG is currently installed on this machine.** Java is also not available, ruling out BFG even if we wanted it. [VERIFIED: command checks returned empty]

## Architecture: Execution Order

The cleanup must happen in a specific sequence:

```
1. Commit working changes (15 modified files) — preserve current work
2. Delete stray PNGs from working tree (rm *.png in root)
3. Update .gitignore (add .agents/, .codex/, .claude/)
4. Commit deletions + gitignore update
5. Run git-filter-repo to purge paths from ALL history
6. Delete all tags (fresh start for public release)
7. Re-add remote origin (filter-repo removes it as safety measure)
8. Force-push all branches (no tags to push — deleted)
```

**Critical:** Steps 1-4 MUST happen before step 5 because `git-filter-repo` rewrites all commits. Any uncommitted work would be lost.

## Paths to Purge from History

Based on audit of tracked files and commits:

| Path | Commits | Action |
|------|---------|--------|
| `.planning/` | 1,974 | Purge entirely |
| `docs/audits/` | tracked | Purge (internal) |
| `docs/GTM/` | tracked | Purge (internal) |
| `docs/decisions/` | tracked | Purge (internal) |
| `docs/dep-audit-2026-03-31.md` | tracked | Purge (internal) |
| `docs/sec-audit-full-2026-03-30.md` | tracked | Purge (internal) |
| `docs/handoff-landing-page-oss-identity-20260403.md` | tracked | Purge (internal) |
| `docs/ux-plan-landing-page-20260403.md` | tracked | Purge (internal) |
| `docs/ux-review-map-builder-retroactive-2026-03-31.md` | tracked | Purge (internal) |
| `docs/api-contract-full-2026-03-30.md` | tracked | Purge (internal — dated snapshot) |
| `docs/cloud-readiness-assessment.md` | tracked | Purge (internal assessment) |
| `docs/connection-budget.md` | tracked | Purge (internal perf doc) |
| `docs/DESIGN-GUIDE.md` | tracked | Keep (public) |
| `plans/` | 13 commits | Purge |
| `prd.md` | 13 commits total | Purge |
| `todo.md` | in those 13 | Purge |
| `smoke-check.md` | in those 13 | Purge |
| `.agents/` | 2 commits | Purge |
| `.codex/` | 2 commits | Purge |
| `.claude/` | 2 commits | Purge |

### Docs to KEEP tracked (public-facing)
- `docs/install-guide.md`
- `docs/admin-guide.md`
- `docs/configuration-reference.md`
- `docs/upgrade-guide.md`
- `docs/cloud-deployment.md`
- `docs/database-design.md`
- `docs/DESIGN-GUIDE.md`
- `docs/testing-and-ci.md`
- `docs/resource-sizing.md`
- `docs/aws-security-groups.md`
- `docs/metadata-standards.md`
- `docs/marketplace-description.md`
- `docs/widget-development.md`
- `docs/llm-data-features.md`
- `docs/llm-map-features.md`
- `docs/images/` (screenshots used in docs)

## git-filter-repo Usage

### Single-pass purge command
```bash
git filter-repo \
  --invert-paths \
  --path .planning/ \
  --path plans/ \
  --path prd.md \
  --path todo.md \
  --path smoke-check.md \
  --path artifacts/ \
  --path .agents/ \
  --path .codex/ \
  --path .claude/ \
  --path docs/audits/ \
  --path docs/GTM/ \
  --path docs/decisions/ \
  --path docs/dep-audit-2026-03-31.md \
  --path docs/sec-audit-full-2026-03-30.md \
  --path docs/handoff-landing-page-oss-identity-20260403.md \
  --path docs/ux-plan-landing-page-20260403.md \
  --path docs/ux-review-map-builder-retroactive-2026-03-31.md \
  --path docs/api-contract-full-2026-03-30.md \
  --path docs/cloud-readiness-assessment.md \
  --path docs/connection-budget.md \
  --force
```
[CITED: https://github.com/newren/git-filter-repo — `--invert-paths` removes listed paths from all commits]

### Post-rewrite steps
```bash
# filter-repo removes origin as a safety measure — re-add it
git remote add origin https://github.com/geolens-io/geolens.git

# Force push all branches (tags already deleted — fresh start)
git push origin --force --all
```

## Common Pitfalls

### Pitfall 1: filter-repo removes the remote
**What happens:** `git-filter-repo` intentionally removes the `origin` remote to prevent accidental push to the wrong repo.
**How to handle:** Re-add origin after the rewrite. This is expected behavior, not an error.

### Pitfall 2: Tags become orphaned
**What happens:** Tags point to old commit SHAs. `git-filter-repo` rewrites tags automatically, but only annotated tags — lightweight tags on deleted commits may become orphaned.
**How to handle:** All 27 tags will be deleted before the rewrite (user decision: fresh start for public release). No tag preservation needed.

### Pitfall 3: docs/ is in .gitignore but files are tracked
**What happens:** `docs/` is in `.gitignore` but 28 files are tracked (committed before the gitignore rule). The gitignore only prevents NEW files from being staged — already-tracked files remain tracked.
**How to handle:** After filter-repo purges internal docs, the remaining public docs will still be tracked. The `.gitignore` rule for `docs/` should be REMOVED (or narrowed) so that public docs remain tracked going forward. Replace `docs/` gitignore with specific internal paths:
```gitignore
# Internal docs (not for public release)
docs/audits/
docs/GTM/
docs/decisions/
docs/handoff-*.md
docs/ux-plan-*.md
docs/ux-review-*.md
docs/dep-audit-*.md
docs/sec-audit-*.md
docs/api-contract-*.md
docs/cloud-readiness-*.md
docs/connection-budget.md
```

### Pitfall 4: Collaborators with existing clones
**What happens:** Anyone with a clone will have diverged history after force-push.
**How to handle:** All collaborators must `git clone` fresh (or `git fetch --all && git reset --hard origin/main`). Since this is pre-public-release, impact is limited.

### Pitfall 5: Forgetting to back up before rewrite
**How to handle:** Create a backup branch or archive before running filter-repo:
```bash
git clone --mirror /Users/ishiland/Code/geolens /Users/ishiland/Code/geolens-backup
```

### Pitfall 6: GitHub cached data
**What happens:** GitHub may cache old objects. Purged files may remain accessible via SHA for a time.
**How to handle:** After force-push, contact GitHub support to run garbage collection, or delete and recreate the repo. Force-push is sufficient for this release; GitHub GC runs eventually.

## .gitignore Updates Needed

Current `.gitignore` needs these additions:
```gitignore
# AI assistant working directories
.agents/
.codex/
.claude/
```

And this modification — replace the blanket `docs/` ignore with selective ignores for internal-only docs (see Pitfall 3 above).

## Public Doc Audit Results

Scanned `README.md`, `FEATURES.md`, `CHANGELOG.md`, `SECURITY.md` for internal references (`.planning`, `ishiland`, `dev-os`, `handoff`, `TODO.*internal`):
- **No leaks found.** The word "internal" in FEATURES.md refers to the publication lifecycle feature, not internal development artifacts. [VERIFIED: grep scan of all root docs]

### Missing public docs (common for open-source)
| File | Status | Note |
|------|--------|------|
| `CONTRIBUTING.md` | Missing | Standard for open-source — to be created (Task 2) |
| `CODE_OF_CONDUCT.md` | Present on disk | Exists at repo root — verify tracked in git |
| `LICENSE` | Present | Already tracked |
| `SECURITY.md` | Present | Already tracked |
| `README.md` | Present | Should be audited for completeness |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Force-push is sufficient (no need to delete/recreate GitHub repo) | Pitfall 6 | Minor — GitHub GC runs eventually anyway |
| A2 | All 27 tags to be deleted — fresh start for public release | Tags | None — user decision |
| A3 | docs/marketplace-description.md, widget-development.md, llm-*.md are public | Docs to keep | Could expose info not intended for public |

## Open Questions (RESOLVED)

1. **Should the GitHub repo be deleted and recreated?**
   - **RESOLVED:** No. Force-push is sufficient. GitHub GC handles cached objects eventually. No need to delete/recreate.

2. **Are all 27 tags worth preserving?**
   - **RESOLVED:** No. User decided to DELETE ALL TAGS and start fresh. Tags reference internal milestones (v1.0 through v14.0) that are not relevant to the public release.

3. **Should CONTRIBUTING.md and CODE_OF_CONDUCT.md be created?**
   - **RESOLVED:** CONTRIBUTING.md will be created in Task 2. CODE_OF_CONDUCT.md already exists at repo root — just needs to be verified as tracked in git.

## Sources

### Primary (HIGH confidence)
- Codebase audit: git log, git ls-files, .gitignore, directory listings
- git-filter-repo official docs (well-established tool, recommended by Git project itself as replacement for git-filter-branch)

### Secondary (MEDIUM confidence)
- BFG limitations: known from official BFG documentation — cannot filter by directory path

**Research date:** 2026-04-05
**Valid until:** 2026-05-05 (stable domain — git tooling doesn't change fast)
