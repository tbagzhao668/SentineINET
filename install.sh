#!/usr/bin/env bash
set -euo pipefail

REPO_URL_DEFAULT="https://github.com/tbagzhao668/SentineINET.git"
BRANCH_DEFAULT="main"
TARGET_DIR_DEFAULT="AI_firewall_configer"

REPO_URL="${REPO_URL:-$REPO_URL_DEFAULT}"
BRANCH="${BRANCH:-$BRANCH_DEFAULT}"
TARGET_DIR="${TARGET_DIR:-$TARGET_DIR_DEFAULT}"
NO_BUILD="${NO_BUILD:-0}"

usage() {
  cat <<'EOF'
Usage:
  curl -fsSL <URL>/install.sh | bash

Optional environment variables:
  REPO_URL   Git repo URL (default: project GitHub repo)
  BRANCH     Git branch (default: main)
  TARGET_DIR Install directory name (default: AI_firewall_configer)
  NO_BUILD   Set to 1 to skip image build (docker compose up -d)

Examples:
  REPO_URL="https://gitee.com/tisnzhao/SentinelNET.git" curl -fsSL <URL>/install.sh | bash
  TARGET_DIR="sentinelnet" curl -fsSL <URL>/install.sh | bash
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing dependency: $1" >&2
    exit 1
  fi
}

need_cmd git
need_cmd docker

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required (docker compose ...)." >&2
  exit 1
fi

port_in_use() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$port" -sTCP:LISTEN -P -n >/dev/null 2>&1
    return $?
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | awk '{print $4}' | grep -E "[:.]${port}\$" >/dev/null 2>&1
    return $?
  fi
  if command -v netstat >/dev/null 2>&1; then
    netstat -an 2>/dev/null | grep -E "[:.]${port}[[:space:]]" | grep -E "LISTEN|LISTENING" >/dev/null 2>&1
    return $?
  fi
  return 1
}

for p in 5175 8000; do
  if port_in_use "$p"; then
    echo "Port ${p} is already in use. Please stop the process using it, or change ports in docker-compose.yml." >&2
    exit 1
  fi
done

if [[ -d "$TARGET_DIR/.git" ]]; then
  echo "Updating existing repo: $TARGET_DIR"
  git -C "$TARGET_DIR" fetch --all --prune
  git -C "$TARGET_DIR" checkout "$BRANCH"
  git -C "$TARGET_DIR" pull --ff-only
elif [[ -e "$TARGET_DIR" ]]; then
  echo "Target path exists but is not a git repo: $TARGET_DIR" >&2
  exit 1
else
  echo "Cloning: $REPO_URL (branch: $BRANCH) -> $TARGET_DIR"
  git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$TARGET_DIR"
fi

cd "$TARGET_DIR"

if [[ "$NO_BUILD" == "1" ]]; then
  docker compose up -d
else
  docker compose up -d --build
fi

echo
echo "Done."
echo "- Frontend: http://127.0.0.1:5175"
echo "- Backend:  http://127.0.0.1:8000"
echo
echo "Common commands:"
echo "- View status: docker compose ps"
echo "- View logs:   docker compose logs -f --tail=200"
echo "- Stop:        docker compose down"
echo
echo "First-time setup:"
echo "- Open Frontend, then fill AI config (api_key/model/base_url) if you need AI features."
echo "- Add devices in Asset Management (or edit backend/app/db.json in test environment)."
