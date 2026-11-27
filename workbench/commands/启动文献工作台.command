#!/bin/zsh
PAPER_LAYOUT_ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
while [ ! -f "$PAPER_LAYOUT_ROOT/workspace.json" ]; do
  if [ "$PAPER_LAYOUT_ROOT" = / ]; then echo "找不到 paper 项目根目录" >&2; exit 1; fi
  PAPER_LAYOUT_ROOT="$(dirname -- "$PAPER_LAYOUT_ROOT")"
done
set -eu
cd "$PAPER_LAYOUT_ROOT"
PAPER_PYTHON="${PAPER_PYTHON:-/Users/xiaoyanhao/venv/bin/python}"
if [[ ! -x "$PAPER_PYTHON" ]]; then
  echo "找不到 Python；请设置 PAPER_PYTHON 为已安装 read 依赖的 Python 3.10+。"
  exit 1
fi
# 常驻拉取与网页制卡独立运行；此入口仅打开工作台，本地模型保持暂停。
# 后台网页服务配置 Tailscale 并保留运行；启动器确认就绪、打印链接后退出。
exec "$PAPER_PYTHON" -m workbench.workbench_service "$@"
