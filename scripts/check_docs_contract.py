#!/usr/bin/env python3
"""Enforce docs-contract.json: the single source of truth for cross-surface
documentation facts (install commands, ports, version, claim wording).

Two jobs:
  1. Self-validate the contract against the real canonical sources in this repo
     (so the contract itself cannot drift from the binaries): app version vs
     backend/pyproject.toml, ports vs scripts/install.sh defaults, compose files
     exist, and the install one-liner appears in the README.
  2. Scan the public-facing READMEs for the contract's `forbidden` patterns —
     the exact drift classes the pre-announcement review caught (geolens.yml,
     raw-port OGC endpoints, "OGC Compliant", admin/admin-on-fresh-install).

The getgeolens.com repo vendors a copy of docs-contract.json and runs the same
`forbidden` list over its marketing + docs content. Pure stdlib; exits non-zero
on any violation. Run: python scripts/check_docs_contract.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "docs-contract.json"
READMES = ["README.md", "README.de.md", "README.es.md", "README.fr.md"]

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def load_contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def pyproject_version() -> str | None:
    txt = (ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', txt, re.MULTILINE)
    return m.group(1) if m else None


def installsh_port(var: str) -> int | None:
    """Parse `[ -n "$x_port" ] || x_port=NNNN` defaults from scripts/install.sh."""
    txt = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    m = re.search(rf"\b{var}=(\d+)\b", txt)
    return int(m.group(1)) if m else None


def validate_contract(c: dict) -> None:
    # version vs backend/pyproject.toml
    pv = pyproject_version()
    if pv != c["version"]:
        err(f"version drift: contract={c['version']!r} but backend/pyproject.toml={pv!r}")

    # ports vs install.sh defaults
    for key, var in (("frontend", "fe_port"), ("api", "api_port"), ("db", "db_port")):
        got = installsh_port(var)
        if got != c["ports"][key]:
            err(f"port drift: contract.ports.{key}={c['ports'][key]} but install.sh {var}={got}")

    # compose files exist
    for f in c["install"]["composeFiles"]:
        if not (ROOT / f).is_file():
            err(f"contract names compose file {f!r} which does not exist")

    # install one-liner present in README
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if c["install"]["oneLiner"] not in readme:
        err(f"README.md is missing the canonical install one-liner: {c['install']['oneLiner']!r}")


def scan_forbidden(c: dict) -> None:
    compiled = [
        (re.compile(f["pattern"], re.IGNORECASE if "i" in f.get("flags", "") else 0), f)
        for f in c["forbidden"]
    ]
    for name in READMES:
        p = ROOT / name
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            for rx, f in compiled:
                if rx.search(line):
                    err(f"{name}:{line_no} forbidden pattern /{f['pattern']}/ — {f['reason']}\n    > {line.strip()[:160]}")


def main() -> int:
    if not CONTRACT.is_file():
        print(f"ERROR: {CONTRACT} not found", file=sys.stderr)
        return 1
    c = load_contract()
    validate_contract(c)
    scan_forbidden(c)
    if errors:
        print("docs-contract check FAILED:\n", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print(f"\n{len(errors)} violation(s). Fix the surface to match docs-contract.json, "
              "or update the contract (and its canonical source) deliberately.", file=sys.stderr)
        return 1
    print("docs-contract check passed — contract matches install.sh/pyproject and "
          "READMEs carry no forbidden drift patterns.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
