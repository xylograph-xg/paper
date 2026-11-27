"""Bounded, file-only observation of exact original-owner deployment."""
import collections
import hashlib
import json
import os
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

HERE=Path(__file__).resolve().parent
DATA=Path('/Users/xiaoyanhao/project/paper/infrastructure/data')
def read(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}
def main():
    release=read(HERE/'validated-release.json');baseline=read(HERE/'baseline.json')
    if not release:raise RuntimeError('validated release required')
    expected=release['module_sha256'];cutoff=release['validated_at'];start=time.time();new_at=None;last=None
    for _ in range(120):
        now=time.time();service=read(DATA/'web-card-service.json');observer=read(DATA/'web-page-observer.json')
        registry=read(DATA/'shared-gpt-window.json');supervision=read(DATA/'owner-supervision.json')
        source=service.get('code_version',{}).get('module_sha256')==expected;owner=service.get('pid')
        fresh=0<=now-observer.get('updated',0)<30 and observer.get('owner_pid')==owner
        targets={s['target_id'] for s in registry.get('slots',[])}
        positions={p['target_id'] for p in observer.get('pages',[]) if p.get('window_observed') is True
                   and p.get('window_id')==registry.get('window_id') and 0<=now-p.get('window_checked_at',0)<30}
        ready=source and fresh and len(targets)==20 and targets<=positions
        controls={n:hashlib.sha256((DATA/n).read_bytes()).hexdigest() for n in baseline['pause_sha256']}
        try:os.kill(baseline['owner_pid'],0);old_exited=False
        except ProcessLookupError:old_exited=True
        if source and new_at is None:new_at=now
        if ready and old_exited and not (HERE/'handoff-confirmed.json').exists():
            (HERE/'handoff-confirmed.json').write_text(json.dumps({'at':now,'owner_pid':owner,
                'old_owner_pid':baseline['owner_pid'],'old_owner_exited':True,'source_hashes':len(expected),
                'source_hashes_match':True,'fixed_targets':20,'all_twenty_fresh':True,
                'pause_controls_unchanged':controls==baseline['pause_sha256'],'pause_sha256':controls,
                'supervision':supervision},ensure_ascii=False,indent=2)+'\n')
        events=[]
        for line in (DATA/'upload-attempt-events.jsonl').read_text().splitlines():
            try:e=json.loads(line)
            except ValueError:continue
            if e.get('owner_pid')==owner and e.get('started_at',e.get('at',0))>=cutoff:events.append(e)
        starts={e['upload_attempt_id']:e for e in events if e.get('kind')=='upload_started'}
        ends={e['upload_attempt_id']:e for e in events if e.get('kind')=='upload_finished'}
        receipts=[]
        for key,e in starts.items():
            folder=DATA/'card_reviews'/e['paper_id']/e['job_id'] if e['lane']=='review' else DATA/'web_cards'/e['paper_id']/'chatgpt'
            candidates=[folder/'attempt.json']+list(folder.glob('history/**/attempt.json'))
            for path in candidates:
                a=read(path)
                if a.get('upload_attempt_id')!=key or a.get('target_id')!=e['target_id']:continue
                raw=path.parent/'response-raw.txt'
                valid=a.get('state')=='response_saved' and raw.is_file() and hashlib.sha256(raw.read_bytes()).hexdigest()==a.get('raw_sha256')
                receipts.append({'upload_attempt_id':key,'target_id':e['target_id'],'state':a.get('state'),
                    'stage':a.get('stage'),'error_type':a.get('error_type'),'failed_stage':a.get('failed_stage'),
                    'send_click_started':a.get('send_click_started'),'raw_valid':valid,'raw_sha256':a.get('raw_sha256'),
                    'observed_complete_at':a.get('observed_complete_at')});break
        probe=read(DATA/'original-put-http1'/'20261016-small-original-put'/'intent.json')
        probe={k:probe.get(k) for k in ['state','transport','status','fulfilled','native_settled','created_at','updated_at','target_id','error_type','error_codes'] if k in probe}
        record={'at':now,'shanghai':datetime.fromtimestamp(now,ZoneInfo('Asia/Shanghai')).isoformat(),
            'owner_pid':owner,'old_owner_exited':old_exited,'source_matches':source,'all_twenty_fresh':ready,
            'observer_age_seconds':now-observer.get('updated',0),'observer_duration_seconds':observer.get('duration_seconds'),
            'receipt_inspection_errors':observer.get('receipt_inspection_errors'),'supervisor_state':supervision.get('state'),
            'pause_controls_unchanged':controls==baseline['pause_sha256'],'native_starts':len(starts),
            'native_ok':sum(x.get('result')=='ok' for x in ends.values()),
            'native_failures':dict(collections.Counter(x.get('failure_kind') for x in ends.values() if x.get('result')!='ok')),
            'native_pending':len(set(starts)-set(ends)),'receipts':receipts,'original_put_probe':probe,
            'uploading_callbacks':service.get('uploading_pages'),'retained':service.get('retained_upload_targets'),
            'admitted_zip_bytes':service.get('upload_admitted_zip_bytes'),'zip_byte_limit':service.get('upload_zip_byte_limit'),'lock_metrics':service.get('submission_lock_metrics'),'dispatch_errors':service.get('upload_dispatch_errors'),
            'owner_errors':service.get('errors'),'channel':service.get('submission_channel')}
        with (HERE/'live-verification.jsonl').open('a') as stream:stream.write(json.dumps(record,ensure_ascii=False)+'\n')
        label=(owner,source,ready,record['native_starts'],record['native_ok'],str(record['native_failures']),
               sum(x['raw_valid'] for x in receipts),probe.get('state'),probe.get('native_settled'))
        if label!=last:
            print(json.dumps({k:record[k] for k in ['shanghai','owner_pid','source_matches','all_twenty_fresh',
                'native_starts','native_ok','native_failures','original_put_probe','lock_metrics']},ensure_ascii=False),flush=True);last=label
        if new_at and now-new_at>=420 or now-start>=1170:
            (HERE/'live-result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n');return
        time.sleep(10)
    (HERE/'live-result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
