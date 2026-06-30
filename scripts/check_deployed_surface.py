#!/usr/bin/env python3
"""Check deployed marketing/docs pages for launch-surface drift.

The checker is stdlib-only so release maintainers can run it without installing
project dependencies. It fetches the URLs configured in
scripts/deployed_surface_gate.json and verifies forbidden and required text
assertions against normalized HTML.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import urljoin, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "scripts" / "deployed_surface_gate.json"
USER_AGENT = "GeoLens deployed-surface-check"
ALLOWED_DEPLOYED_HOSTS = frozenset({"getgeolens.com", "docs.getgeolens.com"})


@dataclass(frozen=True)
class TextAssertion:
    id: str
    pattern: str
    reason: str
    flags: str
    regex: re.Pattern[str]


@dataclass(frozen=True)
class PageConfig:
    id: str
    url: str
    required: list[TextAssertion]
    forbidden: list[TextAssertion]


@dataclass(frozen=True)
class GateConfig:
    timeout_seconds: float
    max_bytes: int
    pages: list[PageConfig]


@dataclass(frozen=True)
class PageFetch:
    url: str
    text: str


@dataclass(frozen=True)
class Failure:
    page_id: str
    url: str
    assertion_id: str
    kind: str
    reason: str
    match: str
    excerpt: str


@dataclass(frozen=True)
class ScanResult:
    pages_scanned: int
    failures: list[Failure]
    errors: list[str]


FetchFn = Callable[[str, float, int], PageFetch]


class VisibleTextParser(HTMLParser):
    ignored_tags = {"script", "style", "template", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_stack: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if tag_name in self.ignored_tags or self._ignored_stack:
            self._ignored_stack.append(tag_name)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if not self._ignored_stack:
            return
        if tag_name in self._ignored_stack:
            while self._ignored_stack:
                popped = self._ignored_stack.pop()
                if popped == tag_name:
                    break

    def handle_data(self, data: str) -> None:
        if not self._ignored_stack:
            self.parts.append(data)


class DeployedRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        validate_deployed_url("redirect", urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def regex_flags(flag_text: str) -> int:
    flags = 0
    for flag in flag_text:
        if flag == "i":
            flags |= re.IGNORECASE
        elif flag:
            raise ValueError(f"unsupported regex flag {flag!r}")
    return flags


def validate_deployed_url(label: str, url: str) -> None:
    parsed = urlparse(url)
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    if parsed.scheme != "https" or hostname not in ALLOWED_DEPLOYED_HOSTS:
        raise ValueError(
            f"{label} url must be https on an allowed deployed host "
            f"({', '.join(sorted(ALLOWED_DEPLOYED_HOSTS))}): {url}"
        )
    if parsed.port not in (None, 443):
        raise ValueError(f"{label} url must use the default HTTPS port: {url}")
    if parsed.username or parsed.password:
        raise ValueError(f"{label} url must not include credentials: {url}")


def require_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def require_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def require_positive_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a positive number")
    number = float(value)
    if number <= 0:
        raise ValueError(f"{label} must be greater than zero")
    return number


def require_positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{label} must be greater than zero")
    return value


def compile_assertion(page_id: str, kind: str, index: int, raw: object) -> TextAssertion:
    entry = require_object(raw, f"{page_id}.{kind}[{index}]")
    for field in ("id", "pattern", "reason"):
        if not str(entry.get(field, "")).strip():
            raise ValueError(f"{page_id}.{kind}[{index}] missing required field: {field}")

    assertion_id = str(entry["id"])
    pattern = str(entry["pattern"])
    flags = str(entry.get("flags", ""))
    try:
        regex = re.compile(pattern, regex_flags(flags))
    except re.error as exc:
        raise ValueError(f"{page_id}.{kind}.{assertion_id} invalid regex: {exc}") from exc

    return TextAssertion(
        id=assertion_id,
        pattern=pattern,
        reason=str(entry["reason"]),
        flags=flags,
        regex=regex,
    )


def load_config(path: Path = DEFAULT_CONFIG) -> GateConfig:
    raw = require_object(json.loads(path.read_text(encoding="utf-8")), str(path))
    for field in ("timeout_seconds", "max_bytes", "pages"):
        if field not in raw:
            raise ValueError(f"{path} missing required top-level key: {field}")

    timeout_seconds = require_positive_number(raw["timeout_seconds"], "timeout_seconds")
    max_bytes = require_positive_integer(raw["max_bytes"], "max_bytes")

    pages: list[PageConfig] = []
    seen_page_ids: set[str] = set()
    for page_index, raw_page in enumerate(require_list(raw["pages"], "pages")):
        page = require_object(raw_page, f"pages[{page_index}]")
        page_id = str(page.get("id", "")).strip()
        url = str(page.get("url", "")).strip()
        if not page_id:
            raise ValueError(f"pages[{page_index}] missing required field: id")
        if page_id in seen_page_ids:
            raise ValueError(f"duplicate page id: {page_id}")
        seen_page_ids.add(page_id)
        if not url:
            raise ValueError(f"{page_id} missing required field: url")
        validate_deployed_url(page_id, url)

        required = [
            compile_assertion(page_id, "required", index, entry)
            for index, entry in enumerate(require_list(page.get("required", []), f"{page_id}.required"))
        ]
        forbidden = [
            compile_assertion(page_id, "forbidden", index, entry)
            for index, entry in enumerate(require_list(page.get("forbidden", []), f"{page_id}.forbidden"))
        ]
        seen_assertions: set[str] = set()
        for assertion in [*required, *forbidden]:
            if assertion.id in seen_assertions:
                raise ValueError(f"{page_id} duplicate assertion id: {assertion.id}")
            seen_assertions.add(assertion.id)
        if not required and not forbidden:
            raise ValueError(f"{page_id} must define at least one assertion")

        pages.append(PageConfig(id=page_id, url=url, required=required, forbidden=forbidden))

    if not pages:
        raise ValueError("pages must contain at least one page")

    return GateConfig(timeout_seconds=timeout_seconds, max_bytes=max_bytes, pages=pages)


def fetch_url(url: str, timeout_seconds: float, max_bytes: int) -> PageFetch:
    validate_deployed_url("configured page", url)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    opener = build_opener(DeployedRedirectHandler)
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            data = response.read(max_bytes + 1)
            final_url = response.geturl()
            validate_deployed_url("final response", final_url)
    except HTTPError as exc:
        raise OSError(f"{url} returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise OSError(f"{url} fetch failed: {exc.reason}") from exc

    if len(data) > max_bytes:
        raise OSError(f"{url} response exceeded max_bytes={max_bytes}")
    return PageFetch(url=final_url, text=data.decode("utf-8", errors="replace"))


def normalize_text(text: str) -> str:
    parser = VisibleTextParser()
    parser.feed(text)
    parser.close()
    return " ".join(" ".join(parser.parts).split())


def trim_excerpt(text: str, start: int, end: int) -> str:
    excerpt = text[max(0, start - 80) : min(len(text), end + 80)].strip()
    excerpt = " ".join(excerpt.split())
    if len(excerpt) > 180:
        return f"{excerpt[:177]}..."
    return excerpt


def missing_excerpt(assertion: TextAssertion) -> str:
    pattern = assertion.pattern
    if len(pattern) > 120:
        return f"missing pattern: {pattern[:117]}..."
    return f"missing pattern: {pattern}"


def scan_page_text(page: PageConfig, text: str, fetched_url: str | None = None) -> list[Failure]:
    normalized = normalize_text(text)
    url = fetched_url or page.url
    failures: list[Failure] = []

    for assertion in page.forbidden:
        for match in assertion.regex.finditer(normalized):
            failures.append(
                Failure(
                    page_id=page.id,
                    url=url,
                    assertion_id=assertion.id,
                    kind="forbidden",
                    reason=assertion.reason,
                    match=match.group(0),
                    excerpt=trim_excerpt(normalized, match.start(), match.end()),
                )
            )

    for assertion in page.required:
        if assertion.regex.search(normalized):
            continue
        failures.append(
            Failure(
                page_id=page.id,
                url=url,
                assertion_id=assertion.id,
                kind="required",
                reason=assertion.reason,
                match="",
                excerpt=missing_excerpt(assertion),
            )
        )

    return failures


def scan_pages(config: GateConfig, fetch: FetchFn = fetch_url) -> ScanResult:
    failures: list[Failure] = []
    errors: list[str] = []
    pages_scanned = 0

    for page in config.pages:
        try:
            fetched = fetch(page.url, config.timeout_seconds, config.max_bytes)
        except (OSError, ValueError) as exc:
            errors.append(f"{page.id} {page.url}: {exc}")
            continue
        pages_scanned += 1
        failures.extend(scan_page_text(page, fetched.text, fetched.url))

    failures.sort(key=lambda item: (item.page_id, item.kind, item.assertion_id, item.match))
    errors.sort()
    return ScanResult(pages_scanned=pages_scanned, failures=failures, errors=errors)


def print_result(result: ScanResult) -> None:
    if result.errors:
        print("Fetch/config errors:", file=sys.stderr)
        for error in result.errors:
            print(f"  - {error}", file=sys.stderr)
    if result.failures:
        print("Deployed surface violations:", file=sys.stderr)
        for failure in result.failures:
            print(
                f"{failure.page_id} {failure.url}: {failure.kind} {failure.assertion_id}: "
                f"{failure.reason}",
                file=sys.stderr,
            )
            if failure.match:
                print(f"    match: {failure.match!r}", file=sys.stderr)
            print(f"    > {failure.excerpt}", file=sys.stderr)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to deployed_surface_gate.json (default: scripts/deployed_surface_gate.json).",
    )
    parser.add_argument(
        "--list-pages",
        action="store_true",
        help="Print configured deployed page IDs and URLs without fetching.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(args.config)
        if args.list_pages:
            for page in config.pages:
                print(f"{page.id}\t{page.url}")
            return 0
        result = scan_pages(config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"deployed-surface gate FAILED: {exc}", file=sys.stderr)
        return 1

    if result.errors or result.failures:
        print_result(result)
        print(
            f"deployed-surface gate FAILED: {len(result.errors)} error(s), "
            f"{len(result.failures)} assertion failure(s).",
            file=sys.stderr,
        )
        return 1

    print(f"deployed-surface gate passed ({result.pages_scanned} deployed page(s) scanned).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
