"""One file-only evidence audit; no polling, browser, queue or control writes."""
import collections
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from browser.api import attempt_history__index_attempts as index_attempts

HERE=Path(__file__).resolve().parent
DATA=Path('/Users/xiaoyanhao/project/paper/infrastructure/data')


def read(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}


def main():
    now=time.time();release=read(HERE/'validated-release.json');handoff=read(HERE/'handoff-confirmed.json')
    baseline=read(HERE/'baseline.json');last=read(HERE/'live-result.json')
    service=read(DATA/'web-card-service.json');observation=read(DATA/'web-page-observer.json')
    registry=read(DATA/'shared-gpt-window.json');owner=handoff.get('owner_pid') or service.get('pid')
    cutoff=last.get('at',now);events=[];errors=[]
    for line in (DATA/'upload-attempt-events.jsonl').read_text().splitlines():
        try:e=json.loads(line)
        except ValueError:continue
        stamp=e.get('started_at',e.get('at',0))
        if e.get('owner_pid')==owner and release['validated_at']<=stamp<=cutoff:events.append(e)
    starts={e['upload_attempt_id']:e for e in events if e.get('kind')=='upload_started'}
    ends={e['upload_attempt_id']:e for e in events if e.get('kind')=='upload_finished' and e.get('finished_at',0)<=cutoff}
    for line in (DATA/'web-page-observer-errors.jsonl').read_text().splitlines():
        try:e=json.loads(line)
        except ValueError:continue
        if e.get('owner_pid')==owner and e.get('check_finished_at',now)>release['validated_at'] and e.get('check_finished_at',now)<=cutoff:errors.append(e)
    records,_=index_attempts(DATA);by_id={}
    for path,a in records.items():
        if a.get('upload_attempt_id') in starts:by_id.setdefault(a['upload_attempt_id'],[]).append((Path(path),a))
    receipts=[]
    for key,e in starts.items():
        proof=[]
        for path,a in by_id.get(key,[]):
            if a.get('target_id')!=e['target_id']:continue
            raw=path.parent/'response-raw.txt';prompt=path.parent/'prompt-actual.txt'
            valid=(a.get('state')=='response_saved' and raw.is_file() and prompt.is_file()
                and hashlib.sha256(raw.read_bytes()).hexdigest()==a.get('raw_sha256')
                and hashlib.sha256(prompt.read_bytes()).hexdigest()==a.get('actual_prompt_sha256'))
            proof.append({'path':str(path),'state':a.get('state'),'send_click_started':a.get('send_click_started'),
                'raw_valid':valid,'saved_before_cutoff':bool(valid and (a.get('observed_complete_at') or a.get('finished') or now)>0 and (a.get('observed_complete_at') or a.get('finished') or now)<=cutoff),'raw_sha256':a.get('raw_sha256'),'observed_complete_at':a.get('observed_complete_at')})
        receipts.append({'upload_attempt_id':key,'target_id':e['target_id'],'lane':e.get('lane'),
            'zip_bytes':e.get('zip_bytes'),'result':ends.get(key,{}).get('result'),'proof':proof})
    fixed={s['target_id'] for s in registry.get('slots',[])}
    fresh={p['target_id']:p for p in observation.get('pages',[]) if p.get('target_id') in fixed
        and observation.get('owner_pid')==owner and 0<=now-p.get('checked_at',0)<30}
    rounds=collections.Counter(e.get('round_id') for e in errors if e.get('diagnostic_kind')=='page_state')
    controls={n:hashlib.sha256((DATA/n).read_bytes()).hexdigest() for n in baseline['pause_sha256']}
    result={'audited_at':now,'shanghai':datetime.fromtimestamp(now,ZoneInfo('Asia/Shanghai')).isoformat(),
        'bounded_observation_end':cutoff,'owner_pid':owner,'service_owner_matches':service.get('pid')==owner,
        'handoff_confirmed':bool(handoff),'source_hashes':handoff.get('source_hashes'),
        'source_hashes_match':handoff.get('source_hashes_match'),'old_owner_exited':handoff.get('old_owner_exited'),
        'pause_controls_unchanged':controls==baseline['pause_sha256'],'fixed_targets':len(fixed),
        'fresh_targets':len(fresh),'awaiting_observation':len(fixed-set(fresh)),
        'fresh_states':dict(collections.Counter(p.get('state') for p in fresh.values())),
        'latest_round_duration':observation.get('duration_seconds'),'latest_status_duration':observation.get('status_duration_seconds'),
        'latest_loop_lag':observation.get('loop_lag_seconds'),'native_started':len(starts),
        'native_ok':sum(e.get('result')=='ok' and e.get('receipt_sufficient') is True
            and e.get('zip_identity_mismatch') is False for e in ends.values()),
        'native_pending':len(set(starts)-set(ends)),
        'native_non_ok':dict(collections.Counter(e.get('failure_kind') for e in ends.values() if e.get('result')!='ok')),
        'confirmed_saved_answers':sum(any(p['saved_before_cutoff'] for p in r['proof']) for r in receipts),
        'inspection_errors':len(errors),'inspection_errors_by_kind':dict(collections.Counter(e.get('diagnostic_kind') for e in errors)),
        'max_failed_check_wall_seconds':max((e.get('duration_seconds',0) for e in errors),default=None),
        'rounds_with_five_or_more_state_errors':sum(n>=5 for n in rounds.values()),
        'receipts':receipts,'scientific_acceptance':'separate; not inferred from transport or saved answer'}
    (HERE/'final-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='receipts'},ensure_ascii=False))


if __name__=='__main__':main()
