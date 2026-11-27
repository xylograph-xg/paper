"""Detached web-only generation keeper, independent of UI and local model lanes."""
import argparse
import fcntl
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from core.api import paths__WorkspacePath as Path
from core.api import catalog__ROOT as ROOT, catalog__Catalog as Catalog, catalog__load_config as load_config, catalog__now as now
from core.api import services__atomic_json as atomic_json
from core.api import runtime__alive as alive
from . import web_card_queue as queue


EXTERNAL_MODULES = (('dependency:web_gpt.core', 'web_gpt/core.py'),
                    ('dependency:web_gpt.package', 'web_gpt/__init__.py'),
                    ('dependency:web_gpt.zip_uploads', 'web_gpt/zip_uploads.py'))


def external_dependencies():
    """Fingerprint the kernel outside this repository that the owner runs on.

    The registered implementation path is the source of truth; the module the
    process actually loaded must match it, otherwise the acceptance receipt
    would describe code that is not running.
    """
    import hashlib
    import sys
    from core.api import paths__workspace_root as workspace_root
    root = workspace_root()
    report = {'status': 'ok', 'import_root': None, 'sdk_version': None,
              'files': {}, 'hashes': {}, 'errors': []}

    def unavailable(path, reason):
        report['status'] = 'incomplete'
        report['errors'].append(reason + '：' + str(path)[:200])
        return hashlib.sha256(('unavailable:' + str(path)).encode()).hexdigest()

    entry = None
    try:
        registry = json.loads((root / 'infrastructure' / 'tool-dependencies.json').read_text())
        entry = next((item for item in registry.get('tools', []) if item.get('id') == 'web_gpt'), None)
        if entry is None:
            raise ValueError('条目缺失')
    except (OSError, ValueError, TypeError) as exc:
        report['status'] = 'incomplete'
        report['errors'].append('外部登记不可读：' + str(exc)[:200])
    package_dir = Path(entry['source_dir']).resolve() if entry and entry.get('source_dir') else None
    registered_root = Path(entry['python_import_root']).resolve() if entry and entry.get('python_import_root') else (
        package_dir.parent if package_dir is not None else None)
    environment = (entry or {}).get('environment') or {}
    override = os.environ.get('WEB_GPT_IMPORT_ROOT') or environment.get('WEB_GPT_IMPORT_ROOT')
    import_root = Path(override).resolve() if override else registered_root
    if package_dir is not None and registered_root is not None and override:
        # An explicit import root that is not the registered one means the owner
        # would fingerprint code different from the code it declares it runs.
        if Path(override).resolve() / 'web_gpt' != package_dir and Path(override).resolve() != registered_root:
            report['status'] = 'incomplete'
            report['errors'].append('WEB_GPT_IMPORT_ROOT 与登记实现路径不同：' + str(override)[:200])
    report['import_root'] = str(import_root) if import_root else None
    if import_root is None:
        report['status'] = 'incomplete'
        report['errors'].append('web_gpt 导入根未登记')
    try:
        import importlib.metadata as metadata
        report['sdk_version'] = metadata.version('playwright')
    except Exception as exc:
        report['status'] = 'incomplete'
        report['errors'].append('Playwright SDK 版本不可读：' + type(exc).__name__)
    targets = [(key, Path(import_root) / relative) for key, relative in EXTERNAL_MODULES] if import_root else []
    if not import_root:
        report['status'] = 'incomplete'
        report['errors'].append('web_gpt 导入根未登记')
    targets.append(('dependency:codex_desktop_chat.bundles', root / 'codex_desktop_chat' / 'bundles.py'))
    if report['sdk_version']:
        report['hashes']['dependency:playwright.sdk'] = hashlib.sha256(
            report['sdk_version'].encode()).hexdigest()
    else:
        report['hashes']['dependency:playwright.sdk'] = unavailable('playwright', 'SDK 版本缺失')
    core_path = None
    for key, path in targets:
        try:
            report['files'][key] = str(path.resolve())
            report['hashes'][key] = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            report['hashes'][key] = unavailable(path, '实现文件不可读')
        if key == 'dependency:web_gpt.core':
            core_path = path
    loaded = sys.modules.get('web_gpt.core')
    loaded_file = getattr(loaded, '__file__', None)
    if core_path is not None and loaded_file:
        try:
            if Path(loaded_file).resolve() != core_path:
                report['status'] = 'incomplete'
                report['errors'].append('实际加载内核与登记路径不同：' + str(loaded_file)[:200])
        except OSError:
            report['status'] = 'incomplete'
            report['errors'].append('实际加载内核不可解析')
    return report


