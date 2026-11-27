"""Exact-span evidence views and small, domain-independent assertion schema."""
from collections import Counter,defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
import re
import unicodedata

STOP=set('a an the and or but for of to in on at by as is are was were be been being with from this that these those it its we our their they can could would should may might will have has had do does did not no using used use study work results result show shows shown also such than between into through both each which when where while then there therefore however respectively very only more most further via about during different due based one two three first other all'.split())
WORD=re.compile(r'[A-Za-z][A-Za-z0-9]*(?:[-‐‑–][A-Za-z0-9]+)*')
SPLIT=re.compile(r'(?<=[.!?;])\s+(?=[A-Z(])|\n\s*\n|\s*;\s*|\s+(?:but|however|whereas)\s+',re.I)
PAST=re.compile(r'\b(previous(?:ly)?|prior|earlier|reported by|as reported|et al|in the literature)\b|^\s*\[?\d+\]?[.)]?\s+[A-Z][a-z]+,?\s+[A-Z]\.',re.I)
NEGATIVE=re.compile(r"\b(?:not(?!\s+only)|never|without|cannot|could not|did not|does not|no evidence|failed to)\b",re.I)
HEDGE=re.compile(r'\b(?:might|could|may|would|future|potentially|hypothes|proposed future)\b',re.I)
TARGET=re.compile(r'\b(?:investigat\w*|elucidat\w*|explain\w*|understand\w*|optimi[sz]\w*|regulat\w*|tun(?:e|ed|ing)|focus\w*|aim\w*|probe\w*|demonstrat\w*|reveal\w*|suppress\w*|enhanc\w*)\b',re.I)
ACTION=re.compile(r'\b(?:measur\w*|perform\w*|calculat\w*|record\w*|determin\w*|fabricat\w*|obtain\w*|conduct\w*|us(?:e|ed|ing)|employ\w*|appl\w*|carried out)\b',re.I)
INTERPRET=re.compile(r'\b(?:indicat\w*|confirm\w*|establish\w*|reveal\w*|demonstrat\w*|explain\w*|evidenc\w*|attribut\w*|leads? to|results? in|originat\w*)\b',re.I)
CURRENT=re.compile(r'\b(?:we|our|herein|here we|this work|this study|this paper)\b',re.I)
SECTION={'results':1.1,'discussion':1.1,'results and discussion':1.1,'conclusion':1.2,'methods':.65,'experimental':.65,'unknown':.55,'introduction':.2,'abstract':.3}


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def tokens(text):
    return [word.lower().replace('‐','-').replace('‑','-').replace('–','-') for word in WORD.findall(unicodedata.normalize('NFKC',text))]


def terms(text):
    return [w for w in tokens(text) if len(w)>1 and w not in STOP]


def normalize(text):
    chars=[];mapping=[]
    for i,c in enumerate(text):
        for n in unicodedata.normalize('NFKC',c).lower():
            chars.append('-' if n in '‐‑‒–—−' else ' ' if n.isspace() else n);mapping.append(i)
    return ''.join(chars),mapping


@dataclass
class View:
    chunk:dict
    start:int
    end:int
    text:str
    section:str
    role:str
    weight:float

    def evidence(self, relation='about'):
        return {'chunk_id':self.chunk['id'],'page':self.chunk.get('page'),'scope':'fulltext',
                'section':self.section,'quote':self.text,'start':self.start,'end':self.end,
                'relation':relation,'assertion_role':self.role}


