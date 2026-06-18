#!/bin/sh
# Consistency test for UPGRADING.md (UPG-03): the documented commands/paths must
# match the actual tooling (scripts/upgrade.sh, scripts/restore.sh, the compose
# files), and the doc must never tell anyone to `psql < dump` a -Fc custom-format
# dump. Pure text checks; no stack.
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DOC="$ROOT/UPGRADING.md"

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf 'ok %d - %s\n' "$((PASS + FAIL))" "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'not ok %d - %s\n' "$((PASS + FAIL))" "$1"; }

[ -f "$DOC" ] && ok "UPGRADING.md exists" || bad "UPGRADING.md missing"

# Referenced scripts must exist and be executable.
for s in scripts/upgrade.sh scripts/restore.sh scripts/backup-entrypoint.sh; do
  if grep -q "$s" "$DOC"; then
    if [ -x "$ROOT/$s" ]; then
      ok "doc references $s and it exists+executable"
    else
      bad "doc references $s but it is missing or not executable"
    fi
  fi
done

# Referenced compose files must exist.
for c in docker-compose.prod.yml docker-compose.yml; do
  if grep -q "$c" "$DOC"; then
    [ -f "$ROOT/$c" ] && ok "doc references $c and it exists" \
                      || bad "doc references $c but it is missing"
  fi
done

# upgrade.sh is the documented primary; the doc must call it out.
grep -q './scripts/upgrade.sh' "$DOC" \
  && ok "doc presents ./scripts/upgrade.sh as the primary path" \
  || bad "doc does not present ./scripts/upgrade.sh"

# restore.sh takes exactly one arg: <backup-file>. The doc must invoke it that way.
grep -Eq 'scripts/restore\.sh [^ ]+\.dump|scripts/restore\.sh backups' "$DOC" \
  && ok "doc invokes restore.sh with a dump-file argument" \
  || bad "doc does not show restore.sh <backup-file> usage"

# Rollback must explicitly state alembic downgrade is NOT supported.
grep -qi 'alembic downgrade.*not' "$DOC" \
  && ok "doc states alembic downgrade is NOT a supported rollback" \
  || bad "doc does not warn against alembic downgrade as rollback"

# HARD: never psql < a -Fc dump. restore.sh uses pg_restore; -Fc dumps are not
# plain SQL. Fail if any 'psql ... < ...dump' pattern appears.
if grep -Eiq 'psql[^\n]*<[^\n]*\.dump' "$DOC"; then
  bad "doc tells the user to 'psql < <dump>' a -Fc dump (WRONG — use pg_restore)"
else
  ok "doc never pipes a -Fc dump into psql"
fi

# The dump format the doc produces must be -Fc (matches restore.sh's pg_restore).
grep -q 'pg_dump' "$DOC" && grep -q -- '-Fc' "$DOC" \
  && ok "doc's pg_dump uses -Fc (custom format restore.sh expects)" \
  || bad "doc's backup command is not the -Fc custom format"

# restore.sh really uses pg_restore (sanity-check the claim the doc makes).
grep -q 'pg_restore' "$ROOT/scripts/restore.sh" \
  && ok "restore.sh uses pg_restore (consistent with doc)" \
  || bad "restore.sh does not use pg_restore — doc claim is wrong"

# upgrade.sh really writes to backups/pre-upgrade (the path the doc cites).
grep -q 'backups/pre-upgrade' "$ROOT/scripts/upgrade.sh" \
  && ok "upgrade.sh writes to backups/pre-upgrade (matches doc)" \
  || bad "upgrade.sh backup dir does not match the doc"

# README points at UPGRADING.md.
grep -q 'UPGRADING.md' "$ROOT/README.md" \
  && ok "README links to UPGRADING.md" \
  || bad "README does not link to UPGRADING.md"

# getgeolens.com cross-repo follow-up is flagged in the doc.
grep -qi 'getgeolens.com' "$DOC" \
  && ok "doc flags the getgeolens.com upgrade.mdx cross-repo follow-up" \
  || bad "doc does not flag the getgeolens.com follow-up"

echo "1..$((PASS + FAIL))"
echo "# $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
