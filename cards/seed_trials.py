"""Three source-only generations for the explicitly enrolled manual roots.

The existing material worker advances this durable state machine. No browser,
model, extra service, synthetic score or unknown-receipt retry is created here.
"""
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from core.api import paths__WorkspacePath as Path, services__atomic_json as atomic_json, catalog__now as now
from .web_card_inputs import digest


def _policy(config):
    policy=config.get('web_cards',{}).get('manual_seed_trials',{})
    if policy.get('enabled') is not True:return None
    if policy.get('rounds')!=3 or not isinstance(policy.get('paper_ids'),list):
        raise ValueError('手选种子仅授权固定三版及明确文献清单')
    sources=policy.get('sources',{})
    if (len(set(policy['paper_ids']))!=len(policy['paper_ids']) or set(sources)!=set(policy['paper_ids'])
            or any(not isinstance(value,str) or len(value)!=64 for value in sources.values())):
        raise ValueError('Fixed source fingerprints are missing or invalid')
    authorization=Path(policy['authorization'])
    if digest(authorization)!=policy['authorization_sha256']:
        raise ValueError('三版制卡授权指纹变化')
    return policy


def _path(catalog,pid):return catalog.path.parent/'manual_seed_trials'/pid/'run.json'


def _load(catalog,pid):
    path=_path(catalog,pid)
    return json.loads(path.read_text()) if path.exists() else None


def _save(catalog,run):
    run['updated_at']=time.time();atomic_json(_path(catalog,run['paper_id']),run)


def _lock(catalog):
    root=catalog.path.parent/'manual_seed_trials';root.mkdir(exist_ok=True)
    return (root/'state.lock').open('a')


def _source(catalog,pid):
    paper=catalog.get(pid)
    with catalog.connect() as db:
        root=db.execute('SELECT 1 FROM manual_seed_roots WHERE paper_id=?',(pid,)).fetchone()
        human=db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='human_decision'",(pid,)).fetchone()
    if not root or human or paper['decision']!='unreviewed':raise ValueError('非手选根种子或人工保护')
    if any(paper['metadata'].get(k) for k in ('identity_review_required','version_review_required','out_of_scope')):
        raise ValueError('原文身份、版本或范围待核对')
    if paper['acquisition']!='available' or digest(paper['asset_path'])!=paper['asset_hash']:
        raise ValueError('原文缺失或指纹变化')
    return paper


def _completed_receipt(path,attempt,packet):
    """Prove a missing archived prompt from its exact saved transport wrapper.

    Original files stay untouched. A temporary verification view contains only
    byte-identical saved evidence and a prefix matching the frozen prompt SHA.
    The existing complete-response validator still checks every other guard.
    """
    from .web_card_retry import finished_response
    try:
        finished_response(path,attempt,packet)
        return None if (path.parent.parent/'prompt.txt').exists() else 'exact_saved_wrapper_and_frozen_prompt_sha'
    except FileNotFoundError as exc:
        missing=path.parent.parent/'prompt.txt'
        if missing.exists() or exc.filename!=str(missing):raise
    from browser.api import web_upload_bundle__ZIP_INSTRUCTION as ZIP_INSTRUCTION
    actual=(path.parent/'prompt-actual.txt').read_bytes();wrapper=ZIP_INSTRUCTION.encode()
    if not actual.endswith(wrapper):raise ValueError('Archived prompt has no exact known transport wrapper')
    original=actual[:-len(wrapper)]
    if (hashlib.sha256(original).hexdigest()!=packet['input_hashes']['prompt.txt'] or
            hashlib.sha256(actual).hexdigest()!=attempt['actual_prompt_sha256']):
        raise ValueError('Archived prompt prefix differs from its frozen SHA')
    with tempfile.TemporaryDirectory(prefix='seed-receipt-proof-') as directory:
        view=Path(directory);provider=view/path.parent.name;provider.mkdir()
        for name in ('attempt.json','response-raw.txt','prompt-actual.txt'):
            shutil.copyfile(path.parent/name,provider/name)
        (view/'prompt.txt').write_bytes(original)
        finished_response(provider/'attempt.json',attempt,packet)
    return 'exact_saved_wrapper_and_frozen_prompt_sha'


