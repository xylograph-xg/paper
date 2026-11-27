"""Isolated crawler adapter; stdout JSON, diagnostics kept inside result.

Importing crawler's top-level config/models cannot contaminate the reading process.
"""
from __future__ import annotations
from core.api import paths__workspace_root as _workspace_root
import json
import sys
import time
import hashlib
import threading
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor,as_completed
from core.api import paths__WorkspacePath as Path

ROOT=_workspace_root()
from crawler.api import load_metadata_parsers
from .oa_policy import eligible as oa_eligible

parse_work,parse_paper=load_metadata_parsers()


def oa_record(w):
    p=parse_work(w).to_dict()
    p['publication_date']=w.get('publication_date')
    access=w.get('open_access') or {}
    p['is_oa']=bool(access.get('is_oa'))
    p['oa_status']=access.get('oa_status')
    locations=[w.get('best_oa_location'),w.get('primary_location')]+(w.get('locations') or [])
    p['pdf_urls']=list(dict.fromkeys(x['pdf_url'] for x in locations if x and x.get('pdf_url')))
    return p


def s2_record(w):
    p=parse_paper(w).to_dict()
    p['pdf_urls']=[w['openAccessPdf']['url']] if (w.get('openAccessPdf') or {}).get('url') else []
    p['is_oa']=bool(p['pdf_urls'])
    return p


def page_state(previous,key):
    state=previous.get(key,{})
    if not isinstance(state,dict):state={}
    if state.get('done') and state.get('next_scan_at',0)>time.time():return None
    return state if not state.get('done') else {}


def distinct_seeds(seeds):
    from core.api import catalog__doi as doi
    result={}
    for seed in seeds:
        key=doi(seed.get('doi'))
        if key and key not in result:result[key]={**seed,'doi':key}
    return list(result.values())


