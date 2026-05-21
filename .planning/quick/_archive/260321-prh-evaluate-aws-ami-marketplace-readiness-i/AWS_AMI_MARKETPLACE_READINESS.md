# AWS Marketplace AMI Readiness Assessment

**Date:** 2026-03-21
**Assessed Version:** v12.3
**AMI Base:** Ubuntu 24.04 LTS (Noble), HVM, EBS-backed, x86_64
**License:** Business Source License 1.1 (BUSL-1.1)

---

## Priority-Ordered Action Items

| # | Priority | Item | Category | Effort |
|---|----------|------|----------|--------|
| 1 | **P0 - Blocker** | Pin all Docker image tags (`:latest` not allowed) | Version Pinning | Low |
| 2 | **P0 - Blocker** | Remove `user: "0:0"` from api/worker (root containers flagged by Marketplace security scan) | Security | Low |
| 3 | **P0 - Blocker** | Integrate AWS Marketplace Metering API (`RegisterUsage`) | Billing | Medium |
| 4 | **P0 - Blocker** | Create product usage instructions (required for listing) | Documentation | Medium |
| 5 | **P0 - Blocker** | Wire product code validation into AMI runtime | Licensing | Low |
| 6 | **P0 - Blocker** | Configure EULA in Marketplace Management Portal | Licensing | Low |
| 7 | **P1 - Required** | Fix `app_version` default (was 9.0.0, should match release) | Versioning | Low |
| 8 | **P1 - Required** | Create CloudFormation Quick Launch template | Buyer UX | Medium |
| 9 | **P1 - Required** | Add `ami_regions` for multi-region distribution | Distribution | Low |
| 10 | **P1 - Required** | Document or automate HTTPS/TLS setup | Security | Medium |
| 11 | **P1 - Required** | Increase default root volume to 40GB | Storage | Low |
| 12 | **P1 - Required** | Enable unattended-upgrades for automatic security updates | Security | Low |
| 13 | **P2 - Recommended** | Configure Docker log rotation | Operations | Low |
| 14 | **P2 - Recommended** | Add swap configuration to cloud-init | Reliability | Low |
| 15 | **P2 - Recommended** | Add health check to first-boot sequence | Reliability | Low |
| 16 | **P2 - Recommended** | Create `/opt/geolens/USAGE.md` on-instance guide | Buyer UX | Low |
| 17 | **P2 - Recommended** | Wire `app_version` into runtime VERSION file | Versioning | Low |
| 18 | **P3 - Nice to have** | ARM64 (Graviton) AMI support | Performance | High |
| 19 | **P3 - Nice to have** | CIS benchmark alignment for trust badge | Security | High |

---

## 1. AWS Marketplace Technical Requirements Checklist

| # | Requirement | Status | Evidence |
|---|-------------|--------|----------|
| 1 | EBS-backed, HVM virtualization | PASS | `geolens-ami.pkr.hcl`: source filter `root-device-type = "ebs"`, `virtualization-type = "hvm"` |
| 2 | Supported base OS | PASS | Ubuntu 24.04 LTS (Noble) from Canonical (owner `099720109477`) |
| 3 | Unencrypted root volume | PASS | `encrypt_boot = false` explicitly set |
| 4 | SSH host keys removed | PASS | `cleanup.sh` line 5: `rm -f /etc/ssh/ssh_host_*` |
| 5 | No baked-in authorized_keys | PASS | `cleanup.sh` lines 8-9 removes all; Packer `ssh_clear_authorized_keys = true` |
| 6 | Password authentication disabled | PASS | `harden-ssh.sh`: sets `PasswordAuthentication no` in both main config and `/etc/ssh/sshd_config.d/99-marketplace.conf` drop-in |
| 7 | Root login disabled | PASS | `harden-ssh.sh` line 7: `PermitRootLogin no` |
| 8 | IMDSv2 enforced | PASS | `imds_support = "v2.0"` on AMI; `metadata_options.http_tokens = "required"` on build instance |
| 9 | No hardcoded credentials | PASS | `.env` generated at first boot by cloud-init; passwords from `openssl rand` |
| 10 | OS packages up to date | PASS | `cleanup.sh` runs `apt-get update && apt-get upgrade -y` |
| 11 | Machine-ID cleaned | PASS | `cleanup.sh` line 31: `truncate -s 0 /etc/machine-id` |
| 12 | Cloud-init state cleaned | PASS | `cleanup.sh` line 28: `cloud-init clean --logs` |
| 13 | Bash history cleared | PASS | `cleanup.sh` lines 12-14 |
| 14 | Temp files removed | PASS | `cleanup.sh` line 25: `rm -rf /tmp/* /var/tmp/*` |
| 15 | Deterministic image tags | **FAIL** | `:latest` used for `geolens-api`, `geolens-frontend`, `titiler` (see Gap E) |
| 16 | Product code integration | **FAIL** | `product_code` variable exists but defaults to `""` with no runtime validation |
| 17 | Usage instructions provided | **FAIL** | No on-instance usage guide or Marketplace listing documentation |
| 18 | Containers run as non-root | **FAIL** | `api` and `worker` set `user: "0:0"` -- Marketplace security scan rejection trigger |

