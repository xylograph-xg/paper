"""Read-only, version-bound reuse of original text. No card answers or model calls."""
from pathlib import Path
import hashlib
import json
import re

from core.api import literature_catalog__source_records as source_records
from core.api import paths__WorkspacePath as WorkspacePath
from .classifier import PATTERNS, canonical, metadata_fingerprint

MAX_CONTEXT_BYTES = 24*1024*1024
MAX_EVIDENCE_CHARS = 14000
SECTION = re.compile(r'^\s*(?:(?:\d+(?:\.\d+)*|[IVXLCDM]+)[.)]?\s*)?(abstract|introduction|results?(?:\s+(?:and|&)\s+discussion)?|discussion|conclusions?|experimental(?: section| details| methods)?|materials and methods|methods?|computational (?:methods|details)|references|bibliography|acknowledg(?:e)?ments?|supporting information)\s*$',re.I)


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):h.update(part)
    return h.hexdigest()


def blocks_from_pages(pages):
    """Exact text spans with explicit section state; never relabel unknown as results."""
    output=[];section='unknown'
    for page in pages:
        raw=page['text'];segments=[];start=0
        for match in re.finditer(r'^.*$',raw,re.M):
            heading=SECTION.fullmatch(match.group())
            if heading:
                if match.start()>start:segments.append((start,match.start(),section))
                name=heading.group(1).lower()
                section=('references' if name in ('references','bibliography') else 'methods' if name.startswith(('method','material','experimental','computational')) else 'conclusion' if name.startswith('conclusion') else 'results and discussion' if name.startswith('result') and 'discussion' in name else 'results' if name.startswith('result') else name)
                start=match.end()
        if start<len(raw):segments.append((start,len(raw),section))
        for a,b,role in segments:
            if role in ('references','acknowledgments','acknowledgements'):continue
            # Preserve whitespace and offsets; use sentence/paragraph boundaries when possible.
            part=raw[a:b];cursor=0
            for end in [m.end() for m in re.finditer(r'[.!?]\s+(?=[A-Z])|\n\s*\n',part)]+[len(part)]:
                if end-cursor<220 and end<len(part):continue
                while end-cursor>1500:
                    cut=part.rfind(' ',cursor+500,cursor+1400)
                    if cut<cursor:cut=cursor+1400
                    output.append({'text':part[cursor:cut],'page':page['source_page'],'section':role,'page_start':a+cursor});cursor=cut
                if end>cursor:output.append({'text':part[cursor:end],'page':page['source_page'],'section':role,'page_start':a+cursor});cursor=end
    return [dict(b,id=f"p{b['page']}-o{b['page_start']}",scope='fulltext',role='body') for b in output if b['text'].strip()]


def select_blocks(blocks, budget=MAX_EVIDENCE_CHARS):
    """Fixed, versioned evidence budget. Same selected text is shown to the evaluator."""
    candidates=[]
    for i,b in enumerate(blocks):
        norm,_=canonical(b['text'])
        hits=sum(bool(pattern.search(norm)) for pattern in PATTERNS.values())
        if not hits:continue
        score=hits+(3 if b['section'] in ('results','discussion','results and discussion','methods','conclusion') else 0)
        candidates.append((-score,i))
    chosen=[];size=0
    for _,i in sorted(candidates):
        b=blocks[i]
        if size+len(b['text'])>budget:continue
        chosen.append(i);size+=len(b['text'])
    return [blocks[i] for i in sorted(chosen)]


