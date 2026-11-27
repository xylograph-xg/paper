"""Repair only broken runtime links whose original geometry proves an SSD target.

Native paths are intentional: WorkspacePath cannot resolve the pre-move parent
geometry without translating it back to the new directory. No target bytes are
written and no source-code links are created.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets


def _version(path):
    s=path.stat();return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]


def _digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def plan(old_data,new_data,archive_root):
    old_data=Path(old_data).absolute();new_data=Path(new_data).resolve();archive=Path(archive_root).resolve(strict=True)
    entries=[];unresolved=[];hashes={};broken=0
    for directory,dirs,files in os.walk(new_data,followlinks=False):
        for name in dirs+files:
            link=Path(directory)/name
            if not link.is_symlink() or link.exists():continue
            broken+=1;raw=os.readlink(link)
            original=old_data/link.relative_to(new_data)
            target=Path(os.path.normpath(original.parent/raw)) if not os.path.isabs(raw) else Path(raw)
            binding='original_pre_migration_geometry'
            relative=link.relative_to(new_data).parts
            # Old retry archives moved the provider directory two levels deeper
            # without rebasing its diagnostic alias. Recover only the exact SSD
            # path named in that alias; it is not proof of capture for an attempt.
            if (not target.exists() and len(relative)==6 and relative[0]=='web_cards' and
                    relative[2]=='history' and relative[3].startswith('automatic-retry-') and
                    relative[4]=='chatgpt' and relative[5]=='error-page.png'):
                parts=Path(raw).parts
                tail=Path(str(archive).lstrip('/'))/'web-inputs'/relative[1]/'chatgpt'/'error-page.png'
                expected=tail.parts
                if (len(parts)>len(expected) and all(p=='..' for p in parts[:-len(expected)]) and
                        parts[-len(expected):]==expected):
                    target=archive/'web-inputs'/relative[1]/'chatgpt'/'error-page.png'
                    binding='original_ssd_diagnostic_alias_only_not_attempt_capture_proof'
            if os.path.isabs(raw) or not target.exists() or not target.resolve().is_relative_to(archive):
                unresolved.append({'path':str(link),'old_link':raw});continue
            target=target.resolve();before=_version(target);file_hash=None
            if target.is_file():
                key=(str(target),tuple(before));file_hash=hashes.get(key)
                if file_hash is None:file_hash=hashes[key]=_digest(target)
            if before!=_version(target):raise ValueError('SSD target changed during planning: '+str(target))
            entries.append({'path':str(link),'old_link':raw,'target':str(target),
                            'target_version':before,'target_sha256':file_hash,
                            'new_link':os.path.relpath(target,link.parent),'binding':binding})
    return {'schema_version':1,'old_data':str(old_data),'new_data':str(new_data),'archive_root':str(archive),
            'broken_count':broken,'entries':entries,'unresolved':unresolved,'no_target_bytes_written':True}


def apply_plan(proposal):
    root=Path(proposal['new_data']).resolve();archive=Path(proposal['archive_root']).resolve();changed=[];errors=[]
    for entry in proposal['entries']:
        link=Path(entry['path']);target=Path(entry['target'])
        try:
            if (not link.parent.resolve().is_relative_to(root) or not target.resolve().is_relative_to(archive) or
                    os.path.normpath(str(link.parent/entry['new_link']))!=str(target)):
                raise ValueError('Link or target outside declared runtime/SSD ownership')
            if not link.is_symlink() or os.readlink(link)!=entry['old_link']:
                raise ValueError('Link changed after planning')
            if link.exists():raise ValueError('Link is already valid; preserve newer state')
            if _version(target)!=entry['target_version']:raise ValueError('SSD target changed after planning')
            temporary=link.with_name('.'+link.name+'.link-fix-'+secrets.token_hex(8))
            try:
                temporary.symlink_to(entry['new_link'],target_is_directory=target.is_dir())
                if os.readlink(link)!=entry['old_link'] or _version(target)!=entry['target_version']:
                    raise ValueError('Evidence changed before atomic link replacement')
                os.replace(temporary,link)
            finally:temporary.unlink(missing_ok=True)
            if link.resolve(strict=True)!=target or _version(target)!=entry['target_version']:
                raise ValueError('Repaired link identity mismatch')
            changed.append(entry)
        except (OSError,ValueError) as exc:errors.append({'path':str(link),'reason':str(exc)})
    return {'changed':changed,'errors':errors,'unresolved':proposal['unresolved'],'no_target_bytes_written':True}


def resume_link_blocked_materials(config, result):
    """Return proven local preparation failures to their original authorized queue."""
    from core.api import catalog__Catalog as Catalog,catalog__now as now
    from core.api import paths__WorkspacePath as RuntimePath
    from cards.api import web_card_retry__eligible as eligible,web_card_retry__frozen_inputs as frozen_inputs
    from cards.api import web_card_rework__submission_history as submission_history
    from correction.api import card_correction_queue__allows_web_job as allows_web_job,card_correction_queue__check_task as check_task
    cat=Catalog(config['catalog_path']);root=cat.path.parent;ids=set()
    for item in result['changed']:
        try:parts=RuntimePath(item['path']).relative_to(root/'web_cards').parts
        except ValueError:continue
        if len(parts)>=2:ids.add(parts[0])
    recovered=[];held=[]
    with cat.connect() as db:
        jobs=[dict(r) for r in db.execute("SELECT * FROM web_card_jobs WHERE state='needs_inspection' AND error LIKE '%No such file or directory%'") if r['paper_id'] in ids]
    for job in jobs:
        try:
            if not allows_web_job(config,job,recovery=True):raise ValueError('Correction paused or binding changed')
            folder=root/'web_cards'/job['paper_id']
            if list(folder.glob('*/attempt.json')):raise ValueError('Current request receipt exists; preserve')
            paper=eligible(cat,job,config);packet=json.loads((folder/'packet.json').read_text())
            frozen_inputs(folder,packet,paper)
            if not submission_history(cat,job,folder).allowed:raise ValueError('Original receipt history unresolved')
            cid=json.loads(job['selection'])['rework']['correction_id']
            with cat.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                fresh=db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(job['paper_id'],)).fetchone()
                correction=db.execute('SELECT * FROM card_correction_jobs WHERE id=?',(cid,)).fetchone()
                if (fresh is None or dict(fresh)!=job or correction is None or correction['state']!='needs_user' or
                        correction['error']!=job['error'] or not allows_web_job(config,job,recovery=True)):
                    raise ValueError('Preparation failure changed during recovery')
                check_task(dict(correction));eligible(cat,job,config);frozen_inputs(folder,packet,cat.get(job['paper_id']))
                if list(folder.glob('*/attempt.json')) or not submission_history(cat,job,folder).allowed:
                    raise ValueError('Receipt history changed during recovery')
                db.execute("UPDATE web_card_jobs SET state='queued',error='',updated=? WHERE paper_id=?",(now(),job['paper_id']))
                db.execute("UPDATE card_correction_jobs SET state='ready',error='迁移链接已核对恢复；原冻结输入与FIFO保持',updated=? WHERE id=?",(now(),cid))
                db.execute("UPDATE web_page_queue SET state=CASE WHEN state='failed' THEN 'waiting' ELSE state END,error='' WHERE paper_id=?",(job['paper_id'],))
                db.execute("UPDATE shared_page_backlog SET state='queued' WHERE lane='correction' AND job_id=? AND state='claimed'",(cid,))
                db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'runtime_link_preparation_recovered',?,?)",
                           (job['paper_id'],json.dumps({'correction_id':cid,'original_error':job['error'],'frozen_inputs':packet['input_hashes'],'no_current_request':True}),now()))
            recovered.append(job['paper_id'])
        except (OSError,ValueError,KeyError,TypeError) as exc:held.append({'paper_id':job['paper_id'],'reason':str(exc)})
    return {'recovered':recovered,'held':held,'no_receipts_modified':True,'no_retry_counters_reset':True}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--plan',required=True);parser.add_argument('--apply',action='store_true')
    parser.add_argument('--resume-materials',action='store_true');args=parser.parse_args()
    if args.resume_materials:
        from core.api import catalog__load_config as load_config
        print(json.dumps(resume_link_blocked_materials(load_config(),json.loads(Path(args.plan).read_text())),ensure_ascii=False));return
    if args.apply:
        path=Path(args.plan);result=apply_plan(json.loads(path.read_text()))
        path.with_name(path.stem+'-applied.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'changed':len(result['changed']),'errors':len(result['errors']), 'unresolved':len(result['unresolved'])}))
    else:
        from core.api import paths__workspace_root as workspace_root
        root=Path(workspace_root());manifest=json.loads((root/'workspace.json').read_text())
        config=json.loads((root/manifest['physical_roots']['config']/'first_round.json').read_text())
        result=plan(root/'data',root/manifest['physical_roots']['data'],config['archive_root'])
        Path(args.plan).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'broken':result['broken_count'],'repairable':len(result['entries']),'unresolved':len(result['unresolved'])}))


if __name__=='__main__':main()
