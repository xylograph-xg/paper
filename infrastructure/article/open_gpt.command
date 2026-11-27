#!/bin/bash
set -eu
PAPER_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$PAPER_ROOT"
ARTICLE_PYTHON="${ARTICLE_PYTHON:-$PAPER_ROOT/.venv-web-feedback/bin/python}"
exec "$ARTICLE_PYTHON" -m article
