"""Version and completion gate shared by reading writers and review consumers."""
from core.api import paths__workspace_root as _workspace_root
import hashlib
import json
from core.api import paths__WorkspacePath as Path
from read.api import generation_state__generation_complete as generation_complete

READING_CONTRACT_VERSION=10


def file_digest(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def verified_completion(folder):
    folder=Path(folder)
    try:
        marker=json.loads((folder/'quality-ready.json').read_text())
        if marker.get('reading_contract_version')!=READING_CONTRACT_VERSION or marker.get('generation_complete') is not True:return None
        if marker.get('producer_fingerprint')!=producer_fingerprint():return None
        from core.api import model_identity__resolve_identity as resolve_identity
        from core.api import catalog__load_config as load_config
        if not marker.get('model_digest') or marker['model_digest']!=resolve_identity(load_config()['model']):return None
        if file_digest(folder/'card.json')!=marker['card_sha256'] or file_digest(folder/'source.pdf')!=marker['source_sha256']:return None
        card=json.loads((folder/'card.json').read_text())
        if card.get('meta',{}).get('reading_contract_version')!=READING_CONTRACT_VERSION or not generation_complete(card):return None
        if card.get('meta',{}).get('producer_fingerprint')!=marker.get('producer_fingerprint') or card.get('meta',{}).get('reading_input_hash')!=marker.get('reading_input_hash') or card.get('meta',{}).get('model_digest')!=marker.get('model_digest'):return None
        if not card.get('meta',{}).get('evidence_coverage'):return None
        for item in card.get('figures',[])+card.get('equations',[]):
            path=Path(item.get('image_path') or '').resolve()
            if not path.is_relative_to(folder.resolve()) or not path.is_file():return None
            if marker.get('evidence_sha256',{}).get(str(path.relative_to(folder.resolve())))!=file_digest(path):return None
        return marker
    except (OSError,ValueError,KeyError,TypeError,AttributeError,RuntimeError):return None


def inventory(root):
    counts={};entries=[]
    for path in sorted(Path(root).glob('*/card.json')):
        try:
            card=json.loads(path.read_text());meta=card.get('meta',{})
            version=meta.get('reading_contract_version')
            protected=bool(meta.get('quality_review'))
            from review.api import review_protection__protection as protection
            protected=protected or bool(protection(path.parent))
            if meta.get('producer')=='web_card_service':
                state='web_source_quotes_verified' if meta.get('evidence_verification',{}).get('evidence_verified') is True else 'web_evidence_needs_review'
            else:state=('current_complete' if verified_completion(path.parent) else 'current_incomplete') if version==READING_CONTRACT_VERSION else ('reviewed_legacy' if protected else 'legacy')
            key=str(version) if version is not None else 'missing'
        except (OSError,ValueError,TypeError,AttributeError):key='invalid';state='needs_manual_check';protected=False
        counts[key]=counts.get(key,0)+1
        entries.append({'path':str(path.resolve()),'version':key,'state':state,'reviewed':protected})
    return {'current_version':READING_CONTRACT_VERSION,'versions':counts,'cards':entries}


def producer_fingerprint():
    from pathlib import Path as InstalledPath
    import read.api as read_api
    from core.api import model_identity__resolve_identity as resolve_identity
    import core.api as core_api
    reader=InstalledPath(read_api.__file__).resolve().parent
    own=InstalledPath(__file__).resolve().parent
    paths=[*sorted((reader/'app').glob('*.py')),*sorted((reader/'app/prompts').glob('*.md'))]
    paths += [own/n for n in ('reading_bridge.py','reading_contract.py','evidence_repair.py','prompt_overlays.py','quantity_supplement.py','media_evidence.py','source_media.py','reading_failures.py','science_verifier.py')]
    paths += [own/'requirements-science.txt',reader/'requirements-pdf-geometry.txt']
    inputs={('read/'+str(p.relative_to(reader)) if p.is_relative_to(reader) else 'reading/'+str(p.relative_to(own))):file_digest(p) for p in paths}
    inputs['core/model_identity.py']=file_digest(InstalledPath(core_api.__file__).resolve().parent/'model_identity.py')
    from importlib.metadata import version
    import sys
    inputs['runtime']={'python':sys.version.split()[0],'pymupdf':version('pymupdf'),'pillow':version('pillow')}
    from .science_verifier import runtime_identity
    inputs['runtime']['science_verifier']=runtime_identity()
    from core.api import catalog__load_config as load_config
    for name,cfg in (('read/app/config.json',json.loads((reader/'app/config.json').read_text())),('config/first_round.json',load_config())):
        inputs[name]={k:cfg[k] for k in ('model','model_identity','max_figures','max_equations','max_context_chars','pdf_geometry') if k in cfg}
    return hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest()