def _receipt_proofs(root,source_hash):
    """Every old receipt must independently prove unsent or fully collected."""
    from .web_card_retry import known_unsent
    records=[]
    for path in sorted(root.rglob('attempt.json')):
        attempt=json.loads(path.read_text())
        prompt_proof=None
        if not known_unsent(attempt):
            packet=None
            for parent in path.parents:
                if parent==root.parent:break
                candidate=parent/'packet.json'
                if candidate.exists():
                    value=json.loads(candidate.read_text())
                    if value.get('input_hashes')==attempt.get('inputs'):
                        packet=value;break
            if not packet:
                # A committed reset moves the shared root packet into a sibling history.
                # Locate only one byte identity matching every original frozen input hash.
                matches={}
                for archived_packet in root.rglob('packet.json'):
                    raw=archived_packet.read_bytes();value=json.loads(raw)
                    if (value.get('input_hashes')==attempt.get('inputs') and
                            value.get('source_original_sha256')==source_hash):
                        matches[hashlib.sha256(raw).hexdigest()]=value
                if len(matches)==1:packet=next(iter(matches.values()))
                elif len(matches)>1:raise ValueError('同源冻结材料存在多个不同身份，保留待核对')
            if not packet or packet.get('source_original_sha256')!=source_hash:
                raise ValueError('原制卡回执缺少同源冻结材料；不新增请求')
            prompt_proof=_completed_receipt(path,attempt,packet)
        proof={'path':str(path.relative_to(root)),'sha256':digest(path)}
        if prompt_proof:proof['archived_prompt_proof']=prompt_proof
        records.append(proof)
    return records


def check_request(catalog,config,job,packet):
    """Final original-owner guard for a separately authorized generation."""
    trial=json.loads(job['selection']).get('manual_seed_trial')
    if not trial:return
    # Later ordinary source repairs retain provenance but have their own guard.
    if json.loads(job['selection']).get('rework',{}).get('kind')=='source_review':return
    policy=_policy(config);paper=_source(catalog,job['paper_id']);run=_load(catalog,job['paper_id'])
    if (not policy or job['paper_id'] not in policy['paper_ids'] or not run
            or run['state']!='generating' or run['id']!=trial['run_id'] or run['round']!=trial['round']
            or paper['asset_hash']!=policy['sources'][job['paper_id']] or run['source_sha256']!=job['source_sha256']):
        raise ValueError('Independent generation authorization changed')
    context=catalog.path.parent/'web_cards'/job['paper_id']/'source-context.json'
    if json.loads(context.read_text()).get('independent_request_id')!=trial['request_id']:
        raise ValueError('Independent request fingerprint mismatch')
    if packet['source_original_sha256']!=run['source_sha256']:raise ValueError('Independent source changed')


def archived_receipts(catalog,job):
    """Only exact, revalidated archives of a committed trial reset are exempt."""
    selection=json.loads(job['selection']);trial=selection.get('manual_seed_trial')
    if not trial:return []
    run=_load(catalog,job['paper_id'])
    if not run or run['id']!=trial['run_id'] or run['source_sha256']!=job['source_sha256']:
        raise ValueError('三版制卡登记与材料不一致')
    if selection.get('rework',{}).get('kind')!='source_review' and _source(catalog,job['paper_id'])['asset_hash']!=run['source_sha256']:
        raise ValueError('Trial source changed')
    root=catalog.path.parent/'web_cards'/job['paper_id']
    current={r['path']:r for r in _receipt_proofs(root,job['source_sha256'])}
    paths=[]
    for reset in run['resets']:
        if reset['state']=='not_started':continue
        if reset['state']!='committed':raise ValueError('三版材料归档尚未提交')
        for proof in reset['receipts']:
            if current.get(proof['path'])!=proof:raise ValueError('三版归档回执指纹变化')
            paths.append(root/proof['path'])
    return paths


