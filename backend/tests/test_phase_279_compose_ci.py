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
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.yml"
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"


# -------------------------------------------------------------------
# ADMIN-10 + ADMIN-12 — MinIO + mc image bump + digest pin
# -------------------------------------------------------------------


def test_minio_image_pinned_by_digest():
    """The MinIO image is pinned as <RELEASE.YYYY-...>@sha256:<64-hex>.

    The digest pin makes pulls reproducible across machines (ADMIN-12) and the
    date-stamped tag must be after the prior 2025-04-22 pin (ADMIN-10).
    """
    text = COMPOSE.read_text()
    match = re.search(
        r"^\s*image:\s*quay\.io/minio/minio:"
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


def test_mc_image_pinned_by_digest():
    """The mc (minio client) image is pinned the same way as minio."""
    text = COMPOSE.read_text()
    match = re.search(
        r"^\s*image:\s*quay\.io/minio/mc:"
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
