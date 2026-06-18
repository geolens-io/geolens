#!/bin/sh
# Regression test for the installer's newer-release detection (UPG-02,
# scripts/install.sh). Pure shell with stubbed docker/git on PATH; no real
# stack, no DB, no network.
#
# Asserts, for a RE-RUN of an existing install (current dir has .env):
#   - a NEWER remote tag  -> non-interactive notice naming the newer version
#                            ("Run './scripts/upgrade.sh' ...") and continues
#                            (does NOT exec upgrade.sh)
#   - the SAME remote tag -> no notice
#   - an OLDER remote tag -> no notice
#   - --upgrade with a newer tag -> exec's scripts/upgrade.sh <newer> (the
#                            stubbed upgrade.sh prints a sentinel and the
#                            installer does NOT continue to its own start)
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_SH="$SCRIPT_DIR/../install.sh"

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf 'ok %d - %s\n' "$((PASS + FAIL))" "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'not ok %d - %s\n' "$((PASS + FAIL))" "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM

# Shared stub bin. docker => no-op (health gate passes on empty `ps`). git is
# regenerated per-case so `ls-remote` returns the tag we want; everything else
# passes through to the real git (the installer also runs `git describe`).
REAL_GIT="$(command -v git)"
SHIM="$WORK/bin"
mkdir -p "$SHIM"
printf '#!/bin/sh\nexit 0\n' > "$SHIM/docker"
chmod +x "$SHIM/docker"

# Build a fake existing install dir: docker-compose.yml + .env.example so the
# installer takes the "Using current directory" path, and a .env with a pinned
# GEOLENS_VERSION so EXISTING_INSTALL=true and the version is readable.
make_install_dir() {
  _dir="$1"; _installed="$2"
  mkdir -p "$_dir"
  printf 'services: {}\n' > "$_dir/docker-compose.yml"
  printf 'JWT_SECRET_KEY=x\nDB_PORT=5434\nAPI_PORT=8001\nFRONTEND_PORT=8080\n' > "$_dir/.env.example"
  cat > "$_dir/.env" <<ENV
JWT_SECRET_KEY=already-set
POSTGRES_PASSWORD=already-set
GEOLENS_ADMIN_USERNAME=admin
GEOLENS_ADMIN_PASSWORD=admin
MINIO_ROOT_USER=x
MINIO_ROOT_PASSWORD=x
GEOLENS_VERSION=${_installed}
ENV
  # a stubbed scripts/upgrade.sh that prints a sentinel + its args so we can
  # detect whether the installer exec'd it.
  mkdir -p "$_dir/scripts"
  cat > "$_dir/scripts/upgrade.sh" <<'UPG'
#!/bin/sh
echo "UPGRADE_SH_INVOKED args=$*"
exit 0
UPG
  chmod +x "$_dir/scripts/upgrade.sh"
}

# git stub: ls-remote prints a single refs/tags/<latest> line; describe etc.
# pass through to real git so the installer's `git describe --exact-match` runs
# (it just fails cleanly outside a repo, which is fine — RELEASE_VERSION stays
# unset and we never reach the prebuilt-pull on these stubbed dirs).
make_git_stub() {
  _latest="$1"
  cat > "$SHIM/git" <<GIT
#!/bin/sh
if [ "\$1" = "ls-remote" ]; then
  printf 'deadbeef\trefs/tags/${_latest}\n'
  exit 0
fi
exec "$REAL_GIT" "\$@"
GIT
  chmod +x "$SHIM/git"
}

# Run the installer in an install dir. Non-interactive (stdin from /dev/null =>
# HAS_TTY false). $1=dir, rest=installer args.
run_install() {
  _dir="$1"; shift
  ( cd "$_dir" \
    && env "PATH=$SHIM:$PATH" GEOLENS_REPO_URL="file:///fake" \
         GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin \
         sh "$INSTALL_SH" "$@" </dev/null > "$_dir/out.txt" 2>&1 )
  echo $? > "$_dir/code.txt"
}

# --- CASE 1: newer tag -> notice, no exec of upgrade.sh ---------------------
D1="$WORK/newer"
make_install_dir "$D1" "1.2.3"
make_git_stub "v1.2.4"
run_install "$D1"
if grep -q "newer GeoLens release (v1.2.4)" "$D1/out.txt"; then
  ok "newer tag prints a notice naming v1.2.4"
else
  bad "newer tag did not print the expected notice"
  sed 's/^/    # /' "$D1/out.txt"
fi
if grep -q "scripts/upgrade.sh" "$D1/out.txt"; then
  ok "newer-tag notice points at scripts/upgrade.sh"
else
  bad "notice did not mention scripts/upgrade.sh"
fi
if ! grep -q "UPGRADE_SH_INVOKED" "$D1/out.txt"; then
  ok "non-interactive newer tag does NOT surprise-upgrade (upgrade.sh not exec'd)"
else
  bad "non-interactive run unexpectedly exec'd upgrade.sh"
fi

# --- CASE 2: same tag -> no notice ------------------------------------------
D2="$WORK/same"
make_install_dir "$D2" "1.2.4"
make_git_stub "v1.2.4"
run_install "$D2"
if ! grep -q "newer GeoLens release" "$D2/out.txt"; then
  ok "same tag prints no upgrade notice"
else
  bad "same tag wrongly printed an upgrade notice"
  sed 's/^/    # /' "$D2/out.txt"
fi

# --- CASE 3: older remote tag -> no notice ----------------------------------
D3="$WORK/older"
make_install_dir "$D3" "1.2.4"
make_git_stub "v1.2.0"
run_install "$D3"
if ! grep -q "newer GeoLens release" "$D3/out.txt"; then
  ok "older remote tag prints no upgrade notice"
else
  bad "older remote tag wrongly printed an upgrade notice"
  sed 's/^/    # /' "$D3/out.txt"
fi

# --- CASE 4: --upgrade with a newer tag -> exec upgrade.sh <newer> ----------
D4="$WORK/doupgrade"
make_install_dir "$D4" "1.2.3"
make_git_stub "v1.2.4"
run_install "$D4" --upgrade
if grep -q "UPGRADE_SH_INVOKED args=1.2.4" "$D4/out.txt"; then
  ok "--upgrade execs scripts/upgrade.sh with the newer version (1.2.4)"
else
  bad "--upgrade did not exec upgrade.sh with the right version"
  sed 's/^/    # /' "$D4/out.txt"
fi
# After exec, the installer must NOT continue to its own "Starting GeoLens".
if ! grep -q "Starting GeoLens" "$D4/out.txt"; then
  ok "--upgrade hands off (installer does not also start the old version)"
else
  bad "--upgrade did not hand off cleanly (installer continued)"
fi

echo "1..$((PASS + FAIL))"
echo "# $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