def _idle(catalog,pid):
    """Local terminal labels never override a potentially active original receipt."""
    with catalog.connect() as db:
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'shared_page_backlog' in tables and db.execute("SELECT 1 FROM shared_page_backlog WHERE paper_id=? AND state='claimed'",(pid,)).fetchone():
            raise ValueError('原页面仍领取，等待唯一所有者释放')
        reviews=[dict(r) for r in db.execute('SELECT * FROM card_review_jobs WHERE paper_id=?',(pid,))]
        corrections=[dict(r) for r in db.execute('SELECT * FROM card_correction_jobs WHERE paper_id=?',(pid,))]
    from .web_card_retry import known_unsent
    for job in reviews:
        if job['state'] in ('submitting','submitted','response_saved','applying','preparing'):
            raise ValueError('原核验仍活动，先收取原回答')
        attempt=Path(job['folder'])/'attempt.json'
        if attempt.exists():
            receipt=json.loads(attempt.read_text())
            if not known_unsent(receipt) and receipt.get('state')!='response_saved':
                raise ValueError('原核验回执不确定，不新增请求')
        if job['state'] in ('queued','ready') and attempt.exists():
            raise ValueError('原核验入口已有回执，等待原所有者核对')
    if any(j['state'] not in ('applied','superseded') for j in corrections):
        raise ValueError('原修正尚未结束，先完成原任务')


def _schedule(catalog,config,run,paper):
    from .web_card_service import enabled
    if not enabled(config):raise ValueError('制卡暂停')
    pid=paper['id'];root=catalog.path.parent/'web_cards'/pid
    with catalog.connect() as db:
        row=db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone()
    if row is None:raise ValueError('等待原材料线程建立制卡任务')
    old=dict(row)
    if old.get('retry_at',0)>time.time():
        raise ValueError('Original retry backoff is still active')
    if old['state'] not in ('completed','queued','failed','needs_inspection'):
        raise ValueError('原制卡仍活动或重置中，先收取原回答')
    _idle(catalog,pid)
    proofs=_receipt_proofs(root,paper['asset_hash'])
    if (old['state']=='completed' or paper.get('card_path')) and not proofs:
        raise ValueError('没有完整原制卡回执，不以完成标签代替结束证据')
    number=len(run['candidates'])+1
    reset_id=run['id']+'-'+str(number)
    prior_intents=sum(row['round']==number for row in run['resets'])
    if prior_intents:reset_id+='-intent-'+str(prior_intents+1)
    history=root/'history'/('manual-seed-trial-'+reset_id);history.mkdir(parents=True,exist_ok=True)
    current_path=Path(paper['card_path']) if paper.get('card_path') else None
    before=digest(current_path) if current_path else None
    if current_path:
        backup=history/'previous-card';backup.mkdir(exist_ok=True)
        if not (backup/'card.json').exists():shutil.copy2(current_path,backup/'card.json')
        if digest(backup/'card.json')!=before:raise ValueError('前版卡片备份冲突')
    selection=json.loads(old['selection']);selection.pop('rework',None)
    selection['manual_seed_trial']={'run_id':run['id'],'round':number,'request_id':reset_id}
    if current_path:
        selection['rework']={'kind':'manual_seed_trial','old_card_path':str(current_path),
            'old_sha256':before,'backup':str(history/'previous-card'),'human_protected':False}
    names={Path(proof['path']).parts[0] for proof in proofs if 'history'!=Path(proof['path']).parts[0]}
    names.update(name for name in ('packet.json','prompt.txt','source-context.json','publication-intent.json','retry.json') if (root/name).exists())
    adjusted=[]
    for proof in proofs:
        relative=Path(proof['path'])
        target=history/relative if relative.parts[0] in names else root/relative
        adjusted.append({**proof,'path':str(target.relative_to(root))})
    reset={'state':'pending','round':number,'history':str(history),'names':sorted(names),
           'receipts':adjusted,'old_job':old,'selection':selection,'before':before,
           'old_card_path':paper.get('card_path')}
    run['resets'].append(reset);run['state']='reset_pending';_save(catalog,run)
    _finish_reset(catalog,config,run,paper)


