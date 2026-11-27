"""Durable page-affine queues and background material preparation (no browser)."""
import json,os,subprocess,threading,time
from core.api import paths__WorkspacePath as Path
from core.api import catalog__ROOT as ROOT, catalog__now as now
from core.api import services__atomic_json as atomic_json
from cards.api import web_card_queue as queue

SEED_TRACE_INTERVAL_SECONDS=60

def install(catalog):
    with catalog.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS web_page_queue(
          paper_id TEXT PRIMARY KEY,target_id TEXT NOT NULL,state TEXT NOT NULL,
          assigned REAL NOT NULL,error TEXT NOT NULL DEFAULT '')''')

def assign(catalog,targets,depth=2,config=None):
    """Only never-claimed due queue entries move; submitted history never moves."""
    queue.install(catalog);install(catalog);targets=sorted(set(targets))
    if config is not None:
        from .shared_workflow_queue import install as install_arrivals
        install_arrivals(catalog)
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("DELETE FROM web_page_queue WHERE paper_id IN (SELECT paper_id FROM web_card_jobs WHERE state!='queued')")
        if not targets:return
        rows=db.execute("SELECT q.* FROM web_page_queue q JOIN web_card_jobs j USING(paper_id) WHERE j.state='queued'").fetchall()
        loads={t:sum(r['target_id']==t for r in rows) for t in targets}
        # A removed/retired slot can surrender only a provably unsent queued item.
        for r in rows:
            if r['target_id'] not in loads:
                t=min(loads,key=lambda k:(loads[k],k));db.execute('UPDATE web_page_queue SET target_id=? WHERE paper_id=?',(t,r['paper_id']));loads[t]+=1
        if config is not None:
            jobs=db.execute("SELECT j.* FROM web_card_jobs j LEFT JOIN web_page_queue q USING(paper_id) JOIN shared_workflow_arrivals a ON a.lane=CASE WHEN json_extract(j.selection,'$.rework.correction_id') IS NULL THEN 'cards' ELSE 'correction' END AND a.job_id=coalesce(json_extract(j.selection,'$.rework.correction_id'),j.paper_id) WHERE j.state='queued' AND j.retry_at<=? AND q.paper_id IS NULL ORDER BY a.queued_at,a.sequence,j.paper_id",(time.time(),)).fetchall()
        else:
            jobs=db.execute("SELECT j.* FROM web_card_jobs j LEFT JOIN web_page_queue q USING(paper_id) WHERE j.state='queued' AND j.retry_at<=? AND q.paper_id IS NULL ORDER BY (json_extract(j.selection,'$.rework') IS NOT NULL) DESC,j.updated",(time.time(),)).fetchall()
        from core.api import workflow_priority__sort as sort_articles
        jobs=sort_articles(db,[dict(job) for job in jobs],config or {})
        for j in jobs:
            if config is not None:
                from correction.api import card_correction_queue__allows_web_job as allows_web_job
                if not allows_web_job(config,dict(j)):continue
            t=min(loads,key=lambda k:(loads[k],k))
            if loads[t]>=depth:break
            db.execute('INSERT INTO web_page_queue(paper_id,target_id,state,assigned) VALUES(?,?,?,?)',(j['paper_id'],t,'waiting',time.time()));loads[t]+=1

def next_ready(catalog,targets):
    if not targets:return None
    with catalog.connect() as db:
        from core.api import workflow_priority__seed_first as seed_first
        candidates=seed_first(db,[dict(row) for row in db.execute("SELECT q.* FROM web_page_queue q JOIN web_card_jobs j USING(paper_id) WHERE q.state='ready' AND j.state='queued' AND j.retry_at<=? AND q.target_id IN ("+','.join('?' for _ in targets)+") ORDER BY (json_extract(j.selection,'$.rework') IS NOT NULL) DESC,q.assigned",(time.time(),*targets))])
        r=candidates[0] if candidates else None
        return dict(r) if r else None

def prepare(config,job):
    from cards.api import web_card_inputs__digest as digest
    from cards.api import web_card_rework__submission_history as submission_history
    from cards.api import web_card_rework__authorization as authorization
    catalog=__import__('core.api',fromlist=['catalog']).catalog.Catalog(config['catalog_path'])
    pid=job['paper_id'];paper=catalog.get(pid);folder=catalog.path.parent/'web_cards'/pid
    with catalog.connect() as db:human=db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='human_decision'",(pid,)).fetchone()
    if not authorization(job,paper) and (paper['decision']!='unreviewed' or paper.get('card_path') or human or (Path(config['studio_library_root'])/pid/'card.json').exists()):raise ValueError('已有卡片或人工决定，不覆盖')
    if any(paper['metadata'].get(k) for k in ('identity_review_required','version_review_required','out_of_scope')):raise ValueError('身份/版本/范围待核对')
    decision=submission_history(catalog,job,folder)
    if not decision.allowed:raise ValueError(decision.reason)
    folder.mkdir(parents=True,exist_ok=True)
    if not (folder/'packet.json').exists():
        request=dict(source=paper['asset_path'],folder=str(folder),paper_id=pid,title=paper['title'],expected_hash=job['source_sha256'])
        trial=json.loads(job['selection']).get('manual_seed_trial')
        if trial:request['independent_request']=trial['request_id']
        if config['web_cards'].get('media_root'):request.update(media_root=config['web_cards']['media_root'],media_volume=config['archive_volume'])
        atomic_json(folder/'prepare-request.json',request)
        with (folder/'prepare.log').open('a') as log:
            result=subprocess.run([config['web_cards']['pdf_python'],'-m','cards.web_card_inputs',str(folder/'prepare-request.json')],cwd=ROOT,stdout=log,stderr=log,timeout=600)
        if result.returncode:raise ValueError('材料准备失败，不重复尝试同输入')
    packet=json.loads((folder/'packet.json').read_text())
    if digest(paper['asset_path'])!=packet['source_original_sha256']:raise ValueError('原文指纹变化')
    for name,h in packet['input_hashes'].items():
        if digest(folder/name)!=h:raise ValueError('冻结材料指纹变化')
    return packet

class MaterialProducer:
    def __init__(self,config):
        from core.api import catalog__Catalog as Catalog
        self.config=config;self.catalog=Catalog(config['catalog_path']);install(self.catalog)
        self.selection={};self.stop_event=threading.Event();self.workers=max(1,min(8,int(config.get('web_cards',{}).get('material_prepare_workers',4))))
        self.threads=[threading.Thread(target=self.run,args=(index,),name='web-material-producer-%d'%index,daemon=True) for index in range(self.workers)]
        self.seed_trace_thread=threading.Thread(target=self._trace_seeds,name='seed-evidence-tracker',daemon=True)
        with self.catalog.connect() as db:db.execute("UPDATE web_page_queue SET state='waiting' WHERE state='preparing'")
    def start(self):
        self.seed_trace_thread.start()
        for thread in self.threads:thread.start()
    def stop(self):
        self.stop_event.set()
        for thread in self.threads:thread.join()
        self.seed_trace_thread.join()
    def _trace_seeds(self):
        """Local evidence only; long preparation/recovery never schedules this clock."""
        from core.api import seed_focus__monitor as seed_monitor
        path=self.catalog.path.parent/'seed-tracking-worker.json'
        report={'owner_pid':os.getpid(),'thread_name':threading.current_thread().name,
                'interval_seconds':SEED_TRACE_INTERVAL_SECONDS,'completed_rounds':0,'failed_rounds':0}
        while not self.stop_event.is_set():
            started=time.monotonic();report.update(state='checking',started_at=time.time())
            atomic_json(path,report)
            try:
                seed_monitor(self.config);report['completed_rounds']+=1;report['state']='checked';report.pop('error',None)
            except Exception as exc:
                error=str(exc)[:700];report['failed_rounds']+=1;report.update(state='evidence_pending',error=error)
                atomic_json(self.catalog.path.parent/'seed-tracking-error.json',{'at':time.time(),'error':error})
            report.update(finished_at=time.time(),duration_seconds=time.monotonic()-started)
            atomic_json(path,report)
            self.stop_event.wait(max(.001,SEED_TRACE_INTERVAL_SECONDS-(time.monotonic()-started)))
        report.update(state='stopped',stopped_at=time.time());atomic_json(path,report)
    def refresh_selection(self):
        """Only the existing preparation worker scans inventory; no browser calls."""
        from cards.api import web_card_service__enabled as enabled
        from core.api import seed_focus__active as focus_active
        if self.stop_event.is_set() or not enabled(self.config) or focus_active(self.config):return
        from .shared_browser_window import enabled as shared_enabled
        from .shared_page_backlog import enabled as backlog_enabled
        config=self.config
        if shared_enabled(config) and backlog_enabled(config):
            config={**config,'web_cards':{**config['web_cards'],'refill_min_pending':0}}
        try:
            result=queue.select(self.catalog,config)
            self.selection=result
            atomic_json(self.catalog.path.parent/'web-selection-discovery.json',
                        {'updated':time.time(),'state':'completed','selection':result})
        except Exception as exc:
            atomic_json(self.catalog.path.parent/'web-selection-discovery.json',
                        {'updated':time.time(),'state':'error','error':str(exc)[:700]})

    def run(self,worker=0):
        from cards.api import web_card_service__owner_enabled as owner_enabled
        from correction.api import card_correction_queue__allows_web_job as allows_web_job
        last_issues = 0; last_manual = 0; last_trials = 0; last_selection = 0
        while not self.stop_event.is_set():
            try:
                if worker == 0:
                    if time.monotonic()-last_selection>=60:
                        self.refresh_selection();last_selection=time.monotonic()
                    from core.api import seed_focus__active as focus_active
                    if not focus_active(self.config) and time.monotonic() - last_manual >= max(10,self.config.get('manual_literature',{}).get('scan_interval_seconds',60)):
                        last_manual = time.monotonic()
                        from reading.api import manual_literature__run_once as scan_manual_library
                        try:scan_manual_library(self.catalog, self.config)
                        except Exception as exc:
                            atomic_json(self.catalog.path.parent/'manual-literature-status.json',
                                {'state':'scan_error','updated':time.time(),'error':str(exc)[:1000]})
                    if time.monotonic()-last_trials>=60:
                        last_trials=time.monotonic()
                        from cards.api import seed_trials__run_once as advance_seed_trials
                        try:advance_seed_trials(self.catalog,self.config)
                        except Exception as exc:
                            atomic_json(self.catalog.path.parent/'manual-seed-trials-status.json',
                                {'state':'policy_or_evidence_pending','updated':time.time(),'error':str(exc)[:1000]})
                    if time.monotonic() - last_issues >= 60:
                        last_issues = time.monotonic()
                        from review.api import production_contract__reconcile as accept_production
                        try:accept_production(self.catalog,self.config)
                        except Exception as exc:
                            atomic_json(self.catalog.path.parent/'production-acceptance-error.json',
                                        {'at':time.time(),'error':str(exc)[:700]})
                        from core.api import automatic_issue_handler__run_once as run_once
                        run_once(self.catalog, self.config, stopping=self.stop_event.is_set,
                                 maintain_review_cycle=False)
                if self.stop_event.is_set():break
                if not owner_enabled(self.config):self.stop_event.wait(1);continue
                with self.catalog.connect() as db:
                    rows=db.execute("SELECT j.*,a.queued_at,a.sequence FROM web_page_queue q JOIN web_card_jobs j USING(paper_id) JOIN shared_workflow_arrivals a ON a.lane=CASE WHEN json_extract(j.selection,'$.rework.correction_id') IS NULL THEN 'cards' ELSE 'correction' END AND a.job_id=coalesce(json_extract(j.selection,'$.rework.correction_id'),j.paper_id) WHERE q.state='waiting' AND j.state='queued' AND j.retry_at<=? ORDER BY a.queued_at,a.sequence,q.assigned",(time.time(),)).fetchall()
                    from core.api import workflow_priority__sort as sort_articles
                    rows=sort_articles(db,[dict(r) for r in rows],self.config)
                    job=next((dict(r) for r in rows if allows_web_job(self.config,dict(r))),None)
                    claimed=db.execute("UPDATE web_page_queue SET state='preparing' WHERE paper_id=? AND state='waiting'",(job['paper_id'],)).rowcount if job else 0
                if not job or claimed==0:self.stop_event.wait(3);continue
                try:
                    if not allows_web_job(self.config,job):state='waiting';error='任务已暂停，保留材料队列'
                    else:prepare(self.config,job);state='ready';error=''
                except Exception as exc:
                    state='failed';error=str(exc)[:700]
                    queue.update(self.catalog,job['paper_id'],state='needs_inspection',error='材料准备：'+error)
                with self.catalog.connect() as db:db.execute('UPDATE web_page_queue SET state=?,error=? WHERE paper_id=?',(state,error,job['paper_id']))
                atomic_json(self.catalog.path.parent/'web-material-producer.json',{'updated':time.time(),'paper_id':job['paper_id'],'state':state,'error':error})
            except Exception as exc:
                atomic_json(self.catalog.path.parent/'web-material-producer.json',{'updated':time.time(),'state':'error','error':str(exc)[:500]});self.stop_event.wait(1)