**Score: 14/18 pass (78%) -- 4 blocking failures must be resolved before submission**

---

## 2. Blocking Gaps (Will Cause Submission Rejection)

### Gap A: Missing EULA / Terms of Use Configuration

**Files:** `LICENSE`

The `BUSL-1.1` license file exists on disk, which is compatible with AWS Marketplace (used by CockroachDB, MariaDB, HashiCorp products). However, AWS Marketplace requires the EULA to be configured through the Marketplace Management Portal, not just present on the AMI filesystem.

**Required actions:**
1. During Marketplace listing creation, configure BUSL-1.1 as the custom EULA (or use AWS Standard Contract for Marketplace if applicable)
2. Ensure the `Additional Use Grant` clause in the LICENSE is reviewed by legal for Marketplace distribution compatibility
3. The "no hosted/managed service" restriction in the Additional Use Grant is standard for BSL products on Marketplace

**Risk:** Low -- administrative step, not a technical change.

---

### Gap B: No Product Code Integration

**Files:** `packer/aws/geolens-ami.pkr.hcl` (line 38-42), `deploy/cloud-init/01-geolens-init.sh`

The `product_code` variable exists in the Packer template but defaults to empty string. After AWS assigns a product code during listing, this must be:

1. **Baked into the AMI** via Packer variable at build time
2. **Validated at runtime** -- the AMI should call the AWS Marketplace Metering API on boot to confirm it was launched through a valid Marketplace subscription

Currently there is no runtime validation. A user could copy the AMI to another account and bypass Marketplace billing.

**Required actions:**
1. After receiving the product code from AWS, pass it as `-var 'product_code=XXXXX'` during `packer build`
2. Add a `RegisterUsage` API call to the cloud-init first-boot script (see Suggestion A)
3. For BYOL listings, `RegisterUsage` is still recommended to track deployments

---

### Gap C: Missing Usage Instructions / Launch Documentation

**Files:** None (missing)

AWS Marketplace requires seller-provided usage instructions. These appear on the listing page and help buyers understand:
- How to access the application after launch
- Minimum instance type requirements
- Required security group rules
- How to find credentials

**Required actions:**
1. Create a structured usage guide for the Marketplace listing
2. Consider also placing a USAGE.md at `/opt/geolens/USAGE.md` on the instance itself
3. Document minimum: instance type (t3.medium), ports (80, 443, 22), first-login workflow

---

### Gap D: No HTTPS/TLS Out of the Box

**Files:** `deploy/cloud-init/01-geolens-init.sh` (lines 66-67)

The cloud-init script generates `http://` URLs for `PUBLIC_APP_URL` and `PUBLIC_API_URL`. AWS Marketplace security best practices expect HTTPS for web applications. The Marketplace security review may flag this.

