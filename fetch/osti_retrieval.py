"""Bounded OSTI public manuscript route, preserving DOI and version evidence."""
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from core.api import paths__WorkspacePath as Path
from urllib.parse import urlencode, urlsplit


class BindingConflict(ValueError):
    """The original or human decision changed; do not try another stale route."""


def lookup(identifier, folder):
    from core.api import catalog__doi as doi
    from .network import ready,pace,failed,DeferredRequest,succeeded
    from core.api import services__CheckedRedirect as CheckedRedirect, services__public_url as public_url, services__atomic_json as atomic_json
    from .public_http import opener
    from .acquisition_budget import remaining
    identifier=doi(identifier)
    if not identifier:return []
    cache=Path(folder)/'osti-cache'/(hashlib.sha256(identifier.encode()).hexdigest()+'.json')
    if cache.exists() and cache.stat().st_size<=2*1024*1024:
        try:
            saved=json.loads(cache.read_text())
            if saved['doi']==identifier and 0<=time.time()-saved['updated']<86400 and isinstance(saved['records'],list) and all(isinstance(row,dict) for row in saved['records']):
                return saved['records']
        except (ValueError,KeyError,TypeError):pass
    provider='pdf:www.osti.gov';ready(provider);pace(provider,1);ready(provider)
    url='https://www.osti.gov/api/v1/records?'+urlencode({'doi':identifier})
    public_url(url);started=time.time()
    request=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'PaperLibrary/0.3 (personal literature research)'})
    try:
        with opener(CheckedRedirect()).open(request,timeout=min(10,remaining(12))) as response:
            raw=response.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise ValueError('OSTI metadata exceeds 2MB')
        rows=json.loads(raw)
        if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):
            raise ValueError('OSTI metadata must be a record list')
    except urllib.error.HTTPError as exc:
        if exc.code in (401,403,429,500,502,503,504):
            raise DeferredRequest(provider,failed(provider,exc.code,exc.headers),exc.code,request_started=True,reason='http') from None
        raise
    succeeded(provider,started=started)
    cache.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(cache,{'doi':identifier,'updated':time.time(),'records':rows})
    return rows


def fetch(paper, folder, target):
    from core.api import catalog__doi as doi
    from core.api import services__download as download, services__verify_identity as verify_identity
    metadata=paper['metadata'];identifier=doi(metadata.get('doi'))
    if (not identifier or metadata.get('publication_kind')=='preprint' or paper.get('card_path')
            or paper.get('decision')!='unreviewed' or any(metadata.get(k) for k in
            ('identity_review_required','version_review_required','out_of_scope','is_correction'))):
        return None
    for row in lookup(identifier,folder):
        if doi(row.get('doi'))!=identifier or row.get('product_type')!='Journal Article':continue
        links=row.get('links') or []
        if not isinstance(links,list):continue
        urls=[link.get('href') for link in links if isinstance(link,dict) and link.get('rel')=='fulltext']
        for url in urls[:1]:
            if not isinstance(url,str):continue
            parsed=urlsplit(url)
            if parsed.scheme!='https' or parsed.hostname!='www.osti.gov' or not re.fullmatch(r'/servlets/purl/\d+',parsed.path):
                continue
            final=download(url,target)
            body=verify_identity(target,metadata)
            if identifier not in body.lower():raise ValueError('OSTI PDF缺少目标DOI，不自动绑定其他版本')
            if re.search(r'^(?:supporting information|supplementary (?:information|materials?))\b',body.lstrip(),re.I):
                raise ValueError('OSTI返回补充材料，不作为原文')
            return {'path':str(target),'verified_sha256':hashlib.sha256(Path(target).read_bytes()).hexdigest(),'url':url,'final_url':final,'osti_id':row.get('osti_id'),
                    'article_type':row.get('article_type') or 'Unknown',
                    'version_review_required':row.get('article_type')!='Published Article'}
    return None


def bind(catalog,config,paper,result):
    """CAS the still-unbound source; accepted/unknown versions cannot enter cards."""
    from core.api import services__store_asset as store_asset
    from core.api import catalog__doi as doi
    path,digest=store_asset(result['path'],config)
    if digest!=result['verified_sha256']:raise ValueError('已验证的OSTI原文在归档前变化')
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current=db.execute('SELECT * FROM papers WHERE id=?',(paper['id'],)).fetchone()
        metadata=json.loads(current['metadata'])
        if (current['asset_path'] or current['card_path'] or current['decision']!='unreviewed'
                or metadata.get('publication_kind')=='preprint'
                or current['title']!=paper['title'] or doi(metadata.get('doi'))!=doi(paper['metadata'].get('doi'))
                or any(metadata.get(k) for k in ('identity_review_required','version_review_required','out_of_scope','is_correction'))
                or db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='human_decision'",(paper['id'],)).fetchone()):
            raise BindingConflict('文献/人工决定/版本保护已变化，不覆盖当前原文')
        metadata.update(asset_version=result['article_type'],asset_version_source='osti',osti_id=result['osti_id'])
        if result['version_review_required']:metadata['version_review_required']=True
        db.execute("UPDATE papers SET asset_path=?,asset_hash=?,acquisition='available',metadata=? WHERE id=?",
                   (path,digest,json.dumps(metadata,ensure_ascii=False),paper['id']))
    catalog.event(paper['id'],'download',{'provider':'osti','url':result['url'],'final_url':result['final_url'],
        'sha256':digest,'osti_id':result['osti_id'],'asset_version':result['article_type'],
        'version_review_required':result['version_review_required']})
    return path,digest
