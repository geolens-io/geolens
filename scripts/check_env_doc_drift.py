"""Env-doc-drift gate (DOC-01): keep `.env.example` honest about installer keys.

`scripts/install.sh` writes a set of environment keys into the operator's `.env`
(via `update_env_value <KEY> ...`). Every such key MUST also be documented in
`.env.example` so an operator who copies the example by hand — instead of running
the installer — gets a complete, accurate template. This guard parses the keys
install.sh persists, compares them to `.env.example`, and FAILS naming any key
that install.sh writes but `.env.example` does not document.

"Documented" means the key appears in `.env.example` either as an active
assignment (`KEY=`) or as a commented example/placeholder (`# KEY=`). Commented
keys count because several keys ship commented-out on purpose (cloud-dev MinIO
creds, the prebuilt-deploy GEOLENS_VERSION/COMPOSE_FILE knobs) — they are
documented, just not active in the default-profile install path.

Usage:
    python scripts/check_env_doc_drift.py
Exit code 0 = no drift; 1 = install.sh writes a key absent from `.env.example`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

# Keys install.sh references for *runtime control flow only* — it reads/derives
# them but never persists them into the operator's .env, so .env.example is not
# obligated to ship them as first-standup template lines. Keep this list tight
# and commented; anything install.sh actually `update_env_value`s must NOT be
# allowlisted away.
RUNTIME_ONLY_ALLOWLIST: frozenset[str] = frozenset(
    {
        # Host-port knobs install.sh only *reads* (get_env_value) to pick the
        # in-use port check; they already ship as active defaults in .env.example,
        # but this allowlist documents that install.sh does not write them.
        # (They are present in .env.example anyway, so this is belt-and-braces.)
    }
)

# Matches `update_env_value <KEY> ...` — the canonical write path install.sh
# uses to persist a value into .env.
WRITE_RE = re.compile(r"^\s*update_env_value\s+([A-Z][A-Z0-9_]*)\b")


def keys_written_by_installer(install_sh: Path) -> set[str]:
    """Return the set of env keys install.sh persists via update_env_value."""
    keys: set[str] = set()
    for line in install_sh.read_text().splitlines():
        m = WRITE_RE.match(line)
        if m:
            keys.add(m.group(1))
    return keys


def keys_documented_in_example(env_example: Path) -> set[str]:
    """Return keys documented in .env.example (active `KEY=` or commented `# KEY=`)."""
    keys: set[str] = set()
    # Active assignment at line start.
    active = re.compile(r"^([A-Z][A-Z0-9_]*)=")
    # Commented example/placeholder: `# KEY=` (any leading-hash + whitespace).
    commented = re.compile(r"^#\s*([A-Z][A-Z0-9_]*)=")
    for line in env_example.read_text().splitlines():
        m = active.match(line) or commented.match(line)
        if m:
            keys.add(m.group(1))
    return keys


def main() -> int:
    if not INSTALL_SH.is_file():
        print(f"error: {INSTALL_SH} not found", file=sys.stderr)
        return 2
    if not ENV_EXAMPLE.is_file():
        print(f"error: {ENV_EXAMPLE} not found", file=sys.stderr)
        return 2

    written = keys_written_by_installer(INSTALL_SH)
    documented = keys_documented_in_example(ENV_EXAMPLE)

    missing = sorted(written - documented - RUNTIME_ONLY_ALLOWLIST)

    if missing:
        print(
            "env-doc drift: install.sh writes the following key(s) that are "
            "NOT documented in .env.example:",
            file=sys.stderr,
        )
        for key in missing:
            print(f"  - {key}", file=sys.stderr)
        print(
            "\nFix: add each key to .env.example (active `KEY=` or commented "
            "`# KEY=` with a description), or — if it is genuinely runtime-only "
            "and install.sh should not persist it — add it to "
            "RUNTIME_ONLY_ALLOWLIST in scripts/check_env_doc_drift.py with a "
            "justification comment.",
            file=sys.stderr,
        )
        return 1

    print(
        f"env-doc-check OK: all {len(written)} installer-written key(s) are "
        "documented in .env.example."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