def views(document):
    output=[]
    for chunk in document.get('chunks',[]):
        if chunk.get('scope')!='fulltext':continue
        raw=chunk['text'];start=0
        cuts=[(m.start(),m.end()) for m in SPLIT.finditer(raw)]+[(len(raw),len(raw))]
        for end,next_start in cuts:
            text=raw[start:end];a=start+len(text)-len(text.lstrip());b=end-len(text)+len(text.rstrip());start=next_start
            if b<=a:continue
            text=raw[a:b];section=chunk.get('section','unknown').lower()
            if section in ('references','bibliography','acknowledgments','acknowledgements') or PAST.search(text):role='background'
            elif NEGATIVE.search(text):role='negated'
            elif HEDGE.search(text) and not CURRENT.search(text):role='hypothesis'
            elif TARGET.search(text):role='study_target'
            elif INTERPRET.search(text) and (section in ('results','discussion','results and discussion','conclusion') or CURRENT.search(text)):role='interpreted_result'
            elif ACTION.search(text):role='method_use'
            elif CURRENT.search(text):role='current_statement'
            else:role='mention'
            output.append(View(chunk,a,b,text,section,role,SECTION.get(section,.55)))
    return output


class BM25:
    def __init__(self, texts):
        self.docs=[Counter(terms(t)) for t in texts];self.lengths=[sum(d.values()) for d in self.docs]
        self.avg=sum(self.lengths)/max(1,len(texts));self.df=Counter(t for d in self.docs for t in d)

    def score(self, query,index):
        doc=self.docs[index];length=self.lengths[index];value=0
        for word in set(terms(query)):
            count=doc[word]
            if count:
                idf=math.log(1+(len(self.docs)-self.df[word]+.5)/(self.df[word]+.5))
                value+=idf*(count*2.2)/(count+1.2*(.25+.75*length/max(1,self.avg)))
        return value


def pagerank(nodes,edges,personalization=None,iterations=60):
    nodes=sorted(nodes)
    if not nodes:return {}
    p={n:max(.001,(personalization or {}).get(n,1)) for n in nodes};total=sum(p.values());p={n:v/total for n,v in p.items()};rank=dict(p)
    for _ in range(iterations):
        next_rank={n:.15*p[n] for n in nodes};sink=0
        for n in nodes:
            neighbors=edges.get(n,{});weight=sum(neighbors.values())
            if not weight:sink+=rank[n]
            else:
                for other,w in neighbors.items():next_rank[other]+=.85*rank[n]*w/weight
        for n in nodes:next_rank[n]+=.85*sink*p[n]
        if sum(abs(next_rank[n]-rank[n]) for n in nodes)<1e-9:return next_rank
        rank=next_rank
    return rank


def phrases(evidence_views,limit=20):
    """Model-free token cooccurrence ranking; discoveries never become controlled tags."""
    edges=defaultdict(Counter);nodes=set();candidates={};freq=Counter()
    for view in evidence_views:
        if view.role in ('background','negated','hypothesis'):continue
        words=[(m.group().lower(),m.start(),m.end()) for m in WORD.finditer(view.text)]
        content=[w for w,a,b in words if len(w)>2 and w not in STOP]
        for i,w in enumerate(content):
            nodes.add(w)
            for other in content[i+1:i+5]:
                if other!=w:edges[w][other]+=1;edges[other][w]+=1
        for size in (2,3,4):
            for i in range(len(words)-size+1):
                block=words[i:i+size];names=[w[0] for w in block]
                if any(w in STOP or len(w)<2 for w in names):continue
                key=' '.join(names);freq[key]+=1
                candidates.setdefault(key,(view,block[0][1],block[-1][2]))
    ranks=pagerank(nodes,edges)
    scores=[]
    for phrase,(view,a,b) in candidates.items():
        score=sum(ranks.get(w,0) for w in phrase.split())/math.sqrt(len(phrase.split()))*(1+math.log1p(freq[phrase]))
        scores.append((score,phrase,view,a,b))
    output=[]
    for score,phrase,view,a,b in sorted(scores,key=lambda r:(-r[0],r[1])):
        if any(len(set(phrase.split())&set(p['normalized'].split()))/len(set(phrase.split())|set(p['normalized'].split()))>.7 for p in output):continue
        e=view.evidence();e.update(quote=view.text[a:b],start=view.start+a,end=view.start+b)
        output.append({'phrase':view.text[a:b],'normalized':phrase,'score':round(score,6),'evidence':[e],'status':'unmapped_discovery_not_a_tag'})
        if len(output)>=limit:break
    return output