**Required actions (choose one):**
1. **Minimum:** Document in usage instructions that users should put an ALB or CloudFront distribution in front, or configure Let's Encrypt
2. **Better:** Add optional Caddy or certbot integration to cloud-init (e.g., if a `DOMAIN` env var is set, auto-provision TLS via Let's Encrypt)
3. **Best:** Provide a CloudFormation template that includes an ALB with ACM certificate

---

### Gap E: Unpinned Docker Image Tags

**Files:** `docker-compose.prod.yml` (lines 20, 37, 95, 140, 169)

All five service images use unpinned tags:

| Service | Image | Tag |
|---------|-------|-----|
| db | `postgis/postgis` | `17-3.5` (acceptable -- major.minor pinned) |
| migrate | `ghcr.io/ishiland/geolens-api` | `:latest` |
| api | `ghcr.io/ishiland/geolens-api` | `:latest` |
| worker | `ghcr.io/ishiland/geolens-api` | `:latest` |
| titiler | `ghcr.io/developmentseed/titiler` | `:latest` |
| frontend | `ghcr.io/ishiland/geolens-frontend` | `:latest` |

AWS Marketplace AMIs must be reproducible and auditable. Using `:latest` means the AMI's behavior can change without a new build, which violates Marketplace requirements for version-controlled software.

**Required actions:**
1. Pin all images to specific version tags (e.g., `ghcr.io/ishiland/geolens-api:v12.3`)
2. Pin titiler to a specific release (e.g., `ghcr.io/developmentseed/titiler:2.0.0`)
3. Store the version in a single place (Packer `app_version` variable) and template it into `docker-compose.prod.yml` or a `.env` override

---

### Gap F: No Marketplace Metering/Billing Integration

**Files:** None (missing)

If selling as a paid AMI (hourly or annual), AWS requires integration with the Marketplace Metering API (`aws-marketplace-metering`). Even for BYOL listings, calling `RegisterUsage` is strongly recommended.

**Required actions:**
1. Install `aws-sdk` or use `awscli` to call `RegisterUsage` on first boot
2. Add the call to `01-geolens-init.sh` after successful stack startup
3. Ensure the EC2 instance has an IAM role with `aws-marketplace:RegisterUsage` permission (document in CloudFormation template)

**If BYOL-only:** This is technically optional but AWS may reject listings without it.

---

### Gap G: Docker Containers Running as Root

**Files:** `docker-compose.prod.yml` (lines 39, 97)

The `api` and `worker` services set `user: "0:0"`, running containers as root. AWS Marketplace security scanning specifically flags containers running as root and this is a known rejection trigger.

**Required actions:**
1. Remove the `user: "0:0"` directive from both services
2. Verify that the container images' default user (non-root) has appropriate permissions for volume mounts

---

## 3. Concerns (Could Cause Issues or Slow Approval)

### Concern A: Root Volume Size

**Files:** `packer/aws/geolens-ami.pkr.hcl` (line 79: `volume_size = 20`)

The 20GB root volume holds: Ubuntu OS (~3GB), Docker Engine (~1GB), Docker images (~4-6GB), PostGIS data (variable), uploaded GIS files (variable). With raster data support (v10.0+), users could exhaust this within hours of first use.

**Recommendation:** Increase to 40-50GB. Alternatively, document that users should attach a separate EBS data volume and configure Docker/PostGIS to use it.

---

### Concern B: Single-Region AMI Build

**Files:** `packer/aws/geolens-ami.pkr.hcl` (line 20: `default = "us-east-1"`)

The AMI is only built in `us-east-1`. AWS Marketplace supports multi-region distribution. Buyers in `eu-west-1` or `ap-southeast-1` would face cross-region AMI copy delays.

**Recommendation:** Add `ami_regions` to the Packer config:
```hcl
ami_regions = ["us-east-1", "us-west-2", "eu-west-1", "eu-central-1", "ap-southeast-1"]
```

---

### Concern C: Docker Image Pre-Pull Failure Tolerance

**Files:** `packer/common/scripts/setup-geolens.sh` (line 30)

The pre-pull step uses `|| echo "WARN: ..."` to allow failure. If GHCR images are not published when the AMI is built, all 5 images (~2-4GB total) download on first boot, adding 2-5 minutes of startup time.

Marketplace testers launch the AMI and expect the application to be ready within a reasonable time. A 5+ minute first-boot delay could trigger a review flag.

**Recommendation:** Ensure GHCR images are published before building Marketplace AMIs. Consider failing the Packer build if pre-pull fails (remove the `|| echo` fallback for Marketplace builds).

---

### Concern D: No Log Rotation Configured

**Files:** `docker-compose.prod.yml` (no `logging:` sections)

Docker container logs grow unbounded. PostGIS WAL and logs also have no rotation policy. On a 20GB volume, logs could fill the disk within days under moderate usage.

**Recommendation:** Add Docker logging driver config:
```yaml
logging:
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"
```

---

### Concern E: Backup Service Script Mount

**Files:** `docker-compose.prod.yml` (line 178: `./scripts:/scripts:ro`), `scripts/backup-entrypoint.sh`, `scripts/backup.sh`

The backup service mounts `./scripts:/scripts:ro` and runs `/scripts/backup-entrypoint.sh` as its entrypoint. The Packer build copies `init-db.sh` to `/opt/geolens/scripts/` but does NOT copy `backup-entrypoint.sh` or `backup.sh`.

**Verification:** `setup-geolens.sh` only copies `init-db.sh` (line 9). The backup container will fail to start because both `backup-entrypoint.sh` and `backup.sh` are not present at `/opt/geolens/scripts/`.

**Recommendation:** Add `backup-entrypoint.sh`, `backup.sh`, and the S3 upload/retention scripts to the Packer file provisioners and `setup-geolens.sh` copy steps.

---

### Concern F: Cloud-Init Output Log Permission Race

**Files:** `deploy/cloud-init/01-geolens-init.sh` (line 95)

The init script restricts `/var/log/cloud-init-output.log` to chmod 600, but between boot start and script execution completion, the log may be briefly world-readable. The script correctly avoids echoing the password to stdout (line 98-99), so actual credential exposure risk is minimal.

**Recommendation:** No action needed -- defense-in-depth is already applied. The dedicated credential log (`/var/log/geolens-init.log`) is the authoritative credential store.

---

### Concern G: Hardcoded Admin Username

**Files:** `deploy/cloud-init/01-geolens-init.sh` (line 65: `GEOLENS_ADMIN_USERNAME=admin`)

The admin username is always `admin`. While the password is randomly generated, a fixed username reduces the attack surface only marginally. Marketplace security reviewers may note this.

**Recommendation:** Low priority. Document that users should create a new admin account and disable the default one.

---

### Concern H: No Swap Configured

**Files:** `deploy/cloud-init/01-geolens-init.sh` (no swap setup)

The recommended instance type is `t3.medium` (4GB RAM). Running PostGIS + 6 Docker containers (db, migrate, api, worker, titiler, frontend, backup) could approach memory limits under load. Without swap, the OOM killer may terminate services.

**Recommendation:** Add swap setup to cloud-init:
```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

---

### Concern I: x86_64 Only Architecture

**Files:** `packer/aws/geolens-ami.pkr.hcl` (line 54: `architecture = "x86_64"`)

Only x86_64 (amd64) AMIs are built. AWS Graviton (arm64) instances offer 20-40% better price-performance and are increasingly expected in Marketplace listings.

**Not a blocker for initial submission** but worth noting for competitiveness. All Docker images (`postgis`, `titiler`, `geolens-api`, `geolens-frontend`) would need multi-arch builds.

---

## 4. Suggestions (Improvements for a Strong Listing)

### Suggestion A: AWS Marketplace Metering API Integration

Add a `RegisterUsage` call after successful stack startup in `01-geolens-init.sh`:

```bash
# Register with AWS Marketplace (requires IAM role with aws-marketplace:RegisterUsage)
if [ -n "${AWS_MARKETPLACE_PRODUCT_CODE:-}" ]; then
    aws marketplace-metering register-usage \
        --product-code "${AWS_MARKETPLACE_PRODUCT_CODE}" \
        --public-key-version 1 \
        --region "$(curl -sf -H "X-aws-ec2-metadata-token: ${TOKEN}" \
            http://169.254.169.254/latest/meta-data/placement/region)" \
        || echo "WARN: Marketplace registration failed (non-fatal)"
fi
```

Install `awscli` during the Docker setup phase or use a lightweight Python call.

---

### Suggestion B: CloudFormation Quick Launch Template

Create a `deploy/cloudformation/geolens-ami.cfn.yaml` that provisions:
- VPC with public subnet (or option to use existing VPC)
- Security group: ingress 22 (SSH), 80 (HTTP), 443 (HTTPS)
- EC2 instance with the GeoLens AMI
- IAM instance profile with `aws-marketplace:RegisterUsage` and optional S3 access
- Outputs: instance public IP, application URL, SSH command

This dramatically improves the buyer experience and is the primary differentiator between "good" and "great" Marketplace listings.

---

### Suggestion C: On-Instance Usage Guide

Create `/opt/geolens/USAGE.md` accessible on the instance, referenced in the MOTD banner:

```
View usage guide:  cat /opt/geolens/USAGE.md
```

Contents: changing admin password, enabling HTTPS, configuring S3 storage, enabling AI features (API keys), backup configuration, recommended instance types for different workloads.

---

### Suggestion D: Health Check in First-Boot Sequence

After `docker compose up --wait`, add a health verification:

```bash
# Verify stack is serving
if curl -sf http://localhost/api/health > /dev/null 2>&1; then
    echo "GeoLens health check: PASS"
else
    echo "WARNING: GeoLens health check failed -- stack may still be starting"
fi
```

This catches silent startup failures before the user sees the MOTD.

---

### Suggestion E: Version File on Instance

Wire `app_version` from Packer into a version file:

In `setup-geolens.sh`:
```bash
echo "${APP_VERSION}" | sudo tee /opt/geolens/VERSION
```

Pass it from Packer as an environment variable. This enables the MOTD and `/health` endpoint to report the installed version, which is important for Marketplace version tracking.

---

### Suggestion F: Pin All Docker Image Tags

Replace `:latest` with specific version tags. Manage versions in one place:

```hcl
# In geolens-ami.pkr.hcl
variable "geolens_version" {
  type    = string
  default = "v12.3"
}

variable "titiler_version" {
  type    = string
  default = "2.0.0"
}
```

Generate a `.env.versions` file during build that overrides image tags in docker-compose.

---

### Suggestion G: Multi-Region AMI Distribution

Add to `geolens-ami.pkr.hcl`:

```hcl
ami_regions = [
  "us-east-1", "us-east-2", "us-west-1", "us-west-2",
  "eu-west-1", "eu-west-2", "eu-central-1",
  "ap-southeast-1", "ap-southeast-2", "ap-northeast-1"
]
```

This copies the AMI to all major commercial regions automatically after build.

---

### Suggestion H: Security Group Documentation

Document minimum required ports for the Marketplace listing:

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 22 | TCP | Your IP | SSH administration |
| 80 | TCP | 0.0.0.0/0 | HTTP (application) |
| 443 | TCP | 0.0.0.0/0 | HTTPS (if TLS configured) |

No other inbound ports are required. All inter-service communication is Docker-internal.

---

### Suggestion I: CIS Benchmark Alignment

The current SSH hardening is a good foundation. For a CIS-hardened trust badge on Marketplace:
- Disable unused filesystems (`cramfs`, `freevxfs`, etc.)
- Configure `auditd` for file integrity monitoring
- Set `UMASK` to 027
- Configure `fail2ban` for SSH brute-force protection
- Enable automatic security updates (`unattended-upgrades`)

This is a significant effort but provides a competitive advantage and buyer trust signal.

---

## 5. What's Already Good

The current AMI infrastructure demonstrates strong security awareness and operational maturity:

| Strength | Implementation | File |
|----------|----------------|------|
| IMDSv2 enforcement | Both build-time (`metadata_options`) and AMI-level (`imds_support = "v2.0"`) | `geolens-ami.pkr.hcl` |
| Credential generation at boot | `openssl rand` for all secrets; never baked into AMI | `01-geolens-init.sh` |
| File permission hardening | `.env` chmod 600, credential log chmod 600 | `01-geolens-init.sh` |
| SSH hardening | No password auth, no root login, drop-in config survives cloud-init overrides | `harden-ssh.sh` |
| Host key cleanup | Removed during build, regenerated by cloud-init on first boot | `cleanup.sh` |
| Machine-ID reset | Truncated for unique instance identity | `cleanup.sh` |
| Cloud-init clean | State fully wiped so per-instance scripts run correctly | `cleanup.sh` |
| Guard clause on re-runs | `.env` existence check prevents credential overwrite | `01-geolens-init.sh` |
| Comprehensive validation | 12-check validation script covers all critical first-run state | `validate-firstrun.sh` |
| systemd auto-restart | `geolens.service` enabled, restarts stack on reboot | `geolens.service` |
| Docker pre-pull | Images cached in AMI to reduce first-boot time | `setup-geolens.sh` |
| Multi-cloud IP detection | IMDSv2 (AWS) + DigitalOcean metadata + localhost fallback | `01-geolens-init.sh` |
| Login banner | Clear MOTD with credential access and management commands | `99-geolens` |

---

## 5.5 Pre-Submission Checklist

Before submitting to AWS Marketplace:

1. **Seller registration** -- Register as an AWS Marketplace seller at https://aws.amazon.com/marketplace/management/. Allow 2-4 weeks for account approval (tax identity, bank account, company verification).
2. **AMI scanning** -- Run the Marketplace Management Portal's self-service AMI scanning tool to check for security issues before submission.
3. **EULA configuration** -- Configure BUSL-1.1 as the custom EULA in the Marketplace Management Portal during listing creation.
4. **Product code** -- After receiving the product code from AWS, rebuild the AMI with `-var 'product_code=XXXXX'`.
5. **Version pinning** -- Ensure all Docker image tags are pinned to specific versions (no `:latest`).
6. **Test launch** -- Launch the AMI in a fresh account/VPC to verify first-boot completes successfully.

---

## 6. Summary

**Overall readiness: 70% -- requires 4 blocking failures to be resolved before submission.**

The checklist identifies 4 failures (image tag pinning, product code, usage docs, root containers) and 7 blocking gaps (EULA, product code, usage docs, HTTPS, image tags, metering, root containers). The overlap is intentional: checklist items map to specific gaps. All 7 gaps must be addressed.

The AMI infrastructure is well-engineered with strong security defaults. The blocking gaps are primarily around Marketplace-specific integration (metering API, product code, version pinning, root containers) and documentation (usage instructions, CloudFormation template). None of the gaps require architectural changes.

**Estimated effort to reach submission-ready:**

| Category | Items | Estimated Effort |
|----------|-------|------------------|
| P0 Blockers (must fix) | 6 items | 2-3 days |
| P1 Required (should fix) | 6 items | 1-2 days |
| P2 Recommended | 5 items | 1 day |
| P3 Nice to have | 2 items | 3-5 days |

**Recommended sequence:**
1. Pin Docker image tags, remove root containers, fix backup script mount (immediate, low effort)
2. Create usage documentation and CloudFormation template
3. Integrate Marketplace Metering API
4. Increase volume size, add log rotation, add swap, enable unattended-upgrades
5. Register as Marketplace seller (start early -- 2-4 week lead time)
6. Multi-region AMI distribution
7. Run AMI scanning tool and resolve findings
8. Submit for Marketplace review
