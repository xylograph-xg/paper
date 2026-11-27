"""Read-only maintenance inventories. Missing references never authorize deletion."""
import hashlib
import json
from core.api import paths__WorkspacePath as Path
from core.api import services__atomic_json as atomic_json
from core.api import catalog__ROOT as ROOT, catalog__now as now


def inventory(root=ROOT):
    root=Path(root);data=root/'data';orphans=[]
    for folder in sorted((data/'shared-page-repairs').glob('*')):
        if not folder.is_dir() or (folder/'journal.json').exists():continue
        paths=[p for p in folder.rglob('*') if p.is_file()]
        orphans.append({'directory':str(folder.relative_to(root)),
            'files':{str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
            'ownership_confirmed':False,'page_close_or_claim_release_authorized':False})
    refs=set();errors=[]
    def visit(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k=='zip_path' and isinstance(v,str):refs.add(str(Path(v).expanduser().resolve()))
                else:visit(v)
        elif isinstance(value,list):
            for x in value:visit(x)
    for name in ('web_cards','card_reviews','quality_reviews'):
        for p in (data/name).rglob('*.json'):
            try:visit(json.loads(p.read_text()))
            except (OSError,ValueError):errors.append(str(p.relative_to(root)))
    zips=list((data/'app-upload-zips').glob('*.zip'))
    return {'checked_at':now(),'mutations':False,'orphan_diagnostics':orphans,
            'zip_scope':['web_cards','card_reviews','quality_reviews'],
            'zip_files':len(zips),'zip_bytes':sum(p.stat().st_size for p in zips),
            'referenced_zip_files':sum(str(p.resolve()) in refs for p in zips),
            'zip_references':len(refs),'missing_referenced_zips':sum(not Path(p).is_file() for p in refs),
            'unreferenced_in_scanned_scope':sum(str(p.resolve()) not in refs for p in zips),
            'external_app_references_checked':False,'delete_authorized':False,'json_read_errors':errors}


if __name__=='__main__':
    out=ROOT/'data/maintenance-audit-1746.json';atomic_json(out,inventory());print(out)
