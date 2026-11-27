"""Bounded arXiv Atom and ChemRxiv/Crossref discovery channels."""
from __future__ import annotations
import html
import re
import time
from datetime import date, datetime, timezone
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

NS={'a':'http://www.w3.org/2005/Atom','x':'http://arxiv.org/schemas/atom'}


def crossref_pdf_urls(work):
    # Some publishers label actual PDF links as "unspecified" in Crossref.
    links=[]
    for link in work.get('link') or []:
        if not link or not link.get('URL'):continue
        url=link['URL'];path=urllib.parse.urlsplit(url).path.lower()
        if link.get('content-type')=='application/pdf' or '/pdf/' in path or path.endswith('.pdf'):
            links.append(url)
    return list(dict.fromkeys(links))


def crossref_record(w):
    title=w.get('title') or []
    title=title if isinstance(title,str) else ' '.join(title)
    abstract=html.unescape(re.sub(r'<[^>]+>',' ',w.get('abstract') or ''))
    parts=(w.get('posted') or w.get('published') or w.get('created') or {}).get('date-parts',[[None]])[0]
    date='-'.join(str(x).zfill(4 if i==0 else 2) for i,x in enumerate(parts) if x is not None)
    pdfs=crossref_pdf_urls(w)
    return {'title':title,'abstract':' '.join(abstract.split()),'doi':w.get('DOI',''),'year':parts[0],
            'publication_date':date,'venue':' '.join(w.get('container-title') or []),'url':w.get('URL') or 'https://doi.org/'+w.get('DOI',''),
            'authors':[' '.join(filter(None,[a.get('given'),a.get('family')])) for a in (w.get('author') or []) if a],
            'pdf_urls':pdfs,'source':['crossref'],'channels':['journal'],'publication_kind':'journal',
            'discovery_reasons':['Crossref 主题书目后备']}





def recent_enough(record, years=20, today=None):
    """Publication-date gate; unknown dates pass rather than being guessed."""
    try: years=int(years)
    except (TypeError,ValueError): years=20
    if years<=0:return True
    today=today or datetime.now(timezone.utc).date()
    try: cutoff=today.replace(year=today.year-years)
    except ValueError: cutoff=today.replace(year=today.year-years,day=28)
    value=record.get('publication_date') or record.get('published') or record.get('year')
    if value in (None,''):return True
    match=re.match(r'^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?',str(value).strip())
    if not match:
        try:return int(str(value)[:4])>=cutoff.year
        except (TypeError,ValueError):return True
    year,month,day=(int(x) if x else None for x in match.groups())
    if month is None:return year>=cutoff.year
    if day is None:return (year,month)>=(cutoff.year,cutoff.month)
    try:return date(year,month,day)>=cutoff
    except ValueError:return True


def relevant(text):
    # Field entry can be OLED/TADF/phosphorescence OR a photophysical mechanism
    # in an organic/molecular context. This keeps exciton-mechanism papers that
    # never mention OLED while rejecting inorganic exciton/quantum keywords.
    text=str(text or '')
    if re.search(r'\bOLEDs?\b',text,re.I) and re.search(r'\b(?:LLM|dLLM|inference|offloading|language model|mixture.of.experts)\b',text,re.I) and not re.search(r'emitt|luminescen|phosphor|exciton|diode|organic|triplet|TADF|rubrene',text,re.I):return False
    low=text.lower()
    oled=bool(re.search(r'\boleds?\b|organic light.emitting|organic led|electroluminescen|light.emitting diode',low))
    mechanism=bool(re.search(r'exciton|excitonic|triplet|singlet|intersystem crossing|\bisc\b|spin.orbit|spin coherence|spin mixing|spin relaxation|spin dynamics|spin polarization|spin chemistry|triplet.triplet|triplet fusion|singlet fission|hot exciton|exciplex|excimer|delayed fluorescence|phosphorescen|up.conversion|dexter|f.rster|charge.transfer|\bct state\b|triplet pair|geminate|polaron pair|polaron|recombination|charge transport|mobility|hopping|thermally activated|aggregation.induced|\baie\b|circularly polarized|\bcpl\b|radical pair|magnetic field effect|magneto.electroluminescen|hyperfine|energy transfer|photoluminescen|electroluminescen|fluorescence|triplet energy|triplet lifetime|triplet diffusion|triplet quenching|triplet sensitiz|singlet exciton|singlet.triplet|exciton binding|exciton diffusion|exciton transport|exciton dynamics|exciton migration|exciton annihilation|exciton dissociation|exciton relaxation|exciton quenching',low))
    organic=bool(re.search(r'organic|molecul|conjugated|polymer|chromophore|\bdye\b|emitter|host.guest|carbazole|iridium|platinum|ligand|donor|acceptor|rubrene|acene|anthracene|tetracene|pentacene|perylene|naphthalene|benzene|phenyl|thiophene|fluorene|triarylamine|phenanthroline|porphyrin|phthalocyanine|fullerene|luminogen|helicene|.aggregate',low))
    inorganic=bool(re.search(r'\bgaas\b|quantum well|quantum dot|perovskite|\bsilicon\b|graphene|carbon nanotube|battery|electrolyte|\bwse2\b|\bmos2\b|monolayer|nanodiamond|silicon vacancy|photonic crystal|topological|superconducting|trapped.ion|quantum simulator|quantum comput|quantum sensing|nv.center|nitrogen.vacancy|qubit|spintronics|scanning.probe|\bcdse\b|\bcdte\b|\bzns\b|\bzno\b|\btio2\b|nanoplatelet|nanocrystal',low))
    bio=bool(re.search(r'bioimag|biomedical|drug delivery|tumor|cancer|clinical|metastasis|transcriptome|\bprotein\b|\benzyme\b|photosystem|chloroplast|lipoxygenase|centriole|\bgfp\b|green fluorescent protein|bacteria|antibody|\bdna\b|wound|pharmaco|photodynamic|photosensitizer',low))
    off=bool(re.search(r'solar cell|photovoltaic|fill factor|photocurrent|photocatalytic|hydrogen evolution|chemosensor|biosensor|mitochond|living cells',low))
    strong=bool(re.search(r'singlet fission|triplet.triplet|triplet fusion|triplet pair|intersystem crossing|spin coherence|spin mixing|radical pair|magnetic field effect|hot exciton|exciton binding|exciton diffusion|exciton transport|exciton dynamics|exciton annihilation|charge.transfer state|\bct state\b|exciplex|thermally activated delayed fluorescence|\btadf\b|room.temperature phosphorescence',low))
    if (inorganic or bio) and not oled:return False
    if off and not oled and not strong:return False
    return bool(oled or (mechanism and organic) or strong)


