"""Explicit, bounded material repairs after a fully collected source review."""
import fcntl
import hashlib
import json
import shutil
import subprocess
from core.api import paths__WorkspacePath as Path

from core.api import catalog__ROOT as ROOT, catalog__now as now
from core.api import services__atomic_json as atomic_json
from cards.api import web_card_inputs__digest as digest


def supplement_packet(catalog, job, config, folder):
    registry=catalog.path.parent/'card_review_supplements'/job['paper_id']/'manifest.json'
    if not registry.exists():return {}
    record=json.loads(registry.read_text());paper=catalog.get(job['paper_id'])
    if (record.get('paper_id')!=job['paper_id'] or record.get('source_original_sha256')!=job['source_sha256'] or
        str(record.get('doi','')).casefold()!=str(paper['metadata'].get('doi','')).casefold() or
        record.get('identity_verified') is not True):
        raise ValueError('补充材料与原文身份或版本未核对')
    source=(registry.parent/record['file']).resolve()
    if not source.is_relative_to(registry.parent.resolve()) or source.suffix.lower()!='.pdf' or digest(source)!=record['sha256']:
        raise ValueError('补充材料路径或指纹变化')
    if not str(record.get('publisher_link','')).startswith('https://'):
        raise ValueError('补充材料缺少已核对的出版来源')
    shutil.copy2(source,folder/'supplement.pdf')
    with (folder/'prepare.log').open('a') as log:
        run=subprocess.run([config['web_cards']['pdf_python'],'-m','review.card_review_repair','--supplement-visual',str(folder)],
                           cwd=ROOT,stdout=log,stderr=log,timeout=600)
    if run.returncode:raise ValueError('补充材料视觉准备失败，保留待核对')
    context=json.loads((folder/'supplement-context.json').read_text())
    return {'files':['supplement.pdf','supplement-visual.pdf','supplement-context.json'],
            'page_count':context['page_count'],'source_sha256':record['sha256'],
            'registry_sha256':digest(registry),'publisher_link':record['publisher_link']}


def collected(catalog, job):
    """Validate frozen original receipts; never make a browser connection."""
    from .card_review_queue import check_packet
    folder=Path(job['folder']);packet=check_packet(folder)
    receipt=json.loads((folder/'attempt.json').read_text())
    if (receipt.get('state')!='response_saved' or not receipt.get('finished') or
        receipt.get('raw_sha256')!=digest(folder/'response-raw.txt') or
        receipt.get('inputs')!=packet['input_hashes'] or
        receipt.get('actual_prompt_sha256')!=packet['actual_prompt_sha256']):
        raise ValueError('原核验尚未完整收取或指纹变化，不重新核验')
    url=receipt.get('conversation_url','')
    if not url.startswith('https://chatgpt.com/c/') or 'local-chatgpt' in url:
        raise ValueError('原核验缺少正式会话回执')
    for path in (catalog.path.parent/'card_reviews').glob('*/*/attempt.json'):
        if path.resolve()==(folder/'attempt.json').resolve():continue
        if json.loads(path.read_text()).get('conversation_url')==url:
            raise ValueError('原核验会话归属不唯一')
    return packet