def code_version():
    """Capture once at owner startup, never label a running owner with new code."""
    import hashlib
    from core.api import concurrency_control
    from core.api import paths__workspace_root as workspace_root
    workspace=json.loads((workspace_root()/'workspace.json').read_text())
    hashes={}
    # Fingerprint real physical packages, not obsolete pipeline aliases.
    for project in ('cards','browser','core','review','correction'):
        folder=workspace_root()/workspace['projects'][project]['path']
        for source in sorted(folder.glob('*.py')):
            hashes[str(source.relative_to(workspace_root()))]=hashlib.sha256(source.read_bytes()).hexdigest()
    intake = workspace_root()/workspace['projects']['reading']['path']/'manual_literature.py'
    hashes[str(intake.relative_to(workspace_root()))] = hashlib.sha256(intake.read_bytes()).hexdigest()
    # Keep the previous diagnostic keys for existing consumers; each alias
    # references a hash of the real physical source above.
    legacy_names=('web_card_service.py','web_card_pool.py','shared_claim_recovery.py',
        'shared_page_backlog.py','web_card_transport.py','web_page_observer.py',
        'owner_upload_jobs.py','card_review_lane.py','shared_page_repair.py',
        'concurrency_control.py','catalog.py')
    for name in legacy_names:
        matches=[value for path,value in hashes.items() if '/' in path and path.rsplit('/',1)[1]==name]
        if len(matches)==1:hashes[name]=matches[0]
    # The unsent-upload attribution and the ZIP adapter live outside this
    # repository, so the acceptance fingerprint must cover them too; a drift
    # there invalidates a validated release instead of silently reusing it.
    external=external_dependencies()
    hashes.update(external['hashes'])
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                        stderr=subprocess.DEVNULL, timeout=3, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    return {'captured_at': time.time(), 'commit': commit, 'module_sha256': hashes,
            'external_dependencies': {key: value for key, value in external.items() if key != 'hashes'},
            'loaded_concurrency_limits': {'fetch': concurrency_control.MAX_FETCH,
                                          'cards': concurrency_control.MAX_CARDS,
                                          'correction': concurrency_control.MAX_CORRECTION}}


def paths(config):return Path(config['catalog_path']).parent


