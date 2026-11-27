#!/bin/zsh
PAPER_LAYOUT_ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
while [ ! -f "$PAPER_LAYOUT_ROOT/workspace.json" ] || [ ! -f "$PAPER_LAYOUT_ROOT/workspace.json" ]; do
  if [ "$PAPER_LAYOUT_ROOT" = / ]; then echo "找不到 paper 项目根目录" >&2; exit 1; fi
  PAPER_LAYOUT_ROOT="$(dirname -- "$PAPER_LAYOUT_ROOT")"
done
set -eu
cd "$PAPER_LAYOUT_ROOT"
exec .venv-web-feedback/bin/python -m core.continuous_start --open-browser
