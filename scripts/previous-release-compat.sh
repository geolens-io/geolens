#!/usr/bin/env bash
# Run a published release's api and worker against this tree's schema.
#
#   scripts/previous-release-compat.sh [VERSION ...]
#
# During a rolling upgrade the new release's migrations run while the previous
# release's api and worker still serve. For each VERSION (default: the newest
# release tag and the newest tag of the minor line before it) this script:
#
#   1. boots VERSION's published api and worker images with the db, migrate
#      and service wiring of docker-compose.prod.yml at tag vVERSION, and
#      ingests one GeoJSON dataset through that api;
#   2. upgrades the schema to this tree's heads with `uv run alembic` from
#      backend/, leaving VERSION's api and worker running;
#   3. with VERSION still serving, reads that dataset and its OGC items,
#      ingests a second file end to end and lists datasets.
#
# Any failure prints the HTTP status, the response body and the api and
# worker log tails, and the script exits non-zero after trying every version.
# Each version gets its own Compose project, removed with its volumes and
# locally built db image on exit.
#
# Needs docker with Compose v2, git with access to the release tags on
# COMPAT_REMOTE (default origin), uv, curl, openssl and python3. The images
# come from ghcr.io/geolens-io unless REGISTRY / IMAGE_OWNER say otherwise.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REMOTE="${COMPAT_REMOTE:-origin}"
WAIT_SECONDS="${COMPAT_WAIT_SECONDS:-300}"

log() { printf '==> %s\n' "$*"; }

release_tags() {
  git -C "${REPO_ROOT}" ls-remote --tags --refs "${REMOTE}" \
    | awk '{print $2}' \
    | grep -E '^refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$' \
    | sed 's#^refs/tags/v##' \
    | sort -t. -k1,1n -k2,2n -k3,3n
}

default_versions() {
  local tags newest line
  tags="$(release_tags)"
  [ -n "${tags}" ] || { echo "no vX.Y.Z tags found on ${REMOTE}" >&2; return 1; }
  newest="$(printf '%s\n' "${tags}" | tail -n 1)"
  line="${newest%.*}"
  printf '%s\n' "${newest}"
  printf '%s\n' "${tags}" | awk -F. -v line="${line}" '$1 "." $2 != line' | tail -n 1
}

if [ "$#" -ne 1 ]; then
  if [ "$#" -eq 0 ]; then
    versions="$(default_versions)"
    # shellcheck disable=SC2086 # one version per line, no spaces
    set -- ${versions}
  fi
  log "previous-release compat: versions $*"
  summary=""
  rc=0
  for version in "$@"; do
    if bash "${BASH_SOURCE[0]}" "${version}"; then
      summary="${summary}PASS ${version}"$'\n'
    else
      summary="${summary}FAIL ${version}"$'\n'
      rc=1
    fi
  done
  printf '\n==> previous-release compat summary (head %s)\n%s' \
    "$(git -C "${REPO_ROOT}" rev-parse --short HEAD)" "${summary}"
  exit "${rc}"
fi

VERSION="$1"
printf '%s' "${VERSION}" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' \
  || { echo "version must look like 1.2.3, got '${VERSION}'" >&2; exit 2; }
for tool in docker git uv curl openssl python3; do
  command -v "${tool}" >/dev/null 2>&1 || { echo "${tool} is required" >&2; exit 2; }
done
# The login and alembic steps reach the published ports on 127.0.0.1.
docker_host="${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)}"
case "${docker_host}" in
  "" | unix://* | npipe://*) ;;
  *) echo "needs a local Docker daemon, got ${docker_host}" >&2; exit 2 ;;
esac

WORK="$(mktemp -d "${TMPDIR:-/tmp}/geolens-compat.XXXXXX")"
RELEASE_DIR="${WORK}/release"
PROJECT="geolens-compat-$(printf '%s' "${VERSION}" | tr . -)-$$"
mkdir "${RELEASE_DIR}"

# Compose gets a clean environment: values such as a provider API key in the
# caller's shell would otherwise reach the containers through the compose
# file's pass-through `KEY:` entries.
compose() {
  local keep=(PATH="${PATH}" HOME="${HOME}")
  local name
  for name in DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_CERT_PATH DOCKER_TLS_VERIFY REGISTRY IMAGE_OWNER; do
    if [ -n "${!name:-}" ]; then keep+=("${name}=${!name}"); fi
  done
  env -i "${keep[@]}" docker compose -p "${PROJECT}" \
    --project-directory "${RELEASE_DIR}" -f "${RELEASE_DIR}/docker-compose.prod.yml" "$@"
}

