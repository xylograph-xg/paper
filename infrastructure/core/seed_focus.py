"""Seed-only admission and durable evidence/semantic progress, no browser or sender."""
import argparse
import hashlib
import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from .paths import WorkspacePath as Path
from .control import read_record, mutate_record
from .services import atomic_json


def root(config):return Path(config['catalog_path']).parent

def active(config):
    if not config.get('catalog_path'):return False
    try:return read_record(root(config)/'seed-focus-control.json').get('enabled',False) is True
    except ValueError:return True  # Damaged admission control never opens ordinary work.


def allowed(config,paper_id):
    if not active(config):return True
    try:
        with closing(sqlite3.connect(Path(config['catalog_path']).as_uri()+'?mode=ro',uri=True,timeout=.3)) as db:
            return db.execute('SELECT 1 FROM manual_seed_roots WHERE paper_id=?',(paper_id,)).fetchone() is not None
    except (OSError,sqlite3.Error):return False


def filter_records(db,records,config=None):
    records=list(records)
    if not records:return records
    if config is None or not config.get('catalog_path'):
        try:filename=db.execute('PRAGMA database_list').fetchone()[2]
        except (TypeError,AttributeError,IndexError):return records
        if not isinstance(filename,str) or not filename:return records
        config={'catalog_path':filename}
    if not active(config):return records
    try:seeds={r[0] for r in db.execute('SELECT paper_id FROM manual_seed_roots')}
    except sqlite3.Error:return []
    return [r for r in records if r['paper_id'] in seeds]


def set_enabled(config,enabled):
    if type(enabled) is not bool:raise ValueError('手选开关必须为布尔值')
    value=mutate_record(root(config)/'seed-focus-control.json',
        {'enabled':enabled,'updated':time.time(),'reason':'用户手选种子独占开关'},event='seed_focus_changed')
    return {'enabled':enabled,'control':value}


def _read(path):
    try:return json.loads(Path(path).read_text())
    except FileNotFoundError:return {}


def _stamp(value,fallback):
    if type(value) in (int,float):return value
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError,AttributeError):return fallback


def capture(config,paper_id,reason):
    """Keep content-addressed original small evidence; large inputs stay pinned by manifests."""
    base=root(config);directory=base/'seed-tracking'/paper_id;objects=directory/'evidence';objects.mkdir(parents=True,exist_ok=True)
    sources=[];f=base/'web_cards'/paper_id
    for name in ('packet.json','prompt.txt','retry.json','source-context.json'):
        if (f/name).is_file():sources.append(f/name)
    sources.extend(f.rglob('attempt.json'))
    for attempt in list(sources):
        if attempt.name=='attempt.json':
            sources.extend(p for p in (attempt.parent/'prompt-actual.txt',attempt.parent/'response-raw.txt',attempt.parent.parent/'packet.json',attempt.parent.parent/'prompt.txt') if p.is_file())
    review_root=base/'card_reviews'/paper_id
    for name in ('attempt.json','feedback.json','assessment.json','packet.json','prompt-actual.txt','response-raw.txt'):
        sources.extend(review_root.glob('*/'+name))
    run=base/'manual_seed_trials'/paper_id/'run.json'
    if run.exists():sources.append(run)
    targets=set()
    for item in sources:
        if item.name=='attempt.json':targets.add(_read(item).get('target_id'))
    registry=_read(base/'shared-gpt-window.json')
    for slot in registry.get('slots',[]):
        for retired in slot.get('replacement_history',[]):
            if retired.get('target_id') not in targets or not retired.get('diagnostics'):continue
            archive=Path(retired['diagnostics'])
            if not archive.resolve().is_relative_to((base/'shared-page-repairs').resolve()):raise ValueError('种子页面归档路径越界')
            for name in ('health.json','body.txt','page.html','capture.json','target-history-before.json','ledger-before.json','prompt-actual.txt'):
                if (archive/name).is_file():sources.append(archive/name)
            if (archive.parent/'journal.json').is_file():sources.append(archive.parent/'journal.json')
    entries=[]
    for source in sorted(set(sources)):
        before=source.stat();data=source.read_bytes();after=source.stat()
        if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('种子证据读取期间变化')
        sha=hashlib.sha256(data).hexdigest();destination=objects/sha
        if not destination.exists():
            from tempfile import NamedTemporaryFile
            with NamedTemporaryFile(dir=objects,delete=False) as stream:
                temporary=Path(stream.name);stream.write(data);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,destination)
        elif hashlib.sha256(destination.read_bytes()).hexdigest()!=sha:raise ValueError('种子证据对象指纹冲突')
        entries.append({'path':str(source),'sha256':sha,'bytes':len(data),'object':str(destination)})
    with closing(sqlite3.connect(Path(config['catalog_path']).as_uri()+'?mode=ro',uri=True,timeout=2)) as evidence_db:
        evidence_db.row_factory=sqlite3.Row
        job=evidence_db.execute('SELECT * FROM web_card_jobs WHERE paper_id=?',(paper_id,)).fetchone()
        review_rows=[dict(r) for r in evidence_db.execute('SELECT * FROM card_review_jobs WHERE paper_id=?',(paper_id,))]
    manifest={'paper_id':paper_id,'reason':reason,'inputs':entries,'job_snapshot':dict(job) if job else None,'review_snapshots':review_rows}
    identity=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    path=directory/'manifests'/(identity+'.json')
    if not path.exists():atomic_json(path,{**manifest,'captured_at':time.time(),'large_inputs':'Original PDF/ZIP paths and frozen hashes remain in packets; no regeneration.'})
    return str(path)


