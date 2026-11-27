"""Two independently implemented, model-free L2 candidates; pure functions only.

No imports from production classifier/focus/input preparation. Concepts are frozen data.
"""
from collections import Counter,defaultdict
from pathlib import Path
import json
import math
import re

from .text import BM25,digest,normalize,pagerank,phrases,terms,views

VERSION='l2-architecture-lab-0.1.0'
CONCEPTS=json.loads(Path(__file__).with_name('concepts.json').read_text())
BY_ID={c['id']:c for c in CONCEPTS['concepts']}
PATTERNS={c['id']:re.compile(r'(?<![a-z0-9])(?:'+'|'.join(c['patterns'])+r')(?![a-z0-9])',re.I) for c in CONCEPTS['concepts']}
CONFIG={'retrieval':{'core_threshold':3.6,'method_threshold':4.0},
        'assertion_graph':{'core_threshold':3.5,'method_threshold':4.0}}
BLOCKED={'background','negated','hypothesis'}
ROLE={'study_target':2.5,'interpreted_result':2.1,'method_use':1.2,'current_statement':1.0,'mention':.15}


def _hits(text):
    normalized,mapping=normalize(text);found=[]
    for concept in CONCEPTS['concepts']:
        for match in PATTERNS[concept['id']].finditer(normalized):
            found.append((concept['id'],mapping[match.start()],mapping[match.end()-1]+1))
    # Generic longest-span disambiguation, same dimension only: RISC vs ISC,
    # TD-DFT vs DFT, without paper-specific or scientific-rule branches.
    return [(cid,a,b) for cid,a,b in found if not any(
        other!=cid and BY_ID[cid]['dimension']==BY_ID[other]['dimension'] and x<=a and y>=b and y-x>b-a
        for other,x,y in found)]


def _admission(doc):
    evidence_views=views(doc);hits=defaultdict(list);mentions=[]
    for index,view in enumerate(evidence_views):
        for cid,a,b in _hits(view.text):
            if view.role in BLOCKED:
                mentions.append({'id':cid,'level':2,'reason':view.role,'evidence':[view.evidence('mentioned')]})
            else:hits[cid].append((index,view,a,b))
    meta={cid for cid,a,b in _hits(doc.get('title','')+' '+(doc.get('abstract') or ''))}
    return evidence_views,hits,mentions,meta


def _label(cid,records,score,core,strategy):
    concept=BY_ID[cid];selected=[];seen=set()
    for index,view,a,b in sorted(records,key=lambda item:(-ROLE[item[1].role],-item[1].weight,item[0],item[2])):
        key=(view.chunk['id'],view.start,view.end)
        if key in seen:continue
        seen.add(key);e=view.evidence('used' if concept['dimension']=='method' else 'about')
        e.update(matched_text=view.text[a:b],match_start=view.start+a,match_end=view.start+b)
        selected.append(e)
        if len(selected)==3:break
    return {'id':cid,'name':concept['name'],'dimension':concept['dimension'],'level':2,
            'importance':'core' if core else 'supporting','score':round(score,5),
            'selection_basis':strategy,'evidence':selected,'status':'experimental_not_production'}


def _retrieval(evidence_views,hits,metadata,config):
    bm=BM25([v.text for v in evidence_views]);core=[];support=[]
    for cid,records in hits.items():
        count=len({(v.chunk['id'],v.start) for i,v,a,b in records});concept=BY_ID[cid]
        scores=[ROLE[v.role]+v.weight+(1.2 if cid in metadata else 0)+.55*math.log1p(count)
                +.6*(bm.score(concept['definition'],i)/(1+bm.score(concept['definition'],i))) for i,v,a,b in records]
        score=max(scores)
        used=any(v.role in ('study_target','interpreted_result','method_use') for i,v,a,b in records)
        threshold=config['method_threshold'] if concept['dimension']=='method' else config['core_threshold']
        is_core=score>=threshold and (used if concept['dimension']=='method' else True)
        label=_label(cid,records,score,is_core,'bm25_evidence_retrieval')
        (core if is_core else support).append(label)
    return core,support


