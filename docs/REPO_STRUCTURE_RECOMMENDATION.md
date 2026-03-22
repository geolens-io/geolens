# Repository Structure Recommendation

**Date:** 2026-03-22
**Status:** Active
**Scope:** helm/, packer/, deploy/ -- evaluate separation to standalone repos under geolens-io GitHub org

## Executive Summary

Keep all directories in the monorepo. The project is a single product maintained by a single developer with ~200 phases shipped. Packer templates reference 13+ files across the repo via relative paths, making extraction costly. Helm is self-contained but has no external consumers. The operational overhead of multi-repo coordination (cross-repo PRs, version sync, duplicate CI) outweighs any organizational benefit at this scale. Add CI validation jobs instead.

## Directory Inventory

| Directory | Files | Purpose | CI Integration |
|-----------|-------|---------|----------------|
| `helm/geolens/` | 20 | Kubernetes deployment chart (Chart.yaml, values.yaml, 16 templates) | None |
| `packer/aws/` | 1 HCL + refs common/ | AWS AMI build for Marketplace | None |
| `packer/do/` | 1 HCL + 2 scripts + refs common/ | DigitalOcean Droplet image build | None |
| `packer/common/` | 4 scripts + 1 motd | Shared provisioning logic for all packer builds | None |
| `deploy/` | 5 | Runtime deployment artifacts (systemd, nginx, cloud-init, CloudFormation, validation) | None |
| `scripts/` | 16 | DB init, backup, seeding, performance testing | None (consumed by packer at build time) |
| `docs/` | 20+ | User-facing documentation | None (gitignored from npm) |

Every infrastructure directory has zero CI integration today.

## CI/CD Coupling Analysis

The two GitHub Actions workflows have no references to helm, packer, or deploy:

- **ci.yml** runs on push/PR to main. Jobs: backend-lint, backend-test, frontend-lint, frontend-test, security-scan, e2e-test. Scope: `backend/` and `frontend/` only.
- **publish.yml** runs on version tags (`v*.*.*`). Builds and pushes `geolens-api` and `geolens-frontend` Docker images to GHCR. Scope: Docker images only.

There is no `packer validate` job, no `helm lint` job, and no infrastructure validation in CI at all. These artifacts are currently unvalidated on push.

## Per-Directory Evaluation

### helm/

**Current state:** 20-file Kubernetes chart. Self-contained -- references only published GHCR image tags (`ghcr.io/geolens-io/geolens-api`, `ghcr.io/geolens-io/geolens-frontend`). No local file dependencies.

**Pros of separation:**
- Technically clean -- no relative path dependencies to break
- Independent versioning (chart 0.1.0 vs app v12.3)
- Standard pattern for chart distribution (`geolens-io/helm-charts` + chart-releaser Action)
- Enables `helm repo add` install workflow for external users

**Cons of separation:**
- 20 files -- separate repo overhead is disproportionate to content
- Chart changes often track app changes (new env vars, new services, new containers)
- No current consumers pulling from a Helm registry -- chart is used by copying
- Single developer -- context switching between repos adds friction with no team benefit

**Verdict:** Separation is technically clean but operationally premature.

### packer/

**Current state:** Two platform-specific templates (AWS, DigitalOcean) plus shared provisioning scripts in `common/`. Templates reference 13+ files across the repo via `../../` relative paths.

**Cross-reference list (AWS AMI):**
- `../../docker-compose.prod.yml`
- `../../scripts/init-db.sh`
- `../../scripts/backup-entrypoint.sh`
- `../../scripts/backup.sh`
- `../../scripts/backup-s3-upload.py`
- `../../scripts/backup-s3-retention.py`
- `../../deploy/cloud-init/01-geolens-init.sh`
- `../../deploy/systemd/geolens.service`
- `../../deploy/validate-firstrun.sh`
- `../../deploy/nginx/tls.conf.template`
- `../../docs/AWS_AMI_USAGE.md`
- `../common/scripts/*` (4 scripts)
- `../common/motd/99-geolens`

**Pros of separation:**
- Independent build cadence (AMIs built per-release, not per-commit)
- Could have its own CI for `packer validate`

**Cons of separation:**
- 13+ cross-references into docker-compose, scripts/, deploy/, docs/
- Extraction requires either: (a) duplicating files, (b) git submodules, or (c) a build step that fetches from the main repo -- all add complexity
- Packer and deploy/ are tightly coupled -- separating one without the other breaks paths
- Single developer means the coordination cost hits one person repeatedly

**Verdict:** Too coupled to main repo files. Separation cost exceeds benefit.

### deploy/

**Current state:** 5 files -- systemd unit, cloud-init script, nginx TLS template, CloudFormation template, first-run validation script. Consumed exclusively by packer templates.

**Pros of separation:** Would co-locate with packer if both were extracted.

**Cons of separation:** Not independently deployable. Separating deploy/ without packer/ makes no sense. Separating both inherits all of packer's coupling problems.

**Verdict:** Keep with packer. No independent separation case.

## Other Directories

| Directory | Separate Repo? | Reasoning |
|-----------|---------------|-----------|
| `docs/` | No | Docs-as-code alongside source is standard practice. Already gitignored from npm build. |
| `plans/` | No | 3 internal planning/handoff files. Not worth a repo. |
| `scripts/` | No | Mixed dev tooling and production scripts. Consumed by packer via relative paths. |
| `e2e/` | No | Tests the application -- must live with app code. |
| `.planning/` | No | Development workflow artifacts. No external relevance. |

## Monorepo vs Polyrepo at This Scale

**Project characteristics:**
- Single product (GeoLens), single developer
- ~200 phases shipped, mature codebase
- 2 publishable Docker images, 1 Helm chart, 2 Packer templates
- No separate release cadence for infrastructure artifacts today
- GitHub org (`geolens-io`) exists but contains only the main repo

**When monorepo is appropriate:**
- Single product with unified release cycle
- Small team where cross-repo coordination adds friction, not clarity
- Infrastructure artifacts tightly coupled to application code
- No external consumers of individual components

All four conditions apply to GeoLens today.

**When polyrepo benefits emerge:**
- Separate teams need isolated access control or CI pipelines
- Components have genuinely independent release cadences
- External users consume components via package registries (Helm, Terraform, npm)
- Infrastructure state management (Terraform) introduces blast-radius concerns

None of these conditions apply today.

## Recommendation

**Keep everything in the monorepo.**

Instead of repository separation, take these incremental actions:

1. **Add CI validation jobs** -- `packer validate` and `helm lint` in ci.yml with path-based triggers (`paths: ['helm/**']`, `paths: ['packer/**']`). This gets validation without repo overhead.

2. **Create `geolens-io/helm-charts` when chart distribution is needed** -- when external users need `helm repo add geolens`, publish the chart to an OCI registry from a dedicated chart repo using chart-releaser GitHub Action. Until then, the chart lives here.

3. **Terraform is the strongest future separation candidate** -- if Terraform modules are added, they benefit most from a separate repo due to state management isolation, provider versioning, and plan/apply CI workflows. Evaluate separation at that point.

4. **Revisit this decision if any trigger is met:**
   - External users consume the Helm chart from a registry
   - Packer builds get their own CI pipeline and independent release tags
   - A second contributor or team needs to modify infrastructure without app code access
   - Terraform state management is introduced

## Decision Date

**2026-03-22.** Revisit if any of the four triggers above are met.