cleanup() {
  local status=$?
  if [ -f "${RELEASE_DIR}/docker-compose.prod.yml" ]; then
    compose down -v --rmi local --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf "${WORK}"
  exit "${status}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

free_port() {
  python3 -I -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'
}

json_field() {
  python3 -I -c 'import json, sys; v = json.load(open(sys.argv[1])).get(sys.argv[2]); print("" if v is None else v)' "$1" "$2"
}

fail_with_evidence() {
  local what="$1" status="${2:-}" body="${3:-}"
  printf '\nFAIL %s: %s\n' "${VERSION}" "${what}" >&2
  [ -z "${status}" ] || printf 'HTTP status: %s\n' "${status}" >&2
  if [ -n "${body}" ] && [ -f "${body}" ]; then
    printf 'Response body:\n%s\n' "$(head -c 4000 "${body}")" >&2
  fi
  printf '\n--- api and worker log tail ---\n' >&2
  compose logs --no-color --tail=80 api worker >&2 2>&1 || true
  printf '\n--- last error lines in the api and worker logs ---\n' >&2
  compose logs --no-color api worker 2>&1 | grep -E '(Error|Exception)\b' | tail -n 20 >&2 || true
  exit 1
}

# request NAME METHOD PATH [curl args...]: stores the body in $BODY and fails
# with evidence unless the status is 2xx.
request() {
  local name="$1" method="$2" path="$3" status
  shift 3
  BODY="${WORK}/${name}.json"
  status="$(curl -sS -o "${BODY}" -w '%{http_code}' -X "${method}" \
    -H "Authorization: Bearer ${TOKEN}" "$@" "${API}${path}")" || status="curl-error"
  case "${status}" in
    2??) ;;
    *) fail_with_evidence "${method} ${path}" "${status}" "${BODY}" ;;
  esac
}

ingest() {
  local file="$1" title="$2" job_id state dataset_id deadline
  request "upload-${title}" POST /ingest/upload -F "file=@${file};type=application/geo+json"
  job_id="$(json_field "${BODY}" job_id)"
  [ -n "${job_id}" ] || fail_with_evidence "upload returned no job_id" "" "${BODY}"
  request "preview-${title}" POST "/ingest/preview/${job_id}"
  request "commit-${title}" POST "/ingest/commit/${job_id}" \
    -H 'Content-Type: application/json' --data "{\"title\": \"${title}\"}"
  deadline=$((SECONDS + 180))
  while :; do
    request "job-${title}" GET "/jobs/${job_id}"
    state="$(json_field "${BODY}" status)"
    dataset_id="$(json_field "${BODY}" dataset_id)"
    case "${state}" in
      complete | completed | succeeded)
        [ -n "${dataset_id}" ] || fail_with_evidence "job ${job_id} finished without a dataset" "" "${BODY}"
        INGESTED_ID="${dataset_id}"
        return 0
        ;;
      failed | error | cancelled)
        fail_with_evidence "ingest job ${job_id} ended ${state}" "" "${BODY}"
        ;;
    esac
    [ "${SECONDS}" -lt "${deadline}" ] || fail_with_evidence "ingest job ${job_id} still ${state} after 180s" "" "${BODY}"
    sleep 2
  done
}

write_geojson() {
  cat >"$1" <<EOF
{"type": "FeatureCollection", "features": [
  {"type": "Feature", "geometry": {"type": "Point", "coordinates": [$2, 40.1]}, "properties": {"name": "a", "value": 1}},
  {"type": "Feature", "geometry": {"type": "Point", "coordinates": [$2, 40.2]}, "properties": {"name": "b", "value": 2}}
]}
EOF
}

process_state() {
  local service id
  for service in api worker; do
    id="$(compose ps -q "${service}")"
    [ -n "${id}" ] || { printf '%s missing\n' "${service}"; continue; }
    docker inspect -f "${service} {{.Id}} {{.State.StartedAt}} restarts={{.RestartCount}} {{.State.Status}}" "${id}"
  done
}

db_revision() {
  compose exec -T db psql -U "${PG_USER}" -d "${PG_DB}" -tAc \
    "SELECT string_agg(version_num, ',') FROM catalog.alembic_version" | tr -d '[:space:]'
}

log "[${VERSION}] release files from v${VERSION}"
if ! git -C "${REPO_ROOT}" rev-parse -q --verify "refs/tags/v${VERSION}^{commit}" >/dev/null; then
  git -C "${REPO_ROOT}" fetch -q --depth=1 "${REMOTE}" "refs/tags/v${VERSION}:refs/tags/v${VERSION}"
fi
git -C "${REPO_ROOT}" archive "v${VERSION}" \
  docker-compose.prod.yml .env.example db scripts/init-db.sh scripts/lib \
  | tar -x -C "${RELEASE_DIR}"

