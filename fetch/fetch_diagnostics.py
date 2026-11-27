"""Read-only acquisition results and reasons for idle capacity; no HTTP probes."""
import collections,datetime,json,time

def report(catalog,hours=24):
    at=time.time();cut=datetime.datetime.fromtimestamp(at-hours*3600,datetime.timezone.utc).isoformat()
    with catalog.connect() as db:
        downloads=db.execute("SELECT count(distinct paper_id) FROM events WHERE kind='download' AND created>=?",(cut,)).fetchone()[0]
        timing=[json.loads(r[0]) for r in db.execute("SELECT payload FROM events WHERE kind='acquisition_timing' AND created>=?",(cut,))]
        pending=dict(db.execute('SELECT state,count(*) FROM discovery_pending GROUP BY state').fetchall())
        due=db.execute("SELECT count(*) FROM discovery_pending WHERE state='pending' AND retry_at<=?",(at,)).fetchone()[0]
        failures=[json.loads(r[0]) for r in db.execute("SELECT payload FROM events WHERE kind='acquisition_pending' AND created>=?",(cut,))]
        transport=[json.loads(r[0]) for r in db.execute("SELECT payload FROM events WHERE kind='fetch_transport_observation' AND created>=?",(cut,))]
        waits=db.execute("SELECT count(*) FROM events WHERE kind='fetch_source_wait' AND created>=?",(cut,)).fetchone()[0]
    def read(name):
        try:return json.loads((catalog.path.parent/name).read_text())
        except (OSError,ValueError):return {}
    network=read('network-state.json');seeds=read('seed-discovery-status.json');worker=read('worker-fetch.json')
    stages={}
    for stage in ('fast','fallback'):
        rows=[x for x in timing if x.get('stage')==stage]
        stages[stage]={'attempts':len(rows),'successes':sum(bool(x.get('available')) for x in rows),'worker_seconds':round(sum(x.get('seconds',0) for x in rows),1)}
    return {'updated':at,'window_hours':hours,'downloaded_unique':downloads,'stages':stages,'pending':pending,'due_pending':due,
            'seed_states':dict(collections.Counter(x.get('state') for x in seeds.get('seeds',{}).values())),
            'seed_observed_at':seeds.get('updated'),'worker_observed_at':worker.get('updated'),'actual_active':worker.get('actual_active'),
            'cooldowns':{k:{'code':v.get('code'),'retry_at':v['retry_at']} for k,v in network.items() if v.get('retry_at',0)>at},
            'failure_classes':dict(collections.Counter(x.get('kind','unspecified') for r in failures for x in r.get('attempts',[]))),
            'failures_without_details':sum(not r.get('attempts') for r in failures),
            'fetchpdf_observations':{'scope':'completed instrumented fetchpdf calls only; excludes direct, OSTI and interrupted calls',
                'calls':len(transport),'requests_started':sum(x.get('requests_started',0) for x in transport),
                'metadata_cache_hits':sum(x.get('metadata_cache_hits',0) for x in transport)},
            'pre_request_waits_preserving_budget':waits}

if __name__=='__main__':
    from core.api import catalog__Catalog as Catalog, catalog__load_config as load_config
    print(json.dumps(report(Catalog(load_config()['catalog_path'])),ensure_ascii=False,indent=2))