import hashlib,inspect
RELEVANCE_POLICY=hashlib.sha256(inspect.getsource(relevant).encode()).hexdigest()[:16]


def parse_arxiv(data):
    out=[]
    root=data if isinstance(data,ET.Element) else safe_xml(data)
    for entry in root.findall('a:entry',NS):
        title=' '.join((entry.findtext('a:title','',NS)).split())
        abstract=' '.join((entry.findtext('a:summary','',NS)).split())

        raw_id=entry.findtext('a:id','',NS).rsplit('/abs/',1)[-1]
        base=re.sub(r'v\d+$','',raw_id)
        if not re.fullmatch(r'(?:\d{4}\.\d{4,5}|[a-z-]+/\d{7})',base):continue
        date=entry.findtext('a:published','',NS)
        journal_doi=entry.findtext('x:doi','',NS)
        out.append({'title':title,'abstract':abstract,'arxiv_id':base,'arxiv_version_id':raw_id,
                    'doi':journal_doi or '10.48550/arXiv.'+base,'linked_journal_doi':journal_doi,
                    'authors':[a.findtext('a:name','',NS) for a in entry.findall('a:author',NS)],
                    'year':int(date[:4]) if date else None,'publication_date':date[:10],
                    'preprint_updated':entry.findtext('a:updated','',NS),'venue':entry.findtext('x:journal_ref','',NS) or 'arXiv',
                    'url':'https://arxiv.org/abs/'+raw_id,'pdf_urls':['https://arxiv.org/pdf/'+raw_id],
                    'source':['arxiv'],'channels':['arxiv'],'publication_kind':'preprint',
                    'discovery_reasons':['arXiv 主题通道']})
    return out


def safe_xml(data):
    raw=data.encode() if isinstance(data,str) else data
    if len(raw)>8*1024*1024 or re.search(br'<!\s*(?:DOCTYPE|ENTITY)',raw,re.I):raise ValueError('XML 包含实体声明或超过 8MB')
    return ET.fromstring(raw)


def parse_chemrxiv(items,warnings=None):
    out=[]
    for w in items:
        try:
            identifier=w.get('DOI','')
            if not identifier.lower().startswith('10.26434/chemrxiv'):continue
            title=' '.join(w.get('title') or [])
            abstract=html.unescape(re.sub(r'<[^>]+>',' ',w.get('abstract') or ''))
            abstract=' '.join(abstract.split())
            if not title:raise ValueError('缺少题名')
            parts=(w.get('posted') or w.get('published') or {}).get('date-parts',[[None]])[0]
            date='-'.join(str(x).zfill(4 if i==0 else 2) for i,x in enumerate(parts) if x is not None)
            pdfs=crossref_pdf_urls(w)
            out.append({'title':title,'abstract':abstract,'doi':identifier,'year':parts[0],
                        'publication_date':date,'venue':'ChemRxiv','url':w.get('URL') or 'https://doi.org/'+identifier,
                        'authors':[' '.join(filter(None,[a.get('given'),a.get('family')])) for a in (w.get('author') or []) if a],
                        'pdf_urls':pdfs,'source':['crossref'],'channels':['chemrxiv'],'publication_kind':'preprint',
                        'discovery_reasons':['ChemRxiv 主题通道（Crossref 书目入口）']})
        except (ValueError,TypeError,KeyError,AttributeError,IndexError) as exc:
            if warnings is not None:warnings.append("chemrxiv malformed record: "+str(exc))
            continue
    # Crossref indexes separate versions; keep the latest version in this pool.
    families={}
    for p in out:
        family=re.sub(r'(?:-v|\.v|/v)\d+$','',p['doi'].lower())
        def order(item):
            version=re.search(r'(?:-v|\.v|/v)(\d+)$',item['doi'])
            return (item['publication_date'],int(version[1]) if version else 0)
        if family not in families or order(p)>order(families[family]):
            families[family]=p
    return list(families.values())


