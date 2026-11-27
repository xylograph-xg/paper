"""Third architecture: extract typed claim fields before concept normalization.

The previous two candidate classifiers are unchanged. Event payload boundaries
prevent tools/conditions from automatically becoming the target of investigation.
"""
import re
from .api import CONCEPTS,BY_ID,_hits,_label,validate_output
from .text import digest,views,phrases

VERSION='l2-claim-frames-0.1.0'
GOAL=re.compile(r'\b(?:investigat\w*|elucidat\w*|understand\w*|explain\w*|optimi[sz]\w*|regulat\w*|tun(?:e|ed|ing)|focus(?:es|ed|ing)? on|aim(?:s|ed)? (?:at|to)|demonstrat\w*|reveal\w*|suppress\w*|enhanc\w*|develop\w*)\b',re.I)
RESULT=re.compile(r'\b(?:indicat\w*|confirm\w*|establish\w*|reveal\w*|demonstrat\w*|attribut\w*|origina\w*|leads? to|results? in|is found|was found)\b',re.I)
USE=re.compile(r'\b(?:measur\w*|perform\w*|calculat\w*|record\w*|determin\w*|fabricat\w*|conduct\w*|us(?:e|ed|ing)|employ\w*|appl\w*|carried out)\b',re.I)
BOUNDARY=re.compile(r'\b(?:using|via|through|by|with|to|because|although|compared with)\b',re.I)
BLOCKED={'background','negated','hypothesis'}


def _payload(text,start):
    rest=text[start:];cut=BOUNDARY.search(rest)
    return start,start+cut.start() if cut else len(text)


def classify_claims(document):
    evidence_views=views(document);metadata={cid for cid,a,b in _hits(document.get('title','')+' '+(document.get('abstract') or ''))}
    fields=[];hits={};reasons={};blocked=[]
    for index,view in enumerate(evidence_views):
        matches=_hits(view.text)
        if view.role in BLOCKED:
            blocked.extend({'id':cid,'level':2,'reason':view.role,'evidence':[view.evidence('mentioned')]} for cid,a,b in matches);continue
        targets=[_payload(view.text,m.end()) for m in GOAL.finditer(view.text)]
        outcomes=[_payload(view.text,m.end()) for m in RESULT.finditer(view.text)]
        actions=[_payload(view.text,m.end()) for m in USE.finditer(view.text)]
        for cid,a,b in matches:
            hits.setdefault(cid,[]).append((index,view,a,b))
            roles=set()
            if any(x<=a and b<=y for x,y in targets):roles.add('research_target')
            if any(x<=a and b<=y for x,y in outcomes):roles.add('result_explanation')
            if any(x<=a and b<=y for x,y in actions):roles.add('actual_method')
            if not roles:roles.add('context_entity')
            reasons.setdefault(cid,set()).update(roles)
            fields.append({'concept_id':cid,'roles':sorted(roles),'entity_text':view.text[a:b],
                'entity_start':view.start+a,'entity_end':view.start+b,'evidence':view.evidence('used' if 'actual_method' in roles else 'about')})
    core=[];support=[]
    for cid,records in hits.items():
        dim=BY_ID[cid]['dimension'];roles=reasons[cid]
        direct=bool(roles&{'research_target','result_explanation'})
        if dim=='method':is_core=direct or ('actual_method' in roles and cid in metadata)
        else:is_core=direct or (cid in metadata and any(view.role=='current_statement' for i,view,a,b in records))
        label=_label(cid,records,2.0 if is_core else 1.0,is_core,'typed_claim_fields_then_concept_normalization')
        label['claim_roles']=sorted(roles)
        (core if is_core else support).append(label)
    output={'paper_id':document['paper_id'],'input_fingerprint':digest(document),'rule_version':VERSION,
        'taxonomy_version':CONCEPTS['version'],'strategy':'claim_frames','level1':[],
        'level2':sorted(core,key=lambda r:r['id']),'supporting_labels':sorted(support,key=lambda r:r['id']),
        'inherited_labels':[],'mentions':blocked,'claim_fields':fields,'unmapped_phrases':phrases(evidence_views),
        'level2_state':'missing_input' if not document.get('chunks') else 'completed' if core else 'unable_to_determine',
        'scientific_verified':False,'production_publish':False,'models_used':False,
        'limitations':list(document.get('limitations',[]))+['bounded_source','lightweight_field_grammar_not_full_semantic_parse','experimental_not_production']}
    validate_output(document,output)
    return output