def repair(catalog, job, config, *, cycle=False):
    """Prepare new evidence once, then atomically replace the current version's job.

    The old folder, response and partial score survive. The existing browser owner
    may submit the ready packet later, subject to pause and attachment controls.
    """
    from . import card_review_queue as queue
    if not queue.enabled(config):raise ValueError('核验暂停，保留原报告')
    with catalog.connect() as db:
        fresh=db.execute('SELECT * FROM card_review_jobs WHERE id=?',(job['id'],)).fetchone()
    if fresh is None or dict(fresh)!=job:raise ValueError('核验任务状态变化')
    result=json.loads(job['result'])
    allowed_state=(job['state']=='needs_user' or
                   cycle and job['state']=='failed' and result.get('failure_kind')=='scientific')
    if not allowed_state or (not cycle and result.get('full_source_checked') is not False):
        raise ValueError('只修复已结束且材料检查未完成的核验')
    paper,path,card=queue.current(catalog,job,config)
    if queue.protected(catalog,paper):raise ValueError('人工决定卡片仅保留建议')
    old_packet=collected(catalog,job)
    if cycle:
        from .review_cycle import completed_failure
        completed_failure(catalog,job,config)
    registry=catalog.path.parent/'card_review_supplements'/job['paper_id']/'manifest.json'
    new_supplement=json.loads(registry.read_text()).get('sha256','') if registry.exists() else ''
    if (not cycle and old_packet.get('review_materials_version')==2 and
        new_supplement==old_packet.get('supplement',{}).get('source_sha256','')):
        raise ValueError('材料没有新增，不重复同输入核验')
    event_kind='card_review_cycle' if cycle else 'card_review_material_repair'
    with catalog.connect() as db:
        count=db.execute("SELECT count(*) FROM events WHERE paper_id=? AND kind=? AND json_extract(payload,'$.card_sha256')=?",
                         (job['paper_id'],event_kind,job['card_sha256'])).fetchone()[0]
    if cycle:
        from .review_cycle import failure_count, failure_limit
        count=failure_count(catalog,job,config)
        limit=failure_limit(config)-1
    else:limit=2
    if count>=limit:raise ValueError('本卡片材料复核已达两次上限')
    old_folder=Path(job['folder']);new_id=hashlib.sha256((job['id']+digest(old_folder/'packet.json')+new_supplement+('cycle-v1-'+str(count) if cycle else 'material-repair-v2')).encode()).hexdigest()[:24]
    new_folder=old_folder.parent/new_id
    preparation_version=hashlib.sha256((digest(Path(__file__))+digest(Path(queue.__file__))+
                                        getattr(repair,'recovery_revision','legacy')).encode()).hexdigest()
    lock=catalog.path.parent/'card-review-material-repair.lock'
    with lock.open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        new_job={**job,'id':new_id,'folder':str(new_folder),'state':'queued'}
        moving=new_folder.with_name('.'+new_folder.name+'.partial-recovery.json')
        if moving.exists():
            saved=json.loads(moving.read_text());intent=saved['intent'];archived=Path(intent['partial_archive'])
            bound=intent.get('old_job',{})
            if (any(bound.get(k)!=job.get(k) for k in ('id','paper_id','card_sha256','source_sha256')) or
                    Path(bound.get('folder','')).resolve()!=old_folder.resolve() or
                    intent.get('old_packet_sha256')!=digest(old_folder/'packet.json') or
                    intent.get('old_raw_sha256')!=digest(old_folder/'response-raw.txt') or
                    intent.get('new_review_id')!=new_id or intent.get('number')!=count+1 or
                    archived.parent.resolve()!=new_folder.parent.resolve() or
                    not archived.name.startswith(new_id+'-partial-') or
                    archived.is_symlink() or new_folder.is_symlink() or
                    any(new_folder.rglob('attempt.json')) or any(new_folder.rglob('response-raw.txt'))):
                raise ValueError('中断准备移动意图归属变化')
            from core.api import archive_paths__move_with_links as move_with_links
            journal=archived.with_name('.'+archived.name+'.links-move.json')
            if journal.exists() or not archived.exists():move_with_links(new_folder,archived)
            for name,sha in intent['partial_fingerprints'].items():
                if Path(name).is_absolute() or '..' in Path(name).parts or digest(archived/name)!=sha:
                    raise ValueError('原半途材料归档变化')
            new_folder.mkdir(exist_ok=True)
            if list(new_folder.iterdir()):
                actual=json.loads((new_folder/'repair-intent.json').read_text()) if (new_folder/'repair-intent.json').is_file() else {}
                if any(actual.get(k)!=value for k,value in intent.items()):
                    raise ValueError('中断恢复目录冲突，不覆盖')
            else:atomic_json(new_folder/'repair-intent.json',intent)
            moving.unlink()
        if new_folder.exists():
            intent=json.loads((new_folder/'repair-intent.json').read_text())
            if intent.get('preparation_failed_version')==preparation_version:
                raise ValueError('同版本本地准备失败，保留候选待实现变化')
            bound=intent.get('old_job',{})
            if (new_folder.is_symlink() or any(bound.get(k)!=job.get(k) for k in
                    ('id','paper_id','card_sha256','source_sha256')) or
                    Path(bound.get('folder','')).resolve()!=old_folder.resolve() or
                    intent.get('old_packet_sha256')!=digest(old_folder/'packet.json') or
                    intent.get('old_raw_sha256')!=digest(old_folder/'response-raw.txt') or
                    intent.get('new_review_id')!=new_id or intent.get('number')!=count+1 or
                    any(new_folder.rglob('attempt.json')) or any(new_folder.rglob('response-raw.txt'))):
                raise ValueError('已有复核候选归属或原回执变化，不恢复准备')
            with catalog.connect() as db:
                if db.execute('SELECT 1 FROM card_review_jobs WHERE id=?',(new_id,)).fetchone():
                    raise ValueError('复核候选已登记，不重复入队')
            if not (new_folder/'packet.json').exists() and any((new_folder/n).exists() for n in
                    ('source.pdf','visual.pdf','card-images.pdf')):
                # Interrupted local renders are not frozen inputs. Preserve the
                # whole partial candidate and use separate storage for recovery.
                source_packet,_,_=queue.source_inputs(catalog,new_job,path,card)
                if ((new_folder/'source.pdf').exists() and
                        digest(new_folder/'source.pdf')!=source_packet['input_hashes']['source.pdf']):
                    active=catalog.path.parent/'web_cards'/job['paper_id']/'packet.json'
                    provenance=json.loads(active.read_text()) if active.is_file() else {}
                    hashes=provenance.get('input_hashes',{})
                    if (provenance.get('paper_id')!=job['paper_id'] or
                            provenance.get('source_original_sha256')!=job['source_sha256'] or
                            hashes.get('source.pdf')!=digest(new_folder/'source.pdf') or
                            not (new_folder/'source-context.json').is_file() or
                            hashes.get('source-context.json')!=digest(new_folder/'source-context.json')):
                        raise ValueError('未冻结候选原文变化，不恢复')
                    intent={**intent,'partial_normalization_origin':{'packet':str(active),
                            'packet_sha256':digest(active),'source_sha256':hashes['source.pdf'],
                            'context_sha256':hashes['source-context.json']}}
                if ((new_folder/'card-original.json').exists() and
                        digest(new_folder/'card-original.json')!=job['card_sha256']):
                    raise ValueError('未冻结候选卡片变化，不恢复')
                files={str(p.relative_to(new_folder)):digest(p) for p in new_folder.rglob('*') if p.is_file()}
                fingerprint=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()[:24]
                archived=new_folder.with_name(new_folder.name+'-partial-'+fingerprint)
                from core.api import archive_paths__move_with_links as move_with_links
                intent={**intent,'partial_archive':str(archived),'partial_fingerprints':files}
                media=config.get('card_review',{}).get('media_root')
                if media:intent['preparation_media_root']=str(Path(media)/'local-preparation-recovery'/fingerprint)
                atomic_json(moving,{'intent':intent})
                move_with_links(new_folder,archived)
                new_folder.mkdir()
                atomic_json(new_folder/'repair-intent.json',intent)
                moving.unlink()
        else:
            new_folder.mkdir()
            atomic_json(new_folder/'repair-intent.json',{'schema_version':1,'old_job':job,'old_packet_sha256':digest(old_folder/'packet.json'),
                'old_raw_sha256':digest(old_folder/'response-raw.txt'),'new_review_id':new_id,'number':count+1,'created':now()})
        intent=json.loads((new_folder/'repair-intent.json').read_text())
        preparation_config=config
        if intent.get('preparation_media_root'):
            original_media=Path(config['card_review']['media_root']).resolve()
            media=Path(intent['preparation_media_root']).resolve()
            if not media.is_relative_to(original_media/'local-preparation-recovery'):
                raise ValueError('独立恢复媒体目录归属变化')
            preparation_config={**config,'card_review':{**config['card_review'],'media_root':str(media)}}
        try:
            if not queue.prepare(catalog,new_job,preparation_config,locate_quote_pages=False):raise ValueError('材料复核准备未完成')
        except ValueError as exc:
            atomic_json(new_folder/'repair-intent.json',{**intent,'preparation_failed_version':preparation_version,
                        'preparation_error':str(exc)[:700]})
            raise
        new_packet=queue.check_packet(new_folder)
        if (new_packet.get('review_materials_version')!=2 or new_packet.get('job_id')!=new_id or
                new_packet.get('card_sha256')!=job['card_sha256'] or
                new_packet.get('source_original_sha256')!=job['source_sha256']):
            raise ValueError('新核验材料契约或任务归属不完整')
        queue.current(catalog,job,config);collected(catalog,job)
        if not queue.enabled(config) or queue.protected(catalog,catalog.get(job['paper_id'])):
            raise ValueError('准备后暂停或人工保护变化，候选保留，不入队')
        feedback=json.loads((old_folder/'feedback.json').read_text()) if (old_folder/'feedback.json').exists() else {}
        retained={**result,'material_recheck_pending':True,'previous_report':str(old_folder/'feedback.json'),
                  'missing_inputs':feedback.get('missing_inputs',result.get('missing_inputs',[]))}
        with catalog.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT * FROM card_review_jobs WHERE id=?',(job['id'],)).fetchone()
            if current is None or dict(current)!=job or digest(path)!=job['card_sha256']:
                raise ValueError('材料准备期间卡片或任务变化，候选保留')
            human=db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='human_decision'",(job['paper_id'],)).fetchone()
            decision=db.execute('SELECT decision,asset_hash FROM papers WHERE id=?',(job['paper_id'],)).fetchone()
            if human or decision['decision']!='unreviewed' or decision['asset_hash']!=job['source_sha256'] or not queue.enabled(config):
                raise ValueError('入队时暂停、原文或人工保护变化')
            db.execute("UPDATE card_review_jobs SET id=?,folder=?,state='ready',error='图像与指纹材料已更新，等待复核；旧分数暂存',result=?,updated=? WHERE id=?",
                       (new_id,str(new_folder),json.dumps(retained,ensure_ascii=False),now(),job['id']))
            db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,?,?,?)",
                       (job['paper_id'],event_kind,json.dumps({'card_sha256':job['card_sha256'],'old_review_id':job['id'],'new_review_id':new_id,
                         'old_folder':str(old_folder),'new_packet_sha256':digest(new_folder/'packet.json'),'number':count+1,
                         'failure_kind':'completed_scientific_review' if cycle else 'material_repair'}),now()))
        return {'paper_id':job['paper_id'],'old_review_id':job['id'],'new_review_id':new_id,'state':'ready','number':count+1}


def supplement_visual(folder):
    import pymupdf
    folder=Path(folder);output=pymupdf.open();texts=[]
    with pymupdf.open(folder/'supplement.pdf') as source:
        if not len(source) or source.is_encrypted:raise ValueError('补充PDF不可读取')
        for index,page in enumerate(source):
            texts.append({'source_page':index+1,'text':page.get_text()})
            target=output.new_page(width=page.rect.width,height=page.rect.height+24)
            target.insert_text((8,16),f'Supplement PDF page {index+1}',fontsize=10)
            target.insert_image(pymupdf.Rect(0,24,page.rect.width,page.rect.height+24),pixmap=page.get_pixmap(dpi=220))
    output.save(folder/'supplement-visual.pdf',garbage=4,deflate=True);output.close()
    atomic_json(folder/'supplement-context.json',{'page_count':len(texts),'source_sha256':digest(folder/'supplement.pdf'),'source_text':texts})


# Included in local check keys to distinguish loaded code from newer disk bytes.
# Bump on semantic changes to repair/preparation recovery.
repair.recovery_revision='terminal-scientific-preparation-v7'

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--supplement-visual',required=True)
    supplement_visual(parser.parse_args().supplement_visual)
