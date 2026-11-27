import collections,datetime,fcntl,json,os,time
from pathlib import Path
from zoneinfo import ZoneInfo
report=Path(__file__).resolve().parent;root=report.parents[1];data=root/'infrastructure/data'
def read(path):
 try:return json.loads(path.read_text())
 except (OSError,ValueError):return {}
def sample():
 now=time.time();owner=read(data/'web-card-service.json');obs=read(data/'web-page-observer.json');health=read(data/'shared-page-health.json');reg=read(data/'shared-gpt-window.json');gate=read(data/'web-channel-control.json').get('chatgpt',{})
 with (report/'minute-stats.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  history=[json.loads(x) for x in (report/'minute-stats.jsonl').read_text().splitlines() if x.strip()];prev=history[-1] if history else {};bucket=int(now//60)
  if prev.get('minute_bucket')==bucket:
   print(json.dumps({k:v for k,v in prev.items() if k not in ('pages','channel')},ensure_ascii=False),flush=True);return
  pages=[];bytarget={p['target_id']:p for p in obs.get('pages',[])};hp=health.get('pages',{})
  for slot in reg.get('slots',[]):
   tid=slot.get('target_id');op=bytarget.get(tid,{});h=hp.get(tid,{});fresh=obs.get('owner_pid')==owner.get('pid') and 0<=now-op.get('checked_at',0)<30 and op.get('window_observed') is True and op.get('window_id')==reg.get('window_id') and 0<=now-op.get('window_checked_at',0)<30
   state='waiting_observation'
   if fresh and op.get('state')=='login_required':state='login_required'
   elif gate.get('manual_verification_required') is True and gate.get('source')=='user_report_current_chat' and slot['slot_id'] in gate.get('target_slots',[]):state='login_reported_by_user'
   elif fresh and op.get('streaming') and op.get('activity_verified'):state='sent_generating'
   elif fresh and 0<=now-h.get('evidence',{}).get('checked_at',0)<90:state=h.get('health','waiting_observation')
   pages.append({'slot':slot['slot_id'],'target_id':tid,'state':state,'observer_state':op.get('state'),'checked_at':op.get('checked_at'),'fresh':fresh,'health':h.get('health'),'reason':h.get('reason'),'login_evidence':op.get('login_evidence',[])})
  since=prev.get('captured_at_epoch',now);events=[]
  for line in (data/'upload-attempt-events.jsonl').read_text().splitlines():
   try:e=json.loads(line)
   except ValueError:continue
   at=e.get('at',e.get('finished_at',e.get('started_at',0)))
   if isinstance(at,(int,float)) and since<at<=now:events.append(e)
  def kind(e):return e.get('event',e.get('kind'))
  alive=False
  try:pid=owner.get('pid');assert type(pid) is int and pid>0;os.kill(pid,0);alive=True
  except (OSError,AssertionError):pass
  row={'captured_at':datetime.datetime.fromtimestamp(now,ZoneInfo('Asia/Shanghai')).isoformat(),'captured_at_epoch':now,'minute_bucket':bucket,'owner_pid':owner.get('pid'),'owner_alive':alive,'owner_state':owner.get('state'),'owner_age':round(now-owner.get('updated',0),1),'observer_age':round(now-obs.get('updated',0),1),'observer_owner_pid':obs.get('owner_pid'),'counts':dict(collections.Counter(p['state'] for p in pages)),'fixed_slots':len(pages),'channel':owner.get('submission_channel'),'owner_metadata_fresh':alive and 0<=now-owner.get('updated',0)<30,'uploading_pages':owner.get('uploading_pages') if alive and 0<=now-owner.get('updated',0)<30 else None,'upload_budget_used':owner.get('upload_budget_used') if alive and 0<=now-owner.get('updated',0)<30 else None,'new_upload_started':sum(kind(e)=='upload_started' for e in events),'new_upload_success':sum(kind(e)=='upload_finished' and e.get('result')=='ok' for e in events),'new_upload_failed':sum(kind(e)=='upload_finished' and e.get('result')=='failed' for e in events),'new_protocol_error_events':sum(kind(e)=='network' and e.get('failure')=='net::ERR_HTTP2_PROTOCOL_ERROR' for e in events),'new_upload_timeout':sum(kind(e)=='upload_finished' and e.get('result')=='failed' and str(e.get('failure_kind','')).endswith('_timeout') for e in events),'new_network_error_events':sum(kind(e)=='network' and bool(e.get('failure')) for e in events),'pages':pages,'interval_since_previous_seconds':round(now-since,3),'observation_gap_seconds':round(now-since,3) if now-since>90 else 0}
  with (report/'minute-stats.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
  print(json.dumps({k:v for k,v in row.items() if k not in ('pages','channel')},ensure_ascii=False),flush=True)

if __name__ == "__main__":
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument("--count",type=int,default=1);args=parser.parse_args()
 if not 1<=args.count<=61:parser.error("count must be 1..61")
 for n in range(args.count):
  sample()
  if n+1<args.count:time.sleep(60)
