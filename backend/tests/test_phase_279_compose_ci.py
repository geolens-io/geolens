"""Phase 279 ADMIN-10..13 regression tests.

Static-analysis tests for compose + CI hygiene changes. Each test fails
loudly if a future PR walks back the change.

ADMIN-10 + ADMIN-12 — MinIO + mc images bumped from RELEASE.2025-04-22 and
                      pinned by sha256 digest in docker-compose.yml.
ADMIN-11           — Stale `--ignore-vuln CVE-2026-4539` removed from the
                      pip-audit step in .github/workflows/ci.yml.
ADMIN-13           — Non-blocking `license-check` job added to ci.yml that
                      uploads a license-report artifact for reviewer use.
"""

import re
import tomllib

import pytest
import yaml

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
COMPOSE = REPO_ROOT / "docker-compose.yml"
COMPOSE_FILES = [COMPOSE, REPO_ROOT / "docker-compose.prod.yml"]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
UV_LOCK = REPO_ROOT / "backend" / "uv.lock"


# -------------------------------------------------------------------
# ADMIN-10 + ADMIN-12 — MinIO + mc image bump + digest pin
# -------------------------------------------------------------------


@pytest.mark.parametrize("compose", COMPOSE_FILES, ids=lambda path: path.name)
def test_minio_image_pinned_by_digest(compose):
    """The MinIO image is pinned as <RELEASE.YYYY-...>@sha256:<64-hex>.

    The digest pin makes pulls reproducible across machines (ADMIN-12) and the
    date-stamped tag must be after the prior 2025-04-22 pin (ADMIN-10). The
    image is pgsty/silo, the maintained fork, because the quay.io/minio
    repositories no longer serve anonymous pulls.
    """
    text = compose.read_text()
    match = re.search(
        r"^\s*image:\s*pgsty/silo:"
        r"(RELEASE\.\d{4}-\d{2}-\d{2}T[\d-]+Z)@sha256:[a-f0-9]{64}",
        text,
        re.MULTILINE,
    )
    assert match, "MinIO image must be pinned as <TAG>@sha256:<DIGEST>"
    tag = match.group(1)
    # Tag's date portion must be after 2025-04-22 (the prior pin).
    date_str = tag.split("RELEASE.")[1].split("T")[0]  # "YYYY-MM-DD"
    year, month, day = (int(p) for p in date_str.split("-"))
    assert (year, month, day) > (2025, 4, 22), (
        f"MinIO tag {tag} is older than the pre-bump pin 2025-04-22"
    )


@pytest.mark.parametrize("compose", COMPOSE_FILES, ids=lambda path: path.name)
def test_minio_entrypoint_execs_the_silo_binary(compose):
    """The silo image ships no `minio` binary, so the entrypoint must run `silo`."""
    text = compose.read_text()
    assert re.search(r"^\s*exec silo server /data\b", text, re.MULTILINE)
    assert not re.search(r"^\s*exec minio server\b", text, re.MULTILINE)


@pytest.mark.parametrize("compose", COMPOSE_FILES, ids=lambda path: path.name)
def test_mc_image_pinned_by_digest(compose):
    """The mc (minio client) image is pinned the same way as minio."""
    text = compose.read_text()
    match = re.search(
        r"^\s*image:\s*pgsty/mc:"
        r"(RELEASE\.\d{4}-\d{2}-\d{2}T[\d-]+Z)@sha256:[a-f0-9]{64}",
        text,
        re.MULTILINE,
    )
    assert match, "mc image must be pinned as <TAG>@sha256:<DIGEST>"
    tag = match.group(1)
    date_str = tag.split("RELEASE.")[1].split("T")[0]
    year, month, day = (int(p) for p in date_str.split("-"))
    assert (year, month, day) > (2025, 4, 22), (
        f"mc tag {tag} is older than the pre-bump pin 2025-04-22"
    )


def test_minio_setup_keeps_mc_config_out_of_read_only_root():
    """minio-setup drops every capability and the mc image's /root is read-only.

    mc cannot create its default config directory there, so the script must
    point MC_CONFIG_DIR at a writable path or the container exits before it
    creates the bucket.
    """
    script = (REPO_ROOT / "scripts" / "minio-setup.sh").read_text()
    assert re.search(r"^MC_CONFIG_DIR=/tmp/\S+$", script, re.MULTILINE)
    assert re.search(r"^export MC_CONFIG_DIR$", script, re.MULTILINE)


# -------------------------------------------------------------------
# ADMIN-11 — CVE-2026-4539 ignore is removed
# -------------------------------------------------------------------


def test_pip_audit_no_longer_ignores_cve_2026_4539():
    """The pip-audit step does not pass --ignore-vuln CVE-2026-4539.

    Comments referencing the CVE in historical context (e.g. "removed in
    Phase 279...") are allowed — the test only fails if the actual
    `--ignore-vuln CVE-2026-4539` flag re-appears in a `run:` line.
    """
    text = CI.read_text()
    # Strip lines that are purely comments — bare # lines or `      #` etc.
    non_comment = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    assert "--ignore-vuln CVE-2026-4539" not in non_comment, (
        "CI pip-audit step must not ignore CVE-2026-4539 — Phase 279 ADMIN-11 "
        "removed this carve-out because pip is patched and the CVE no longer "
        "surfaces in pip-audit output."
    )


def test_security_scan_lockfile_pins_patched_pip():
    """The locked dev env keeps pip patched for the pip-audit venv scan."""
    doc = tomllib.loads(UV_LOCK.read_text())
    pip_packages = [package for package in doc["package"] if package["name"] == "pip"]
    assert len(pip_packages) == 1, "Expected one locked pip package."

    version = tuple(int(part) for part in pip_packages[0]["version"].split("."))
    assert version >= (26, 1, 2), (
        "backend/uv.lock must keep pip at a version fixed for PYSEC-2026-196 "
        "because Security Scan audits the locked uv-managed dev environment."
    )


# -------------------------------------------------------------------
# ADMIN-13 — license-check job present and non-blocking
# -------------------------------------------------------------------


def test_license_check_job_present():
    """ci.yml has a job named `license-check` (or `license_check`)."""
    doc = yaml.safe_load(CI.read_text())
    jobs = doc.get("jobs", {})
    # GitHub Actions allows hyphen-or-underscore in job names; accept both.
    names = set(jobs.keys())
    assert "license-check" in names or "license_check" in names, (
        f"Expected 'license-check' job in ci.yml, got: {sorted(names)}"
    )


def test_license_check_job_is_non_blocking():
    """No other job depends on license-check via `needs:`.

    ADMIN-13 mandates the job is non-blocking — it can fail without
    blocking PR merge. Any `needs: license-check` would re-blockify it.
    """
    doc = yaml.safe_load(CI.read_text())
    jobs = doc.get("jobs", {})
    license_job_names = {n for n in jobs if n in ("license-check", "license_check")}
    assert license_job_names, "license-check job not found"

    for name, body in jobs.items():
        if name in license_job_names:
            continue
        needs = body.get("needs")
        if needs is None:
            continue
        if isinstance(needs, str):
            needs = [needs]
        for dep in needs:
            assert dep not in license_job_names, (
                f"Job '{name}' depends on license-check via 'needs:' — that "
                "makes the license-check blocking, but ADMIN-13 mandates "
                "non-blocking. Remove the 'needs:' entry."
            )
