---
phase: quick-260321-prh
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/quick/260321-prh-evaluate-aws-ami-marketplace-readiness-i/AWS_AMI_MARKETPLACE_READINESS.md
autonomous: true
requirements: [EVAL-01]

must_haves:
  truths:
    - "Report identifies all AWS Marketplace AMI technical requirements and maps current state against them"
    - "Report calls out specific gaps that would cause Marketplace submission rejection"
    - "Report provides actionable suggestions with priority ordering"
  artifacts:
    - path: ".planning/quick/260321-prh-evaluate-aws-ami-marketplace-readiness-i/AWS_AMI_MARKETPLACE_READINESS.md"
      provides: "Complete readiness assessment report"
      min_lines: 100
  key_links: []
---

<objective>
Evaluate the existing GeoLens AWS AMI/Packer infrastructure against AWS Marketplace listing requirements. Produce a comprehensive readiness report identifying gaps, issues, concerns, and suggestions.

Purpose: Determine what work remains before the GeoLens AMI can be submitted to AWS Marketplace.
Output: A detailed readiness assessment document.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md

Key files already analyzed for this assessment:
- packer/aws/geolens-ami.pkr.hcl (AMI build definition)
- packer/common/scripts/*.sh (setup-docker, setup-geolens, harden-ssh, cleanup)
- deploy/cloud-init/01-geolens-init.sh (first-boot initialization)
- deploy/systemd/geolens.service (service management)
- deploy/validate-firstrun.sh (post-boot validation)
- docker-compose.prod.yml (production compose stack)
- packer/common/motd/99-geolens (login banner)
- backend/Dockerfile, frontend/Dockerfile, db/Dockerfile (container images)
- frontend/nginx.conf (reverse proxy config)
- LICENSE (BUSL-1.1)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Produce AWS Marketplace AMI Readiness Assessment</name>
  <files>.planning/quick/260321-prh-evaluate-aws-ami-marketplace-readiness-i/AWS_AMI_MARKETPLACE_READINESS.md</files>
  <action>
Create a comprehensive readiness assessment document evaluating the GeoLens AMI against AWS Marketplace requirements. The report must cover these dimensions:

**1. AWS Marketplace Technical Requirements Checklist**
Evaluate each official requirement and mark pass/fail/partial:
- AMI must be built from a supported base (Ubuntu 24.04 LTS -- currently used, good)
- EBS-backed, HVM virtualization (currently configured, good)
- No encrypted root volume (explicitly set encrypt_boot=false, good)
- SSH host key cleanup (cleanup.sh removes them, good)
- No authorized_keys baked in (cleanup.sh + ssh_clear_authorized_keys, good)
- Password auth disabled (harden-ssh.sh, good)
- PermitRootLogin no (harden-ssh.sh, good)
- IMDSv2 enforced (imds_support v2.0, good)
- No hardcoded credentials (.env generated at first boot via cloud-init, good)
- OS packages up to date (apt upgrade in cleanup.sh, good)

**2. Gaps and Issues (things that WILL block submission)**

A. **Missing EULA / Terms of Use**: AWS Marketplace requires seller-provided EULA or use of Standard Contract for Marketplace (SCMP). The BUSL-1.1 LICENSE file exists but Marketplace needs it configured in the listing, not just on disk. Confirm whether BUSL-1.1 is compatible with Marketplace EULA requirements (it should be -- BSL is used by other Marketplace products like CockroachDB, MariaDB).

B. **No product code integration**: The `product_code` variable exists in the Packer template but defaults to empty string. After initial Marketplace listing, the product code must be baked into the AMI so AWS can meter/validate subscriptions. Currently no runtime validation of product code via AWS Marketplace Metering API.

C. **Missing usage instructions / CloudFormation template**: AWS Marketplace strongly recommends (and for some categories requires) a CloudFormation template or Launch Guide. Currently there is none. This should include: instance type recommendations, security group rules (port 80/443 inbound), IAM role for S3 if using cloud storage.

D. **No HTTPS/TLS out of the box**: The cloud-init script generates HTTP URLs. Marketplace best practices expect HTTPS. At minimum, document that users must set up a load balancer or configure Let's Encrypt. Consider adding Caddy or certbot as an optional first-boot TLS setup.

E. **Version pinning concerns**: `titiler:latest` tag in docker-compose.prod.yml is not reproducible. Marketplace AMIs should have deterministic, version-pinned images for auditability. The GHCR images (geolens-api, geolens-frontend) use `:latest` too.

F. **No Marketplace metering/billing integration**: If selling as a paid AMI (not just BYOL), need to integrate the AWS Marketplace Metering SDK to report usage. If BYOL or free tier, this is not needed.

G. **Architecture**: Only x86_64 (amd64) AMIs. Consider whether arm64 (Graviton) support is needed for Marketplace competitiveness. Not a blocker but worth noting.

**3. Concerns (things that COULD cause issues)**

A. **20GB root volume may be tight**: PostGIS + Docker images + uploaded GIS data all on root. For production use with raster data, users will quickly exhaust 20GB. Suggest either increasing default to 40-50GB or documenting data volume attachment.

B. **Single-region AMI**: Packer builds in us-east-1 only. Marketplace allows multi-region AMI copying. Need `ami_regions` in Packer config to publish to all commercial regions.

C. **Docker image pre-pull may fail**: setup-geolens.sh pulls GHCR images during build but allows failure. If images aren't published, first boot download adds 2-5 min. Marketplace testers may flag slow first-boot times.

D. **No log rotation configured**: Docker container logs and PostgreSQL logs will grow unbounded. Production AMIs should have logrotate or Docker log driver limits.

E. **backup service mounts ./scripts**: The backup service in docker-compose.prod.yml mounts `./scripts:/scripts:ro` which requires the scripts directory to exist at /opt/geolens/scripts. The Packer build copies init-db.sh there, but the backup entrypoint script is not copied. Verify backup-entrypoint.sh is available.

F. **cloud-init-output.log permissions**: The init script restricts it to 600, but between boot start and script execution, it may briefly be world-readable. This is a minor concern since credentials are only in the dedicated log file, not echoed to stdout.

G. **Admin username hardcoded to "admin"**: The cloud-init generates a random password but the username is always "admin". Not a security issue per se, but worth noting.

H. **No swap configured**: For t3.medium (4GB RAM), running PostGIS + 5 Docker containers could OOM under load without swap. Consider adding swap setup to cloud-init.

**4. Suggestions (improvements for a strong listing)**

A. **Add AWS Marketplace Metering API call**: Even for BYOL, calling `RegisterUsage` on boot validates the AMI was launched via Marketplace. This is required for paid listings.

B. **Create a CloudFormation Quick Launch template**: Define VPC, security group (80, 443, 22), EC2 instance, EBS volume, optional S3 bucket, and IAM role. This dramatically improves the buyer experience and is a Marketplace best practice.

C. **Add /opt/geolens/USAGE.md**: A usage guide accessible on the instance (referenced in MOTD) covering: changing admin password, enabling HTTPS, configuring S3 storage, enabling AI features, backup configuration.

D. **Add health check endpoint in MOTD or cloud-init**: After `docker compose up --wait`, run a quick `curl localhost/api/health` to confirm the stack is actually serving. Log the result.

E. **Version the AMI properly**: Wire `app_version` from Packer into the .env or a /opt/geolens/VERSION file so `GET /health` or MOTD can report the installed version.

F. **Pin all Docker image tags**: Replace `:latest` with specific version tags (e.g., `ghcr.io/ishiland/geolens-api:v12.3`, `titiler:0.18.0`). Store version in one place for easy updates.

G. **Add ami_regions to Packer**: Copy the AMI to all commercial AWS regions for broader Marketplace availability.

H. **Security group documentation**: Document minimum required ports (22 for SSH, 80/443 for web) and recommended VPC setup.

I. **Consider CIS benchmark alignment**: While not required, CIS-hardened AMIs get a trust badge on Marketplace. The current SSH hardening is a good start.

**5. What's Already Good**

Highlight these strengths:
- IMDSv2 enforcement (both build-time and AMI)
- Credential generation at first boot (not baked in)
- File permission hardening (.env 600, credential log 600)
- SSH hardening (no password auth, no root login, host key cleanup)
- machine-id truncation for unique instance identity
- cloud-init clean for proper re-initialization
- Comprehensive first-boot validation script
- systemd service for auto-restart on reboot
- Guard clause preventing .env overwrite on re-runs

Format the report with clear sections, tables where appropriate, and a priority-ordered action items summary at the top.
  </action>
  <verify>
    <automated>test -f .planning/quick/260321-prh-evaluate-aws-ami-marketplace-readiness-i/AWS_AMI_MARKETPLACE_READINESS.md && wc -l .planning/quick/260321-prh-evaluate-aws-ami-marketplace-readiness-i/AWS_AMI_MARKETPLACE_READINESS.md | awk '{if ($1 >= 100) print "PASS"; else print "FAIL: only " $1 " lines"}'</automated>
  </verify>
  <done>Comprehensive readiness report exists with: technical requirements checklist, blocking gaps, concerns, suggestions, and priority-ordered action items</done>
</task>

</tasks>

<verification>
- Report covers all 5 dimensions (requirements checklist, gaps, concerns, suggestions, strengths)
- Each gap/concern references specific files in the codebase
- Action items are priority-ordered
- Report is actionable (a developer could work through items sequentially)
</verification>

<success_criteria>
- AWS_AMI_MARKETPLACE_READINESS.md exists with 100+ lines
- Report identifies at least 5 blocking gaps and 5 concerns
- Report includes a priority-ordered action items summary
- All findings reference specific files/configurations in the codebase
</success_criteria>

<output>
After completion, create `.planning/quick/260321-prh-evaluate-aws-ami-marketplace-readiness-i/260321-prh-SUMMARY.md`
</output>
