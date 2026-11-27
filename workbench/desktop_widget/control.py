"""Pause an existing isolated model group using the pipeline control contract."""
from core.api import paths__workspace_root as _workspace_root
import json
import sys
from core.api import paths__WorkspacePath as Path

ROOT = _workspace_root()
sys.path.insert(0, str(ROOT))
from core.api import model_schedule__set_user_pause as set_user_pause


def pause(path):
    path = Path(path).resolve()
    base = ROOT / 'data/model_comparisons/20261006_same_prompt'
    if path.parent.parent != base or path.name != 'config.json':
        raise ValueError('只能控制现有隔离模型组')
    config = json.loads(path.read_text())
    if Path(config['catalog_path']).resolve().parent != path.parent:
        raise ValueError('队列与任务目录不一致')
    set_user_pause(config, True, '用户从任务面板暂停本组模型，保留断点')


if __name__ == '__main__':
    pause(sys.argv[1])
