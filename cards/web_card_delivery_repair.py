"""Explicit one-off delivery retries; source answers and ordinary limits persist."""
import fcntl
import json
import re
import time
from core.api import paths__WorkspacePath as Path
from core.api import catalog__Catalog as Catalog, catalog__now as now
from core.api import services__atomic_json as atomic_json
from .web_card_inputs import digest, check_material_delivery, MaterialDeliveryError
from .web_card_retry import eligible, frozen_inputs, finished_response


def _check_delivery(raw):
    from .web_card_json import normalize
    text=re.sub(r'^JSON\s+(?=\{)','',normalize(raw).strip())
    if text.startswith('```') and text.endswith('```'):
        text='\n'.join(text.splitlines()[1:-1])
    try:card=json.loads(text)
    except ValueError:card=None
    check_material_delivery(raw,card)


def authorized_archive(path, attempt, repair):
    """An archived completed delivery failure has one bound human authorization."""
    if not isinstance(repair,dict) or repair.get('used')!=1:return False
    history=Path(repair['history']).resolve()
    if path.resolve()!=history/'chatgpt/attempt.json':return False
    manifest=Path(repair['authorization_path'])
    if manifest.resolve().parent!=history.parent.parent.parent.parent/'audit_index':return False
    if not manifest.is_file() or digest(manifest)!=repair['authorization_sha256']:return False
    data=json.loads(manifest.read_text())
    if data.get('kind')!='human_one_extra_delivery_retry' or data.get('max_extra_per_paper')!=1:return False
    pid=history.parent.parent.name
    item=next((r for r in data['requests'] if r['paper_id']==pid),None)
    if (item is None or attempt.get('inputs')!=item['old_inputs']
            or attempt.get('raw_sha256')!=item['old_response_sha256']):return False
    packet=json.loads((history.parent.parent/'packet.json').read_text())
    raw=finished_response(path,attempt,packet)
    try:_check_delivery(raw)
    except MaterialDeliveryError:return True
    return False


def schedule(config, authorization_path):
    """Archive and queue only the specified, unchanged complete delivery failures.

    Never opens a browser or modifies frozen input/scientific content. A durable
    used marker precedes archiving; ambiguous interrupted repairs do not repeat.
    """
    from .web_card_service import enabled
    from browser.api import attempt_history__submission_history as submission_history
    from codex_desktop_chat.api import bundles__verify_bundle as verify_bundle
    manifest=Path(authorization_path).resolve();auth=json.loads(manifest.read_text())
    if auth.get('kind')!='human_one_extra_delivery_retry' or auth.get('max_extra_per_paper')!=1:
        raise ValueError('缺少单次材料修复授权')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',auth.get('authorization_id','')):
        raise ValueError('材料修复授权标识无效')
    catalog=Catalog(config['catalog_path']);root=catalog.path.parent.resolve()
    if manifest.parent!=root/'audit_index':raise ValueError('材料修复授权必须为本目录独立审计记录')
    if not enabled(config):raise ValueError('制卡已暂停，不安排额外重试')
    auth_hash=digest(manifest);results=[]
    with (root/'web-card-retry.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for item in auth['requests']:
            pid=item['paper_id'];folder=root/'web_cards'/pid;path=folder/'chatgpt/attempt.json'
            with catalog.connect() as db:job=dict(db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone())
            if job['state']!='needs_inspection':raise ValueError('原材料故障状态变化：'+pid)
            ledger_path=folder/'retry.json';ledger=json.loads(ledger_path.read_text())
            if ledger.get('delivery_repair'):raise ValueError('单次材料修复已登记，不重复安排：'+pid)
            packet=json.loads((folder/'packet.json').read_text());paper=eligible(catalog,job,config)
            frozen_inputs(folder,packet,paper)
            attempt=json.loads(path.read_text());attempt_hash=digest(path)
            if list(folder.glob('*/attempt.json'))!=[path]:raise ValueError('存在其他原请求，保留核对')
            if packet['input_hashes']!=item['old_inputs'] or attempt['raw_sha256']!=item['old_response_sha256']:
                raise ValueError('授权材料或回答指纹变化')
            raw=finished_response(path,attempt,packet)
            try:_check_delivery(raw)
            except MaterialDeliveryError:pass
            else:raise ValueError('不是明确材料投递失败，不执行额外生成')
            bundle=item['candidate_bundle'];verified=verify_bundle(Path(bundle['zip_path']))
            if verified['zip_sha256']!=bundle['zip_sha256']:raise ValueError('修复ZIP已变化')
            import zipfile,hashlib
            with zipfile.ZipFile(bundle['zip_path']) as z:
                if any(hashlib.sha256(z.read(n)).hexdigest()!=packet['input_hashes'][n] for n in packet['files']):
                    raise ValueError('修复ZIP与冻结原文材料不同')
            # This is a new transport wrapper for old pre-ZIP delivery failures.
            if attempt.get('upload_bundle') or (path.parent/'prompt-actual.txt').read_text()!=(folder/'prompt.txt').read_text():
                raise ValueError('原请求已使用ZIP/其他传输，不能按本次授权重复同输入')
            if not submission_history(folder,exclude_paths=[path]).allowed:raise ValueError('历史请求仍不确定')
            history=folder/'history'/('delivery-repair-'+auth['authorization_id'])
            if history.exists():raise ValueError('修复归档已存在，不重复安排')
            with catalog.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                current=db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone()
                if dict(current)!=job or not enabled(config) or digest(manifest)!=auth_hash:
                    raise ValueError('任务/暂停/授权已变化')
                eligible(catalog,job,config);frozen_inputs(folder,packet,paper)
                if digest(path)!=attempt_hash or json.loads(ledger_path.read_text())!=ledger:
                    raise ValueError('原回执或重试账本并发变化')
                finished_response(path,attempt,packet)
                repair={'used':1,'authorization_path':str(manifest),'authorization_sha256':auth_hash,
                    'history':str(history),'scheduled_at':now(),'old_attempt_sha256':attempt_hash,
                    'bundle_sha256':bundle['zip_sha256']}
                ledger.update(delivery_repair=repair,state='scheduled',retry_at=time.time()+300,
                    reason='用户单次授权：旧附件缺失，已核对单ZIP修复')
                atomic_json(ledger_path,ledger)
                history.mkdir(parents=True,exist_ok=False);path.parent.rename(history/'chatgpt')
                db.execute("UPDATE web_card_jobs SET state='queued',retry_at=?,error=?,updated=? WHERE paper_id=?",
                    (ledger['retry_at'],'材料修复额外1次：原2次计数保留；等待单ZIP派发',now(),pid))
                db.execute("INSERT INTO events(paper_id,kind,payload,created) VALUES(?,'authorized_delivery_repair_scheduled',?,?)",
                    (pid,json.dumps(repair),now()))
            results.append({'paper_id':pid,'state':'queued','retry_at':ledger['retry_at']})
    return results
