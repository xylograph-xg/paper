#!/bin/bash
PAPER_LAYOUT_ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
while [ ! -f "$PAPER_LAYOUT_ROOT/workspace.json" ]; do
  if [ "$PAPER_LAYOUT_ROOT" = / ]; then echo "找不到 paper 项目根目录" >&2; exit 1; fi
  PAPER_LAYOUT_ROOT="$(dirname -- "$PAPER_LAYOUT_ROOT")"
done
set -e
TASK_ROOT="$PAPER_LAYOUT_ROOT"
TASK_APP="$TASK_ROOT/workbench/desktop_widget/build/任务状态.app"
TASK_SOURCE="$TASK_ROOT/workbench/desktop_widget/TaskPanel.swift"
if [ ! -x "$TASK_APP/Contents/MacOS/TaskPanel" ] || [ "$TASK_SOURCE" -nt "$TASK_APP/Contents/MacOS/TaskPanel" ]; then
  mkdir -p "$TASK_APP/Contents/MacOS" "$TASK_ROOT/workbench/desktop_widget/build/module-cache"
  swiftc -O -module-cache-path "$TASK_ROOT/workbench/desktop_widget/build/module-cache" "$TASK_SOURCE" -o "$TASK_APP/Contents/MacOS/TaskPanel"
  /usr/bin/python3 - "$TASK_ROOT" "$TASK_APP" <<'PY'
import plistlib,sys
from pathlib import Path
root,app=sys.argv[1:]
with (Path(app)/'Contents/Info.plist').open('wb') as f:
    plistlib.dump(dict(CFBundleExecutable='TaskPanel',CFBundlePackageType='APPL',CFBundleIdentifier='local.paper.task-status',CFBundleName='任务状态',CFBundleVersion='1',CFBundleShortVersionString='1.0',LSUIElement=True,NSHighResolutionCapable=True,TaskProjectRoot=root,TaskPython='/Users/xiaoyanhao/venv/bin/python'),f)
PY
  codesign --force --sign - "$TASK_APP"
  /usr/bin/python3 - "$TASK_APP/Contents/MacOS/TaskPanel" <<'PY'
import os,signal,subprocess,sys
for line in subprocess.check_output(['ps','-axo','pid=,command='],text=True).splitlines():
    parts=line.strip().split(None,1)
    if len(parts)==2 and parts[1]==sys.argv[1]:
        try:os.kill(int(parts[0]),signal.SIGTERM)
        except ProcessLookupError:pass
PY
fi
open "$TASK_APP"
