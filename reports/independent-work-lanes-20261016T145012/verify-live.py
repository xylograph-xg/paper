"""Finite, read-only original-owner handoff and natural workflow verification."""
import collections
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE=Path(__file__).resolve().parent
ROOT=Path('/Users/xiaoyanhao/project/paper/infrastructure/data')


def read(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}


def main():
    release=read(HERE/'validated-release.json');baseline=read(HERE/'baseline.json')
    if not release:raise RuntimeError('Exact validated release is required')
    desired=release['module_sha256'];old_pid=baseline['owner_pid'];seen_saves={}
    peak=0;new_owner_at=None;last_label=None
    for _ in range(90):
        at=time.time();service=read(ROOT/'web-card-service.json');observer=read(ROOT/'web-page-observer.json')
        registry=read(ROOT/'shared-gpt-window.json');supervision=read(ROOT/'owner-supervision.json')
        match=service.get('code_version',{}).get('module_sha256')==desired
        owner=service.get('pid');fresh=0<=at-observer.get('updated',0)<30 and observer.get('owner_pid')==owner
        targets={s['target_id'] for s in registry.get('slots',[])}
        positions={p.get('target_id') for p in observer.get('pages',[]) if
            p.get('window_observed') is True and p.get('window_id')==registry.get('window_id')
            and 0<=at-p.get('window_checked_at',0)<30}
        ready=match and fresh and len(targets)==20 and positions==targets
        if ready and new_owner_at is None:
            new_owner_at=at
            (HERE/'handoff-confirmed.json').write_text(json.dumps({
                'at':at,'owner_pid':owner,'old_owner_pid':old_pid,'new_source_loaded':True,
                'all_twenty_registered_targets_observed':True,'window_id':registry.get('window_id'),
                'pause_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                    for name in baseline['pause_sha256']},'supervision':supervision},indent=2)+'\n')
        events=[]
        for line in (ROOT/'upload-attempt-events.jsonl').read_text().splitlines():
            try:event=json.loads(line)
            except ValueError:continue
            if event.get('owner_pid')==owner and event.get('started_at',event.get('at',0))>=release['validated_at']:
                events.append(event)
        starts={e['upload_attempt_id']:e for e in events if e.get('kind')=='upload_started'}
        ends={e['upload_attempt_id']:e for e in events if e.get('kind')=='upload_finished'}
        for identifier,event in starts.items():
            folder=ROOT/'card_reviews'/event['paper_id']/event['job_id'] if event['lane']=='review' else ROOT/'web_cards'/event['paper_id']/'chatgpt'
            receipt=read(folder/'attempt.json')
            if receipt.get('state')=='response_saved' and receipt.get('observed_complete_at',0)>=release['validated_at']:
                seen_saves[identifier]={k:receipt.get(k) for k in ['target_id','conversation_url','raw_sha256','observed_complete_at']}
        if ready:peak=max(peak,service.get('uploading_pages') or 0)
        verified=[p for p in observer.get('pages',[]) if p.get('streaming') is True and p.get('activity_verified') is True] if fresh else []
        frame={'at':at,'shanghai':datetime.fromtimestamp(at,ZoneInfo('Asia/Shanghai')).isoformat(),
            'owner_pid':owner,'source_match':match,'all_twenty_fresh':ready,
            'supervisor_state':supervision.get('state'),'service_age':at-service.get('updated',0),
            'observer_age':at-observer.get('updated',0),'generating':len(verified),
            'uploading_pages':service.get('uploading_pages'),'upload_budget_used':service.get('upload_budget_used'),
            'retained':service.get('retained_upload_targets'),'dispatch_errors':service.get('upload_dispatch_errors'),
            'channel':service.get('submission_channel'),'new_native_starts':len(starts),
            'new_native_ok':sum(e.get('result')=='ok' for e in ends.values()),
            'new_native_failures':dict(collections.Counter(e.get('failure_kind') for e in ends.values() if e.get('result')!='ok')),
            'peak_upload_submit_callbacks':peak,'saved_new_answers':len(seen_saves),
            'new_dispatch':read(ROOT/'owner-upload-dispatch.json')}
        with (HERE/'live-verification.jsonl').open('a') as stream:stream.write(json.dumps(frame,ensure_ascii=False)+'\n')
        label=(owner,match,ready,frame['generating'],frame['uploading_pages'],frame['new_native_ok'],frame['saved_new_answers'],frame['supervisor_state'])
        if label!=last_label:print(json.dumps({k:v for k,v in frame.items() if k not in ['new_dispatch','retained']},ensure_ascii=False),flush=True);last_label=label
        if ready and peak>=5 and frame['new_native_ok'] and seen_saves:
            (HERE/'live-result.json').write_text(json.dumps(dict(frame,saved_answers=seen_saves,state='five_slot_dispatch_and_independent_collection_observed'),ensure_ascii=False,indent=2)+'\n');return
        if new_owner_at and at-new_owner_at>300:
            (HERE/'live-result.json').write_text(json.dumps(dict(frame,saved_answers=seen_saves,state='bounded_observation_completed'),ensure_ascii=False,indent=2)+'\n');return
        time.sleep(10)
    (HERE/'live-result.json').write_text(json.dumps(dict(frame,state='handoff_or_observation_pending'),ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