def _requests(base,paper_id):
    steps={};times=[]
    for path in (base/'web_cards'/paper_id).rglob('attempt.json'):
        receipt=_read(path);created=receipt.get('created');target=receipt.get('target_id');prompt=receipt.get('actual_prompt_sha256')
        if type(created) not in (int,float) or not target or not prompt:continue
        state=receipt.get('state');raw=path.parent/'response-raw.txt'
        if state=='response_saved' and receipt.get('raw_sha256') and raw.exists() and hashlib.sha256(raw.read_bytes()).hexdigest()==receipt['raw_sha256']:
            step=2;moment=_stamp(receipt.get('finished'),created)
        elif state=='submitted' and receipt.get('send_click_started') is True:step=1;moment=created
        else:continue
        identity=hashlib.sha256(json.dumps([target,prompt,created]).encode()).hexdigest()
        steps[identity]=max(steps.get(identity,0),step);times.append(moment)
    return steps,times


def _card_bound(path,card,selected,reviews):
    actual=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if actual==selected.get('card_sha256'):return True
    proof=card.get('meta',{}).get('source_review',{})
    if (proof.get('job_id')!=selected.get('review_id') or proof.get('card_sha256')!=selected.get('card_sha256')
            or proof.get('report_sha256')!=selected.get('report_sha256')
            or not any(r['id']==proof['job_id'] and r['state']=='passed' for r in reviews)):return False
    backup=Path(path).parent/'history'/('source-review-'+proof['job_id'])/'card.json'
    if not backup.exists() or hashlib.sha256(backup.read_bytes()).hexdigest()!=selected['card_sha256']:return False
    original=_read(backup)
    return {k:v for k,v in card.items() if k!='meta'}=={k:v for k,v in original.items() if k!='meta'}



_PROGRESS_CONTRACT='qualified-material-v2'


def _event_time(value,created,at):
    moment=_stamp(value,0)
    return moment if type(moment) in (int,float) and 0<moment<=at and moment>=created else 0


