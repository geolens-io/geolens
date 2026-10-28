# SPDX-License-Identifier: Apache-2.0
"""Create GeoLens users in bulk: ``geolens admin users import``.

Hand-maintained. Reads a CSV with the columns ``username``, ``email`` and
``role``, or takes the rows from an ArcGIS inventory: every item owner as an
editor, so migrate can hand them their items, and every member of a group an
item is shared with as a viewer. A user GeoLens already has, by username or
email, is skipped.

Each new user gets a generated password that meets the GeoLens password
policy. Only with ``--print-passwords`` is it shown, once, on standard output;
otherwise nobody knows it and the operator sets one per user through the
admin password reset. A password is never written to a file, a log or an
error message.

An instance that signs in through an identity provider (OpenID Connect,
SAML or a sign-in extension) creates its users at their first sign-in, so by
default nothing is created there and those owners and members stay pending
until a migrate rerun finds them. ``--link-by-email`` creates them anyway,
with a password nobody is shown, for that first sign-in to link to by email;
GeoLens links only when the provider sends ``email_verified``. An email an
admin enters counts as verified, so a provider sign-in with that address
takes the account: rows' emails need review before ``--link-by-email``.
"""

from __future__ import annotations

import csv
import io
import os
import secrets
import string
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import typer

from . import arcgis_plan as _plan
from . import output as _output
from ._sdk_helpers import EXIT_AUTH, EXIT_GENERIC, EXIT_OK, EXIT_SERVER, EXIT_USAGE
from .arcgis_migrate_session import GeoLens, GeoLensError
from .arcgis_portal import Redactor

ROLES = ("admin", "editor", "viewer")
COLUMNS = ("username", "email", "role")
OWNER_ROLE = "editor"
MEMBER_ROLE = "viewer"
USERNAME_LENGTH = (3, 150)
EXIT_INTERRUPTED = 130
USER_PAGE_SIZE = 200
# A spreadsheet reads a cell starting with one of these as a formula.
_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")
# Well past the default 12-character policy and under bcrypt's 72 bytes.
PASSWORD_LENGTH = 32
_PASSWORD_CLASSES = (
    string.ascii_lowercase,
    string.ascii_uppercase,
    string.digits,
    "-_.!@#%^*+=?",
)


class UsageError(Exception):
    """The rows can't be read or the options don't go together."""


@dataclass(frozen=True)
class Row:
    username: str
    email: str | None
    role: str


@dataclass
class ImportOptions:
    csv_path: Path | None
    inventory_path: Path | None
    seed_path: Path | None = None
    print_passwords: bool = False
    link_by_email: bool = False
    dry_run: bool = False


