"""One explicitly authorized source-only regeneration with a new format packet."""
import fcntl
import json
import os
import re
import shutil
import time
import zipfile
import hashlib
from core.api import paths__WorkspacePath as Path
from core.api import catalog__Catalog as Catalog, catalog__now as now
from core.api import services__atomic_json as atomic_json
from .web_card_inputs import digest
from .web_card_retry import eligible, frozen_inputs, known_unsent


def saved(path, attempt, packet, original_prompt):
    if attempt.get('state') != 'response_saved' or attempt.get('inputs') != packet['input_hashes']:
        raise ValueError('原请求不完整或输入归属变化')
    from browser.api import web_upload_bundle__ZIP_INSTRUCTION as ZIP_INSTRUCTION
    raw = path.parent/'response-raw.txt';prompt = path.parent/'prompt-actual.txt'
    if (not raw.read_text().strip() or digest(raw) != attempt.get('raw_sha256')
            or digest(prompt) != attempt.get('actual_prompt_sha256')
            or prompt.read_text() not in (original_prompt, original_prompt+ZIP_INSTRUCTION)):
        raise ValueError('原回答或实际提示变化')
    url = attempt.get('conversation_url', '')
    if not url.startswith('https://chatgpt.com/c/') or 'local-chatgpt' in url:
        raise ValueError('原请求没有唯一正式会话回执')
    if prompt.read_text() != original_prompt:
        from codex_desktop_chat.api import bundles__verify_bundle as verify_bundle
        bundle = attempt.get('upload_bundle', {})
        if verify_bundle(Path(bundle['zip_path']))['zip_sha256'] != bundle['zip_sha256']:
            raise ValueError('原ZIP指纹变化')


def authorized_archives(folder, repair):
    """Only the exact immutable old receipts bound by this single-use grant."""
    if not repair:return set()
    folder = Path(folder).resolve()
    if repair.get('used') != 1 or repair.get('state') != 'scheduled':
        raise ValueError('专项格式修复未完整登记，保留原回执')
    auth_path = Path(repair['authorization_path'])
    if auth_path.parent != folder.parent.parent/'audit_index' or digest(auth_path) != repair['authorization_sha256']:
        raise ValueError('格式修复授权清单变化')
    auth = json.loads(auth_path.read_text())
    if auth.get('kind') != 'human_one_extra_structure_retry' or auth.get('max_extra_per_paper') != 1:
        raise ValueError('缺少明确单次格式修复授权')
    item = next(x for x in auth['requests'] if x['paper_id'] == folder.name)
    history = Path(repair['history']).resolve()
    if (history != folder/'history'/('structure-repair-'+auth['authorization_id'])
            or digest(history/'packet.json') != item['old_frozen_packet_sha256']
            or digest(folder/'packet.json') != item['candidate_packet_sha256']):
        raise ValueError('旧输入归档或候选输入变化')
    packet = json.loads((history/'packet.json').read_text())
    if any(digest(history/n) != h for n,h in packet['input_hashes'].items()):
        raise ValueError('旧冻结材料归档变化')
    primary = history/'chatgpt/attempt.json'
    if digest(primary) != item['old_attempt_sha256']:
        raise ValueError('原正式回答归档变化')
    primary_record = json.loads(primary.read_text())
    if primary_record['raw_sha256'] != item['old_response_sha256']:
        raise ValueError('专项授权未绑定本回答')
    excluded = set();original_prompt = (history/'prompt.txt').read_text()
    for record in repair['receipts']:
        path = Path(record['path']).resolve()
        if not path.is_relative_to(folder/'history') or digest(path) != record['sha256']:
            raise ValueError('历史回执归档路径或指纹变化')
        attempt = json.loads(path.read_text())
        if not known_unsent(attempt):saved(path, attempt, packet, original_prompt)
        excluded.add(path)
    if primary not in excluded:raise ValueError('缺少原完整回答归档')
    return excluded