def _owner_process_confirmed(record, folder, config):
    """A recycled PID cannot authorize reuse or a stop request."""
    if not record.get('token') or not alive(record.get('pid')):return False
    try:
        import shlex
        command=subprocess.check_output(['ps','-p',str(record['pid']),'-o','command='],
            text=True,stderr=subprocess.DEVNULL,timeout=3)
        words=shlex.split(command)
        if not any(words[i:i+3]==['-m','cards.web_card_service','run'] for i in range(len(words))):return False
        expected=config.get('_config_path') or record.get('config_path')
        if expected and ('--config' not in words or
                Path(words[words.index('--config')+1]).resolve()!=Path(expected).resolve()):return False
        with (folder/'web-card-service.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return True
        return False
    except (OSError,ValueError,IndexError,subprocess.SubprocessError):return False


def status(config):
    folder=paths(config)
    try:r=json.loads((folder/'web-card-service.json').read_text())
    except (OSError,ValueError):r={}
    live=_owner_process_confirmed(r,folder,config)
    r['heartbeat_stale']=time.time()-r.get('updated',0)>=30
    state=r.get('state','running') if live else 'stopped'
    from core.api import control__pause_decision as pause_decision
    decision=pause_decision(config,'web_cards',enabled=config.get('web_cards',{}).get('enabled',True))
    if not decision.allowed:state='paused_by_user' if decision.state=='paused' else decision.state
    try:
        tabs=json.loads((folder/'web-tab-check.json').read_text())
        if live and state=='running' and not r.get('workers') and time.time()-tabs.get('updated',0)<120 and tabs.get('total_pages')==0:state='waiting_browser'
    except (OSError,ValueError):pass
    from browser.api import shared_workflow_activity__project as project
    from core.api import control__read_record as read_record
    try:observation=read_record(folder/'web-page-observer.json')
    except ValueError:observation={}
    activity=project(r,owner_live=live,observer=observation)
    from browser.api import shared_browser_window__enabled as shared_enabled
    if live and shared_enabled(config):
        from browser.api import web_card_pool__shared_submission_status as shared_submission_status
        channel=shared_submission_status(config)
        r['submission_channel']=channel
        if state=='running' and not channel['allowed'] and activity.get('actual_parallel')=={'cards':0,'review':0,'correction':0}:
            state='waiting_channel'
    from .seed_trials import status as trial_status
    return {**r,**activity,'state':state,'alive':live,'control':decision.as_dict(),'manual_seed_trials':trial_status(config)}


def start(config,config_path=None):
    current=status(config)
    if current['alive']:return {**current,'reused':True}
    if not owner_enabled(config):raise ValueError('制卡、核验与修正均未开启或已被用户暂停')
    folder=paths(config);(folder/'logs').mkdir(parents=True,exist_ok=True)
    python=Path(config['web_cards'].get('python',ROOT/'.venv-web-feedback/bin/python'))
    # Preserve venv path; resolving its symlink would lose installed Playwright.
    with (folder/'logs/web-card-service.log').open('a') as log:
        child=subprocess.Popen([str(python),'-u','-m','cards.web_card_service','run','--config',str(config_path or config['_config_path'])],cwd=ROOT,
                               stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    threading.Thread(target=child.wait,daemon=True).start()
    for _ in range(100):
        if child.poll() is not None:raise RuntimeError('网页版服务启动失败，查看web-card-service.log')
        current=status(config)
        if current['alive']:return current
        time.sleep(.1)
    raise RuntimeError('网页版服务启动尚未确认，勿重复启动')


def stop(config):
    r=status(config)
    from core.api import control__mutate_record as mutate_record
    mutate_record(paths(config)/'web-card-control.json',{'paused_by_user':True,'reason':'用户停止网页版制卡','updated':now()},event='user_pause')
    if r['alive'] and not owner_enabled(config):atomic_json(paths(config)/'web-card-stop.json',{'pid':r['pid'],'token':r['token']})
    return {'state':'stop_requested' if r['alive'] else 'paused_by_user'}


def enabled(config):
    from core.api import control__pause_decision as pause_decision
    return pause_decision(config,'web_cards',enabled=config.get('web_cards',{}).get('enabled',False)).allowed


def formula_only_enabled(config):
    if not (paths(config)/"formula-only-control.json").is_file():return False
    from oled_formulas.api import enabled
    return enabled(config)


def owner_enabled(config):
    """Keep the single driver while any independently authorized web lane runs."""
    if formula_only_enabled(config):return True
    if enabled(config):return True
    from browser.api import shared_browser_window__enabled as shared_enabled
    if shared_enabled(config):
        from review.api import card_review_queue__enabled as review_enabled
        from correction.api import card_correction_queue__enabled as correction_enabled
        return review_enabled(config) or correction_enabled(config)
    return False


def _publication_identity_guard(catalog, job, packet, fresh):
    from .web_card_inputs import digest,valid_source_hash
    reasons=[]
    expected=job.get('source_sha256')
    if not valid_source_hash(expected):reasons.append('任务缺少有效原文SHA-256')
    if packet.get('paper_id')!=job['paper_id']:reasons.append('冻结材料文献身份变化')
    if fresh.get('asset_hash')!=expected or packet.get('source_original_sha256')!=expected:
        reasons.append('生成期间目录或冻结原文指纹变化')
    try:
        if digest(fresh['asset_path'])!=expected:reasons.append('生成期间实时原文指纹变化')
    except (OSError,ValueError,TypeError,KeyError):reasons.append('生成期间实时原文不可核对')
    if fresh.get('acquisition')!='available':reasons.append('原文获取状态不可用')
    if any(fresh.get('metadata',{}).get(k) for k in ('identity_review_required','version_review_required','out_of_scope')):
        reasons.append('生成期间身份、版本或范围需确认')
    with catalog.connect() as db:
        current=db.execute('SELECT selection,source_sha256 FROM web_card_jobs WHERE paper_id=?',(job['paper_id'],)).fetchone()
    if current is None or current['selection']!=job['selection'] or current['source_sha256']!=expected:
        reasons.append('生成期间修正任务或原文绑定变化')
    return '；'.join(reasons)


def _source_review_publication_guard(catalog, job, packet, fresh, human):
    """A completed source rework cannot override decisions made while it ran."""
    from .web_card_inputs import digest
    reasons=[]
    with catalog.connect() as db:
        current=db.execute('SELECT selection,source_sha256 FROM web_card_jobs WHERE paper_id=?',
                           (job['paper_id'],)).fetchone()
    if (current is None or current['selection']!=job['selection'] or
            current['source_sha256']!=job['source_sha256']):
        reasons.append('生成期间修正任务或原文绑定变化')
    if (fresh.get('asset_hash')!=job['source_sha256'] or
            packet.get('source_original_sha256')!=job['source_sha256']):
        reasons.append('生成期间目录或冻结原文指纹变化')
    try:
        if digest(fresh['asset_path'])!=job['source_sha256']:
            reasons.append('生成期间实时原文指纹变化')
    except (OSError,ValueError,TypeError,KeyError):
        reasons.append('生成期间实时原文不可核对')
    if any(fresh['metadata'].get(key) for key in ('identity_review_required','version_review_required','out_of_scope')):
        reasons.append('生成期间身份、版本或范围需确认')
    if human or fresh['decision']!='unreviewed':
        reasons.append('生成期间出现人工决定')
    from .web_card_rework import authorization
    try:authorization(job,fresh)
    except (ValueError,OSError,KeyError,TypeError) as exc:
        reasons.append('生成期间旧卡片授权需核对：'+str(exc))
    return '；'.join(reasons)


def publish_saved(config,job,raw,attempt,provider):
    """Publish a saved response with the same human protection as live generation."""
    from .web_card_inputs import digest,parse_card,MaterialDeliveryError
    from browser.api import web_media_storage__require_config_storage as require_config_storage
    require_config_storage(config)
    catalog=Catalog(config['catalog_path']);pid=job['paper_id']
    folder=paths(config)/'web_cards'/pid
    target=Path(config['studio_library_root'])/pid
    packet_path=folder/'packet.json';packet=json.loads(packet_path.read_text())
    from .web_card_json import normalize
    normalized=normalize(raw)
    if normalized != raw:
        normalized_path=folder/'response-publication-normalized.txt'
        normalized_path.write_text(normalized)
        attempt={**attempt,'normalization':{'kind':'json_syntax_only',
            'normalized_sha256':digest(normalized_path)}}
    try:card=parse_card(normalized,packet)
    except MaterialDeliveryError as exc:
        queue.update(catalog,pid,state='needs_inspection',error=str(exc))
        return
    from .web_card_evidence import verify as verify_evidence
    evidence=verify_evidence(card,folder,packet,config)
    publication_id=secrets.token_hex(16)
    card['meta']={'publication_id':publication_id,'producer':'web_card_service','provider':provider,'actual_settings':attempt['settings'],
                  'source_original_sha256':packet['source_original_sha256'],'source_sha256':packet['input_hashes']['source.pdf'],'input_hashes':packet['input_hashes'],
                  'conversation_url':attempt['conversation_url'],'raw_sha256':attempt['raw_sha256'],
                  'actual_prompt_sha256':attempt.get('actual_prompt_sha256'),'syntax_normalization':attempt.get('normalization'),
                  'structural_complete':packet.get('card_contract_version')=='card-contract-v2',
                  'card_contract_version':packet.get('card_contract_version'),
                  'structure_validation':'contract_valid' if packet.get('card_contract_version')=='card-contract-v2' else 'legacy_valid','scientific_verified':False,'production_contract_complete':False,
                  'production_contract_status':'not_adapted','scientific_validation_status':'unreviewed',
                  'quality_status':'needs_review','selection':json.loads(job['selection']),
                  'evidence_coverage':{**{group:len(card[group]) for group in ('figures','equations','tables')},
                      'verified_quotes':evidence['verified_count'],'needs_review_quotes':evidence['needs_review_count']},
                  'evidence_verification':{k:evidence[k] for k in ('kind','state','evidence_verified')},
                  'paper_evaluation_version':packet.get('paper_evaluation_version'),
                  'work_summary_version':packet.get('work_summary_version'),
                  'card_format_version':packet.get('card_format_version'),
                  'format_warnings':['key_findings条目未分行'] if '\n' not in card['key_findings'] else []}
    # Publish only a structurally complete formal result; never rewrite existing cards.
    target.mkdir(parents=True,exist_ok=True)
    with (target/'web-publish.lock').open('a') as lock, catalog.connect() as publication_db:
        fcntl.flock(lock,fcntl.LOCK_EX)
        publication_db.execute('BEGIN IMMEDIATE')
        def update_job(**fields):
            if 'state' in fields:
                from core.api import control__transition_decision as transition_decision
                before=publication_db.execute('SELECT state FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone()
                if before is None:raise ValueError('网页任务不存在')
                decision=transition_decision(before['state'],fields['state'])
                if not decision.allowed:raise ValueError(decision.reason)
            publication_db.execute('UPDATE web_card_jobs SET '+','.join(k+'=?' for k in fields)+',updated=? WHERE paper_id=?',(*fields.values(),now(),pid))
        fresh=catalog.get(pid)
        with catalog.connect() as db:human=db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='human_decision'",(pid,)).fetchone()
        from .web_card_rework import authorization
        original_rework=json.loads(job['selection']).get('rework')
        blocked_reason=_publication_identity_guard(catalog,job,packet,fresh)
        intent_path=folder/'publication-intent.json';resume_intent=None
        if intent_path.exists():
            intent=json.loads(intent_path.read_text())
            if intent.get('state')!='committed':
                current=publication_db.execute('SELECT state FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone()
                try:
                    receipt_output=Path(intent['output'])
                    if not receipt_output.is_relative_to(target):raise ValueError('发布回执目录不属于原文献')
                    provenance=json.loads((receipt_output/'web-provenance.json').read_text())
                    saved_card=json.loads((receipt_output/'card.json').read_text())
                    files_valid=(intent.get('state')=='files_written' and intent.get('paper_id')==pid and
                        intent.get('raw_sha256')==attempt['raw_sha256'] and
                        saved_card['meta'].get('input_hashes')==packet['input_hashes'] and
                        saved_card['meta'].get('source_original_sha256')==job['source_sha256'] and
                        digest(receipt_output/'source.pdf')==packet['input_hashes']['source.pdf'] and
                        digest(receipt_output/'card.json')==intent.get('card_sha256')==provenance.get('card_sha256') and
                        digest(receipt_output/'web-evidence-verification.json')==provenance.get('evidence_verification_sha256') and
                        all(digest(receipt_output/'pages'/f"P{x['source_page']:03d}.png")==x['sha256'] for x in packet['page_manifest']))
                    committed_event=publication_db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='web_card_generated' AND json_extract(payload,'$.card_path')=?",(pid,str(receipt_output/'card.json'))).fetchone()
                    confirmed=bool(files_valid and current and committed_event and fresh.get('card_path')==str(receipt_output/'card.json'))
                except (OSError,ValueError,KeyError,TypeError):confirmed=False;files_valid=False
                if confirmed:
                    if current['state']!='completed':update_job(state='completed',error='原发布事务与完整文件已核对；科学核验未完成')
                    publication_db.commit()
                    atomic_json(intent_path,{**intent,'state':'committed','reconciled_at':now()});return
                if files_valid and not blocked_reason:resume_intent=intent
                else:blocked_reason='；'.join(filter(None,(blocked_reason,'发布中断待核对，原回答保留；不重发')))

        if original_rework and original_rework.get('kind')=='source_review':
            blocked_reason='；'.join(filter(None,(blocked_reason,_source_review_publication_guard(catalog,job,packet,fresh,human))))
        rework=original_rework if blocked_reason else authorization(job,fresh)
        if rework and provider!='chatgpt':raise ValueError('重做仅允许GPT网页版结果')
        if resume_intent and not blocked_reason and not human and fresh['decision']=='unreviewed' and not (rework or {}).get('human_protected') and (rework or not fresh.get('card_path')):
            resumed_path=str(receipt_output/'card.json')
            cursor=publication_db.execute('UPDATE papers SET card_path=? WHERE id=? AND asset_hash=? AND decision=? AND card_path IS ?',
                (resumed_path,pid,job['source_sha256'],fresh['decision'],fresh.get('card_path')))
            if cursor.rowcount!=1:raise ValueError('中断发布绑定变化；不重发')
            update_job(state='completed',error='原发布文件完整，已核对恢复数据库登记；科学核验未完成')
            publication_db.execute('INSERT INTO events(paper_id,kind,payload,created) VALUES(?,?,?,?)',
                (pid,'web_card_generated',json.dumps({'provider':provider,'card_path':resumed_path,'scientific_verified':False,'reconciled':True}),now()))
            publication_db.commit()
            atomic_json(intent_path,{**resume_intent,'state':'committed','reconciled_at':now()});return

        candidate=bool(rework and (blocked_reason or human or rework.get('human_protected')))
        if blocked_reason:
            card['meta']['publication_protection']={'state':'needs_inspection','reason':blocked_reason,
                'source_review_card_sha256':(original_rework or {}).get('old_sha256'),
                'expected_original_source_sha256':job['source_sha256'],'checked_at':now()}
        if not rework and (blocked_reason or (target/'card.json').exists() or fresh.get('card_path') or fresh['decision']!='unreviewed' or human):
            candidate_path=folder/'card-candidate.json'
            if config.get('web_cards',{}).get('media_root'):
                candidate_path=Path(config['web_cards']['media_root'])/pid/'card-candidate.json'
                candidate_path.parent.mkdir(parents=True,exist_ok=True)
            atomic_json(candidate_path,card)
            if candidate_path!=folder/'card-candidate.json':
                alias=folder/'card-candidate.json';temporary=alias.with_name(alias.name+'.ssd-link')
                temporary.unlink(missing_ok=True);temporary.symlink_to(candidate_path);os.replace(temporary,alias)
            update_job(state='needs_inspection' if blocked_reason else 'protected',error=blocked_reason or '生成期间已有卡片/人工决定；网页输出独立保存');return
        # Reworks publish into a new version directory: even a crash cannot
        # change the old card still referenced by a rolled-back Catalog.
        output=(folder/'gpt-rework-candidate' if candidate else
                target/'publications'/publication_id if rework else target)
        if candidate and config.get('web_cards',{}).get('media_root'):
            output=Path(config['web_cards']['media_root'])/pid/'gpt-rework-candidate'
            alias=folder/'gpt-rework-candidate'
            if not alias.exists() and not alias.is_symlink():alias.symlink_to(output,target_is_directory=True)
        output.mkdir(parents=True,exist_ok=True)
        intent_path=folder/'publication-intent.json'
        if not candidate:
            if intent_path.exists() and json.loads(intent_path.read_text()).get('state')!='committed':
                update_job(state='needs_inspection',error='发布中断待核对，原回答保留；不重发');return
            atomic_json(intent_path,{'state':'writing','publication_id':publication_id,'paper_id':pid,'source_sha256':job['source_sha256'],
                'raw_sha256':attempt['raw_sha256'],'output':str(output),'started_at':now()})
        stage=output/('.publication-stage-'+secrets.token_hex(8))
        stage.mkdir()
        # Stage metadata before switching any official metadata file.
        from .publication_materials import copy as copy_publication_materials
        copy_publication_materials(folder,stage)
        if digest(stage/'source.pdf')!=packet['input_hashes']['source.pdf']:
            raise ValueError('发布暂存原文与冻结指纹不一致')
        for item in packet['page_manifest']:
            if digest(stage/'pages'/f"P{item['source_page']:03d}.png")!=item['sha256']:
                raise ValueError('发布暂存页图与冻结指纹不一致')
        for group in ('figures','equations','tables'):
            for item in card[group]:item['image_path']=str(output/'pages'/f"P{item['source_page']:03d}.png")
        atomic_json(stage/'card.json',card)
        atomic_json(stage/'web-evidence-verification.json',{**evidence,'card_sha256':digest(stage/'card.json'),'raw_sha256':attempt['raw_sha256'],'verified_at':now()})
        atomic_json(stage/'web-provenance.json',{'publication_id':publication_id,'packet':str(packet_path),'attempt':attempt,'rework':rework,'card_sha256':digest(stage/'card.json'),
            'evidence_verification_sha256':digest(stage/'web-evidence-verification.json')})
        # Source is checked again before any canonical metadata is replaced.
        if not candidate:
            final_reason=_publication_identity_guard(catalog,job,packet,fresh)
            if final_reason:raise ValueError(final_reason)
        copy_publication_materials(stage,output)
        for name in ('card.json','web-evidence-verification.json','web-provenance.json'):
            os.replace(stage/name,output/name)
        import shutil
        shutil.rmtree(stage)
        if candidate:
            update_job(state='needs_inspection' if blocked_reason else 'protected',
                         error=('完整修正候选已保存；'+blocked_reason) if blocked_reason else 'GPT重做候选版已落盘；保留人工卡片')
            publication_db.execute('INSERT INTO events(paper_id,kind,payload,created) VALUES(?,?,?,?)',(pid,'web_card_rework_candidate',json.dumps({'card_path':str(output/'card.json')}),now()))
            return
        # Recheck the live source after file operations while other DB writers wait.
        final_reason=_publication_identity_guard(catalog,job,packet,fresh)
        if final_reason:raise ValueError(final_reason)
        card_hash=digest(output/'card.json')
        atomic_json(intent_path,{'state':'files_written','publication_id':publication_id,'paper_id':pid,'source_sha256':job['source_sha256'],
            'raw_sha256':attempt['raw_sha256'],'output':str(output),'card_sha256':card_hash,'updated':now()})
        cursor=publication_db.execute('UPDATE papers SET card_path=? WHERE id=? AND asset_hash=? AND decision=? AND card_path IS ?',
            (str(output/'card.json'),pid,job['source_sha256'],fresh['decision'],fresh.get('card_path')))
        if cursor.rowcount!=1:raise ValueError('发布目录绑定变化，保留发布意图与原回答')
        update_job(state='completed',error='结构已检查；科学核验和生产合同尚未完成')
        publication_db.execute('INSERT INTO events(paper_id,kind,payload,created) VALUES(?,?,?,?)',
            (pid,'web_card_generated',json.dumps({'provider':provider,'card_path':str(output/'card.json'),'scientific_verified':False}),now()))
    atomic_json(intent_path,{'state':'committed','publication_id':publication_id,'paper_id':pid,'card_sha256':card_hash,
        'source_sha256':job['source_sha256'],'raw_sha256':attempt['raw_sha256'],'output':str(output),'updated':now()})


def process_job(config,job,router,prepare_slots,stopping):
    from browser.api import web_card_transport__run_with_failover as run_with_failover, web_card_transport__DeferredWeb as DeferredWeb, web_card_transport__UncertainWeb as UncertainWeb
    from .web_card_inputs import digest,parse_card
    catalog=Catalog(config['catalog_path']);pid=job['paper_id'];paper=catalog.get(pid)
    folder=paths(config)/'web_cards'/pid
    target=Path(config['studio_library_root'])/pid
    try:
        from browser.api import web_media_storage__require_config_storage as require_config_storage
        try:require_config_storage(config)
        except OSError as exc:raise DeferredWeb(str(exc)) from exc
        if paper['decision']!='unreviewed' or paper.get('card_path') or (target/'card.json').exists():
            queue.update(catalog,pid,state='protected',error='已有卡片或人工决定；不覆盖');return
        if any(paper['metadata'].get(k) for k in ('identity_review_required','version_review_required','out_of_scope')):
            queue.update(catalog,pid,state='protected',error='身份/版本/范围待人工核对');return
        folder.mkdir(parents=True,exist_ok=True);queue.update(catalog,pid,folder=str(folder))
        packet_path=folder/'packet.json'
        with prepare_slots:
            if stopping():raise DeferredWeb('用户停止服务')
            if not packet_path.exists():
                request=dict(source=paper['asset_path'],folder=str(folder),paper_id=pid,title=paper['title'],expected_hash=job['source_sha256'])
                if config['web_cards'].get('media_root'):
                    request.update(media_root=config['web_cards']['media_root'],media_volume=config['archive_volume'])
                atomic_json(folder/'prepare-request.json',request)
                with (folder/'prepare.log').open('a') as log:
                    result=subprocess.run([config['web_cards'].get('pdf_python',sys.executable),'-m','cards.web_card_inputs',str(folder/'prepare-request.json')],
                                          cwd=ROOT,stdout=log,stderr=log,timeout=600)
                if result.returncode:raise ValueError('原文材料准备失败，见prepare.log；不循环重试')
            packet=json.loads(packet_path.read_text())
            if digest(paper['asset_path'])!=packet['source_original_sha256']:raise ValueError('当前原文与冻结输入不一致')
        fresh=catalog.get(pid)
        identity_reason=_publication_identity_guard(catalog,job,packet,fresh)
        if identity_reason:
            queue.update(catalog,pid,state='needs_inspection',error=identity_reason);return
        if fresh['decision']!='unreviewed':
            queue.update(catalog,pid,state='protected',error='发送前出现人工决定');return
        # Any prior sent/unknown attempt blocks duplicate calls, including after crash.
        previous_attempts=[]
        for previous in folder.glob('*/attempt.json'):
            a=json.loads(previous.read_text())
            previous_attempts.append(a)
            if a.get('state')=='submitted' and job.get('error')=='resume_known_submitted_target':
                from browser.api import web_card_transport__resume_known_response as resume_known_response
                raw,attempt=resume_known_response(a['provider'],previous.parent,config['web_cards'],stopping)
                publish_saved(config,job,raw,attempt,a['provider']);return
        from core.api import control__submission_decision as submission_decision
        decision=submission_decision(previous_attempts)
        if not decision.allowed:raise UncertainWeb(decision.reason)
        queue.update(catalog,pid,state='submitting')
        (raw,attempt),provider=run_with_failover(router,packet,folder,config['web_cards'],stopping=stopping)
        queue.update(catalog,pid,state='collecting',provider=provider)
        publish_saved(config,job,raw,attempt,provider)
    except DeferredWeb as exc:
        queue.update(catalog,pid,state='queued',error=str(exc),retry_at=time.time()+30)
    except UncertainWeb as exc:queue.update(catalog,pid,state='needs_inspection',error=str(exc))
    except Exception as exc:
        try: fast=bool(catalog.get(pid)['metadata'].get('manual_seed_fast_lane'))
        except Exception: fast=False
        if fast:queue.update(catalog,pid,state='queued',error=type(exc).__name__+': '+str(exc)[:1200],retry_at=time.time()+300)
        else:queue.update(catalog,pid,state='failed',error=type(exc).__name__+': '+str(exc)[:1200])


def run(config):
    if not owner_enabled(config):return
    folder=paths(config);folder.mkdir(parents=True,exist_ok=True)
    with (folder/'web-card-service.lock').open('a') as lock:
        contention_logged=False
        while True:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not contention_logged:
                    print(json.dumps({'event':'owner_lock_wait','at':time.time(),
                        'reason':'existing owner holds exclusive lock'}),flush=True)
                    contention_logged=True
                if not owner_enabled(config):return
                time.sleep(5)
        print(json.dumps({'event':'owner_lock_acquired','at':time.time(),'pid':os.getpid()}),flush=True)
        if not owner_enabled(config):return
        if formula_only_enabled(config):
            from oled_formulas.api import run
            return run(config)
        # Both executors reconcile interrupted states under the same exclusive lock.
        catalog=Catalog(config['catalog_path']);queue.recover(catalog)
        if config.get('web_cards',{}).get('background_no_create'):
            from browser.api import web_card_pool__run_pool as run_pool
            # An operator can capture all Python stacks from the original owner
            # without a second browser connection or root/debugger privileges.
            import faulthandler
            with (folder/'owner-thread-dump.log').open('a') as diagnostic:
                faulthandler.register(signal.SIGUSR1,file=diagnostic,all_threads=True)
                try:return run_pool(config)
                finally:faulthandler.unregister(signal.SIGUSR1)
        from browser.api import web_card_transport__Router as Router, web_card_transport__DeferredWeb as DeferredWeb
        router=Router(folder,policy=config['web_cards']);stop_event=threading.Event();token=secrets.token_hex(24)
        signal.signal(signal.SIGTERM,lambda *_:stop_event.set());signal.signal(signal.SIGINT,lambda *_:stop_event.set())
        futures=set();last_select=0;selection={};prepare_slots=threading.BoundedSemaphore(2)
        parallel=config.get('web_cards',{}).get('max_parallel_jobs',40)
        with ThreadPoolExecutor(max_workers=parallel,thread_name_prefix='web-card') as pool:
            while not stop_event.is_set() and enabled(config):
                try:request=json.loads((folder/'web-card-stop.json').read_text())
                except (OSError,ValueError):request={}
                if request.get('pid')==os.getpid() and request.get('token')==token:break
                finished={f for f in futures if f.done()}
                for f in finished:
                    try:f.result()
                    except Exception as exc:print('web worker error:',type(exc).__name__,str(exc)[:200],flush=True)
                futures-=finished
                if time.monotonic()-last_select>=60:
                    selection=queue.select(catalog,config);last_select=time.monotonic()
                # Cooldowns prevent workers from repeatedly opening known-bad channels.
                try:router.choose();available=True
                except DeferredWeb:available=False
                while available and len(futures)<parallel:
                    job=queue.claim(catalog)
                    if not job:break
                    futures.add(pool.submit(process_job,config,job,router,prepare_slots,stop_event.is_set))
                counts={}
                for j in queue.jobs(catalog):counts[j['state']]=counts.get(j['state'],0)+1
                atomic_json(folder/'web-card-service.json',{'pid':os.getpid(),'token':token,'state':'running','updated':time.time(),
                            'selection':{k:v for k,v in selection.items() if k!='added'},'jobs':counts,'workers':len(futures),
                            'max_pages_per_provider':20,'providers':router.state,'config_path':config['_config_path']},durable=False)
                stop_event.wait(2)
            stop_event.set()
            atomic_json(folder/'web-card-service.json',{'pid':os.getpid(),'token':token,'state':'stopping','updated':time.time()})
        atomic_json(folder/'web-card-service.json',{'pid':os.getpid(),'token':token,'state':'stopped','updated':time.time()})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('run','start','stop','status'));parser.add_argument('--config')
    args=parser.parse_args();config=load_config(args.config)
    if args.command=='run':run(config)
    else:print(json.dumps({'start':start,'stop':stop,'status':status}[args.command](config),ensure_ascii=False,indent=2))
