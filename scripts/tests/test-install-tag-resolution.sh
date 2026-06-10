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

# Deterministic git invocation: pin default branch + identity + disable commit/tag
# signing, so fixture creation does not depend on (or fail under) the runner's
# global git config (e.g. a global commit.gpgsign=true with no key).
g() {
  git -c init.defaultBranch=main -c user.email=ci@geolens.test -c user.name=ci \
      -c commit.gpgsign=false -c tag.gpgsign=false "$@"
}

# The real git binary, captured before any PATH shim is prepended (the atomicity
# case below runs the installer with a git wrapper that fails only `fetch`).
REAL_GIT="$(command -v git)"

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

# --- Remote C: a real release tag v1.2.0 plus a NESTED decoy tag
#     refs/tags/decoy/v9.9.99 whose basename (v9.9.99) sorts above the real
#     release. A correct resolver matches the full refs/tags/ ref and ignores it.
SRC3="$WORK/src3"
mkdir -p "$SRC3"
g init -q "$SRC3"
(
  cd "$SRC3" || exit 1
  seed_common
  printf 'REAL_REL\n' > marker.txt
  g add -A && g commit -qm c1
  g tag -a v1.2.0 -m 'release 1.2.0'
  printf 'DECOY\n' > marker.txt
  g add -A && g commit -qm c2
  g tag -a decoy/v9.9.99 -m 'nested decoy'   # refs/tags/decoy/v9.9.99
  g checkout -q main
)
DECOY="$WORK/decoy.git"
g clone -q --bare "$SRC3" "$DECOY" 2>/dev/null

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
expect_exit0() {  # assert a case completed cleanly (catches post-checkout regressions)
  if [ "$(cat "$WORK/run-$1/code.txt")" = "0" ]; then
    ok "$1 installer exits 0"
  else
    bad "$1 installer exit=$(cat "$WORK/run-$1/code.txt")"
  fi
}

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
expect_exit0 pin

# 3) Non-tag GEOLENS_REF must still track the branch (no regression).
run_installer branch "file://$REMOTE" feature-x
if [ "$(marker_of branch)" = "FEATURE_X" ]; then
  ok "GEOLENS_REF=<branch> still tracks the branch"
else
  bad "branch override installed '$(marker_of branch)' (expected FEATURE_X)"
fi
expect_exit0 branch

# 4) No release tags => default-branch fallback.
run_installer notags "file://$NOTAGS"
if [ "$(marker_of notags)" = "DEFAULT_BRANCH" ]; then
  ok "no-tags remote falls back to the default branch"
else
  bad "no-tags fallback installed '$(marker_of notags)' (expected DEFAULT_BRANCH)"
fi
expect_exit0 notags

# 5) ATOMICITY: a tag-path fetch failure must leave NO INSTALL_DIR behind, so a
#    re-run is not wedged (the tag checkout builds in a temp dir and only moves
#    into place on success). Inject the failure with a git wrapper that fails
#    only `fetch` (ls-remote classification still passes through to real git).
FAILBIN="$WORK/failbin"
mkdir -p "$FAILBIN"
printf '#!/bin/sh\nexit 0\n' > "$FAILBIN/docker"
chmod +x "$FAILBIN/docker"
{
  printf '#!/bin/sh\n'
  printf 'for a in "$@"; do\n'
  printf '  if [ "$a" = fetch ]; then echo "fatal: simulated fetch failure" >&2; exit 128; fi\n'
  printf 'done\n'
  printf 'exec %s "$@"\n' "$REAL_GIT"
} > "$FAILBIN/git"
chmod +x "$FAILBIN/git"
atomic_dir="$WORK/run-atomic"
mkdir -p "$atomic_dir"
( cd "$atomic_dir" \
  && env "PATH=$FAILBIN:$PATH" GEOLENS_REPO_URL="file://$REMOTE" GEOLENS_REF=v9.9.9 \
       GEOLENS_INSTALL_DIR="$atomic_dir/install" \
       GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin \
       sh "$INSTALL_SH" </dev/null > "$atomic_dir/out.txt" 2>&1 )
atomic_code=$?
if [ "$atomic_code" -ne 0 ] && [ ! -e "$atomic_dir/install" ]; then
  ok "failed tag fetch exits non-zero and leaves no INSTALL_DIR (atomic, re-runnable)"
else
  bad "fetch failure was not atomic (exit=$atomic_code, INSTALL_DIR exists=$([ -e "$atomic_dir/install" ] && echo yes || echo no))"
  sed 's/^/    # /' "$atomic_dir/out.txt"
fi

# 6) SLASH-TAG DECOY: a nested refs/tags/decoy/v9.9.99 must NOT outrank the real
#    top-level v1.2.0 release (basename matching would pick the decoy, mis-announce
#    it, then fail the fetch).
run_installer decoy "file://$DECOY"
if [ "$(marker_of decoy)" = "REAL_REL" ]; then
  ok "nested decoy tag is ignored; real top-level release is installed"
else
  bad "decoy test installed '$(marker_of decoy)' (expected REAL_REL)"
  sed 's/^/    # /' "$WORK/run-decoy/out.txt"
fi
if grep -q 'Installing release v1.2.0' "$WORK/run-decoy/out.txt"; then
  ok "decoy test announces the real release (v1.2.0), not the decoy"
else
  bad "decoy test announced the wrong release"
fi

# 7) FAIL-CLOSED: if the tag list cannot be queried for an explicit tag-shaped
#    GEOLENS_REF, the installer must FAIL — never silently fall back to the
#    shadowable `clone --branch`. Inject via a git wrapper that fails only
#    `ls-remote` (clone/fetch pass through), against Remote A where a v9.9.9
#    branch shadows the v9.9.9 tag: pre-fix code would clone the malicious branch.
NOLSBIN="$WORK/nolsbin"
mkdir -p "$NOLSBIN"
printf '#!/bin/sh\nexit 0\n' > "$NOLSBIN/docker"
chmod +x "$NOLSBIN/docker"
{
  printf '#!/bin/sh\n'
  printf 'for a in "$@"; do\n'
  printf '  if [ "$a" = ls-remote ]; then echo "fatal: simulated ls-remote failure" >&2; exit 128; fi\n'
  printf 'done\n'
  printf 'exec %s "$@"\n' "$REAL_GIT"
} > "$NOLSBIN/git"
chmod +x "$NOLSBIN/git"
fc_dir="$WORK/run-failclosed"
mkdir -p "$fc_dir"
( cd "$fc_dir" \
  && env "PATH=$NOLSBIN:$PATH" GEOLENS_REPO_URL="file://$REMOTE" GEOLENS_REF=v9.9.9 \
       GEOLENS_INSTALL_DIR="$fc_dir/install" \
       GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin \
       sh "$INSTALL_SH" </dev/null > "$fc_dir/out.txt" 2>&1 )
fc_code=$?
if [ "$fc_code" -ne 0 ] && [ ! -e "$fc_dir/install" ]; then
  ok "unqueryable remote with an explicit tag ref fails closed (no shadowable fallback)"
else
  bad "fail-closed not honored (exit=$fc_code, INSTALL_DIR exists=$([ -e "$fc_dir/install" ] && echo yes || echo no))"
  sed 's/^/    # /' "$fc_dir/out.txt"
fi

echo "1..$((PASS + FAIL))"
echo "# $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
