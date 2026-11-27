"""Recoverable local source/config versions and SQLite/history backups; no Git or uploads."""
import hashlib,json,os,shutil,sqlite3,tempfile
from contextlib import closing
from datetime import datetime,timezone
from .paths import WorkspacePath as Path
from .catalog import ROOT
from read.api import atomic_io__atomic_json as atomic_json
from reading.api import reading_contract__file_digest as file_digest

def capture(config,root=ROOT):
    root=Path(root);folder=Path(config['catalog_path']).parent/'workflow_versions';folder.mkdir(parents=True,exist_ok=True);folder.chmod(0o700)
    blocks=('fetch','cards','review','correction','reading','browser','core','workbench',
            'maintenance','read/app','article/src','pipeline','config','codex_desktop_chat','desktop_widget')
    sources=[p for name in blocks for p in (root/name).rglob('*')
             if p.is_file() and not p.is_symlink()
             and p.suffix in ('.py','.md','.json','.html','.sh','.cjs','.mjs','.js','.swift','.toml')
             and not any(n in p.parts for n in ('__pycache__','workspace','data','build','node_modules'))]
    sources += [p for p in [root/'AGENTS.md',root/'README.md',root/'WORKFLOWS.md',root/'workspace.json',root/'Makefile',root/'requirements-test.txt',root/'tool-dependencies.json',root/'article/tool-dependencies.json',*(root/'.github/workflows').glob('*.yml')] if p.is_file()]
    hashes={str(p.relative_to(root)):file_digest(p) for p in sources}
    identity=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest();target=folder/identity
    if target.exists():
        proof=json.loads((target/'manifest.json').read_text())
        if proof['files']!=hashes or not all(file_digest(target/p)==h for p,h in hashes.items()):raise ValueError('流程版本备份损坏，禁止覆盖')
        return target
    stage=Path(tempfile.mkdtemp(prefix='.version-',dir=folder))
    try:
        for p in sources:
            out=stage/p.relative_to(root);out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,out);out.chmod(0o600)
        if any(file_digest(stage/p)!=h for p,h in hashes.items()):raise ValueError('流程在备份期间变化，保留当前源代码重新备份')
        from importlib.metadata import version
        import sys
        environment={'python':sys.version.split()[0],'pymupdf':version('pymupdf'),'pillow':version('pillow')}
        atomic_json(stage/'manifest.json',{'environment':environment,'identity':identity,'created':datetime.now(timezone.utc).isoformat(),'files':hashes})
        os.replace(stage,target)
    finally:
        if stage.exists():shutil.rmtree(stage)
    return target

def backup_state(config,root=ROOT):
    raise RuntimeError("用户已禁用数据备份；不创建备份")

if __name__=='__main__':
    from .catalog import load_config
    cfg=load_config();print(capture(cfg))