def _graph(evidence_views,hits,metadata,config):
    edges=defaultdict(Counter);per_view=defaultdict(set);prior={}
    for cid,records in hits.items():
        prior[cid]=.1+max(ROLE[v.role]+v.weight for i,v,a,b in records)+(1 if cid in metadata else 0)
        for i,v,a,b in records:per_view[i].add(cid)
    for index,nodes in per_view.items():
        # The graph links assertions in the same or immediately adjacent original
        # evidence view. It cannot bridge separate source chunks or references.
        group=set(nodes)
        if index+1<len(evidence_views) and evidence_views[index].chunk['id']==evidence_views[index+1].chunk['id']:
            group|=per_view.get(index+1,set())
        for first in group:
            for second in group:
                if first!=second:edges[first][second]+=1
    rank=pagerank(hits,edges,prior);core=[];support=[]
    for cid,records in hits.items():
        concept=BY_ID[cid];roles={v.role for i,v,a,b in records}
        count=len({(v.chunk['id'],v.start) for i,v,a,b in records})
        centrality=min(2.0,rank[cid]*len(hits))
        score=max(ROLE[v.role]+.5*v.weight for i,v,a,b in records)+centrality+(.7 if cid in metadata else 0)+.3*math.log1p(count)
        if concept['dimension']=='method':
            # Schema: a use event plus a relevance signal, never a bare keyword.
            admitted=bool(roles&{'study_target','interpreted_result','method_use'}) and (bool(roles&{'study_target','interpreted_result'}) or cid in metadata or count>=2)
            threshold=config['method_threshold']
        else:
            admitted=bool(roles&{'study_target','interpreted_result','current_statement'}) or cid in metadata or count>=2
            threshold=config['core_threshold']
        is_core=admitted and score>=threshold
        label=_label(cid,records,score,is_core,'personalized_concept_assertion_graph')
        (core if is_core else support).append(label)
    return core,support


def classify_level2(document, strategy='retrieval', config=None):
    """Same bounded frozen input as baseline; title/abstract prioritize but never prove L2."""
    if strategy not in CONFIG:raise ValueError('未知独立二级策略')
    settings=dict(CONFIG[strategy] if config is None else config)
    if set(settings)!={'core_threshold','method_threshold'} or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<v<20 for v in settings.values()):
        raise ValueError('实验阈值不合法')
    evidence_views,hits,mentions,metadata=_admission(document)
    core,support=(_retrieval if strategy=='retrieval' else _graph)(evidence_views,hits,metadata,settings)
    candidates=phrases(evidence_views)
    output={'paper_id':document['paper_id'],'input_fingerprint':digest(document),'rule_version':VERSION+':'+strategy,
            'taxonomy_version':CONCEPTS['version'],'strategy':strategy,'configuration':settings,
            'level1':[],'level2':sorted(core,key=lambda r:(-r['score'],r['id'])),
            'supporting_labels':sorted(support,key=lambda r:(-r['score'],r['id'])),
            'inherited_labels':[],'mentions':mentions,'unmapped_phrases':candidates,
            'level2_state':'missing_input' if not document.get('chunks') else 'completed' if core else 'unable_to_determine',
            'scientific_verified':False,'production_publish':False,'models_used':False,
            'limitations':list(document.get('limitations',[]))+['same_bounded_input_not_full_paper','experimental_not_production']}
    validate_output(document,output)
    return output


def validate_output(document,output):
    if output['paper_id']!=document['paper_id'] or output['input_fingerprint']!=digest(document):raise ValueError('输入归属不一致')
    chunks={c['id']:c for c in document.get('chunks',[])};count=0
    for label in output['level2']+output['supporting_labels']+output['mentions']+output['unmapped_phrases']:
        for evidence in label['evidence']:
            chunk=chunks.get(evidence['chunk_id'])
            if not chunk or chunk.get('scope')!='fulltext' or evidence['scope']!='fulltext' or chunk.get('page')!=evidence['page']:raise ValueError('原文来源不一致')
            if not evidence['quote'] or chunk['text'][evidence['start']:evidence['end']]!=evidence['quote']:raise ValueError('精确证据位置不一致')
            if 'match_start' in evidence and chunk['text'][evidence['match_start']:evidence['match_end']]!=evidence['matched_text']:raise ValueError('术语位置不一致')
            count+=1
    return {'checked':count,'valid':count,'fraction':1.0 if count else None}
