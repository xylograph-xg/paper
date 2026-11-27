"""Paperscraper's Open Engage source under existing acquisition protections.

Returns new verified metadata links, never marks a PDF downloaded or resets retries.
"""
import hashlib,json,time
from core.api import paths__WorkspacePath as Path
from core.api import catalog__doi as doi
from .network import ProviderClient
from core.api import services__atomic_json as atomic_json
from .vendor.paperscraper_chemrxiv import pdf_url

API='https://www.cambridge.org/engage/coe/public-api/v1/items/doi/'

def resolve(client,folder,metadata):
    identifier=doi(metadata.get('doi'))
    if not identifier.startswith('10.26434/chemrxiv-'):return None
    cache=Path(folder)/'chemrxiv-source-cache'/(hashlib.sha256(identifier.encode()).hexdigest()+'.json')
    try:cached=json.loads(cache.read_text())
    except (OSError,ValueError):cached={}
    if cached.get('expires',0)>time.time():item=cached.get('item')
    else:
        item=client.get(API+identifier,provider='pdf:www.cambridge.org')
        item=item.get('item',item)
        if doi(item.get('doi'))!=identifier:raise ValueError('Open Engage DOI 与目标不一致')
        atomic_json(cache,{'expires':time.time()+86400,'item':item})
    if not item:return None
    url=pdf_url(item)
    from urllib.parse import urlsplit
    from core.api import catalog__title_key as title_key
    import difflib
    if not isinstance(url,str) or (urlsplit(url).hostname!='www.cambridge.org' or urlsplit(url).scheme!='https'):raise ValueError('Open Engage 原文地址异常')
    if difflib.SequenceMatcher(None,title_key(item.get('title','')),title_key(metadata['title'])).ratio()<.92:raise ValueError('Open Engage 题名与目标不一致')
    return {**metadata,'pdf_urls':list(dict.fromkeys([*(metadata.get('pdf_urls') or []),url])),
            'discovery_reasons':['ChemRxiv Open Engage 原文入口（Paperscraper）']}

def enrich(catalog,folder,limit=5):
    folder=Path(folder);state_path=folder/'chemrxiv-enrichment-status.json'
    try:prior=json.loads(state_path.read_text())
    except (OSError,ValueError):prior={}
    with catalog.connect() as db:
        rows=[dict(x) for x in db.execute("SELECT id,metadata FROM papers WHERE acquisition!='available' AND seed=0 AND decision NOT IN ('reject','ignore') AND json_extract(metadata,'$.doi') LIKE '10.26434/chemrxiv-%' ORDER BY id")]
    rows=[x for x in rows if not any(json.loads(x['metadata']).get(k) for k in ('out_of_scope','identity_review_required','version_review_required','human_decision','manual_decision'))]
    selected=[x for x in rows if x['id']>prior.get('last_id','')][:limit]
    if not selected:selected=rows[:limit]
    client=ProviderClient(folder);records=[];errors=[];new_links=0
    for row in selected:
        try:
            record=resolve(client,folder,json.loads(row['metadata']))
            if record:
                new_links+=bool(set(record['pdf_urls'])-set(json.loads(row['metadata']).get('pdf_urls') or []))
                records.append(record)
        except Exception as exc:errors.append({'paper_id':row['id'],'error':str(exc)})
    atomic_json(state_path,{'updated':time.time(),'last_id':selected[-1]['id'] if selected else '',
                          'checked':len(selected),'new_links':new_links,
                          'errors':errors})
    return records,errors
