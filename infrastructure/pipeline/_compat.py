"""Same-object adapters for old owners; never starts or resumes a service."""
import importlib,json,sys
from core.api import paths__WorkspacePath as Path
MAPPING=json.loads(Path(__file__).with_name('interface.json').read_text())['module_aliases']
def bind(name):
    for old,target in MAPPING.items():
        existing=sys.modules.get('pipeline.'+old)
        if existing is not None and target not in sys.modules and not getattr(existing,'_paper_adapter',False):
            sys.modules[target]=existing
    target=MAPPING[name]
    module=importlib.import_module(target)
    sys.modules['pipeline.'+name]=module
    return module