def discover(settings,on_page=None):
    from datetime import datetime,timezone,timedelta
    from .network import ProviderClient
    from .discovery_bridge import page_state
    client=ProviderClient(settings.get('state_dir'),settings.get('network',{}).get('request_timeout_seconds',15))
    rows=min(100,max(1,settings.get('network',{}).get('page_size',100)))
    output={'pool':[],'raw':[],'warnings':[],'channels':{},'positions':{}}
    previous=settings.get('positions',{})
    def emit(part,provider):
        output['pool'].extend(part.get('pool',[]));output['raw'].extend(part.get('raw',[]))
        output['warnings'].extend(part.get('warnings',[]));output['positions'].update(part.get('positions',{}))
        count=sum(provider in p.get('channels',[]) for p in output['pool'])
        output['channels'][provider]={'state':('partial' if count else 'failed') if any(w.startswith(provider) for w in output['warnings']) else 'ok','pool_count':count}
        part["channel"]=provider
        if on_page:on_page(part)
    for query in settings.get('arxiv_queries',[]):
        key='v2:arxiv:'+query;state=page_state(previous,key)
        if state is None:continue
        try:
            now=datetime.now(timezone.utc)
            # Scan only the window since the last completed pass. The old
            # snapshot/offset design re-read a large historical result set.
            until=now.strftime('%Y%m%d%H%M')
            since=state.get('since') or state.get('snapshot') or (now-timedelta(days=7)).strftime('%Y%m%d%H%M')
            start=state.get('offset',0)
            params={'search_query':f'({query}) AND submittedDate:[{since} TO {until}]','start':start,
                    'max_results':rows,'sortBy':'submittedDate','sortOrder':'descending'}
            data=client.get('https://export.arxiv.org/api/query',params,'arxiv',xml=True)
            root=safe_xml(data)
            if root.find('a:entry/a:id',NS) is not None and 'api/errors' in root.findtext('a:entry/a:id','',NS):raise ValueError('arXiv API 返回错误条目')
            count=len(root.findall('a:entry',NS));found=parse_arxiv(root);done=count<rows
            progress={'since':until,'snapshot':until,'offset':0,'done':done,'next_scan_at':time.time()+3600 if done else 0} if done else \
                     {'since':since,'snapshot':until,'offset':start+count,'done':False,'next_scan_at':0}
            emit({'pool':found,'positions':{key:progress},'raw':[{'provider':'arxiv','query':query,'response':data.decode()}]},'arxiv')
        except Exception as exc:emit({'warnings':['arxiv: '+str(exc)]},'arxiv')
    for query in settings.get('chemrxiv_queries',[]):
        key='v2:chemrxiv:'+query;state=page_state(previous,key)
        if state is None:continue
        try:
            now=datetime.now(timezone.utc)
            until=now.date().isoformat()
            since=state.get('since') or state.get('snapshot') or (now.date()-timedelta(days=7)).isoformat()
            # Crossref's 2026 cursor contract forbids sorting by published.
            params={'query':query,'cursor':state.get('cursor','*'),'rows':rows,
                    'filter':f'from-created-date:{since},until-created-date:{until}'}
            data=client.get('https://api.crossref.org/prefixes/10.26434/works',params,'crossref')
            message=data.get('message',{});items=message.get('items') or [];cursor=message.get('next-cursor');done=len(items)<rows or not cursor
            progress={'since':until,'snapshot':until,'cursor':'*','done':done,'next_scan_at':time.time()+3600 if done else 0} if done else \
                     {'since':since,'snapshot':until,'cursor':cursor,'done':False,'next_scan_at':0}
            record_warnings=[]
            records=parse_chemrxiv(items,record_warnings)
            emit({'warnings':record_warnings,'pool':records,'positions':{key:progress},'raw':[{'provider':'chemrxiv-crossref','query':query,'response':data}]},'chemrxiv')
        except Exception as exc:emit({'warnings':['chemrxiv-crossref: '+str(exc)]},'chemrxiv')
    return output