def _finish_reset(catalog,config,run,paper):
    from .web_card_service import enabled
    if not enabled(config):raise ValueError('制卡暂停；保留归档意图')
    pid=paper['id'];reset=run['resets'][-1];root=catalog.path.parent/'web_cards'/pid;history=Path(reset['history'])
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current=dict(db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone())
        changed_card=(paper.get('card_path')!=reset['old_card_path'] or
            reset['before'] and digest(paper['card_path'])!=reset['before'])
        changed_job=(current!=reset['old_job'] and current['state']!='seed_trial_reset_pending'
            and current['selection']!=json.dumps(reset['selection'],ensure_ascii=False))
        if changed_card or changed_job:
            if any((history/name).exists() for name in reset['names']):
                raise ValueError('已开始归档后原状态变化，保留证据')
            # No working file was touched. Keep the aborted intent, then wait
            # for the newly observed original task rather than freezing forever.
            reset['state']='not_started';run['state']='reviewed' if run['candidates'] else 'waiting';_save(catalog,run);return
        if current['selection']==json.dumps(reset['selection'],ensure_ascii=False) and current['state']=='queued':
            reset['state']='committed';run['state']='generating';run['round']=reset['round'];_save(catalog,run);return
        if current==reset['old_job']:
            # Retire only unused old review preparation in the same write
            # transaction as the reset barrier. An owner claim that won the
            # race remains protected; a later claim sees superseded instead.
            _idle(catalog,pid)
            db.execute("UPDATE card_review_jobs SET state='superseded',error='User authorized independent seed candidates; unused review retained' WHERE paper_id=? AND state IN ('queued','ready')",(pid,))
            tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'shared_page_backlog' in tables:
                db.execute("DELETE FROM shared_page_backlog WHERE paper_id=? AND lane='review' AND state='queued'",(pid,))
            db.execute("UPDATE web_card_jobs SET state='seed_trial_reset_pending' WHERE paper_id=?",(pid,))
        elif current['state']!='seed_trial_reset_pending' or current['selection']!=reset['old_job']['selection']:
            raise ValueError('原制卡账本在归档期间变化')
    from core.api import archive_paths__move_with_links as move_with_links
    for name in reset['names']:
        source=root/name;destination=history/name
        if (source.is_dir() and not source.is_symlink()) or (destination.parent/('.'+destination.name+'.links-move.json')).exists():
            move_with_links(source,destination)
        elif source.exists() or source.is_symlink():
            if destination.exists():
                if digest(source)!=digest(destination):raise ValueError('三版归档文件冲突')
                source.unlink()
            else:os.replace(source,destination)
    for proof in reset['receipts']:
        if digest(root/proof['path'])!=proof['sha256']:raise ValueError('三版归档回执校验失败')
    retry=history/'retry.json'
    if retry.exists() and not (root/'retry.json').exists():
        old=json.loads(retry.read_text());retained={key:old[key] for key in ('external_retries','delivery_repair','structure_repair') if key in old}
        atomic_json(root/'retry.json',{**retained,'state':'independent_seed_round','prior_ledger':str(retry)})
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        fresh=dict(db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone())
        if fresh['state']!='seed_trial_reset_pending' or _source(catalog,pid)['asset_hash']!=run['source_sha256']:
            raise ValueError('重置期间原文或账本变化')
        # Only never-sent old preparation is retired, with its original row kept.
        for row in db.execute("SELECT id,folder FROM card_review_jobs WHERE paper_id=? AND state IN ('queued','ready')",(pid,)):
            if (Path(row['folder'])/'attempt.json').exists():raise ValueError('旧核验出现新回执')
        db.execute("UPDATE card_review_jobs SET state='superseded',error='用户授权三版独立制卡；旧未发送核验保留' WHERE paper_id=? AND state IN ('queued','ready')",(pid,))
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'web_page_queue' in tables:db.execute('DELETE FROM web_page_queue WHERE paper_id=?',(pid,))
        if 'shared_page_backlog' in tables:db.execute("DELETE FROM shared_page_backlog WHERE paper_id=? AND state='queued'",(pid,))
        db.execute("UPDATE web_card_jobs SET state='queued',selection=?,retry_at=0,error='',updated=? WHERE paper_id=?",
            (json.dumps(reset['selection'],ensure_ascii=False),now(),pid))
    reset['state']='committed';run['state']='generating';run['round']=reset['round'];_save(catalog,run)


