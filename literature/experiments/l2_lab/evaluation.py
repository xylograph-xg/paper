"""Evaluation-only gold reader. Never imported by candidate prediction modules."""
from pathlib import Path
import json
import math
import statistics
import time

from .api import BY_ID,classify_level2,validate_output
from .text import digest


def score(documents,predictions,gold,mappings=None):
    mapping=mappings or {};references={p['paper_id']:p for p in gold['papers']}
    if len(references)!=len(documents) or set(references)!={d['paper_id'] for d in documents}:raise ValueError('参考样本覆盖不一致')
    if len(predictions)!=len(documents):raise ValueError('预测样本数不一致')
    tp=fp=fn=0;counts=[];rows=[];oov=0;checks=valid=0;source_checks=source_valid=0
    for doc,prediction in zip(documents,predictions):
        reference=references[doc['paper_id']]
        if prediction['paper_id']!=doc['paper_id'] or prediction['input_fingerprint']!=digest(doc) or reference['input_fingerprint']!=digest(doc):raise ValueError('输入指纹不一致')
        for item in reference['level2']:
            if not item.get('evidence'):raise ValueError('参考证据为空')
            for e in item['evidence']:
                chunk=next((c for c in doc['chunks'] if c['id']==e['chunk_id']),None)
                if not chunk or not e.get('quote') or e['quote'] not in chunk['text'] or e['page']!=chunk['page']:raise ValueError('参考引文不在冻结原文')
        expected={mapping.get(t['id'],t['id']) for t in reference['level2']};actual={t['id'] for t in prediction['level2']}
        eligible=reference.get('eligible_levels',{}).get('level2',True)
        row={'paper_id':doc['paper_id'],'title':doc['title'],'eligible':eligible,'expected':sorted(expected),'predicted':sorted(actual),'correct':sorted(actual&expected),'false_positives':sorted(actual-expected),'missed':sorted(expected-actual)}
        if eligible:
            tp+=len(actual&expected);fp+=len(actual-expected);fn+=len(expected-actual);counts.append(len(actual));oov+=sum(t not in BY_ID for t in expected)
        else:row['exclusion_reason']=reference.get('exclusion_reason','Frozen source eligibility protection')
        chunks={c['id']:c for c in doc['chunks']}
        for label in prediction['level2']+prediction.get('supporting_labels',[])+prediction.get('inherited_labels',[]):
            if label['level']!=2:continue
            for e in label['evidence']:
                checks+=1;source_checks+=1;chunk=chunks.get(e['chunk_id'])
                located=bool(chunk and e.get('scope')=='fulltext' and e.get('page')==chunk.get('page'))
                source_valid+=located
                valid+=bool(located and e.get('quote') and e['quote'] in chunk['text'])
        rows.append(row)
    p=tp/(tp+fp) if tp+fp else 0;r=tp/(tp+fn) if tp+fn else 0
    return {'scope':'same bounded input, assistant reference, not expert consensus or corpus accuracy',
            'metrics':{'tp':tp,'fp':fp,'fn':fn,'precision':p,'recall':r,'f1':2*p*r/(p+r) if p+r else 0,
                       'selected_papers':len(documents),'eligible_papers':len(counts),
                       'core_counts':counts,'mean_core_labels':statistics.mean(counts) if counts else 0,
                       'empty_papers':sum(n==0 for n in counts),'oov_gold':oov,
                       'in_vocabulary_recall':tp/(tp+fn-oov) if tp+fn-oov else 0,
                       'evidence_checks':checks,'evidence_valid':valid,'evidence_fraction':valid/checks if checks else None,
                       'source_checks':source_checks,'source_valid':source_valid,'source_fraction':source_valid/source_checks if source_checks else None},
            'papers':rows}


def predict_documents(documents,strategy):
    if strategy=='baseline':
        # Only the comparison harness imports the original implementation.
        from literature.api import classify
        return [classify(d) for d in documents]
    if strategy=='claim_frames':
        from .claim_api import classify_claims
        return [classify_claims(d) for d in documents]
    return [classify_level2(d,strategy) for d in documents]


def run_arm(documents,gold,strategy,output,mappings=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    start=time.perf_counter();predictions=predict_documents(documents,strategy);elapsed=time.perf_counter()-start
    result=score(documents,predictions,gold,mappings);result['strategy']=strategy;result['elapsed_seconds']=elapsed
    for name,value in [('predictions.json',predictions),('metrics.json',result)]:
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return result
