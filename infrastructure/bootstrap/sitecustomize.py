"""Load nested component import roots. No business imports or service actions."""
import json
from pathlib import Path
import sys
root=next(p for p in Path(__file__).resolve().parents if (p/'workspace.json').is_file())
sys.pycache_prefix=str(root/'infrastructure/cache/python')
if (root/'workspace.json').is_file():
    workspace=json.loads((root/'workspace.json').read_text())
    for entry in workspace.get('projects',{}).values():
        parent=str((root/entry.get('path','')).parent)
        if parent not in sys.path:sys.path.append(parent)