def record_review(catalog,config,job,result):
    """Save the real review before ordinary repair; do not award a pass here."""
    policy=_policy(config)
    if not policy or job['paper_id'] not in policy['paper_ids']:return False
    from review.api import card_review_queue__current as current,card_review_queue__protected as protected,card_review_queue__enabled as enabled,card_review_queue as review_queue
    if not enabled(config):raise ValueError('核验暂停')
    with _lock(catalog) as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        run=_load(catalog,job['paper_id'])
        if not run:return False
        captured=next((row for row in run['candidates'] if row['review_id']==job['id']),None)
        if captured and run['state']=='selecting' and run.get('winner')==captured['round']:return False
        if not captured and run['state'] not in ('generating','reviewing','reviewed'):return False
        paper,path,card=current(catalog,job,config)
        if protected(catalog,paper):raise ValueError('人工保护')
        trial=card.get('meta',{}).get('selection',{}).get('manual_seed_trial',{})
        number=captured['round'] if captured else run['round']
        if trial.get('run_id')!=run['id'] or trial.get('round')!=number:return False
        folder=Path(job['folder']);packet=review_queue.check_packet(folder)
        attempt=json.loads((folder/'attempt.json').read_text())
        if (attempt.get('state')!='response_saved' or attempt.get('raw_sha256')!=digest(folder/'response-raw.txt')
                or attempt.get('inputs')!=packet['input_hashes'] or attempt.get('actual_prompt_sha256')!=packet['actual_prompt_sha256']
                or not attempt.get('conversation_url','').startswith('https://chatgpt.com/c/')
                or 'local-chatgpt' in attempt.get('conversation_url','')):
            raise ValueError('三版核验尚无完整正式回执')
        parsed,assessment=review_queue.parse_review((folder/'response-raw.txt').read_text(),folder,
            optional_external_supplements=config.get('review_standard',{}).get('external_supplements_optional') is True)
        if parsed!=json.loads((folder/'feedback.json').read_text()) or any(result.get(k)!=assessment.get(k) for k in
                ('weighted_score','pass','model_report_pass','verdict','scores','issue_counts','full_source_checked','missing_inputs')):
            raise ValueError('三版核验与原始报告不一致，不接受替代评分')
        existing=captured or next((r for r in run['candidates'] if r['round']==number),None)
        candidate={'round':number,'card_path':str(path),'card_sha256':job['card_sha256'],
            'review_id':job['id'],'review_folder':job['folder'],'assessment':result,
            'report_sha256':digest(Path(job['folder'])/'feedback.json')}
        if existing and existing!=candidate:raise ValueError('三版同轮核验冲突；保留原回执')
        if not existing:
            run['candidates'].append(candidate)
            run['state']='reviewed';_save(catalog,run)
        from review.api import card_review_queue__update as update
        update(catalog,job['id'],'trial_reviewed','三版候选核验已保存，等待全部三版择优',result)
        return True


