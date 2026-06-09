#!/bin/sh
# Regression test for the installer release-tag checkout (scripts/install.sh).
#
# Guards the fix for the branch/tag shadowing vulnerability: `git clone --branch
# <name>` resolves <name> as a branch before a tag, so a remote branch named
# identically to a release tag could be built by fresh installs instead of the
# tag. The installer must check out release tags by their fully-qualified
# refs/tags/ ref, which a same-named branch cannot shadow.
#
# Pure shell + git: no Docker, no DB, no network (uses file:// remotes and a
# fake `docker` shim). Runnable locally and in CI.
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_SH="$SCRIPT_DIR/../install.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf 'ok %d - %s\n' "$((PASS + FAIL))" "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'not ok %d - %s\n' "$((PASS + FAIL))" "$1"; }

# Deterministic git invocation: pinned default branch + identity, so the test
# does not depend on the runner's global git config.
g() { git -c init.defaultBranch=main -c user.email=ci@geolens.test -c user.name=ci "$@"; }

# Fake `docker` so the installer's `docker compose version/up/ps` calls succeed
# instantly (empty `ps` output => no unhealthy services => health gate passes).
SHIM="$WORK/bin"
mkdir -p "$SHIM"
printf '#!/bin/sh\nexit 0\n' > "$SHIM/docker"
chmod +x "$SHIM/docker"

seed_common() {
  printf 'JWT_SECRET_KEY=\nDB_PORT=5434\nAPI_PORT=8001\nFRONTEND_PORT=8080\n' > .env.example
  printf 'services: {}\n' > docker-compose.yml
}

# --- Remote A: annotated release tag v9.9.9 (the real-world tag shape) shadowed
#     by a same-named malicious branch; plus a normal feature branch. ---
SRC="$WORK/src"
mkdir -p "$SRC"
g init -q "$SRC"
(
  cd "$SRC" || exit 1
  seed_common
  printf 'DEFAULT\n' > marker.txt
  g add -A && g commit -qm c1
  printf 'TAG_RELEASE\n' > marker.txt
  g add -A && g commit -qm c2
  g tag -a v9.9.9 -m 'release 9.9.9'   # annotated, like real GeoLens releases
  g tag -a v9.8.0 -m 'release 9.8.0' HEAD~1
  g checkout -q -b v9.9.9               # malicious branch shadowing the tag
  printf 'MALICIOUS_BRANCH\n' > marker.txt
  g add -A && g commit -qm c3
  g checkout -q -b feature-x main
  printf 'FEATURE_X\n' > marker.txt
  g add -A && g commit -qm c4
  g checkout -q main
)
REMOTE="$WORK/remote.git"
g clone -q --bare "$SRC" "$REMOTE" 2>/dev/null

# --- Remote B: no semver tags (exercises the default-branch fallback). ---
SRC2="$WORK/src2"
mkdir -p "$SRC2"
g init -q "$SRC2"
(
  cd "$SRC2" || exit 1
  seed_common
  printf 'DEFAULT_BRANCH\n' > marker.txt
  g add -A && g commit -qm only
)
NOTAGS="$WORK/notags.git"
g clone -q --bare "$SRC2" "$NOTAGS" 2>/dev/null

# Run the real installer non-interactively with the docker shim on PATH.
# $1 = case name, $2 = repo url, $3 = optional GEOLENS_REF
run_installer() {
  _name="$1"; _url="$2"; _ref="${3:-}"
  _dir="$WORK/run-$_name"
  mkdir -p "$_dir"
  if [ -n "$_ref" ]; then _refenv="GEOLENS_REF=$_ref"; else _refenv="GEOLENS_REF="; fi
  ( cd "$_dir" \
    && env "PATH=$SHIM:$PATH" "$_refenv" \
         GEOLENS_REPO_URL="$_url" \
         GEOLENS_INSTALL_DIR="$_dir/install" \
         GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin \
         sh "$INSTALL_SH" </dev/null > "$_dir/out.txt" 2>&1 )
  echo $? > "$_dir/code.txt"
}

marker_of() { cat "$WORK/run-$1/install/marker.txt" 2>/dev/null; }

# 1) PRIMARY GUARD: auto-resolve must check out the release TAG, never the
#    same-named shadow branch.
run_installer auto "file://$REMOTE"
if [ "$(marker_of auto)" = "TAG_RELEASE" ]; then
  ok "auto-resolve checks out the release tag, not the shadowing branch"
else
  bad "auto-resolve installed '$(marker_of auto)' (expected TAG_RELEASE)"
  sed 's/^/    # /' "$WORK/run-auto/out.txt"
fi
if [ "$(cat "$WORK/run-auto/code.txt")" = "0" ]; then
  ok "auto-resolve installer exits 0"
else
  bad "auto-resolve installer exit=$(cat "$WORK/run-auto/code.txt")"
fi
if grep -q 'Installing release v9.9.9' "$WORK/run-auto/out.txt"; then
  ok "auto-resolve announces the highest release tag (v9.9.9)"
else
  bad "auto-resolve did not announce 'Installing release v9.9.9'"
fi

# 2) Explicit tag pin must also take the shadow-safe path.
run_installer pin "file://$REMOTE" v9.9.9
if [ "$(marker_of pin)" = "TAG_RELEASE" ]; then
  ok "explicit GEOLENS_REF=<tag> checks out the tag (shadow-safe)"
else
  bad "tag pin installed '$(marker_of pin)' (expected TAG_RELEASE)"
fi

# 3) Non-tag GEOLENS_REF must still track the branch (no regression).
run_installer branch "file://$REMOTE" feature-x
if [ "$(marker_of branch)" = "FEATURE_X" ]; then
  ok "GEOLENS_REF=<branch> still tracks the branch"
else
  bad "branch override installed '$(marker_of branch)' (expected FEATURE_X)"
fi

# 4) No release tags => default-branch fallback.
run_installer notags "file://$NOTAGS"
if [ "$(marker_of notags)" = "DEFAULT_BRANCH" ]; then
  ok "no-tags remote falls back to the default branch"
else
  bad "no-tags fallback installed '$(marker_of notags)' (expected DEFAULT_BRANCH)"
fi

echo "1..$((PASS + FAIL))"
echo "# $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