def generate_password() -> str:
    """A random password with every character class, ASCII so its length is
    its size in bytes."""
    alphabet = "".join(_PASSWORD_CLASSES)
    chars = [secrets.choice(group) for group in _PASSWORD_CLASSES]
    chars += [secrets.choice(alphabet) for _ in range(PASSWORD_LENGTH - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _row(username: str, email: str, role: str, where: str) -> Row:
    username = username.strip()
    role = role.strip().lower() or MEMBER_ROLE
    low, high = USERNAME_LENGTH
    if not low <= len(username) <= high:
        raise UsageError(f"{where}: a username takes {low} to {high} characters")
    if role not in ROLES:
        raise UsageError(f"{where}: role {role} is not one of {', '.join(ROLES)}")
    return Row(username, email.strip() or None, role)


def _unique(rows: list[Row]) -> list[Row]:
    seen: dict[str, str] = {}
    for row in rows:
        for key in (row.username, row.email):
            if key and seen.setdefault(key.lower(), row.username) != row.username:
                raise UsageError(f"{key} is given to more than one row")
    return rows


def read_csv(path: Path) -> list[Row]:
    """The rows of a ``username,email,role`` CSV with that header."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            header = [(name or "").strip().lower() for name in reader.fieldnames or []]
            if "username" not in header:
                raise UsageError(
                    f"{path} needs a header row naming the columns {','.join(COLUMNS)}"
                )
            reader.fieldnames = header
            rows = [
                _row(
                    record.get("username") or "",
                    record.get("email") or "",
                    record.get("role") or "",
                    f"{path} line {reader.line_num}",
                )
                for record in reader
                if any((value or "").strip() for value in record.values())
            ]
    except OSError as exc:
        raise UsageError(f"can't read {path}: {exc.strerror}") from None
    except (UnicodeDecodeError, csv.Error) as exc:
        raise UsageError(f"{path} is not a CSV file: {exc}") from None
    return _unique(rows)


def rows_from_inventory(inventory: Mapping[str, Any]) -> list[Row]:
    """Every item owner as an editor and every member of a group an item is
    shared with as a viewer, by ArcGIS username."""
    roles: dict[str, str] = {}
    emails: dict[str, str | None] = {}
    for item in inventory["items"]:
        if item["owner"]:
            roles[item["owner"]] = OWNER_ROLE
            emails[item["owner"]] = emails.get(item["owner"]) or item["owner_email"]
    for group in inventory.get("groups", []):
        for member in group["members"] or []:
            roles.setdefault(member, MEMBER_ROLE)
    return _unique(
        [
            _row(name, emails.get(name) or "", role, f"inventory user {name}")
            for name, role in sorted(roles.items())
        ]
    )


def _cell(value: str) -> str:
    """*value* made inert for a spreadsheet the CSV is opened in."""
    return f"'{value}" if value.startswith(_FORMULA_LEAD) else value


def write_seed(path: Path, rows: Iterable[Row]) -> None:
    """Write *rows* as a new CSV, at mode 0600 since it holds email addresses,
    to review and edit before importing it; an existing file is refused."""
    text = io.StringIO()
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(
        [_cell(row.username), _cell(row.email or ""), row.role] for row in rows
    )
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise UsageError(
            f"{path} already exists; pass another --seed-csv path"
        ) from None
    except OSError as exc:
        raise UsageError(f"can't write {path}: {exc.strerror}") from None
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        out.write(text.getvalue())


def _list_users(geolens: GeoLens) -> list[Any]:
    from geolens.api.admin import list_users_admin_users_get as list_users

    users: list[Any] = []
    while True:
        page = geolens.call(
            list_users.sync_detailed, skip=len(users), limit=USER_PAGE_SIZE
        )
        users.extend(page.users)
        if not page.users or len(users) >= page.total:
            return users


def _identity_providers(geolens: GeoLens) -> list[str]:
    """The instance's sign-in methods other than its own password form."""
    from geolens.api.admin import get_capabilities_capabilities_get as get

    methods = geolens.call(get.sync_detailed).auth.methods
    return [method for method in methods if method != "password"]


def _create(geolens: GeoLens, row: Row, password: str) -> Any:
    from geolens.api.admin import create_user_admin_users_post as create
    from geolens.models.admin_user_create import AdminUserCreate

    body = AdminUserCreate(username=row.username, password=password, role=row.role)
    if row.email:
        body.email = row.email
    return geolens.call(create.sync_detailed, body=body, expected=201)


def _load_rows(opts: ImportOptions) -> list[Row]:
    if (opts.csv_path is None) == (opts.inventory_path is None):
        raise UsageError("give a CSV file or --from-inventory, not both or neither")
    if opts.seed_path is not None and opts.inventory_path is None:
        raise UsageError("--seed-csv goes with --from-inventory")
    if opts.print_passwords and opts.link_by_email:
        raise UsageError(
            "--link-by-email users sign in through the identity provider, so "
            "their passwords are never printed; drop --print-passwords"
        )
    if opts.inventory_path is None:
        return read_csv(opts.csv_path) if opts.csv_path else []
    try:
        inventory = _plan.load_inventory(opts.inventory_path)
    except _plan.PlanError as exc:
        raise UsageError(str(exc)) from None
    return rows_from_inventory(inventory)


def _pending_reason(row: Row, opts: ImportOptions, provider: bool) -> str | None:
    if not provider:
        return None
    if not opts.link_by_email:
        return (
            "this instance signs in through an identity provider, which creates "
            "the user at first sign-in"
        )
    if not row.email:
        return "no email for the identity provider's first sign-in to link to"
    return None


def new_result() -> dict[str, Any]:
    """What an import did, filled in as it goes."""
    return {
        "identity_providers": None,
        "created": [],
        "skipped": [],
        "conflicts": [],
        "pending": [],
        "failed": [],
        "stopped": None,
    }


def import_users(
    geolens: GeoLens,
    rows: list[Row],
    opts: ImportOptions,
    redact: Redactor,
    result: dict[str, Any],
) -> None:
    """Create each row's user unless it exists, conflicts with an account or
    must wait, recording each outcome in *result* as it happens, so whatever
    stops the run leaves the users already created in it."""
    providers = _identity_providers(geolens)
    if opts.link_by_email and not providers:
        raise UsageError(
            "--link-by-email is for an instance that signs in through an "
            "identity provider, and this one has none"
        )
    accounts = _Accounts(_list_users(geolens))
    result["identity_providers"] = providers
    for row in rows:
        _import_row(geolens, row, opts, redact, accounts, providers, result)


class _Accounts:
    """GeoLens users by lower-cased username and email."""

    def __init__(self, users: Iterable[Any]) -> None:
        self.by_name: dict[str, Any] = {}
        self.by_email: dict[str, Any] = {}
        for user in users:
            self.add(user)

    def add(self, user: Any) -> None:
        self.by_name[user.username.lower()] = user
        if user.email:
            self.by_email[user.email.lower()] = user

    def conflict(self, row: Row) -> tuple[bool, str | None]:
        """Whether *row* is already a user, and why it clashes with one."""
        account = self.by_name.get(row.username.lower())
        holder = self.by_email.get(row.email.lower()) if row.email else None
        if account is not None and (not row.email or holder is account):
            return True, None
        if account is not None:
            return True, f"GeoLens user {account.username} has another email"
        if holder is not None:
            return True, f"the email belongs to GeoLens user {holder.username}"
        return False, None


def _import_row(
    geolens: GeoLens,
    row: Row,
    opts: ImportOptions,
    redact: Redactor,
    accounts: _Accounts,
    providers: list[str],
    result: dict[str, Any],
) -> None:
    entry = {"username": row.username, "email": row.email, "role": row.role}
    exists, clash = accounts.conflict(row)
    if clash:
        result["conflicts"].append({**entry, "reason": clash})
        return
    if exists:
        result["skipped"].append({**entry, "reason": "already a GeoLens user"})
        return
    reason = _pending_reason(row, opts, bool(providers))
    if reason:
        result["pending"].append({**entry, "reason": reason})
        return
    if opts.dry_run:
        result["created"].append(entry)
        return
    password = generate_password()
    redact.add(password)
    try:
        created = _create(geolens, row, password)
    except GeoLensError as exc:
        if exc.status == 409:
            result["conflicts"].append({**entry, "reason": redact(str(exc))})
        else:
            result["failed"].append({**entry, "error": redact(str(exc))})
        return
    accounts.add(created)
    shown = {"password": password} if opts.print_passwords else {}
    result["created"].append({**entry, "id": str(created.id), **shown})


def _print(
    fmt: _output.Formatter, result: Mapping[str, Any], opts: ImportOptions
) -> None:
    verb = "Would create" if opts.dry_run else "Created"
    fmt.info(f"{verb} {len(result['created'])} user(s).")
    for user in result["created"]:
        line = f"  {user['username']} ({user['role']})"
        if "password" in user:
            line += f"  {user['password']}"
            # Shown this once, so --quiet doesn't hide it.
            fmt.console_stdout.print(line, soft_wrap=True, markup=False)
        else:
            fmt.info(line)
    for user in result["skipped"]:
        fmt.info(f"  skipped {user['username']}: {user['reason']}")
    for user in result["pending"]:
        fmt.warn(f"{user['username']} waits: {user['reason']}")
    for user in result["conflicts"]:
        fmt.error(f"{user['username']} not created: {user['reason']}")
    for user in result["failed"]:
        fmt.error(f"{user['username']}: {user['error']}")
    if result["stopped"]:
        fmt.error(
            f"{result['stopped']}; a user being created when it stopped may exist "
            "without its password shown, so set one through the admin password reset"
        )
    if result["created"] and not opts.dry_run and not opts.print_passwords:
        if opts.link_by_email:
            fmt.info(
                "They sign in through the identity provider, which links to them "
                "by email only when it sends email_verified."
            )
        else:
            fmt.info(
                "Nobody knows their passwords: set one for each through the admin "
                "password reset and pass it on."
            )


def run_cli(
    fmt: _output.Formatter,
    opts: ImportOptions,
    *,
    sdk_factory: Callable[[], Any],
    instance: str,
) -> int:
    """Run ``geolens admin users import`` and return its exit code."""
    redact = Redactor()
    try:
        rows = _load_rows(opts)
        if opts.seed_path is not None:
            write_seed(opts.seed_path, rows)
            fmt.success(f"Wrote {len(rows)} user(s) to {opts.seed_path}")
            return EXIT_OK
    except UsageError as exc:
        fmt.error(str(exc))
        return EXIT_USAGE
    geolens = GeoLens(sdk_factory(), instance, redact)
    result = new_result()
    try:
        import_users(geolens, rows, opts, redact, result)
        code = EXIT_GENERIC if result["failed"] or result["conflicts"] else EXIT_OK
    except UsageError as exc:
        fmt.error(str(exc))
        return EXIT_USAGE
    except KeyboardInterrupt:
        result["stopped"], code = "interrupted", EXIT_INTERRUPTED
    except typer.Exit as exc:
        # The failed request was reported where it failed.
        result["stopped"] = "stopped by a failed request"
        code = exc.exit_code or EXIT_GENERIC
    except click.ClickException as exc:
        result["stopped"], code = redact(exc.format_message()), exc.exit_code
    except GeoLensError as exc:
        result["stopped"] = redact(
            f"can't read the GeoLens users and sign-in setup: {exc}"
        )
        code = EXIT_GENERIC
        if exc.status in (401, 403):
            code = EXIT_AUTH
        elif exc.status >= 500:
            code = EXIT_SERVER
    except Exception as exc:  # broad: last guard so a traceback can't print a password
        result["stopped"] = redact(f"unexpected error: {type(exc).__name__}: {exc}")
        code = EXIT_GENERIC
    # Every way out shows what was created: a rerun skips those users, so a
    # password not shown now is lost.
    if result["identity_providers"] is None:
        fmt.error(str(result["stopped"]))
    elif fmt.json_mode:
        fmt.json({"dry_run": opts.dry_run, **result})
        if result["stopped"]:
            fmt.error(str(result["stopped"]))
    else:
        _print(fmt, result, opts)
    return code
