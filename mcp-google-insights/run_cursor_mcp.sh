#!/usr/bin/env bash
# Cursor の .cursor/mcp.json から相対パスで起動するためのラッパー。
# リポジトリ直下の .venv を使用（別パスならこのファイルを編集）。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PYTHONPATH="$SCRIPT_DIR"
exec "${MCP_PYTHON:-$REPO_ROOT/.venv/bin/python3}" -m mcp_google_insights