def schedule(config, authorization_path):
    """Freeze/queue once; no browser calls, ordinary counters or scientific edits."""
    from .web_card_service import enabled
    from browser.api import attempt_history__submission_history as submission_history
    from codex_desktop_chat.api import bundles__verify_bundle as verify_bundle
    catalog = Catalog(config['catalog_path']);root = catalog.path.parent.resolve()
    manifest = Path(authorization_path).resolve();auth = json.loads(manifest.read_text())
    if (manifest.parent != root/'audit_index' or auth.get('kind') != 'human_one_extra_structure_retry'
            or auth.get('max_extra_per_paper') != 1
            or not re.fullmatch(r'[a-zA-Z0-9_-]+', auth.get('authorization_id', ''))):
        raise ValueError('缺少本项目单次格式修复授权')
    auth_hash = digest(manifest);results = []
    with (root/'web-card-retry.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        for item in auth['requests']:
            pid = item['paper_id'];folder = root/'web_cards'/pid;active = folder/'chatgpt/attempt.json'
            with catalog.connect() as db:job = dict(db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone())
            if not enabled(config) or job['state'] != 'failed':raise ValueError('暂停或原失败状态变化')
            ledger_path = folder/'retry.json';ledger = json.loads(ledger_path.read_text())
            if ledger.get('structure_repair'):raise ValueError('专项格式次数已登记，不重复安排')
            if ledger.get('external_retries') != 2 or ledger.get('delivery_repair',{}).get('used') != 1:
                raise ValueError('原重试及首次专项计数变化')
            paper = eligible(catalog,job,config);packet = json.loads((folder/'packet.json').read_text())
            frozen_inputs(folder,packet,paper)
            if digest(folder/'packet.json') != item['old_frozen_packet_sha256'] or digest(active) != item['old_attempt_sha256']:
                raise ValueError('授权对应原输入或回执变化')
            if list(folder.glob('*/attempt.json')) != [active]:raise ValueError('存在其他当前请求')
            attempt = json.loads(active.read_text());saved(active,attempt,packet,(folder/'prompt.txt').read_text())
            if attempt['raw_sha256'] != item['old_response_sha256']:raise ValueError('授权对应原回答变化')
            if not submission_history(folder,exclude_paths=[active]).allowed:raise ValueError('历史回执仍不确定')
            candidate = Path(item['candidate_folder']);new_packet = json.loads((candidate/'packet.json').read_text())
            if digest(candidate/'packet.json') != item['candidate_packet_sha256']:
                raise ValueError('候选材料指纹变化')
            original_context = json.loads((folder/'source-context.json').read_text())
            new_context = json.loads((candidate/'source-context.json').read_text())
            from .web_card_inputs import SCHEMA
            if (new_packet['source_original_sha256'] != packet['source_original_sha256']
                    or new_packet['page_manifest'] != packet['page_manifest']
                    or new_context['source_text'] != original_context['source_text']
                    or new_context['schema'] != SCHEMA
                    or new_packet['upload_bundle'] != item['candidate_bundle']
                    or any(digest(candidate/n) != h for n,h in new_packet['input_hashes'].items())
                    or any(new_packet['input_hashes'][n] != packet['input_hashes'][n] for n in ('source.pdf','visual.pdf'))
                    or verify_bundle(Path(item['candidate_bundle']['zip_path']))['zip_sha256'] != item['candidate_bundle']['zip_sha256']):
                raise ValueError('新单ZIP或绑定原文/视觉证据变化')
            with zipfile.ZipFile(item['candidate_bundle']['zip_path']) as archive:
                if (set(archive.namelist()) != {'source.pdf','visual.pdf','source-context.json','_upload_manifest.json'}
                        or any(hashlib.sha256(archive.read(n)).hexdigest() != new_packet['input_hashes'][n]
                               for n in ('source.pdf','visual.pdf','source-context.json'))):
                    raise ValueError('候选ZIP不是冻结原文/空白结构副本')
            history = folder/'history'/('structure-repair-'+auth['authorization_id'])
            if history.exists():raise ValueError('归档已存在，保留待核对')
            receipts = []
            for path in folder.rglob('attempt.json'):
                record = json.loads(path.read_text())
                if not known_unsent(record):saved(path,record,packet,(folder/'prompt.txt').read_text())
                destination = history/'chatgpt/attempt.json' if path == active else path
                receipts.append({'path':str(destination),'sha256':digest(path)})
            with catalog.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                fresh = db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone()
                if (dict(fresh) != job or not enabled(config) or digest(manifest) != auth_hash
                        or json.loads(ledger_path.read_text()) != ledger or digest(active) != item['old_attempt_sha256']):
                    raise ValueError('任务/暂停/授权或回执并发变化')
                eligible(catalog,job,config);frozen_inputs(folder,packet,paper)
                repair = {'used':1,'state':'preparing','authorization_path':str(manifest),'authorization_sha256':auth_hash,
                          'history':str(history),'receipts':receipts,'scheduled_at':now()}
                ledger['structure_repair'] = repair;atomic_json(ledger_path,ledger)
                history.mkdir(parents=True)
                for name in [*packet['input_hashes'],'packet.json']:
                    shutil.copy2(folder/name,history/name)
                folder.joinpath('chatgpt').rename(history/'chatgpt')
                for name in [*new_packet['input_hashes'],'packet.json']:
                    staging = folder/('.structure-repair-'+name);shutil.copy2(candidate/name,staging);os.replace(staging,folder/name)
                repair['state'] = 'scheduled';atomic_json(ledger_path,ledger)
                authorized_archives(folder,repair)
                db.execute("UPDATE web_card_jobs SET state='queued',error='专项格式修复额外1次：原2次及附件专项计数保留',retry_at=?,updated=? WHERE paper_id=?",
                           (time.time()+300,now(),pid))
                db.execute("UPDATE web_page_queue SET state='waiting',error='' WHERE paper_id=?",(pid,))
                db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'authorized_structure_repair_scheduled',?,?)",
                           (pid,json.dumps(repair),now()))
            results.append({'paper_id':pid,'state':'queued','structure_repair_used':1,'external_retries':2,'delivery_repair_used':1})
    return results