def _event_id(parts):
    return hashlib.sha256(json.dumps(parts,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def _qualified_events(base,paper,card,reviews,complete,at):
    """Only saved original content/current-version acceptance; never queue transitions."""
    events={};source=paper.get('asset_hash');body={k:v for k,v in card.items() if k!='meta'}
    def add(identity,kind,moment):
        if moment and (identity not in events or moment<events[identity]['at']):events[identity]={'kind':kind,'at':moment}
    for lane in ('web_cards','card_reviews'):
        for path in (base/lane/paper['id']).rglob('attempt.json'):
            receipt=_read(path);created=receipt.get('created');prompt=receipt.get('actual_prompt_sha256');raw=receipt.get('raw_sha256')
            if (receipt.get('state')!='response_saved' or type(created) not in (int,float) or not receipt.get('target_id')
                    or not prompt or not raw or not str(receipt.get('conversation_url','')).startswith('https://chatgpt.com/c/')):continue
            packet_path=path.parent/'packet.json' if lane=='card_reviews' else path.parent.parent/'packet.json'
            packet=_read(packet_path)
            if (not source or packet.get('source_original_sha256')!=source or not receipt.get('inputs')
                    or packet.get('input_hashes')!=receipt['inputs']):continue
            try:
                answer=(path.parent/'response-raw.txt').read_bytes();actual=(path.parent/'prompt-actual.txt').read_bytes()
            except FileNotFoundError:continue
            if not answer.strip() or hashlib.sha256(answer).hexdigest()!=raw or hashlib.sha256(actual).hexdigest()!=prompt:continue
            times=[_event_time(receipt.get(k),created,at) for k in ('observed_complete_at','finished')];times=[t for t in times if t]
            if times:add(_event_id([lane,receipt['target_id'],prompt,created,raw]),'original_answer',min(times))
    meta=card.get('meta',{});bound=bool(source and meta.get('source_original_sha256')==source and paper.get('card_path'))
    if bound and body and meta.get('producer')=='web_card_service':
        add(_event_id(['card_body',source,body]),'card_body',_event_time(Path(paper['card_path']).stat().st_mtime,0,at))
    if bound:
        proof=meta.get('source_review',{})
        for review in reviews:
            if (review['id']!=proof.get('job_id') or review['state']!='passed'
                    or review.get('source_sha256')!=source or review.get('card_sha256')!=proof.get('card_sha256')):continue
            try:result=json.loads(review.get('result') or '{}')
            except (ValueError,TypeError):continue
            if (result.get('full_source_checked') is not True or result.get('verdict')!='pass'
                    or not isinstance(result.get('weighted_score'),(int,float)) or result['weighted_score']<85
                    or result.get('missing_inputs') or result.get('offline_blockers')
                    or any(result.get('issue_counts',{}).get(k,0) for k in ('major','critical')) or any(i.get('severity') in ('major','critical') for i in result.get('issues',[]))):continue
            selected={'review_id':review['id'],'card_sha256':proof.get('card_sha256'),'report_sha256':proof.get('report_sha256')}
            if _card_bound(paper['card_path'],card,selected,reviews):
                add(_event_id(['scientific_pass',source,body,review['id']]),'scientific_pass',_event_time(review.get('updated'),0,at))
        if complete:add(_event_id(['production_complete',source,body,proof]),'production_complete',_event_time(Path(paper['card_path']).stat().st_mtime,0,at))
    return events


def _qualified_clock(saved,old,events,job,at):
    """Migrate with original bytes retained; stable IDs retain their first evidence time."""
    prior=old.get('qualified_progress',{});migrating=prior.get('contract')!=_PROGRESS_CONTRACT
    migration=old.get('clock_migration_evidence')
    if migrating:
        baseline=min(at,_stamp(job.get('updated'),old.get('last_advanced_at',at)))
        event_file=saved.parent/'events.jsonl'
        if event_file.exists():
            with event_file.open() as stream:
                for line in stream:
                    try:first=json.loads(line)
                    except ValueError:continue
                    if type(first.get('last_advanced_at')) in (int,float):baseline=min(at,first['last_advanced_at']);break
        if old:
            raw=saved.read_bytes();sha=hashlib.sha256(raw).hexdigest();archive=saved.parent/'evidence'/sha;archive.parent.mkdir(parents=True,exist_ok=True)
            if not archive.exists():archive.write_bytes(raw)
            elif archive.read_bytes()!=raw:raise ValueError('种子时钟迁移证据指纹冲突')
            migration={'path':str(archive),'sha256':sha,'bytes':len(raw)}
        # A pre-existing card's mtime may be a metadata publication: record its
        # identity as a baseline, without claiming a newly created body/pass.
        merged={key:{**event,'at':baseline} if event['kind']!='original_answer' else event for key,event in events.items()}
    else:
        baseline=prior['baseline_at'];merged=dict(prior.get('events',{}))
        for key,event in events.items():
            if key not in merged:merged[key]=event
    qualified={'contract':_PROGRESS_CONTRACT,'baseline_at':baseline,'events':{k:merged[k] for k in sorted(merged)}}
    last=max([baseline]+[e['at'] for e in merged.values()])
    return last,qualified,migration


def monitor(config,*,at=None):
    """Read production only; append trace on real transitions, never a heartbeat advance."""
    import fcntl
    at=time.time() if at is None else at;base=root(config);directory=base/'seed-tracking';directory.mkdir(parents=True,exist_ok=True)
    with (directory/'monitor.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        with closing(sqlite3.connect(Path(config['catalog_path']).as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
            db.row_factory=sqlite3.Row
            columns={r['name'] for r in db.execute('PRAGMA table_info(papers)')}
            source_column='p.asset_hash' if 'asset_hash' in columns else 'NULL'
            papers=[dict(r) for r in db.execute('SELECT p.id,p.title,p.card_path,'+source_column+' AS asset_hash FROM papers p JOIN manual_seed_roots m ON m.paper_id=p.id')]
            items=[]
            for paper in papers:
                pid=paper['id'];saved=directory/pid/'trace.json';old=_read(saved);run=_read(base/'manual_seed_trials'/pid/'run.json')
                row=db.execute('SELECT state,error,updated FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone();job=dict(row) if row else {}
                reviews=[dict(r) for r in db.execute('SELECT * FROM card_review_jobs WHERE paper_id=? ORDER BY updated DESC',(pid,))]
                ranks={'response_saved':1,'applying':2,'corrected':3,'trial_reviewed':3,'passed':4}
                reached=dict(old.get('progress',{}).get('reviews',[]))
                for review in reviews:
                    state=review['state'];previous=reached.get(review['id'])
                    if state in ranks and ranks[state]>ranks.get(previous,0):reached[review['id']]=state
                semantic=[[key,reached[key]] for key in sorted(reached)]
                card=_read(paper['card_path']) if paper.get('card_path') else {};meta=card.get('meta',{})
                selected=next((c for c in run.get('candidates',[]) if c.get('round')==run.get('winner')),None)
                if not run:
                    # New manual roots outside the fixed five-paper experiment
                    # finish through their normal reviewed production version.
                    proof=meta.get('source_review',{})
                    if proof.get('job_id') and any(r['id']==proof['job_id'] and r['state']=='passed' for r in reviews):
                        selected={'card_sha256':proof.get('card_sha256'),'review_id':proof['job_id'],
                                  'report_sha256':proof.get('report_sha256')}
                if run.get('state')=='repairing':
                    current_review=meta.get('source_review',{})
                    trial=meta.get('selection',{}).get('manual_seed_trial',{})
                    if (run.get('id') and trial.get('run_id')==run['id'] and current_review.get('job_id')
                            and any(r['id']==current_review['job_id'] and r['state']=='passed' for r in reviews)):
                        selected={'card_sha256':current_review.get('card_sha256'),'review_id':current_review['job_id'],
                                  'report_sha256':current_review.get('report_sha256')}
                    else:selected=None
                complete=bool((not run or run.get('state') in ('selected','repairing')) and selected and paper.get('card_path')
                    and _card_bound(paper['card_path'],card,selected,reviews)
                    and meta.get('source_original_sha256')==(run.get('source_sha256') if run else paper['asset_hash'])
                    and meta.get('scientific_verified') is True and meta.get('production_contract_complete') is True)
                requests,request_times=_requests(base,pid)
                reached_requests=dict(old.get('progress',{}).get('requests',[]))
                for key,value in requests.items():reached_requests[key]=max(reached_requests.get(key,0),value)
                token={'round':run.get('round',0),'reviewed':len(run.get('candidates',[])),'reviews':semantic,'winner':run.get('winner'),'complete':complete,
                       'requests':[[key,reached_requests[key]] for key in sorted(reached_requests)],
                       'card_response':old.get('progress',{}).get('card_response',False) or job.get('state') in ('completed','response_saved','collecting')}
                phase='成品卡完成' if complete else '待核对原回执' if job.get('state') in ('failed','needs_inspection','needs_user') else '候选核验' if semantic else '等待制卡'
                error=job.get('error','')
                if not error and reviews:error=reviews[0].get('error','')
                if complete:error=''
                events=_qualified_events(base,paper,card,reviews,complete,at)
                last,qualified,migration=_qualified_clock(saved,old,events,job,at)
                origin='qualified-material-v2: 原回答完整收取/当前版本内容与验收证据时间；排队、发送、轮询、归档不计进展'
                evidence=capture(config,pid,'tracking')
                value={'paper_id':pid,'title':paper['title'],'phase':phase,'job_state':job.get('state'),'error':error,'progress':token,
                       'qualified_progress':qualified,'clock_migration_evidence':migration,'last_advanced_at':last,'progress_time_source':origin,'checked_at':at,'complete':complete,'evidence_manifest':evidence,
                       'stalled':not complete and at-last>=10800,'stalled_seconds':max(0,at-last),'retention':'Keep until verified final card; completed evidence is retained too.'}
                if not old or old.get('progress')!=token or old.get('qualified_progress')!=qualified or old.get('error')!=error:
                    event=directory/pid/'events.jsonl';event.parent.mkdir(parents=True,exist_ok=True)
                    with event.open('a') as stream:stream.write(json.dumps(value,ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())
                atomic_json(saved,value);items.append(value)
        result={'enabled':active(config),'checked_at':at,'items':items};atomic_json(directory/'status.json',result);return result


def status(config):
    value=_read(root(config)/'seed-tracking/status.json');value['enabled']=active(config)
    for item in value.get('items',[]):
        item['stalled_seconds']=max(0,time.time()-item['last_advanced_at']);item['stalled']=not item['complete'] and item['stalled_seconds']>=10800
    return value


if __name__=='__main__':
    from .catalog import load_config
    parser=argparse.ArgumentParser();parser.add_argument('--config',default='infrastructure/config/first_round.json');parser.add_argument('--enable',action='store_true');parser.add_argument('--disable',action='store_true');args=parser.parse_args()
    if args.enable and args.disable:parser.error('不能同时开启和关闭')
    config=load_config(args.config)
    if args.enable or args.disable:result=set_enabled(config,args.enable)
    else:result=monitor(config)
    print(json.dumps(result,ensure_ascii=False))
