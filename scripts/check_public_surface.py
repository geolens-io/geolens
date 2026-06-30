#!/usr/bin/env python3
"""Scan public source surfaces for launch-sensitive wording.

The scanner is intentionally stdlib-only so it can run in local checks and CI
without dependency installation. It scans tracked files only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "scripts" / "public_surface_gate.json"
ALLOWLIST_FIELDS = {"id", "path", "pattern_id", "match", "reason"}
WILDCARD_CHARS = set("*?[")


@dataclass(frozen=True)
class ForbiddenPattern:
    id: str
    pattern: str
    reason: str
    flags: str
    regex: re.Pattern[str]


@dataclass(frozen=True)
class GateConfig:
    include_globs: list[str]
    exclude_globs: list[str]
    exclude_rationales: dict[str, str]
    forbidden: list[ForbiddenPattern]
    allowlist: list[dict[str, str]]


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    pattern_id: str
    match: str
    reason: str
    excerpt: str


@dataclass(frozen=True)
class ScanResult:
    files: list[str]
    violations: list[Violation]
    errors: list[str]


def regex_flags(flag_text: str) -> int:
    flags = 0
    for flag in flag_text:
        if flag == "i":
            flags |= re.IGNORECASE
        elif flag:
            raise ValueError(f"unsupported regex flag {flag!r}")
    return flags


def load_config(path: Path = DEFAULT_CONFIG) -> GateConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = {"include_globs", "exclude_globs", "exclude_rationales", "forbidden", "allowlist"}
    missing = sorted(required - set(raw))
    if missing:
        raise ValueError(f"{path} missing required top-level keys: {', '.join(missing)}")

    forbidden: list[ForbiddenPattern] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(raw["forbidden"]):
        for field in ("id", "pattern", "reason"):
            if not str(entry.get(field, "")).strip():
                raise ValueError(f"forbidden[{index}] missing required field: {field}")
        pattern_id = str(entry["id"])
        if pattern_id in seen_ids:
            raise ValueError(f"duplicate forbidden pattern id: {pattern_id}")
        seen_ids.add(pattern_id)
        flags = str(entry.get("flags", ""))
        forbidden.append(
            ForbiddenPattern(
                id=pattern_id,
                pattern=str(entry["pattern"]),
                reason=str(entry["reason"]),
                flags=flags,
                regex=re.compile(str(entry["pattern"]), regex_flags(flags)),
            )
        )

    return GateConfig(
        include_globs=[str(item) for item in raw["include_globs"]],
        exclude_globs=[str(item) for item in raw["exclude_globs"]],
        exclude_rationales={str(key): str(value) for key, value in raw["exclude_rationales"].items()},
        forbidden=forbidden,
        allowlist=[dict(item) for item in raw["allowlist"]],
    )


def tracked_files(root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return sorted(path for path in completed.stdout.decode("utf-8").split("\0") if path)


def path_matches(path: str, pattern: str) -> bool:
    normalized_path = path.replace("\\", "/").strip("/")
    normalized_pattern = pattern.replace("\\", "/").strip("/")
    path_parts = tuple(part for part in normalized_path.split("/") if part)
    pattern_parts = tuple(part for part in normalized_pattern.split("/") if part)

    if "/" not in normalized_pattern and not normalized_pattern.startswith("**"):
        return len(path_parts) == 1 and fnmatchcase(path_parts[0], normalized_pattern)

    @lru_cache(maxsize=None)
    def match_from(pattern_index: int, path_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)

        pattern_part = pattern_parts[pattern_index]
        if pattern_part == "**":
            return any(
                match_from(pattern_index + 1, next_path_index)
                for next_path_index in range(path_index, len(path_parts) + 1)
            )

        if path_index >= len(path_parts):
            return False
        if not fnmatchcase(path_parts[path_index], pattern_part):
            return False
        return match_from(pattern_index + 1, path_index + 1)

    return match_from(0, 0)


def is_candidate(path: str, config: GateConfig) -> bool:
    included = any(path_matches(path, pattern) for pattern in config.include_globs)
    excluded = any(path_matches(path, pattern) for pattern in config.exclude_globs)
    return included and not excluded


def collect_candidate_files(root: Path, config: GateConfig) -> list[str]:
    return [path for path in tracked_files(root) if is_candidate(path, config)]


def validate_allowlist(
    entries: Sequence[dict[str, str]],
    pattern_ids: set[str],
    tracked: set[str],
) -> tuple[list[dict[str, str]], list[str]]:
    valid: list[dict[str, str]] = []
    errors: list[str] = []
    seen_ids: set[str] = set()

    for index, entry in enumerate(entries):
        entry_id = str(entry.get("id", f"allowlist[{index}]"))
        missing = sorted(field for field in ALLOWLIST_FIELDS if not str(entry.get(field, "")).strip())
        for field in missing:
            errors.append(f"{entry_id}: missing required field: {field}")
        if "id" not in missing:
            if entry_id in seen_ids:
                errors.append(f"{entry_id}: duplicate allowlist id")
            seen_ids.add(entry_id)
        if missing:
            continue

        path = str(entry["path"])
        pattern_id = str(entry["pattern_id"])
        if any(char in path for char in WILDCARD_CHARS):
            errors.append(f"{entry_id}: wildcard paths are not allowed in allowlist entries: {path}")
            continue
        if pattern_id not in pattern_ids:
            errors.append(f"{entry_id}: unknown forbidden pattern id: {pattern_id}")
            continue
        if path not in tracked:
            errors.append(f"{entry_id}: allowlist path is not tracked by git: {path}")
            continue

        valid.append(
            {
                "id": entry_id,
                "path": path,
                "pattern_id": pattern_id,
                "match": str(entry["match"]),
                "reason": str(entry["reason"]).strip(),
            }
        )

    return valid, errors


def is_allowlisted(
    allowlist: Sequence[dict[str, str]],
    observed_allowlist_ids: set[str],
    path: str,
    pattern_id: str,
    match: str,
) -> bool:
    for entry in allowlist:
        if entry["id"] in observed_allowlist_ids:
            continue
        if entry["path"] == path and entry["pattern_id"] == pattern_id and entry["match"] == match:
            observed_allowlist_ids.add(entry["id"])
            return True
    return False


def trim_excerpt(line: str) -> str:
    excerpt = " ".join(line.strip().split())
    if len(excerpt) > 160:
        return f"{excerpt[:157]}..."
    return excerpt


def scan_file(
    root: Path,
    path: str,
    config: GateConfig,
    allowlist: Sequence[dict[str, str]],
    observed_allowlist_ids: set[str],
) -> Iterable[Violation]:
    file_path = root / path
    with file_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            for forbidden in config.forbidden:
                for match in forbidden.regex.finditer(line):
                    match_text = match.group(0)
                    if is_allowlisted(allowlist, observed_allowlist_ids, path, forbidden.id, match_text):
                        continue
                    yield Violation(
                        path=path,
                        line=line_number,
                        pattern_id=forbidden.id,
                        match=match_text,
                        reason=forbidden.reason,
                        excerpt=trim_excerpt(line),
                    )


def scan_repository(root: Path = ROOT, config_path: Path = DEFAULT_CONFIG) -> ScanResult:
    config = load_config(config_path)
    tracked = set(tracked_files(root))
    files = collect_candidate_files(root, config)
    allowlist, errors = validate_allowlist(
        config.allowlist,
        {pattern.id for pattern in config.forbidden},
        tracked,
    )
    observed_allowlist_ids: set[str] = set()
    violations: list[Violation] = []

    for path in files:
        violations.extend(scan_file(root, path, config, allowlist, observed_allowlist_ids))

    for entry in allowlist:
        if entry["id"] not in observed_allowlist_ids:
            errors.append(
                "stale allowlist entry "
                f"{entry['id']}: exact hit not observed for {entry['path']} "
                f"{entry['pattern_id']} {entry['match']!r}"
            )

    violations.sort(key=lambda item: (item.path, item.line, item.pattern_id, item.match))
    errors.sort()
    return ScanResult(files=files, violations=violations, errors=errors)


def print_result(result: ScanResult) -> None:
    if result.errors:
        print("Config errors:", file=sys.stderr)
        for error in result.errors:
            print(f"  - {error}", file=sys.stderr)
    if result.violations:
        print("Public surface violations:", file=sys.stderr)
        for violation in result.violations:
            print(
                f"{violation.path}:{violation.line}: {violation.pattern_id}: "
                f"{violation.reason}",
                file=sys.stderr,
            )
            print(f"    match: {violation.match!r}", file=sys.stderr)
            print(f"    > {violation.excerpt}", file=sys.stderr)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to public_surface_gate.json (default: scripts/public_surface_gate.json).",
    )
    parser.add_argument(
        "--list-files",
        action="store_true",
        help="Print tracked files selected by the include/exclude boundary and exit.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = args.config
    try:
        config = load_config(config_path)
        if args.list_files:
            for path in collect_candidate_files(ROOT, config):
                print(path)
            return 0
        result = scan_repository(ROOT, config_path)
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"public-surface gate FAILED: {exc}", file=sys.stderr)
        return 1

    if result.errors or result.violations:
        print_result(result)
        print(
            f"public-surface gate FAILED: {len(result.errors)} config error(s), "
            f"{len(result.violations)} violation(s).",
            file=sys.stderr,
        )
        return 1

    print(f"public-surface gate passed ({len(result.files)} tracked file(s) scanned).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
