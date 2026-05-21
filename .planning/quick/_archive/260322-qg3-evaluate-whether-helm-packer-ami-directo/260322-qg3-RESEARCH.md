# Quick Task 260322-qg3: Evaluate helm/packer/deploy Repo Separation - Research

**Researched:** 2026-03-22
**Domain:** Repository structure, infrastructure-as-code packaging
**Confidence:** HIGH

## Summary

The helm/, packer/, and deploy/ directories are **infrastructure packaging artifacts** that reference the main app's published Docker images (ghcr.io/geolens-io/*) and several repo-root files. They have **zero coupling to application CI** -- the CI pipeline (ci.yml) tests only backend/ and frontend/ code. The publish pipeline (publish.yml) builds only Docker images. Neither pipeline touches helm, packer, or deploy.

However, packer templates have **heavy cross-references** into the main repo: they copy docker-compose.prod.yml, scripts/*, deploy/*, and docs/ files into images using relative paths (`../../`). Extracting packer without also extracting deploy/ and scripts/ would require significant refactoring or git submodule wiring.

**Primary recommendation:** Keep helm/ and packer/ in the main repo for now. The coupling cost of separation outweighs the organizational benefit at this project's scale.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Recommendation document only -- no repo changes or implementation
- Written analysis with pros/cons and clear recommendation

### Claude's Discretion
- CI/CD coupling -- investigate current CI state from repo to determine coupling level

### Specific Ideas
- Consider other items beyond helm/packer that may warrant separate repos
- Evaluate GitHub organization structure best practices
- Consider monorepo vs polyrepo trade-offs specific to this project's scale
</user_constraints>

## Current State Analysis

### Directory Inventory

| Directory | Files | Purpose | CI Integration |
|-----------|-------|---------|----------------|
| `helm/geolens/` | 20 files (Chart.yaml, values.yaml, 16 templates) | Kubernetes deployment chart | None |
| `packer/aws/` | 1 HCL + references common/ | AWS AMI for Marketplace | None |
| `packer/do/` | 1 HCL + 2 scripts + references common/ | DigitalOcean Droplet image | None |
| `packer/common/` | 4 scripts + 1 motd | Shared provisioning logic | None |
| `deploy/` | 5 files (systemd, nginx, cloud-init, CloudFormation, validation) | Runtime deployment artifacts | None |
| `scripts/` | 16 files | DB init, backup, seeding, perf testing | None (used by packer at build time) |
| `docs/` | 20+ files | User-facing documentation | None (gitignored from npm) |
| `plans/` | 3 files | Future roadmap/handoff docs | None |

### CI/CD Pipeline Analysis

**ci.yml** -- Runs on push/PR to main. Jobs: backend-lint, backend-test, frontend-lint, frontend-test, security-scan, e2e-test. Zero references to helm/, packer/, or deploy/.

**publish.yml** -- Runs on version tags (v*.*.*). Builds and pushes geolens-api and geolens-frontend Docker images to GHCR. Zero references to helm/, packer/, or deploy/.

**Key finding:** There is no helm lint/test job, no packer validate job, and no infrastructure CI at all. These artifacts are currently unvalidated in CI.

### Cross-Reference Map

**Packer AWS AMI references these repo files:**
- `../../docker-compose.prod.yml` -- app composition
- `../../scripts/init-db.sh` -- database initialization
- `../../scripts/backup-entrypoint.sh` -- backup service
- `../../scripts/backup.sh` -- backup logic
- `../../scripts/backup-s3-upload.py` -- S3 backup upload
- `../../scripts/backup-s3-retention.py` -- S3 retention policy
- `../../deploy/cloud-init/01-geolens-init.sh` -- first-run setup
- `../../deploy/systemd/geolens.service` -- systemd unit
- `../../deploy/validate-firstrun.sh` -- validation
- `../../deploy/nginx/tls.conf.template` -- TLS config
- `../../docs/AWS_AMI_USAGE.md` -- embedded usage doc
- `../common/scripts/*` -- shared provisioning (4 scripts)
- `../common/motd/99-geolens` -- login banner

**Packer DO Droplet references (subset):**
- `../../docker-compose.prod.yml`
- `../../scripts/init-db.sh`
- `../../deploy/cloud-init/01-geolens-init.sh`
- `../../deploy/systemd/geolens.service`
- `../../deploy/validate-firstrun.sh`
- `../common/scripts/*`, `../common/motd/99-geolens`

**Helm chart references:** Self-contained. Uses only published GHCR image tags (`ghcr.io/geolens-io/geolens-api`, `ghcr.io/geolens-io/geolens-frontend`). No local file dependencies.

## Separation Analysis

### Helm Chart -- COULD Separate

**Pros:**
- Fully self-contained -- no local file dependencies
- Independent versioning (currently 0.1.0, app is v12.3)
- Could publish to a Helm repository (OCI or ChartMuseum) for `helm install` workflows
- Standard pattern: many projects host charts in separate repos (e.g., `geolens-io/helm-charts`)

**Cons:**
- Small chart (20 files) -- overhead of separate repo, separate issues, separate PRs
- Chart changes often track app changes (new env vars, new services)
- No current consumers pulling the chart from a registry -- it is used by copying
- Team of one -- context switching between repos adds friction

**Verdict:** Separation is technically clean but operationally premature. Revisit when: (a) the chart is published to a Helm registry, or (b) external users install via `helm repo add`.

### Packer Templates -- SHOULD NOT Separate (Now)

**Pros:**
- Independent build cadence (AMIs built per-release, not per-commit)
- Could have its own CI for `packer validate`

**Cons:**
- References 13+ files across docker-compose.prod.yml, scripts/, deploy/, docs/
- Separation requires either: (a) duplicating those files, (b) git submodules, or (c) a build step that fetches them from the main repo
- All three options add complexity that is not justified by current scale
- Packer and deploy/ are tightly coupled -- separating one without the other breaks the reference paths

**Verdict:** Too coupled to main repo files. Separation cost exceeds benefit.

### Deploy Directory -- SHOULD NOT Separate

Deploy/ files (systemd, cloud-init, nginx, CloudFormation) are consumed exclusively by packer templates. They are not independently deployable. Separating deploy/ without packer/ makes no sense, and separating both has the coupling problems described above.

### Other Directories

| Directory | Separate Repo? | Reasoning |
|-----------|---------------|-----------|
| `docs/` | No | Already gitignored from build. Small. Docs-as-code alongside source is standard. |
| `plans/` | No | Internal planning artifacts, 3 files. Not worth a repo. |
| `scripts/` | No | Mixed concerns (dev tooling + production scripts). Consumed by packer via relative paths. |
| `e2e/` | No | Tests the app -- must live with app code. |
| `.planning/` | No | Development workflow artifacts. |

## Monorepo vs Polyrepo at This Scale

**Project characteristics:**
- Single product (GeoLens), single team/developer
- ~200 phases shipped, mature codebase
- 2 publishable Docker images, 1 Helm chart, 2 Packer templates
- No separate release cadence for infra artifacts today

**Industry guidance for this profile:**
- Monorepo is standard for single-product, small-team projects
- Polyrepo benefits emerge with: separate teams, separate release cadences, separate access control needs, or package registry publishing
- GitHub org (`geolens-io`) is appropriate for: the main app repo, any future standalone tools/SDKs, and eventually a helm-charts repo if chart distribution is needed

**When to reconsider:**
1. Helm chart is published to OCI/Helm registry and external users consume it
2. Packer builds get their own CI pipeline and release tags
3. A second contributor/team needs to modify infra without app code access
4. Terraform state management is added (Terraform repos benefit strongly from separation)

## Recommendation

**Keep everything in the main repo.** The project is a single product with a single developer. The operational overhead of multiple repos (cross-repo PRs, version synchronization, duplicate CI config) outweighs the organizational tidiness.

**Specific actions to consider instead:**
1. Add `packer validate` and `helm lint` jobs to ci.yml -- validates infra artifacts without repo separation
2. Use path-based CI triggers (`paths: ['helm/**']`) to run helm jobs only when chart changes
3. When ready to distribute the Helm chart publicly, create `geolens-io/helm-charts` as a chart-only repo with chart-releaser GitHub Action
4. If Terraform is added in the future, that is the strongest candidate for a separate repo due to state management concerns

## Sources

### Primary (HIGH confidence)
- Direct inspection of repo files: `.github/workflows/ci.yml`, `.github/workflows/publish.yml`
- Direct inspection of `packer/aws/geolens-ami.pkr.hcl` cross-references (13 `../../` paths)
- Direct inspection of `helm/geolens/values.yaml` (self-contained, GHCR references only)

## Metadata

**Confidence:** HIGH -- all findings based on direct repo inspection, no external sources needed
**Research date:** 2026-03-22
**Valid until:** Indefinite (structural analysis, not version-dependent)
