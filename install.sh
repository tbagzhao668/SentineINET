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
