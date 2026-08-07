#!/usr/bin/env bash
# Archive-then-delete retention for catalog.audit_logs.
#
# RUNBOOK.md §8 is the operator-facing documentation. This script is the
# procedure itself; the RUNBOOK no longer carries a copy of the SQL.
#
# The table has no built-in expiry and no in-app pruning endpoint, so a
# retention window is applied out of band. Deleting rows that were never
# exported is data loss rather than retention, so every step below is ordered
# to make the archive provably complete BEFORE anything is deleted:
#
#   1. One cutoff timestamp is evaluated ONCE, in the database, and every later
#      step reuses that frozen string. Nothing re-evaluates `now() - interval`,
#      so the count, the export and the delete cannot drift apart across the
#      minutes a large run takes.
#   2. The tenant scope is chosen by an explicit flag, never inferred. There is
#      no code path from an unset or empty tenant id into an unscoped delete:
#      the scopes are separate values of $MODE, and the per-tenant one aborts
#      before any other query if the slug does not resolve.
#   3. Every archive filename carries the scope, a UTC timestamp and the pid,
#      and the script refuses to write over a file that already exists -- two
#      tenants, or two runs, on the same day cannot silently truncate each
#      other's only copy.
#   4. curl runs with --fail, so an auth failure or proxy error cannot land an
#      error document on disk as if it were the archive. Each archive is then
#      re-read: it must parse as a JSON array, hold exactly as many rows as the
#      database counts for the identical window, contain no row outside that
#      window, and carry exactly the row ids the delete is about to remove.
#      That last check is the only one that separates a correct archive from a
#      same-sized, same-era slice of another tenant's history.
#   5. The delete reuses the same predicate the count used -- one string, two
#      uses -- and runs only after every window passed every check above.
#   6. Nothing this script writes is world-readable; see the umask below.
#
# Connection: the bundled Postgres via `docker compose exec db` by default, or
# any external/managed Postgres via --db-url or the standard PG* environment
# variables. The credential must be able to see and modify rows across every
# tenant; the app's least-privilege runtime login deliberately cannot. See
# RUNBOOK.md §8.
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Timestamps are exchanged with both Postgres and the export API in one
# canonical shape: UTC, microsecond precision, `Z` suffix. Postgres round-trips
# it exactly (timestamptz resolution is microseconds) and Pydantic parses it,
# so a window boundary means the same instant on both sides.
TS_FORMAT='YYYY-MM-DD"T"HH24:MI:SS.US"Z"'

# One definition: the help text, the comparison below, and RUNBOOK.md §8 all
# have to agree, because an operator copy-pastes it.
SINGLE_TENANT_PHRASE="yes, this deployment has no per-tenant host routing"

# fix(#1248): an archive is a verbatim dump of usernames, IP addresses and
# activity for a whole retention window, and the id lists below are audit-log
# primary keys. Under the usual umask 022 `curl -o` creates its output 0644,
# readable by every local account on the host. Setting the umask up here rather
# than chmod-ing after the fact means no file this script writes is ever
# world-readable, not even for the moment between creation and a chmod.
umask 077

# Scratch space for the archive/database id lists compared in export_window.
# Removed on every exit path, including each `die`.
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

say() { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

need_command() {
    command -v "$1" >/dev/null 2>&1 || die "'$1' is required but not installed."
}

usage() {
    cat <<EOF
Usage: $SCRIPT_NAME --api-url URL (--days N | --cutoff TS)
                    (--tenant-slug SLUG | --confirm-single-tenant PHRASE) [options]

Exports every catalog.audit_logs row at or before the cutoff, verifies the
archive, then deletes exactly that window.

Required:
  --api-url URL     Base API URL for the export endpoint, e.g.
                    https://geolens.example.com/api . On a deployment with
                    per-tenant host routing this must be the host belonging to
                    --tenant-slug: the export is scoped by host and there is no
                    cross-tenant export call.
  --days N          Cutoff is N days before now, evaluated once in the database.
  --cutoff TS       Explicit cutoff instead of --days, as an ISO 8601 timestamp
                    Postgres accepts (e.g. 2026-01-31T00:00:00Z).

Scope -- choose exactly one. There is no default and no fallback between them:
  --tenant-slug SLUG
                    Per-tenant host routing. The slug is resolved to a tenant id
                    and the run aborts if it resolves to nothing.
  --confirm-single-tenant PHRASE
                    Unscoped: touches every row before the cutoff regardless of
                    tenant. PHRASE must be exactly
                      $SINGLE_TENANT_PHRASE
                    typed by an operator who has personally confirmed this
                    deployment has no per-tenant host routing. No config value
                    is consulted.

Options:
  --archive-dir DIR Where archives are written (default: ./audit-archives).
  --db-url URL      Connect to an external/managed Postgres with this libpq URL
                    instead of the bundled db container. A SQLAlchemy driver
                    suffix (postgresql+asyncpg://) is stripped automatically.
                    A password in the URL is moved out of psql's command line,
                    but it is still visible in THIS script's own command line;
                    prefer GEOLENS_RETENTION_DB_URL or PGPASSWORD.
  --batch-size N    Rows per delete statement (default: 5000).
  --max-rows N      Rows per export call (default: 100000, the endpoint's cap).
                    Windows larger than this are split automatically.
  --dry-run         Archive and verify, then stop without deleting.
  --vacuum          Run VACUUM (ANALYZE) catalog.audit_logs after the delete.
  -h, --help        Show this help.

Environment:
  ADMIN_TOKEN       Required. Bearer token for the export endpoint.
  GEOLENS_RETENTION_DB_URL
                    Same as --db-url, but never appears in any command line.
                    Prefer it when the URL carries a password.
  PGHOST PGPORT PGUSER PGDATABASE PGPASSWORD PGSERVICE
                    Used when no URL is given; setting PGHOST or PGSERVICE is
                    what selects the direct-connection mode.
  POSTGRES_USER POSTGRES_DB
                    Used for the bundled \`docker compose exec db\` path, read
                    from .env like the other scripts in this directory.

No row is deleted unless every archive for the window passed every check.
EOF
}

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------

API_URL=""
DAYS=""
CUTOFF_ARG=""
TENANT_SLUG=""
CONFIRM_PHRASE=""
ARCHIVE_DIR="./audit-archives"
DB_URL=""
BATCH_SIZE=5000
MAX_ROWS=100000
DRY_RUN=0
RUN_VACUUM=0

# A flag whose value is missing must say so, not fall off the end of "$@" and
# fail inside `shift 2` with an unrelated message.
require_value() {
    if [ "$2" -lt 2 ]; then
        die "$1 requires a value."
    fi
}

while [ $# -gt 0 ]; do
    case "$1" in
        --api-url) require_value "$1" $#; API_URL="$2"; shift 2 ;;
        --days) require_value "$1" $#; DAYS="$2"; shift 2 ;;
        --cutoff) require_value "$1" $#; CUTOFF_ARG="$2"; shift 2 ;;
        --tenant-slug) require_value "$1" $#; TENANT_SLUG="$2"; shift 2 ;;
        --confirm-single-tenant) require_value "$1" $#; CONFIRM_PHRASE="$2"; shift 2 ;;
        --archive-dir) require_value "$1" $#; ARCHIVE_DIR="$2"; shift 2 ;;
        --db-url) require_value "$1" $#; DB_URL="$2"; shift 2 ;;
        --batch-size) require_value "$1" $#; BATCH_SIZE="$2"; shift 2 ;;
        --max-rows) require_value "$1" $#; MAX_ROWS="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        --vacuum) RUN_VACUUM=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "unknown argument: $1" ;;
    esac
done

[ -n "$API_URL" ] || { usage >&2; die "--api-url is required."; }
[ -n "${ADMIN_TOKEN:-}" ] || die "ADMIN_TOKEN is not set; the export endpoint needs a bearer token."

if [ -n "$DAYS" ] && [ -n "$CUTOFF_ARG" ]; then
    die "--days and --cutoff are mutually exclusive; pick one boundary."
fi
if [ -z "$DAYS" ] && [ -z "$CUTOFF_ARG" ]; then
    usage >&2
    die "one of --days or --cutoff is required."
fi
if [ -n "$DAYS" ]; then
    case "$DAYS" in
        ''|*[!0-9]*) die "--days must be a whole number of days, got '$DAYS'." ;;
    esac
    [ "$DAYS" -ge 1 ] || die "--days must be at least 1."
fi
case "$BATCH_SIZE" in ''|*[!0-9]*) die "--batch-size must be a positive integer." ;; esac
[ "$BATCH_SIZE" -ge 1 ] || die "--batch-size must be at least 1."
case "$MAX_ROWS" in ''|*[!0-9]*) die "--max-rows must be a positive integer." ;; esac
if [ "$MAX_ROWS" -lt 1 ] || [ "$MAX_ROWS" -gt 100000 ]; then
    die "--max-rows must be between 1 and 100000 (the export endpoint's own cap)."
fi

# The scope is a choice between two explicit modes. An empty --tenant-slug is
# not "probably single-tenant": a mistyped slug or a failed lookup must never
# fall through to an unscoped, cross-tenant delete, so neither branch can be
# reached by leaving a variable unset.
if [ -n "$TENANT_SLUG" ] && [ -n "$CONFIRM_PHRASE" ]; then
    die "--tenant-slug and --confirm-single-tenant are mutually exclusive."
fi
if [ -n "$TENANT_SLUG" ]; then
    MODE="tenant"
elif [ -n "$CONFIRM_PHRASE" ]; then
    MODE="single"
    if [ "$CONFIRM_PHRASE" != "$SINGLE_TENANT_PHRASE" ]; then
        die "refusing to run unscoped: --confirm-single-tenant must be exactly
  $SINGLE_TENANT_PHRASE
This mode deletes every row before the cutoff with no tenant scoping. On a
deployment with per-tenant host routing that removes every other tenant's audit
history, which the host-scoped export never captured -- permanent loss with no
archive. The phrase is not read from any config file precisely because a
config-derived signal can be absent, stale, or injected by an orchestrator in a
way this script cannot detect."
    fi
else
    usage >&2
    die "one of --tenant-slug or --confirm-single-tenant is required; this script does not detect your deployment's tenancy mode."
fi

need_command psql
need_command curl
need_command jq

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
#
# Three paths, checked in order. The first two reach a managed or external
# Postgres directly; only the last needs a local db container.
if [ -n "$DB_URL" ] || [ -n "${GEOLENS_RETENTION_DB_URL:-}" ]; then
    if [ -n "$DB_URL" ]; then
        _url_in="$DB_URL"
        CONN_DESC="--db-url"
    else
        _url_in="$GEOLENS_RETENTION_DB_URL"
        CONN_DESC="GEOLENS_RETENTION_DB_URL"
    fi

    # libpq's URI parser accepts only postgresql:// and postgres://. A
    # privileged credential copied out of a SQLAlchemy config carries a driver
    # suffix, which libpq rejects outright.
    PG_URI="$(printf '%s' "$_url_in" | sed -E 's#^postgresql\+[A-Za-z0-9_]+://#postgresql://#')"

    # fix(#1248): a password in the URI must not reach psql's argv. Command
    # lines are world-readable (`ps`, /proc/<pid>/cmdline), so a URI handed
    # straight to psql publishes the BYPASSRLS credential to every local
    # account for the life of each query. Environment is the carrier instead:
    # /proc/<pid>/environ is owner-only. The rest of the URI stays in argv,
    # which keeps `ps` useful for debugging and leaks nothing.
    #
    # Split scheme://[userinfo@]authority[/path][?params] by hand rather than
    # with a regex, because the parts are positional: userinfo ends at the LAST
    # '@' (a password may contain an encoded one), and the password starts at
    # the FIRST ':' of the userinfo.
    _scheme="${PG_URI%%://*}://"
    _after_scheme="${PG_URI#*://}"
    _authority="${_after_scheme%%[/?]*}"
    _uri_rest="${_after_scheme:${#_authority}}"
    case "$_authority" in
        *@*) _userinfo="${_authority%@*}"; _hostpart="${_authority##*@}" ;;
        *)   _userinfo=""; _hostpart="$_authority" ;;
    esac
    case "$_userinfo" in
        *:*) _uri_user="${_userinfo%%:*}"; _pw_enc="${_userinfo#*:}" ;;
        *)   _uri_user="$_userinfo"; _pw_enc="" ;;
    esac

    if [ -n "$_pw_enc" ]; then
        # The URI form percent-encodes; PGPASSWORD wants the raw bytes. Decode
        # by turning every %XX into \xXX and letting bash's printf %b do it.
        # That is only sound for a well-formed encoding, so require one rather
        # than silently mangling: a stray '%' would otherwise become a bogus
        # \x escape, and a literal backslash would be interpreted rather than
        # passed through.
        if ! printf '%s' "$_pw_enc" | grep -qE '^([^%\]|%[0-9A-Fa-f][0-9A-Fa-f])*$'; then
            die "the password in $CONN_DESC is not valid percent-encoding, so it cannot be moved out of the psql command line safely.
Pass the URL without a password and put the password in PGPASSWORD (raw, not percent-encoded) instead."
        fi
        # A decoded NUL or newline cannot survive a shell variable or a psql
        # invocation intact, and command substitution would silently eat a
        # trailing newline. Refuse rather than hand over a truncated password.
        if printf '%s' "$_pw_enc" | grep -qiE '%0[0ad]'; then
            die "the password in $CONN_DESC contains an encoded NUL, newline or carriage return, which cannot be passed through the environment intact.
Pass the URL without a password and put the password in PGPASSWORD instead."
        fi
        PGPASSWORD="$(printf '%b' "${_pw_enc//%/\\x}")"
        export PGPASSWORD

        # Rebuild without the password. Dropping the '@' too when there is no
        # user keeps `postgresql://:pw@host/db` from becoming `postgresql://@host/db`.
        if [ -n "$_uri_user" ]; then
            PG_URI="${_scheme}${_uri_user}@${_hostpart}${_uri_rest}"
        else
            PG_URI="${_scheme}${_hostpart}${_uri_rest}"
        fi

        if [ "$CONN_DESC" = "--db-url" ]; then
            # Honest about the half this script cannot fix: its OWN argv still
            # holds whatever was typed, for the whole run, which is longer than
            # any psql child lives.
            warn "the password given to --db-url is visible in this script's own command line for the duration of the run.
It has been kept out of every psql command line, but to keep it out of \`ps\` entirely, pass the URL
without a password and set PGPASSWORD, or put the whole URL in GEOLENS_RETENTION_DB_URL."
        fi
    fi

    PSQL=(psql "$PG_URI")
elif [ -n "${PGHOST:-}" ] || [ -n "${PGSERVICE:-}" ]; then
    PSQL=(psql)
    CONN_DESC="PG* environment variables"
else
    need_command docker
    if [ -f "$PROJECT_ROOT/.env" ]; then
        set -a
        # shellcheck source=/dev/null
        . "$PROJECT_ROOT/.env"
        set +a
    fi
    PSQL=(docker compose -f "$PROJECT_ROOT/${COMPOSE_FILE:-docker-compose.yml}" exec -T db
          psql -U "${POSTGRES_USER:-geolens}" -d "${POSTGRES_DB:-geolens}")
    CONN_DESC="bundled db container"
fi

# Every query goes through here. $1 is the SQL; anything after it is passed to
# psql (in practice -v name=value bindings).
#
# The SQL arrives on stdin, NOT via -c. psql performs :name / :'name'
# substitution only on input it lexes itself, which means files and stdin --
# a -c string is handed to the server verbatim and every binding silently
# survives into the query text as a syntax error at best. Passing it here, in
# the one place every query goes through, is what keeps that from having to be
# remembered at each call site.
#
# -X ignores ~/.psqlrc, whose output settings would otherwise break -tA
# parsing; ON_ERROR_STOP turns a failed statement into a non-zero exit instead
# of a silently empty result; -tA gives one bare value per line.
psql_value() {
    local sql="$1"
    shift
    # fix(#1248): `SET row_security = off` on EVERY connection, not once at
    # startup -- each call here is its own psql process and its own session, so
    # a one-time SET elsewhere would not survive to the query that matters.
    #
    # It is the RLS bypass check, expressed where it cannot be skipped. For a
    # session that can bypass row-level security (superuser, BYPASSRLS, or the
    # table owner without FORCE) it is a no-op. For anything else -- notably the
    # app's own least-privilege runtime login -- any query touching an RLS table
    # then fails with "query would be affected by row-level security policy",
    # which ON_ERROR_STOP turns into a non-zero exit. Without it that credential
    # reads through the tenant_isolation policy on catalog.audit_logs, sees zero
    # rows, and the run reports "nothing to archive or delete" and exits 0: a
    # silent no-op that looks exactly like a correctly-empty window.
    #
    # -q is load-bearing here and not cosmetic. SET emits a "SET" command tag on
    # stdout, which under -tA would be parsed as the first value of every query;
    # -q suppresses it. Measured: `-X -q -tA` returns "42\n" with or without the
    # SET, while dropping -q returns "SET\n42\n".
    printf 'SET row_security = off;\n%s\n' "$sql" \
        | "${PSQL[@]}" -X -q -v ON_ERROR_STOP=1 -tA "$@"
}

# ---------------------------------------------------------------------------
# Scope predicate: ONE definition, used by the count, the window search and the
# delete. They cannot drift, because there is only one string.
# ---------------------------------------------------------------------------
if [ "$MODE" = "tenant" ]; then
    SCOPE_SQL="tenant_id = :'tenant_id'::uuid"
else
    # Unscoped by explicit confirmation. Deliberately not `tenant_id IS NULL`:
    # the export endpoint returns every row the host can see, so a narrower
    # delete predicate here would leave behind rows the archive claims to cover.
    SCOPE_SQL="TRUE"
fi

# Both bounds inclusive, matching the export endpoint's own filters
# (created_at >= date_from AND created_at <= date_to). Using < anywhere would
# let a row landing exactly on a boundary be counted by one step and missed by
# another -- at the export cap, that boundary row can displace an older in-range
# row out of the archive while the delete still removes it.
#
# Rows are only ever inserted with created_at = now(), so a window ending in the
# past is immutable for the length of the run: nothing new can appear inside it
# between the count and the delete. That is what lets a count taken now still
# describe the rows deleted later.
window_predicate() {
    # $1 = lower-bound expression, or empty for no lower bound. $2 = upper bound.
    if [ -n "$1" ]; then
        printf 'created_at >= %s AND created_at <= %s AND %s' "$1" "$2" "$SCOPE_SQL"
    else
        printf 'created_at <= %s AND %s' "$2" "$SCOPE_SQL"
    fi
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

say "Connecting via $CONN_DESC ..."
# Connectivity and "does this table exist" only. The credential's ability to
# see past row-level security is NOT established here -- a LIMIT 0 succeeds for
# a session that RLS would filter to nothing. That check lives in psql_value,
# on every query, so a credential that cannot bypass RLS fails loudly on the
# first real statement instead of quietly counting zero rows.
psql_value "SELECT 1 FROM catalog.audit_logs LIMIT 0" >/dev/null \
    || die "cannot read catalog.audit_logs through $CONN_DESC.
Check the connection, and that the credential is a privileged/migrator-class
login. If the failure mentions row-level security, that is this script
refusing to run as a credential that RLS would filter: catalog.audit_logs
carries the tenant_isolation policy (migration 0022), and reading through it
would silently do nothing instead of the documented thing. Use the same
privileged credential RUNBOOK.md §2 calls out for schema changes, not the
steady-state runtime login your deployment authenticates with day to day."

# The cutoff is evaluated once, here, and never again. Every later step is
# handed this exact string.
if [ -n "$CUTOFF_ARG" ]; then
    CUTOFF="$(psql_value \
        "SELECT to_char((:'c')::timestamptz AT TIME ZONE 'UTC', '$TS_FORMAT')" \
        -v c="$CUTOFF_ARG")" \
        || die "--cutoff '$CUTOFF_ARG' is not a timestamp Postgres accepts."
else
    CUTOFF="$(psql_value \
        "SELECT to_char((now() - (:'d' || ' days')::interval) AT TIME ZONE 'UTC', '$TS_FORMAT')" \
        -v d="$DAYS")"
fi
[ -n "$CUTOFF" ] || die "failed to resolve the retention cutoff."
say "Retention cutoff (frozen for this run): $CUTOFF"

# Resolve the tenant before anything else touches the table. A slug that
# resolves to nothing ends the run here, so no later step can ever see an empty
# tenant id.
TENANT_ID=""
if [ "$MODE" = "tenant" ]; then
    TENANT_ID="$(psql_value \
        "SELECT id FROM catalog.tenants WHERE slug = :'slug'" \
        -v slug="$TENANT_SLUG")"
    if [ -z "$TENANT_ID" ]; then
        die "no tenant found for slug '$TENANT_SLUG' -- aborting rather than falling through to an unscoped, all-tenants run."
    fi
    # Belt and braces: the lookup can only return a uuid, but pinning the shape
    # here means no future edit can reach the ::uuid cast with an empty or
    # malformed value and get a cast error instead of this message.
    _hex4='[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]'
    case "$TENANT_ID" in
        ${_hex4}${_hex4}-${_hex4}-${_hex4}-${_hex4}-${_hex4}${_hex4}${_hex4}) ;;
        *) die "tenant lookup for '$TENANT_SLUG' returned '$TENANT_ID', which is not a uuid." ;;
    esac
    say "Scope: tenant '$TENANT_SLUG' ($TENANT_ID)"
    SCOPE_LABEL="$TENANT_SLUG"
else
    say "Scope: unscoped, by explicit operator confirmation (single-tenant deployment)"
    SCOPE_LABEL="single-tenant"
fi

# psql refuses a query that references an unset variable, so both are always
# bound; the single-tenant predicate simply never mentions :'tenant_id'.
PSQL_VARS=(-v "cutoff=$CUTOFF" -v "tenant_id=$TENANT_ID")

TOTAL_IN_WINDOW="$(psql_value \
    "SELECT count(*) FROM catalog.audit_logs WHERE $(window_predicate '' ":'cutoff'::timestamptz")" \
    "${PSQL_VARS[@]}")"
say "Rows at or before the cutoff in scope: $TOTAL_IN_WINDOW"

if [ "$TOTAL_IN_WINDOW" -eq 0 ]; then
    say "Nothing to archive or delete. Done."
    exit 0
fi

# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------

# 0700 when this script creates it; an existing directory keeps whatever the
# operator gave it. See the umask near the top of the file.
mkdir -p "$ARCHIVE_DIR"

# Unique per scope AND per run. Two tenants archived on the same day, or the
# same tenant archived twice, would otherwise write the same filename and the
# second curl -o would truncate the first archive -- possibly after those rows
# were already deleted. The refusal in export_window makes even a same-second
# collision impossible rather than merely unlikely.
SAFE_LABEL="$(printf '%s' "$SCOPE_LABEL" | tr -c 'A-Za-z0-9._-' '-')"
ARCHIVE_TAG="${SAFE_LABEL}-$(date -u +%Y%m%dT%H%M%SZ)-$$"

# fix(#1248): the bearer token goes to curl in a file, not on its command line.
# `-H "Authorization: Bearer $ADMIN_TOKEN"` publishes an admin credential to
# every local account via `ps` for as long as the export streams, which on a
# 100,000-row window is not brief. curl's `-H @file` form reads headers from a
# file instead; the umask at the top of this script makes it 0600 inside a 0700
# directory, and the EXIT trap removes it.
AUTH_HEADER_FILE="$WORK_DIR/auth-header"
printf 'Authorization: Bearer %s\n' "$ADMIN_TOKEN" > "$AUTH_HEADER_FILE"

# Sum over every exported window. Adjacent windows share their boundary instant
# (both bounds are inclusive), so a row on a boundary is archived twice and the
# sum is >= the window total, never <. Duplicating an archive entry is harmless;
# offsetting a bound by an epsilon to avoid it would silently drop the boundary
# row from every export instead.
ARCHIVED_TOTAL=0
WINDOW_INDEX=0

export_window() {
    local window_from="$1"
    local window_to="$2"
    local expected="$3"
    local stamp out got archive_ids db_ids

    WINDOW_INDEX=$((WINDOW_INDEX + 1))
    stamp="$(printf '%s' "$window_from" | tr -c 'A-Za-z0-9' '-')"
    out="${ARCHIVE_DIR}/audit-archive-${ARCHIVE_TAG}-$(printf '%03d' "$WINDOW_INDEX")-${stamp}.json"

    if [ -e "$out" ]; then
        die "refusing to overwrite an existing archive: $out"
    fi

    say "  window $WINDOW_INDEX: $window_from .. $window_to ($expected rows)"

    # --fail is not optional. Without it an expired token, a wrong host, or any
    # other 4xx/5xx still exits 0 and writes the error body (e.g.
    # {"detail":"Not authenticated"}) to the output file as if it were the
    # archive, and the delete would then run against a window that was never
    # exported. --fail makes curl exit non-zero and discard that body.
    curl -sS --fail \
        -H "@$AUTH_HEADER_FILE" \
        "${API_URL%/}/admin/audit-logs/export/json?date_from=${window_from}&date_to=${window_to}&max_rows=${MAX_ROWS}" \
        -o "$out" \
        || die "export request failed for $window_from .. $window_to -- nothing has been deleted."

    # A 200 with an unexpected body (a proxy error page, a truncated stream)
    # gets past --fail. jq has to parse the whole file to answer this, so a
    # truncated download fails here instead of reporting a plausible count.
    jq -e 'type == "array"' "$out" >/dev/null \
        || die "$out is not a JSON array -- nothing has been deleted."

    got="$(jq 'length' "$out")"
    if [ "$got" != "$expected" ]; then
        die "archive row count mismatch for $window_from .. $window_to: the database counts $expected, $out holds $got. Nothing has been deleted."
    fi

    # Catches an archive that is the right SIZE but holds the wrong ROWS. The
    # export is scoped by host, so a wrong --api-url, or the wrong tenant's
    # host, can return a same-sized slice of somebody else's history.
    if [ "$got" -gt 0 ]; then
        jq -e 'all(.[]; .timestamp != null and (.timestamp | test("(Z|\\+00:00)$")))' "$out" >/dev/null \
            || die "$out contains a row whose timestamp is missing or is not UTC, so it cannot be checked against the window. Nothing has been deleted."
        jq -e --arg lo "$window_from" --arg hi "$window_to" \
            'all(.[]; .timestamp[0:19] >= $lo[0:19] and .timestamp[0:19] <= $hi[0:19])' "$out" >/dev/null \
            || die "$out contains a row outside $window_from .. $window_to. Nothing has been deleted."

        # fix(#1248): identity, not size. Pairing --tenant-slug with the wrong
        # tenant's API host returns that tenant's rows, and when both tenants
        # have the same number of rows in the window every check above passes:
        # the count matches, and the other tenant's timestamps legitimately
        # fall inside the same range. Comparing the archive's row ids against
        # the ids the delete predicate selects is what separates "archived the
        # rows I am about to delete" from "archived somebody else's".
        jq -e 'all(.[]; (.id? // "") != "")' "$out" >/dev/null \
            || die "$out has a row with no \"id\". This script requires an API that exports the audit-log id, which ships alongside it -- the server is older than the script, so upgrade the deployment rather than working around this. Nothing has been deleted."

        archive_ids="$WORK_DIR/archive-ids"
        db_ids="$WORK_DIR/db-ids"
        jq -r '.[].id' "$out" | LC_ALL=C sort > "$archive_ids"
        psql_value \
            "SELECT id FROM catalog.audit_logs
             WHERE $(window_predicate ":'wf'::timestamptz" ":'wt'::timestamptz")" \
            "${PSQL_VARS[@]}" -v "wf=$window_from" -v "wt=$window_to" \
            | LC_ALL=C sort > "$db_ids"
        # cmp, not a count: this is multiset equality, so a duplicated id on
        # one side and a missing one on the other cannot cancel out.
        cmp -s "$archive_ids" "$db_ids" \
            || die "$out does not hold the rows this window would delete: $(LC_ALL=C comm -13 "$archive_ids" "$db_ids" | wc -l | tr -d ' ') row(s) in the database are missing from the archive and $(LC_ALL=C comm -23 "$archive_ids" "$db_ids" | wc -l | tr -d ' ') row(s) in the archive are not in the window. Check that --api-url points at the host for this tenant. Nothing has been deleted."
    fi

    ARCHIVED_TOTAL=$((ARCHIVED_TOTAL + got))
    say "    archived $got rows -> $out"
}

say "Archiving to $ARCHIVE_DIR (tag $ARCHIVE_TAG) ..."

WINDOW_FROM="$(psql_value \
    "SELECT to_char(min(created_at) AT TIME ZONE 'UTC', '$TS_FORMAT')
     FROM catalog.audit_logs WHERE $(window_predicate '' ":'cutoff'::timestamptz")" \
    "${PSQL_VARS[@]}")"
[ -n "$WINDOW_FROM" ] || die "could not determine the oldest row in the window."

while :; do
    remaining="$(psql_value \
        "SELECT count(*) FROM catalog.audit_logs
         WHERE $(window_predicate ":'wf'::timestamptz" ":'cutoff'::timestamptz")" \
        "${PSQL_VARS[@]}" -v "wf=$WINDOW_FROM")"
    if [ "$remaining" -eq 0 ]; then
        break
    fi

    if [ "$remaining" -le "$MAX_ROWS" ]; then
        export_window "$WINDOW_FROM" "$CUTOFF" "$remaining"
        break
    fi

    # More rows than one export call can return. Narrowing date_to alone does
    # not help: the endpoint always returns the NEWEST rows in the range, so
    # repeating the same call returns the same slice forever. Split instead.
    #
    # Timestamps are not unique -- ties are ordinary on a busy instance -- so
    # the MAX_ROWS-th oldest row can land in the MIDDLE of a group of rows
    # sharing one instant. That is what makes this fiddly, and the four cases
    # below are the whole space. Let `sub` be the timestamp of the MAX_ROWS-th
    # oldest row in [wf, cutoff] and `expected` be count[wf, sub]:
    #
    #   (a) expected <= MAX_ROWS and sub > wf
    #       The cap landed cleanly between instants. Export [wf, sub]; the next
    #       window reopens at sub, duplicating that instant's rows into two
    #       archives by design.
    #   (b) expected <= MAX_ROWS and sub == wf
    #       The whole window is one instant, which fits. Normal at --max-rows 1,
    #       where the oldest row IS the boundary. Export [wf, wf] and step to
    #       the next distinct timestamp.
    #   (c) expected > MAX_ROWS and sub > wf
    #       The cap cut through the tie AT sub, and rows exist before it. The
    #       tie may well be exportable on its own, so back off to the last
    #       distinct timestamp before sub and export what precedes it. That is
    #       always <= MAX_ROWS: every row at or before the backed-off boundary
    #       is strictly older than sub, so every one of them was already inside
    #       the LIMIT that reached sub.
    #   (d) expected > MAX_ROWS and sub == wf
    #       One instant alone holds more rows than a single export call can
    #       return. No choice of bounds fixes that, so this is the only die.
    #
    # Loop variant, over all of them: every path exports a window whose
    # expected <= MAX_ROWS, then either strictly increases WINDOW_FROM or
    # breaks. The set of distinct created_at values at or before the cutoff is
    # finite, so the loop terminates. Nothing is deleted during the archive
    # phase, so a WINDOW_FROM that merely stayed put would spin forever.
    sub_window_to="$(psql_value \
        "SELECT to_char(max(created_at) AT TIME ZONE 'UTC', '$TS_FORMAT') FROM (
             SELECT created_at FROM catalog.audit_logs
             WHERE $(window_predicate ":'wf'::timestamptz" ":'cutoff'::timestamptz")
             ORDER BY created_at LIMIT $MAX_ROWS) t" \
        "${PSQL_VARS[@]}" -v "wf=$WINDOW_FROM")"
    [ -n "$sub_window_to" ] || die "could not compute a sub-window boundary."

    expected="$(psql_value \
        "SELECT count(*) FROM catalog.audit_logs
         WHERE $(window_predicate ":'wf'::timestamptz" ":'wt'::timestamptz")" \
        "${PSQL_VARS[@]}" -v "wf=$WINDOW_FROM" -v "wt=$sub_window_to")"

    if [ "$expected" -gt "$MAX_ROWS" ]; then
        if [ "$sub_window_to" = "$WINDOW_FROM" ]; then
            # Case (d).
            die "more than $MAX_ROWS rows share the instant $sub_window_to, so the window cannot be split small enough for one export call. Raise --max-rows (up to 100000), or archive that instant by hand. Nothing has been deleted."
        fi
        # Case (c). The strict `<` finds the neighbouring distinct timestamp;
        # it is not a window bound. Every bound this script exports or deletes
        # on is inclusive, and the only strict comparisons in the whole script
        # are this one and the `>` below, both of which locate an ADJACENT
        # distinct timestamp rather than delimiting a window. Keeping that
        # distinction is what stops either of them being "corrected" into an
        # inclusive form later: with `<=` here the back-off would return
        # sub_window_to unchanged and nothing would improve.
        sub_window_to="$(psql_value \
            "SELECT to_char(max(created_at) AT TIME ZONE 'UTC', '$TS_FORMAT')
             FROM catalog.audit_logs
             WHERE created_at >= :'wf'::timestamptz
               AND created_at < :'sub'::timestamptz
               AND $SCOPE_SQL" \
            "${PSQL_VARS[@]}" -v "wf=$WINDOW_FROM" -v "sub=$sub_window_to")"
        # WINDOW_FROM always names a real row (it is either the window's oldest
        # created_at, a previous boundary, or a previous next_from), and
        # sub > WINDOW_FROM here, so [wf, sub) is non-empty and this has a value.
        [ -n "$sub_window_to" ] || die "could not back off from a tied sub-window boundary."
        expected="$(psql_value \
            "SELECT count(*) FROM catalog.audit_logs
             WHERE $(window_predicate ":'wf'::timestamptz" ":'wt'::timestamptz")" \
            "${PSQL_VARS[@]}" -v "wf=$WINDOW_FROM" -v "wt=$sub_window_to")"
        # Unreachable given the argument in case (c) above; kept because the
        # cost is one comparison and the alternative to a loud failure here is
        # an export call silently truncated at the cap.
        if [ "$expected" -gt "$MAX_ROWS" ]; then
            die "internal error: backing off to $sub_window_to still selects $expected rows, above the $MAX_ROWS cap. Nothing has been deleted."
        fi
    fi

    export_window "$WINDOW_FROM" "$sub_window_to" "$expected"

    if [ "$sub_window_to" = "$WINDOW_FROM" ]; then
        # Cases (b) and (c)-collapsed-to-one-instant. Leaving WINDOW_FROM here
        # would never advance, so step to the next distinct timestamp. next_from
        # is the SMALLEST created_at greater than the instant just archived, so
        # no row exists between the two windows and they leave no gap. Widening
        # this `>` to `>=` returns WINDOW_FROM again and hangs.
        next_from="$(psql_value \
            "SELECT to_char(min(created_at) AT TIME ZONE 'UTC', '$TS_FORMAT')
             FROM catalog.audit_logs
             WHERE created_at > :'wf'::timestamptz
               AND created_at <= :'cutoff'::timestamptz
               AND $SCOPE_SQL" \
            "${PSQL_VARS[@]}" -v "wf=$WINDOW_FROM")"
        [ -n "$next_from" ] || break
        WINDOW_FROM="$next_from"
    else
        # Case (a). sub_window_to is a max over rows at or after WINDOW_FROM and
        # differs from it, so it is strictly greater.
        WINDOW_FROM="$sub_window_to"
    fi
done

if [ "$ARCHIVED_TOTAL" -lt "$TOTAL_IN_WINDOW" ]; then
    die "the archives hold $ARCHIVED_TOTAL rows but the window contains $TOTAL_IN_WINDOW. Nothing has been deleted."
fi
say "Archive verified: $ARCHIVED_TOTAL rows across $WINDOW_INDEX file(s) for a window of $TOTAL_IN_WINDOW."

if [ "$DRY_RUN" -eq 1 ]; then
    say "--dry-run: stopping before the delete. The archives above are keepers."
    exit 0
fi

# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------
#
# Batched: the only DELETE-supporting index is
# ix_catalog_audit_logs_created_action_resource (created_at DESC, action,
# resource_type), so an unbounded DELETE on a multi-million-row table holds
# locks and bloats the table. Run this in a low-traffic maintenance window.
#
# The loop lives in the shell rather than in a PL/pgSQL DO block on purpose.
# psql's :name substitution is skipped inside quoted SQL literals, and a
# dollar-quoted $$...$$ body is one -- parameters passed that way silently never
# reach the delete. Here every statement is a plain statement, psql binds and
# quotes :'cutoff' and :'tenant_id' itself, and the predicate is the same string
# the count above used.

say "Deleting in batches of $BATCH_SIZE ..."
DELETED_TOTAL=0
while :; do
    deleted="$(psql_value "
        WITH doomed AS (
            SELECT id FROM catalog.audit_logs
            WHERE $(window_predicate '' ":'cutoff'::timestamptz")
            ORDER BY created_at
            LIMIT $BATCH_SIZE
        ), removed AS (
            DELETE FROM catalog.audit_logs a USING doomed d WHERE a.id = d.id
            RETURNING 1
        )
        SELECT count(*) FROM removed" "${PSQL_VARS[@]}")"
    [ -n "$deleted" ] || die "a delete batch returned no row count; stopping with $DELETED_TOTAL rows deleted so far."
    if [ "$deleted" -eq 0 ]; then
        break
    fi
    DELETED_TOTAL=$((DELETED_TOTAL + deleted))
    say "  deleted $DELETED_TOTAL / $TOTAL_IN_WINDOW"
done

LEFTOVER="$(psql_value \
    "SELECT count(*) FROM catalog.audit_logs WHERE $(window_predicate '' ":'cutoff'::timestamptz")" \
    "${PSQL_VARS[@]}")"
[ "$LEFTOVER" -eq 0 ] \
    || die "$LEFTOVER rows at or before the cutoff remain in scope after the delete loop; investigate before re-running."

say "Deleted $DELETED_TOTAL rows. The archives are in $ARCHIVE_DIR -- keep them offsite (RUNBOOK.md §1)."

if [ "$RUN_VACUUM" -eq 1 ]; then
    say "Running VACUUM (ANALYZE) catalog.audit_logs ..."
    psql_value "VACUUM (ANALYZE) catalog.audit_logs" >/dev/null
fi