PG_USER=geolens
PG_DB=geolens
PG_PASSWORD="$(openssl rand -hex 24)"
ADMIN_USER=compat-admin
ADMIN_PASSWORD="Compat-$(openssl rand -hex 12)-Pw"
DB_PORT="${COMPAT_DB_PORT:-$(free_port)}"
API_PORT="${COMPAT_API_PORT:-$(free_port)}"
API="http://127.0.0.1:${API_PORT}"
{
  grep -vE '^(POSTGRES_USER|POSTGRES_PASSWORD|POSTGRES_DB|JWT_SECRET_KEY|GEOLENS_ADMIN_USERNAME|GEOLENS_ADMIN_PASSWORD|DB_PORT|API_PORT|GEOLENS_VERSION|DATABASE_SSL_MODE|COMPOSE_FILE|COMPOSE_PROFILES)=' \
    "${RELEASE_DIR}/.env.example" || true
  printf 'POSTGRES_USER=%s\nPOSTGRES_DB=%s\nPOSTGRES_PASSWORD=%s\n' "${PG_USER}" "${PG_DB}" "${PG_PASSWORD}"
  printf 'JWT_SECRET_KEY=%s\n' "$(openssl rand -hex 32)"
  printf 'GEOLENS_ADMIN_USERNAME=%s\nGEOLENS_ADMIN_PASSWORD=%s\n' "${ADMIN_USER}" "${ADMIN_PASSWORD}"
  printf 'DB_PORT=%s\nAPI_PORT=%s\nGEOLENS_VERSION=%s\nDATABASE_SSL_MODE=disable\n' "${DB_PORT}" "${API_PORT}" "${VERSION}"
} >"${RELEASE_DIR}/.env"
chmod 600 "${RELEASE_DIR}/.env"

log "[${VERSION}] starting db, migrate, api and worker (project ${PROJECT}, api port ${API_PORT})"
compose pull -q migrate api worker
compose --progress quiet up -d --wait --wait-timeout "${WAIT_SECONDS}" db migrate api worker \
  || fail_with_evidence "the ${VERSION} stack did not become healthy"

deadline=$((SECONDS + WAIT_SECONDS))
TOKEN=""
while [ -z "${TOKEN}" ]; do
  if curl -fsS -o "${WORK}/login.json" -X POST "${API}/auth/login" \
    --data-urlencode "username=${ADMIN_USER}" --data-urlencode "password=${ADMIN_PASSWORD}" 2>/dev/null; then
    TOKEN="$(json_field "${WORK}/login.json" access_token)"
  fi
  if [ -z "${TOKEN}" ]; then
    [ "${SECONDS}" -lt "${deadline}" ] || fail_with_evidence "admin login never succeeded" "" "${WORK}/login.json"
    sleep 3
  fi
done

write_geojson "${WORK}/seed.geojson" -73.9
ingest "${WORK}/seed.geojson" compat-seed
SEED_ID="${INGESTED_ID}"
release_revision="$(db_revision)"
before="$(process_state)"
log "[${VERSION}] seeded dataset ${SEED_ID} at schema ${release_revision}"

log "[${VERSION}] upgrading the schema to this tree's heads while ${VERSION} serves"
(
  cd "${REPO_ROOT}/backend"
  export DATABASE_URL_OVERRIDE="postgresql+asyncpg://${PG_USER}:${PG_PASSWORD}@127.0.0.1:${DB_PORT}/${PG_DB}"
  export DATABASE_SSL_MODE=disable PGSSLMODE=disable PYTHONPATH=.
  export POSTGRES_USER="${PG_USER}" POSTGRES_PASSWORD="${PG_PASSWORD}" POSTGRES_DB="${PG_DB}"
  export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="${DB_PORT}"
  JWT_SECRET_KEY="$(openssl rand -hex 32)"
  export JWT_SECRET_KEY
  export GEOLENS_ADMIN_USERNAME="${ADMIN_USER}" GEOLENS_ADMIN_PASSWORD="${ADMIN_PASSWORD}"
  uv run --locked --no-dev alembic upgrade heads
) || fail_with_evidence "alembic upgrade heads failed against the ${VERSION} schema"
head_revision="$(db_revision)"
log "[${VERSION}] schema ${release_revision} -> ${head_revision}"

request dataset GET "/datasets/${SEED_ID}"
request items GET "/collections/${SEED_ID}/items?limit=2"
python3 -I -c 'import json, sys; sys.exit(len(json.load(open(sys.argv[1])).get("features") or []) != 2)' "${BODY}" \
  || fail_with_evidence "OGC items response does not hold the two seeded features" "" "${BODY}"
write_geojson "${WORK}/after.geojson" -74.0
ingest "${WORK}/after.geojson" compat-after-upgrade
AFTER_ID="${INGESTED_ID}"
request ingested-dataset GET "/datasets/${AFTER_ID}"
request list GET "/datasets/"
for id in "${SEED_ID}" "${AFTER_ID}"; do
  grep -q "${id}" "${BODY}" || fail_with_evidence "dataset list is missing ${id}" "" "${BODY}"
done

after="$(process_state)"
if [ "${before}" != "${after}" ]; then
  printf 'before:\n%s\nafter:\n%s\n' "${before}" "${after}" >&2
  fail_with_evidence "the ${VERSION} api or worker restarted during the run"
fi

printf 'PASS %s: api and worker %s served schema %s (upgraded from %s): dataset read, OGC items, ingest, list\n' \
  "${VERSION}" "${VERSION}" "${head_revision}" "${release_revision}"
