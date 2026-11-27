"""Move user intake originals only after the current complete review loop."""
import hashlib
import os
import time
from core.api import paths__WorkspacePath as Path
from core.api import services__atomic_json as atomic_json


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def completed_papers(catalog):
    # Reuse the actual reader's version-bound correction/pass predicate,
    # including already-read papers without changing the UI's default.
    result={};offset=0
    while True:
        page=catalog.page(limit=200,offset=offset,tab='deep',include_read=True)
        for row in page['papers']:
            paper=catalog.get(row['id'])
            if paper['decision'] in ('reject','ignore') or any(paper['metadata'].get(k) for k in
                    ('identity_review_required','version_review_required','out_of_scope')):continue
            try:
                if (paper.get('asset_hash') and paper.get('asset_path') and paper.get('card_path')
                        and digest(paper['asset_path'])==paper['asset_hash']
                        and digest(paper['card_path'])==row['evaluation_card_sha256']):
                    result[paper['id']]={**paper,'verified_card_sha256':row['evaluation_card_sha256']}
            except OSError:continue # Missing evidence never grants archive permission.
        offset+=200
        if offset>=page['total']:return result


def move_verified(source,library,expected,guard):
    """Preserve bytes; never overwrite a destination or unlink changed inputs."""
    import tempfile
    import shutil
    source=Path(source);library=Path(library)
    if source.is_symlink() or digest(source)!=expected:raise ValueError('待转移文件指纹变化')
    identity=source.stat()
    guard();library.mkdir(parents=True,exist_ok=True)
    target=library/source.name
    if target.exists() and digest(target)!=expected:
        target=library/(source.stem+'--'+expected[:12]+source.suffix)
    # Independent bytes: edits through an existing source fd cannot alter archive.
    fd,temporary=tempfile.mkstemp(prefix='.archive-',dir=library)
    staging=Path(temporary);holding=None;published=False;committed=False
    try:
        with os.fdopen(fd,'wb') as out, source.open('rb') as inp:
            shutil.copyfileobj(inp,out);out.flush();os.fsync(out.fileno())
        if digest(staging)!=expected:raise ValueError('转移期间文件变化，原文件保留')
        guard()
        # Atomically take custody, then verify what was actually moved. Never
        # unlink a path that another process can replace after our final guard.
        holding=source.parent/('.archive-custody-'+os.urandom(16).hex())
        source.rename(holding)
        def sync_directory(folder):
            fd=os.open(folder,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
        sync_directory(source.parent)
        current=holding.lstat()
        if (current.st_dev,current.st_ino)!=(identity.st_dev,identity.st_ino) or holding.is_symlink() or digest(holding)!=expected:
            raise ValueError('转移期间源文件身份变化，保留原文件')
        if target.exists():
            if target.is_symlink() or digest(target)!=expected:raise ValueError('文献库目标名称冲突，不覆盖')
        else:
            os.link(staging,target);published=True
        sync_directory(library)
        if digest(holding)!=expected:raise ValueError('转移期间源文件变化，保留原文件')
        holding.unlink();holding=None;committed=True
        sync_directory(source.parent)
        return str(target)
    except BaseException:
        if published and not committed:target.unlink(missing_ok=True)
        if holding is not None and os.path.lexists(holding):
            try:
                os.link(holding,source,follow_symlinks=False)
            except FileExistsError:
                raise RuntimeError(f'源路径已被占用；原字节保留于 {holding}')
            else:holding.unlink()
        raise
    finally:staging.unlink(missing_ok=True)


def run_once(catalog,config):
    policy=config.get('manual_literature',{})
    if not policy.get('archive_completed_enabled'):return {'state':'disabled','moved':[]}
    folders=[Path(policy['directory']).expanduser().resolve(),Path(policy.get('failed_directory',str(Path.home()/'Desktop/拉取失败'))).resolve()]
    library=Path(policy.get('completed_directory',str(Path.home()/'Desktop/文献库'))).expanduser().resolve()
    if any(library.is_relative_to(f) or f.is_relative_to(library) for f in folders):
        raise ValueError('文献库不能与暂存/失败目录重合或嵌套')
    library.mkdir(parents=True,exist_ok=True)
    complete=completed_papers(catalog);report={'state':'checked','checked_at':time.time(),'destination':str(library),'moved':[],'retained':[]}
    with catalog.connect() as db:
        registered={r['path']:dict(r) for r in db.execute('SELECT * FROM manual_literature_items')}
    hashes={}
    for pid,paper in complete.items():hashes.setdefault(paper['asset_hash'],[]).append(pid)
    for folder in folders:
        if not folder.is_dir():continue
        for source in sorted(folder.rglob('*')):
            if not source.is_file() or source.is_symlink() or source.suffix.lower() not in ('.pdf','.docx'):continue
            try:
                sha=digest(source);item=registered.get(str(source),{})
                pid=item.get('paper_id') if item.get('source_hash')==sha else None
                if source.suffix.lower()=='.pdf':
                    ids=hashes.get(sha,[])
                    if len(ids)==1:pid=ids[0]
                    else:pid=None
                if pid not in complete:
                    report['retained'].append({'path':str(source),'reason':'当前版本未完成完整修正及科学核验，或身份/指纹未确认'});continue
                paper=complete[pid]
                def guard():
                    if (digest(paper['card_path'])!=paper['verified_card_sha256'] or
                            digest(paper['asset_path'])!=paper['asset_hash'] or pid not in completed_papers(catalog)):
                        raise ValueError('归库前当前卡片/原文/验收链变化')
                target=move_verified(source,library,sha,guard)
                entry={'paper_id':pid,'from':str(source),'to':target,'source_hash':sha,'card_sha256':paper['verified_card_sha256']}
                catalog.event(pid,'completed_manual_literature_archived',entry)
                with catalog.connect() as db:
                    db.execute("UPDATE manual_literature_items SET state='archived',error='',updated=? WHERE path=? AND source_hash=?",(time.time(),str(source),sha))
                report['moved'].append(entry)
            except Exception as exc:report['retained'].append({'path':str(source),'reason':str(exc)})
    atomic_json(catalog.path.parent/'completed-literature-archive-status.json',report)
    return report