def choose(candidates):
    """Only complete real passing reports compete; no score is manufactured."""
    def passed(row):
        a=row['assessment'];score=a.get('weighted_score');issues=a.get('issue_counts',{})
        return (a.get('pass') is True and a.get('model_report_pass',a.get('pass')) is True
            and a.get('action')=='pass' and a.get('verdict')=='pass' and a.get('full_source_checked') is True
            and type(score) in (int,float) and 85<=score<=100 and a.get('missing_inputs')==[]
            and issues.get('major')==0 and issues.get('critical')==0)
    eligible=[row for row in candidates if passed(row)]
    if not eligible:return None
    return max(eligible,key=lambda row:(row['assessment']['weighted_score'],-row['round']))


def run_once(catalog,config):
    policy=_policy(config)
    if not policy:return {'state':'disabled'}
    from .web_card_service import enabled
    from review.api import card_review_queue__enabled as reviews_enabled
    if not enabled(config) or not reviews_enabled(config):return {'state':'paused'}
    from review.api import card_review_queue as review_queue
    from correction.api import card_correction_queue as correction_queue
    review_queue.install(catalog);correction_queue.install(catalog)
    report={'checked_at':time.time(),'items':[]};finalize=[]
    with _lock(catalog) as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'state':'another_check_running'}
        for pid in policy['paper_ids']:
            try:
                paper=_source(catalog,pid)
                if paper['asset_hash']!=policy['sources'][pid]:raise ValueError('Source version is outside the frozen scope')
                run=_load(catalog,pid)
                if run is None:
                    run={'id':hashlib.sha256((pid+paper['asset_hash']+policy['authorization_sha256']).encode()).hexdigest()[:24],
                        'paper_id':pid,'title':paper['title'],'source_sha256':paper['asset_hash'],'state':'waiting','candidates':[],
                        'resets':[],'baseline_card_path':paper.get('card_path'),'created_at':time.time()}
                    _save(catalog,run)
                if run['source_sha256']!=paper['asset_hash']:raise ValueError('原文版本变化；本轮不扩展')
                if run['state']=='reviewed' and run['candidates']:
                    captured=run['candidates'][-1]
                    with catalog.connect() as db:
                        row=db.execute('SELECT state,result FROM card_review_jobs WHERE id=?',(captured['review_id'],)).fetchone()
                        if row and row['state']=='applying' and json.loads(row['result'])==captured['assessment']:
                            if digest(Path(captured['review_folder'])/'feedback.json')!=captured['report_sha256'] or digest(captured['card_path'])!=captured['card_sha256']:
                                raise ValueError('原候选报告变化，保留回执')
                            db.execute("UPDATE card_review_jobs SET state='trial_reviewed' WHERE id=?",(captured['review_id'],))
                if run['state'] in ('selected','repairing'):continue
                if run['state']=='reset_pending':_finish_reset(catalog,config,run,paper)
                elif run['state'] in ('waiting','reviewed') and len(run['candidates'])<3:_schedule(catalog,config,run,paper)
                elif run['state']=='reviewed' and len(run['candidates'])==3:
                    _idle(catalog,pid)
                    winner=choose(run['candidates'])
                    if winner is None:
                        # This is only the input for normal repair, never a passing winner.
                        winner=max(run['candidates'],key=lambda r:(r['assessment'].get('full_source_checked') is True,
                            r['assessment'].get('weighted_score') if type(r['assessment'].get('weighted_score')) in (int,float) else -1,-r['round']))
                        run['selection_kind']='repair_input'
                    else:run['selection_kind']='passing_winner'
                    run['winner']=winner['round'];run['state']='selecting';_save(catalog,run)
                if run['state']=='selecting':finalize.append(pid)
                report['items'].append({'paper_id':pid,'state':run['state'],'reviewed':len(run['candidates'])})
            except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
                report['items'].append({'paper_id':pid,'state':'waiting_original_evidence','reason':str(exc)[:600]})
    for pid in finalize:
        try:_finalize(catalog,config,pid)
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
            report['items'].append({'paper_id':pid,'state':'selection_pending','reason':str(exc)[:600]})
    atomic_json(catalog.path.parent/'manual-seed-trials-status.json',report)
    return report


