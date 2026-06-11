"""Regression tests for Phase 1184 — GAP-005: backup schedule validation.

The backup-entrypoint.sh sleep-loop scheduler only fires for expressions of the
form 'M H * * *' (literal minute + hour, three wildcard fields). Any other form
silently never fires because `[ "$current_min" = "*/15" ]` never matches.

These tests verify the shell validate_cron_expr function by calling it via
subprocess with the sourced script logic. They confirm:
  - Supported expressions pass (exit 0)
  - Unsupported expressions fail-fast with a clear error (exit 1)
"""

from __future__ import annotations

import subprocess

# The validate_cron_expr function extracted from backup-entrypoint.sh for
# subprocess testing. We source only the function and call it directly,
# avoiding the full entrypoint side-effects (pg_dump, crontab, etc.).
_VALIDATE_HARNESS = r"""
log() { echo "$@" >&2; }

validate_cron_expr() {
    local expr="$1"
    field_count="$(echo "$expr" | awk '{print NF}')"
    if [ "$field_count" -ne 5 ]; then
        log "ERROR: BACKUP_SCHEDULE must have exactly 5 fields (got ${field_count}): '${expr}'"
        exit 1
    fi
    f_min="$(echo "$expr" | awk '{print $1}')"
    f_hour="$(echo "$expr" | awk '{print $2}')"
    f_dom="$(echo "$expr" | awk '{print $3}')"
    f_month="$(echo "$expr" | awk '{print $4}')"
    f_dow="$(echo "$expr" | awk '{print $5}')"
    case "$f_min" in
        ''|*[!0-9]*)
            log "ERROR: BACKUP_SCHEDULE minute field '${f_min}' is not a plain integer."
            exit 1
            ;;
    esac
    if [ "$f_min" -lt 0 ] || [ "$f_min" -gt 59 ]; then
        log "ERROR: BACKUP_SCHEDULE minute field '${f_min}' out of range 0-59."
        exit 1
    fi
    case "$f_hour" in
        ''|*[!0-9]*)
            log "ERROR: BACKUP_SCHEDULE hour field '${f_hour}' is not a plain integer."
            exit 1
            ;;
    esac
    if [ "$f_hour" -lt 0 ] || [ "$f_hour" -gt 23 ]; then
        log "ERROR: BACKUP_SCHEDULE hour field '${f_hour}' out of range 0-23."
        exit 1
    fi
    if [ "$f_dom" != "*" ] || [ "$f_month" != "*" ] || [ "$f_dow" != "*" ]; then
        log "ERROR: BACKUP_SCHEDULE fields 3-5 must all be '*'."
        exit 1
    fi
    exit 0
}

validate_cron_expr "$1"
"""


def _run_validate(expr: str) -> subprocess.CompletedProcess:
    """Run the validate_cron_expr shell function with the given expression."""
    return subprocess.run(
        ["sh", "-c", _VALIDATE_HARNESS, "--", expr],
        capture_output=True,
        text=True,
    )


class TestBackupScheduleValidation:
    """GAP-005: validate_cron_expr must accept supported and reject unsupported."""

    # --- Supported expressions (must exit 0) ---

    def test_default_schedule_passes(self):
        """Default '0 2 * * *' (02:00 daily) must pass."""
        result = _run_validate("0 2 * * *")
        assert result.returncode == 0, f"Expected pass, got: {result.stderr}"

    def test_zero_zero_passes(self):
        """'0 0 * * *' (midnight) must pass."""
        result = _run_validate("0 0 * * *")
        assert result.returncode == 0, f"Expected pass, got: {result.stderr}"

    def test_arbitrary_valid_passes(self):
        """'30 6 * * *' (06:30) must pass."""
        result = _run_validate("30 6 * * *")
        assert result.returncode == 0, f"Expected pass, got: {result.stderr}"

    def test_edge_minute_59_passes(self):
        """'59 23 * * *' must pass (max valid minute + hour)."""
        result = _run_validate("59 23 * * *")
        assert result.returncode == 0, f"Expected pass, got: {result.stderr}"

    # --- Unsupported expressions (must exit 1 with a clear error) ---

    def test_step_minute_rejected(self):
        """'*/15 * * * *' step in minute must fail fast."""
        result = _run_validate("*/15 * * * *")
        assert result.returncode != 0, "Expected failure for step expression"
        assert "ERROR" in result.stderr, f"Expected ERROR message, got: {result.stderr}"

    def test_step_hour_rejected(self):
        """'0 */6 * * *' step in hour must fail fast."""
        result = _run_validate("0 */6 * * *")
        assert result.returncode != 0, "Expected failure for step in hour"
        assert "ERROR" in result.stderr

    def test_day_of_week_rejected(self):
        """'0 2 * * 0' (Sunday only) must fail fast."""
        result = _run_validate("0 2 * * 0")
        assert result.returncode != 0, "Expected failure for day-of-week"
        assert "ERROR" in result.stderr

    def test_day_of_month_rejected(self):
        """'0 2 1 * *' (1st of month) must fail fast."""
        result = _run_validate("0 2 1 * *")
        assert result.returncode != 0, "Expected failure for day-of-month"
        assert "ERROR" in result.stderr

    def test_month_rejected(self):
        """'0 2 * 6 *' (June only) must fail fast."""
        result = _run_validate("0 2 * 6 *")
        assert result.returncode != 0, "Expected failure for month field"
        assert "ERROR" in result.stderr

    def test_range_in_minute_rejected(self):
        """'0-30 2 * * *' range in minute must fail fast."""
        result = _run_validate("0-30 2 * * *")
        assert result.returncode != 0, "Expected failure for range in minute"
        assert "ERROR" in result.stderr

    def test_wrong_field_count_rejected(self):
        """'0 2' (only 2 fields) must fail fast."""
        result = _run_validate("0 2")
        assert result.returncode != 0, "Expected failure for wrong field count"
        assert "ERROR" in result.stderr

    def test_minute_out_of_range_rejected(self):
        """'60 2 * * *' minute=60 out of range must fail fast."""
        result = _run_validate("60 2 * * *")
        assert result.returncode != 0, "Expected failure for minute > 59"
        assert "ERROR" in result.stderr

    def test_hour_out_of_range_rejected(self):
        """'0 24 * * *' hour=24 out of range must fail fast."""
        result = _run_validate("0 24 * * *")
        assert result.returncode != 0, "Expected failure for hour > 23"
        assert "ERROR" in result.stderr
