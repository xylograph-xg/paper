"""Verified one-time main-library SSD migration; does not send or generate anything."""
import json
import os
import shutil
from core.api import paths__WorkspacePath as Path
from core.api import catalog__ROOT as ROOT, catalog__now as now
from reading.api import reading_contract__file_digest as file_digest
from core.api import services__atomic_json as atomic_json


def migrate():
    config_path = ROOT/'config/first_round.json'
    config = json.loads(config_path.read_text())
    volume = Path(config['archive_volume'])
    if not volume.is_mount():
        raise OSError('SSD未挂载')
    archive = Path(config['archive_root'])
    if not archive.resolve().is_relative_to(volume.resolve()):
        raise ValueError('归档目录不在SSD内')
    local = ROOT/'data'
    library = local/'deep_read'
    destination = archive/'cards'
    media = archive/'web-inputs'
    record_path = local/'ssd-organization-20261007.json'
    summary = {'updated':now(), 'state':'copying', 'database':config['catalog_path'],
               'cards':str(destination), 'media':str(media), 'moved_files':0,
               'moved_bytes':0, 'verified_files':0, 'aliases':[]}
    atomic_json(record_path,summary)
    if not library.is_symlink():
        if not destination.exists():
            shutil.copytree(library,destination,symlinks=True)
        # Every original file must be present and byte-identical before removing its local copy.
        for source in library.rglob('*'):
            if not source.is_file():continue
            target = destination/source.relative_to(library)
            if not target.is_file() or file_digest(source)!=file_digest(target):
                raise OSError('正式库副本不一致：'+str(source))
            summary['verified_files']+=1
            summary['moved_bytes']+=source.stat().st_size
        old = local/'deep_read.ssd-migration-old'
        if old.exists():raise OSError('发现旧迁移目录，需核对')
        summary['state']='library_verified';atomic_json(record_path,summary)
        library.rename(old)
        library.symlink_to(destination,target_is_directory=True)
        shutil.rmtree(old)
    elif library.resolve()!=destination.resolve():
        raise ValueError('正式库已有其他链接，保留待核对')
    # Receipts/queue/packet/context remain local. Move only media and card candidates.
    for source in (local/'web_cards').rglob('*'):
        if not source.is_file() or source.is_symlink():continue
        if source.suffix.lower() not in ('.pdf','.png') and source.name not in ('card.json','card-candidate.json'):
            continue
        target = media/source.relative_to(local/'web_cards')
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():shutil.copy2(source,target)
        digest = file_digest(source)
        if digest!=file_digest(target):raise OSError('材料副本不一致：'+str(source))
        size=source.stat().st_size
        temporary=source.with_name(source.name+'.ssd-link')
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(os.path.relpath(target,source.parent))
        os.replace(temporary,source)
        summary['moved_files']+=1;summary['moved_bytes']+=size
    # Keep old card paths valid; do not rewrite scientific JSON or rework authorization.
    config['studio_library_root']=str(destination)
    config['web_cards']['media_root']=str(media)
    atomic_json(config_path,config)
    links=[p for p in (local/'web_cards').rglob('*') if p.is_symlink()]
    broken=[str(p) for p in links if not p.exists()]
    if broken:raise OSError('迁移后链接失效：'+repr(broken[:5]))
    summary.update(state='complete',updated=now(),aliases=[str(library)],verified_links=len(links),broken_links=0)
    atomic_json(record_path,summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':migrate()