def _finalize(catalog,config,pid):
    from review.api import card_review_queue__apply_result as apply_result
    run=_load(catalog,pid);winner=next(row for row in run['candidates'] if row['round']==run['winner'])
    path=Path(winner['card_path']);folder=Path(winner['review_folder'])
    if digest(folder/'feedback.json')!=winner['report_sha256']:raise ValueError('择优原报告变化')
    paper=_source(catalog,pid);_idle(catalog,pid)
    with catalog.connect() as db:
        job=dict(db.execute('SELECT * FROM card_review_jobs WHERE id=?',(winner['review_id'],)).fetchone())
    if job['state']=='passed':
        meta=json.loads(path.read_text()).get('meta',{});review=meta.get('source_review',{})
        if (run['selection_kind']!='passing_winner' or paper.get('card_path')!=str(path)
                or meta.get('scientific_verified') is not True or review.get('job_id')!=winner['review_id']
                or review.get('report_sha256')!=winner['report_sha256']
                or review.get('card_sha256')!=winner['card_sha256']):
            raise ValueError('择优发布恢复证据不完整')
    elif run['selection_kind']=='repair_input' and job['state'] in ('correction_queued','rework_queued','failed','needs_user'):
        # The original result handler already accepted this exact saved report.
        if json.loads(job['result']).get('weighted_score')!=winner['assessment'].get('weighted_score'):
            raise ValueError('原修正入口报告变化')
    else:
        if digest(path)!=winner['card_sha256'] or job['state']!='trial_reviewed':
            raise ValueError('择优卡片或原核验状态变化')
        with catalog.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            cursor=db.execute('UPDATE papers SET card_path=? WHERE id=? AND card_path IS ? AND asset_hash=? AND decision=?',
                (str(path),pid,paper.get('card_path'),run['source_sha256'],'unreviewed'))
            if cursor.rowcount!=1:raise ValueError('择优期间正式指针变化')
        apply_result(catalog,job,config)
        with catalog.connect() as db:
            final_state=db.execute('SELECT state FROM card_review_jobs WHERE id=?',(winner['review_id'],)).fetchone()[0]
        if run['selection_kind']=='passing_winner' and final_state!='passed':
            raise ValueError('择优仍未通过原发布守卫')
    with _lock(catalog) as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        run=_load(catalog,pid);run['state']='selected' if run['selection_kind']=='passing_winner' else 'repairing';_save(catalog,run)


def status(config):
    """Read-only progress; queued rounds are never counted as generated answers."""
    policy=_policy(config)
    if not policy:return []
    root=Path(config['catalog_path']).parent/'manual_seed_trials';items=[]
    from core.api import seed_focus__status as seed_tracking
    traces={r['paper_id']:r for r in seed_tracking(config).get('items',[])}
    for pid in policy['paper_ids']:
        path=root/pid/'run.json'
        if not path.exists():
            items.append({'paper_id':pid,'state':'waiting','reviewed':0,'round':0});continue
        run=json.loads(path.read_text());candidates=run.get('candidates',[])
        if traces.get(pid,{}).get('error') and not traces[pid].get('complete'):run={**run,'state':'blocked'}
        items.append({'paper_id':pid,'title':run.get('title',pid),'state':run['state'],
            'reviewed':len(candidates),'round':run.get('round',0),'winner':run.get('winner'),
            'blocking_reason':traces.get(pid,{}).get('error',''),
            'scores':[row['assessment'].get('weighted_score') for row in candidates],
            'result_path':str(path)})
    return items
