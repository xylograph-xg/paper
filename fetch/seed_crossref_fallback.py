"""Bounded DOI-exact Crossref references when the primary seed source fails.

Independent cursor, durable cache and original DOI lineage; never invents citations.
"""
import hashlib,json,time
from core.api import paths__WorkspacePath as Path
from core.api import catalog__doi as doi
from .preprints import crossref_record
from core.api import services__atomic_json as atomic_json


def discover_seed(client,folder,seed,previous,rows=3):
    identifier=doi(seed.get('doi'));key='v3:crossref-references:'+identifier
    state=previous.get(key) or {}
    if state.get('next_scan_at',0)>time.time():return [],[],{},'waiting'
    cache=Path(folder)/'seed-crossref-cache'/(hashlib.sha256(identifier.encode()).hexdigest()+'.json')
    try:cached=json.loads(cache.read_text())
    except (OSError,ValueError):cached={}
    if cached.get('expires',0)>time.time():work=cached['work']
    else:
        work=client.get('https://api.crossref.org/works/'+identifier,provider='crossref')['message']
        if doi(work.get('DOI'))!=identifier:raise ValueError('Crossref 种子 DOI 不一致')
        atomic_json(cache,{'expires':time.time()+86400,'work':work})
    references=list(dict.fromkeys(doi(x.get('DOI')) for x in work.get('reference',[]) if isinstance(x,dict) and doi(x.get('DOI'))))
    start=0 if state.get('done') else state.get('offset',0);records=[]
    # Do not advance an unsuccessful reference. Successful partial pages survive.
    position={'offset':start,'done':False,'next_scan_at':0};errors=[]
    for ref in references[start:start+rows]:
        try:
            item=client.get('https://api.crossref.org/works/'+ref,provider='crossref')['message']
            if doi(item.get('DOI'))!=ref:raise ValueError('Crossref 参考文献 DOI 不一致')
            record=crossref_record(item)
            record['discovery_reasons']=['参考文献：'+seed.get('title',identifier)+'（Crossref）']
            record['discovered_from_seed_dois']=[identifier]
            records.append(record);position['offset']+=1
        except Exception as exc:
            errors.append(str(exc));position['next_scan_at']=getattr(exc,'retry_at',time.time()+900);break
    position['done']=position['offset']>=len(references)
    if position['done']:position['next_scan_at']=time.time()+86400
    return records,[crossref_record(work)],{key:position},errors