def prepare_document(record, *, fallback_pdf=False, budget=MAX_EVIDENCE_CHARS):
    """Title/abstract plus bounded ORIGINAL fulltext evidence, not scientific answers."""
    document={'schema':'directions-input-v1','paper_id':record['id'],'title':record['title'],
              'abstract':record['metadata'].get('abstract') or '',
              'metadata_fingerprint':metadata_fingerprint(record),'source_fingerprint':record.get('asset_hash'),
              'chunks':[],'source_provenance':None,'limitations':[]}
    if not document['abstract']:document['limitations'].append('missing_abstract')
    m=record['metadata']
    if any(m.get(k) for k in ('identity_review_required','version_review_required','out_of_scope')):
        document['limitations'].append('source_identity_version_or_scope_protected');return document
    source=WorkspacePath(record['asset_path']) if record.get('asset_path') else None
    if record.get('acquisition')!='available' or not source or not source.is_file() or not record.get('asset_hash'):
        document['limitations'].append('missing_registered_original');return document
    if digest(source)!=record['asset_hash']:
        document['limitations'].append('current_original_hash_mismatch');return document
    pages=None;issues=[]
    for item in sorted(record.get('materials',[]),key=lambda x:(x['lane']!='web_card_jobs',x['folder'])):
        folder=WorkspacePath(item['folder']);context=folder/'source-context.json';packet=folder/'packet.json'
        if not context.is_file() or not packet.is_file():continue
        try:
            if context.stat().st_size>MAX_CONTEXT_BYTES:raise ValueError('context_too_large')
            p=json.loads(packet.read_text())
            bound=p.get('paper_id')==record['id'] if item['lane']=='web_card_jobs' else p.get('job_id')==item['original_job_id']
            if not bound or p.get('source_original_sha256')!=record['asset_hash'] or item['source_sha256']!=record['asset_hash']:
                raise ValueError('stale_or_unbound_material')
            raw=context.read_bytes();context_hash=hashlib.sha256(raw).hexdigest()
            if context_hash!=p.get('input_hashes',{}).get('source-context.json'):raise ValueError('frozen_context_hash_mismatch')
            original=json.loads(raw).get('source_text')
            if not isinstance(original,list) or not original:raise ValueError('missing_original_text_layer')
            if any(not isinstance(x,dict) or type(x.get('source_page')) is not int or x['source_page']<1 or not isinstance(x.get('text'),str) for x in original):
                raise ValueError('invalid_original_page_map')
            if len({x['source_page'] for x in original})!=len(original):raise ValueError('duplicate_original_pages')
            pages=[{'source_page':x['source_page'],'text':x['text']} for x in original]
            document['source_provenance']={'kind':'frozen_source_context','path':str(context),'sha256':context_hash,'original_path':str(source)}
            break
        except (ValueError,OSError,KeyError,TypeError) as exc:issues.append(str(exc))
    if pages is None and fallback_pdf:
        # Public parser only; parse_pdf does not start models or render visual packets.
        from read.api import parser__parse_pdf as parse_pdf
        parsed=parse_pdf(source)
        pages=[{'source_page':i+1,'text':t} for i,t in enumerate(parsed.page_texts)]
        document['source_provenance']={'kind':'local_pdf_text','path':str(source),'sha256':record['asset_hash']}
    if pages is None:
        document['limitations'].append('no_verified_text_intermediate')
        document['material_errors']=sorted(set(issues));return document
    # Source identity is independent of hash integrity. A registered SI-only PDF
    # cannot supply main-article evidence merely because its frozen hash matches.
    cover=pages[0]['text'][:1200]
    supporting=re.search(r'\b(?:supporting|supplementary)\s+(?:information|material)\b',cover,re.I)
    si_numbering=bool(re.match(r'^\s*S\s*1\b',cover,re.I))
    si_heading=bool(re.match(r'^\s*(?:supporting|supplementary)\s+(?:information|material)',cover,re.I))
    if supporting and (si_numbering or si_heading):
        document['source_provenance']['source_kind']='supplementary_only'
        document['limitations'].append('supplementary_input_not_main_article')
        document['input_policy_version']='source-identity-v2'
        return document
    document['source_provenance']['source_kind']='registered_main_article'
    document['input_policy_version']='source-identity-v2'
    blocks=blocks_from_pages(pages);selected=select_blocks(blocks,budget)
    document['chunks']=selected
    document['coverage']={'original_pages':len(pages),'selected_pages':sorted({b['page'] for b in selected}),
                          'available_body_chars':sum(len(b['text']) for b in blocks),'selected_chars':sum(len(b['text']) for b in selected),
                          'budget_chars':budget,'selection_version':'evidence-window-v1',
                          'body_truncated':len(selected)<len(blocks)}
    if document['coverage']['body_truncated']:document['limitations'].append('bounded_text_evidence_not_full_paper')
    if not selected:document['limitations'].append('no_matching_body_evidence')
    return document


def load_documents(catalog_path,paper_ids,**options):
    rows=source_records(catalog_path,paper_ids)
    by_id={r['id']:r for r in rows}
    if any(pid not in by_id for pid in paper_ids):raise ValueError('文献不存在')
    return [prepare_document(by_id[pid],**options) for pid in paper_ids]
