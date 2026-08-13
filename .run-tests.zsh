#!/bin/zsh
set -e
cd "$(dirname "$0")/backend"
set -a; source ../.env.test; set +a
uv run pytest "$@"