def discover(request):
    from .network import ProviderClient,DeferredRequest,ready as provider_ready
    from core.api import services__atomic_json as atomic_json
    previous=request.get('positions',{});settings=request.get('network',{})
    def recent_cutoff():
        try:years=int(settings.get('discovery_max_age_years',20) or 0)
        except (TypeError,ValueError):years=20
        if years<=0:return None
        today=datetime.now(timezone.utc).date()
        try:cutoff=today.replace(year=today.year-years)
        except ValueError:cutoff=today.replace(year=today.year-years,day=28)
        return cutoff.isoformat()
    oa_only=bool(settings.get('oa_only',False))
    folder=Path(request.get('state_dir') or ROOT/'data')
    if folder.resolve()==(ROOT/'data').resolve():
        from core.api import catalog__Catalog as Catalog, catalog__load_config as load_config
        from .seed_expansion import expand_when_idle
        expansion=expand_when_idle(Catalog(folder/'catalog.sqlite3'),load_config())
        if expansion.get('state')=='expanded':
            request={**request,'seeds':[*(request.get('seeds') or []),expansion['metadata']]}
    client=ProviderClient(folder,timeout=settings.get('request_timeout_seconds',15))
    rows=min(100,max(1,settings.get('page_size',100)))
    output={'pool':[],'resolved':[],'warnings':[],'raw':[],'positions':{},'channels':{}}
    def keep(record):return not oa_only or oa_eligible(record)
    mutex=threading.Lock();seed_context=threading.local();seed_channel_failure=[None];crossref_used=[0]
    seed_workers=min(10,max(1,settings.get('seed_workers',settings.get('source_workers',4))))
    topic_workers=min(6,max(1,settings.get('topic_workers',2)))
    seeds=distinct_seeds(request.get('seeds',[]))
    # A full seed graph can exceed the discovery timeout. Rotate the starting
    # point each run so late seeds get the same chance as the first ones.
    rotation_path=folder/'seed-rotation.json'
    try:rotation=json.loads(rotation_path.read_text())
    except (OSError,ValueError):rotation={}
    if seeds:
        offset=int(rotation.get('offset',0))%len(seeds)
        seeds=seeds[offset:]+seeds[:offset]
        atomic_json(rotation_path,{'offset':(offset+max(1,seed_workers*4))%len(seeds),'updated':time.time()})
        # New manual seeds stay ahead of the rotation; derived/auto seeds retain it.
        seeds.sort(key=lambda s:(not bool(s.get('manual_seed_fast_lane')),s.get('doi','')))
    output['seed_tasks']={s['doi']:{'state':'queued','title':s.get('title',''),'records':0,'warnings':0} for s in seeds}
    # Only a bounded rotating subset may use secondary requests each cycle.
    # Oldest secondary scan first prevents the first seeds monopolizing fallback.
    fallback_limit=settings.get('seed_crossref_fallback_limit',0)
    fallback_candidates=sorted(seeds,key=lambda s:(not bool(s.get('manual_seed_fast_lane')),previous.get('v3:crossref-references:'+s['doi'],{}).get('last_checked',0)))
    fallback_seeds={s['doi'] for s in fallback_candidates if previous.get('v3:crossref-references:'+s['doi'],{}).get('next_scan_at',0)<=time.time()}
    fallback_seeds=set(s['doi'] for s in fallback_candidates if s['doi'] in fallback_seeds and not all(page_state(previous,p+s['doi']) is None for p in ('v2:oa-references:','v2:oa-citations:'))) if fallback_limit else set()
    fallback_seeds=set([s['doi'] for s in fallback_candidates if s['doi'] in fallback_seeds][:fallback_limit])
    try:fallback_batch_size=max(1,min(seed_workers,int(settings.get('seed_fallback_batch',seed_workers))))
    except (TypeError,ValueError):fallback_batch_size=seed_workers
    fallback_due=[s for s in fallback_candidates if previous.get('v3:crossref-references:'+s['doi'],{}).get('next_scan_at',0)<=time.time()]
    fallback_batch_keys={s['doi'] for s in (fallback_due or fallback_candidates)[:fallback_batch_size]}
    attempted=set()
    seed_status_path=folder/'seed-discovery-status.json'
    last_seed_status=[0]
    def save_seed_status(force=False):
        if not force and time.monotonic()-last_seed_status[0]<1:return
        last_seed_status[0]=time.monotonic()
        atomic_json(seed_status_path,{'updated':time.time(),'seed_workers':seed_workers,'topic_workers':topic_workers,'seeds':{k:v for k,v in output['seed_tasks'].items() if k in attempted}})
    checkpoint=request.get('checkpoint_path')
    try:checkpoint_gap=max(0.0,float(settings.get('checkpoint_seconds',2.0)))
    except (TypeError,ValueError):checkpoint_gap=2.0
    last_checkpoint=[0.0]

    def emit(records=None,positions=None,raw=None,resolved=None,channel='journal',warning=None):
        from core.api import record_contract__normalize as normalize
        def checked(items):
            result=[]
            for item in items or []:
                try:result.append(normalize(item))
                except (ValueError,TypeError) as exc:
                    with mutex:
                        output.setdefault('quarantined',[]).append({'record':item,'error':str(exc)})
                        output['warnings'].append('隔离书目记录：'+str(exc))
            return result
        records=checked(records);resolved=checked(resolved)
        seed_key=getattr(seed_context,'key',None)
        if seed_key:
            from core.api import catalog__doi as doi
            for record in [*records,*resolved]:
                if doi(record.get('doi')) != seed_key:
                    record['discovered_from_seed_dois']=list(dict.fromkeys(
                        [*(record.get('discovered_from_seed_dois') or []),seed_key]))
        with mutex:
            output['pool'].extend(records or []);output['resolved'].extend(resolved or [])
            output['positions'].update(positions or {})
            output['raw'].extend(raw or [])
            seed_key=getattr(seed_context,'key',None)
            if seed_key:
                stat=output['seed_tasks'][seed_key];stat['records']+=len(records or []);stat['warnings']+=bool(warning)
                save_seed_status()
            if warning:output['warnings'].append(warning)
            state=output['channels'].setdefault(channel,{'state':'ok','pool_count':0})
            state['pool_count']+=len(records or [])
            if warning:state['state']='partial' if state['pool_count'] else 'failed'
            elif state['state']=='failed':state['state']='partial'
            if checkpoint and (not last_checkpoint[0] or time.monotonic()-last_checkpoint[0]>=checkpoint_gap):
                atomic_json(checkpoint,output);last_checkpoint[0]=time.monotonic()

    def convert(items,reason):
        records=[]
        for item in items:
            try:
                p=oa_record(item)
                if p.get('title'):records.append({**p,'channels':['journal'],'discovery_reasons':[reason]})
            except (KeyError,ValueError,TypeError,AttributeError) as exc:
                with mutex:output.setdefault('quarantined',[]).append({'record':item,'error':str(exc)})
                emit(warning='OpenAlex 记录隔离：'+str(exc))
        return records

    def oa_page(key,params,reason,recent_only=False):
        state=page_state(previous,key)
        if state is None:return False
        snapshot=state.get('snapshot') or datetime.now(timezone.utc).date().isoformat()
        params={**params,'per_page':rows,'cursor':state.get('cursor','*')}
        cutoff=recent_cutoff() if recent_only else None
        params['filter']=','.join(filter(None,[params.get('filter'),'from_publication_date:'+cutoff if cutoff else None,'to_publication_date:'+snapshot]))
        data=client.get('https://api.openalex.org/works',params,'openalex')
        items=data.get('results') or [];cursor=(data.get('meta') or {}).get('next_cursor')
        done=not items or not cursor
        progress={'cursor':cursor,'snapshot':snapshot,'done':done,'next_scan_at':time.time()+86400 if done else 0}
        records=[r for r in convert(items,reason) if keep(r)]
        emit(records,{key:progress},[{'provider':'openalex','query_key':key,'response':data}])
        return bool(records)

    def topic(query):
        # Exhausted/cooling-down sources are not the end of this topic search.
        # Each provider retains its own cursor and failure protection.
        primary_failed=False
        try:
            if oa_page('v2:oa-topic:'+query,{'search':query,'filter':'open_access.is_oa:true'},'OLED 主题检索：'+query,recent_only=True):return
        except Exception as exc:
            primary_failed=True;emit(warning='openalex: '+str(exc))
        key='v2:s2-topic:'+query;state=page_state(previous,key)
        if state is not None:
            try:
                fields='paperId,title,abstract,authors,year,venue,externalIds,citationCount,openAccessPdf,url'
                params={'query':query,'limit':100,'offset':state.get('offset',0),'fields':fields}
                cutoff=recent_cutoff()
                if cutoff:params['year']=cutoff[:4]+'-'+str(datetime.now(timezone.utc).year)
                data=client.get('https://api.semanticscholar.org/graph/v1/paper/search',params,'s2')
                records=[{**s2_record(w),'channels':['journal'],'discovery_reasons':['OLED 主题检索：'+query]} for w in data.get('data',[]) if w.get('title')]
                records=[r for r in records if keep(r)]
                next_offset=data.get('next');done=next_offset is None
                emit(records,{key:{'offset':next_offset or 0,'done':done,'next_scan_at':time.time()+86400 if done else 0}},[{'provider':'s2','query_key':key,'response':data}])
                if records:return
            except Exception as error:
                primary_failed=True;emit(warning='s2: '+str(error))
        from .preprints import crossref_record
        mode=str(settings.get('crossref_topic_fallback','always'))
        if mode=='never' or (mode=='provider_failure' and not primary_failed):return
        try:budget=int(settings.get('crossref_topic_budget',3))
        except (TypeError,ValueError):budget=3
        with mutex:
            if budget>0 and crossref_used[0]>=budget:return
            crossref_used[0]+=1
        key='v2:crossref-topic:'+query;state=page_state(previous,key)
        if state is None:return
        try:
            snapshot=state.get('snapshot') or datetime.now(timezone.utc).date().isoformat()
            cutoff=recent_cutoff()
            try:crossref_rows=min(rows,max(1,int(settings.get('crossref_topic_rows',rows))))
            except (TypeError,ValueError):crossref_rows=rows
            params={'query.bibliographic':query,'rows':crossref_rows,'cursor':state.get('cursor','*'),
                    'filter':','.join(filter(None,['type:journal-article','until-created-date:'+snapshot,'from-pub-date:'+cutoff if cutoff else None]))}
            data=client.get('https://api.crossref.org/works',params,'crossref')
            message=data.get('message',{});items=message.get('items') or [];cursor=message.get('next-cursor');done=len(items)<rows or not cursor
            records=[]
            for item in items:
                try:
                    record=crossref_record(item)
                    if record['title'] and keep(record):records.append(record)
                except (TypeError,ValueError,KeyError,IndexError):continue
            emit(records,{key:{'cursor':cursor,'snapshot':snapshot,'done':done,'next_scan_at':time.time()+3600 if done else 0}},
                 [{'provider':'crossref','query_key':key,'response':data}])
        except Exception as failure:emit(warning='crossref topic: '+str(failure))

    def crossref_seed(seed):
        from .seed_crossref_fallback import discover_seed
        identifier=seed.get('doi');key='v3:crossref-references:'+identifier
        try:
            records,resolved,positions,errors=discover_seed(client,folder,seed,previous,settings.get('seed_crossref_reference_batch',3))
            for value in positions.values():value['last_checked']=time.time()
            emit(records,positions,resolved=resolved,warning='; '.join(errors) if isinstance(errors,list) and errors else None)
            with mutex:output['seed_tasks'][identifier]['secondary_state']='partial' if errors else 'completed'
        except Exception as fallback_error:
            emit(positions={key:{**previous.get(key,{}),'last_checked':time.time(),'next_scan_at':getattr(fallback_error,'retry_at',time.time()+900)}},
                 warning='crossref seed: '+str(fallback_error))
            with mutex:output['seed_tasks'][identifier]['secondary_state']='failed'

    def seed_task(seed,primary=True):
        identifier=seed.get('doi')
        if not identifier:return
        if not primary:
            with mutex:output['seed_tasks'][identifier]['primary_state']='deferred'
            crossref_seed(seed);return
        try:
            cache=folder/'seed-cache'/ (hashlib.sha256(identifier.encode()).hexdigest()+'.json')
            try:cached=json.loads(cache.read_text())
            except (OSError,ValueError):cached={}
            if cached.get('expires',0)>time.time():work=cached['work']
            else:
                work=client.get('https://api.openalex.org/works/https://doi.org/'+identifier,provider='openalex')
                atomic_json(cache,{'expires':time.time()+86400,'work':work})
            parsed=oa_record(work);emit(resolved=[parsed])
            refkey='v2:oa-references:'+identifier;state=page_state(previous,refkey)
            if state is not None:
                start=state.get('offset',0);references=work.get('referenced_works') or [];batch=references[start:start+rows]
                if batch:
                    data=client.get('https://api.openalex.org/works',{'filter':'openalex_id:'+'|'.join(x.rsplit('/',1)[-1] for x in batch)+',open_access.is_oa:true','per_page':rows},'openalex')
                    done=start+rows>=len(references)
                    emit([r for r in convert(data.get('results') or [],'参考文献：'+seed['title']) if keep(r)],{refkey:{'offset':start+rows,'done':done,'next_scan_at':time.time()+86400 if done else 0}},[{'provider':'openalex','query_key':refkey,'response':data}])
                else:emit(positions={refkey:{'done':True,'next_scan_at':time.time()+86400}})
            oa_page('v2:oa-citations:'+identifier,{'filter':'cites:'+parsed['openalex_id']+',open_access.is_oa:true'},'引用种子：'+seed['title'])
            correction=seed.get('linked_correction_doi')
            if correction:
                key='v2:oa-correction:'+correction
                if page_state(previous,key) is not None:
                    data=client.get('https://api.openalex.org/works/https://doi.org/'+correction,provider='openalex')
                    emit(resolved=[{**oa_record(data),'is_correction':True}],positions={key:{'done':True,'next_scan_at':time.time()+86400}})
        except Exception as exc:
            if isinstance(exc,DeferredRequest) and exc.provider=='openalex':seed_channel_failure[0]=exc
            emit(warning='openalex seed: '+str(exc))
            with mutex:
                output['seed_tasks'][identifier].update(primary_state='deferred',retry_at=getattr(exc,'retry_at',time.time()+900),reason=str(exc))
            if identifier in fallback_seeds:
                crossref_seed(seed)


    def preprints():
        from .preprints import discover as fetch
        settings={**request.get('preprints',{}),'positions':previous,'state_dir':str(folder),'network':request.get('network',{})}
        channels=request.get('discovery_channels',['oled_topic','seed_related','arxiv','chemrxiv'])
        if 'arxiv' not in channels:settings['arxiv_queries']=[]
        if 'chemrxiv' not in channels:settings['chemrxiv_queries']=[]
        def progress(part):
            channel=part.get('channel')
            if channel not in ('arxiv','chemrxiv'):raise ValueError('预印本页面缺少来源归属')
            emit(part.get('pool',[]),part.get('positions'),part.get('raw',[]),channel=channel,
                 warning='; '.join(part.get('warnings',[])) or None)
        fetch(settings,on_page=progress)

    def run_seed(seed,primary=True):
        key=seed['doi']
        if not primary:
            attempted.add(key);seed_context.key=key
            with mutex:
                output['seed_tasks'][key].update(state='running',started=time.time());save_seed_status()
            try:seed_task(seed,False)
            finally:
                with mutex:
                    stat=output['seed_tasks'][key]
                    stat.update(state='partial' if stat['records'] else 'fallback_waiting',finished=time.time());save_seed_status()
                seed_context.key=None
            return
        keys=['v2:oa-references:'+key,'v2:oa-citations:'+key]
        correction=seed.get('linked_correction_doi')
        if correction:keys.append('v2:oa-correction:'+correction)
        if all(page_state(previous,k) is None for k in keys):
            with mutex:
                output['seed_tasks'][key].update(state='waiting_next_scan',next_scan_at=min(previous[k]['next_scan_at'] for k in keys));save_seed_status()
            return
        gate=seed_channel_failure[0]
        if gate is not None:
            # A provider-wide failure hit during this run. Only the bounded
            # fallback batch continues through Crossref; the rest stay retryable.
            if key in fallback_batch_keys:
                attempted.add(key);seed_context.key=key
                with mutex:
                    output['seed_tasks'][key].update(state='running',started=time.time());save_seed_status()
                try:seed_task(seed,False)
                finally:
                    with mutex:
                        stat=output['seed_tasks'][key]
                        stat.update(state='partial' if stat['records'] else 'fallback_waiting',finished=time.time());save_seed_status()
                    seed_context.key=None
            else:
                with mutex:
                    output['seed_tasks'][key].update(state='deferred',primary_state='deferred',reason=str(gate),
                                                      retry_at=getattr(gate,'retry_at',time.time()+900));save_seed_status()
            return
        attempted.add(key);seed_context.key=key
        with mutex:
            output['seed_tasks'][key].update(state='running',started=time.time());save_seed_status()
        try:seed_task(seed,True)
        finally:
            with mutex:
                stat=output['seed_tasks'][key]
                stat.update(state=('partial' if stat['records'] else 'deferred' if stat.get('primary_state')=='deferred' else 'unavailable') if stat['warnings'] else 'completed',finished=time.time());save_seed_status()
            seed_context.key=None

    # Reserve seed slots separately so slow topic/preprint queries cannot occupy them.
    channels=request.get('discovery_channels',['oled_topic','seed_related','arxiv','chemrxiv'])
    seed_batch=list(seeds);openalex_down=False
    def seed_pages_due(seed):
        keys=['v2:oa-references:'+seed['doi'],'v2:oa-citations:'+seed['doi']]
        if seed.get('linked_correction_doi'):keys.append('v2:oa-correction:'+seed['linked_correction_doi'])
        return any(page_state(previous,k) is not None for k in keys)
    if 'seed_related' in channels and seeds and any(seed_pages_due(s) for s in seeds):
        try:
            provider_ready('openalex',folder)
        except DeferredRequest as exc:
            # The free OpenAlex budget is shared per IP and can return 401 after
            # exhaustion. Keep every seed retryable and run the DOI-exact Crossref
            # reference fallback for all seeds instead of the small rotating subset.
            openalex_down=True
            for seed in seeds:
                output['seed_tasks'][seed['doi']].update(state='deferred',primary_state='deferred',reason=str(exc),
                                                          retry_at=getattr(exc,'retry_at',0))
            seed_batch=[s for s in fallback_candidates if s['doi'] in fallback_batch_keys]
            output['seed_tasks']={s['doi']:output['seed_tasks'][s['doi']] for s in seed_batch}
            emit(channel='seed_related',warning=f'openalex 种子通道暂缓（免费额度/401）；本轮 {len(seed_batch)} 个种子改用 Crossref 参考文献后备，引用链待额度恢复：'+str(exc))
        except Exception as exc:
            seed_batch=[]
            emit(channel='seed_related',warning='openalex 种子通道状态不可读；本轮跳过种子请求：'+str(exc))
    with ThreadPoolExecutor(max_workers=seed_workers) as seed_pool, ThreadPoolExecutor(max_workers=topic_workers) as topic_pool:
        tasks=([seed_pool.submit(run_seed,s,not openalex_down) for s in seed_batch] if 'seed_related' in channels else [])+([topic_pool.submit(topic,q) for q in request.get('queries',[])] if 'oled_topic' in channels else [])+[topic_pool.submit(preprints)]
        for future in as_completed(tasks):
            try:future.result()
            except Exception as exc:emit(warning='discovery: '+str(exc))
    save_seed_status(force=True)
    if settings.get('chemrxiv_enrichment_limit',0) and folder.resolve()==(ROOT/'data').resolve():
        from .chemrxiv_enrichment import enrich
        from core.api import catalog__Catalog as Catalog
        records,errors=enrich(Catalog(folder/'catalog.sqlite3'),folder,settings['chemrxiv_enrichment_limit'])
        emit(records,channel='chemrxiv',warning='; '.join(x['error'] for x in errors) or None)
    if checkpoint:atomic_json(checkpoint,output)
    return output


if __name__=='__main__':
    from core.api import process_runner__watch_parent as watch_parent
    watch_parent()
    try:print(json.dumps(discover(json.load(sys.stdin)),ensure_ascii=False))
    except Exception:
        import traceback
        traceback.print_exc(file=sys.stderr);sys.exit(1)
