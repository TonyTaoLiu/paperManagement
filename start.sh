#!/usr/bin/env bash
# One-click launcher for Linux/macOS. Installs uv if missing, syncs deps, starts PaperMind.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "[PaperMind] Installing uv ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
uv sync --frozen --no-dev
if [ "${PAPERMIND_NO_OPEN:-}" = "1" ]; then
  exec uv run --no-dev papermind serve "$@"
else
  exec uv run --no-dev papermind serve --open "$@"
fi
