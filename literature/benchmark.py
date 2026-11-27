"""Reproducible ten-paper, same-input evaluation. Gold labels are evaluation-only."""
from importlib.resources import files
from pathlib import Path
import hashlib
import json
import re

from core.api import literature_catalog__metadata_rows as metadata_rows
from core.api import literature_catalog__source_records as source_records
from .classifier import classify, RULE_VERSION, TAXONOMY, BY_ID
from .inputs import prepare_document
from .store import fingerprint

STRATA = [
    ('mr_tadf',r'MR[- ]TADF|multi(?:ple)?[- ]resonan'),
    ('exciplex',r'exciplex'),
    ('hyperfluorescence',r'hyperfluorescen|sensitized fluorescen'),
    ('phosphorescence',r'phosphorescen'),
    ('aggregation',r'aggregation[- ]induced'),
    ('host_materials',r'host materials?|bipolar hosts?'),
    ('stability',r'operational (?:stability|lifetime)|device lifetime'),
    ('theory',r'density functional|TD[- ]DFT|computational|theoretical'),
    ('tadf',r'TADF|thermally activated delayed fluorescen'),
    ('other_emission',r'fluorescen|luminescen|emission'),
]


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def freeze_pilot(catalog_path, output_dir, *, seed='directions-pilot-20261020', budget=7000,
                 exclude_paper_ids=(), generate_predictions=True):
    """Freeze code BEFORE metadata-stratified selection; never inspect predictions to select."""
    if type(generate_predictions) is not bool:raise ValueError('预测设置须为布尔值')
    excluded=set(exclude_paper_ids)
    out=Path(output_dir)
    out.mkdir(parents=True,exist_ok=False)
    code_files=['classifier.py','focus.py','inputs.py','taxonomy.json','benchmark.py']
    code_hashes={name:hashlib.sha256(files('literature').joinpath(name).read_bytes()).hexdigest() for name in code_files}
    dump(out/'protocol.json',{'schema':'same-input-pilot-v1','seed':seed,'budget_chars':budget,'rule_version':RULE_VERSION,
        'taxonomy_version':TAXONOMY['version'],'source_sha256':code_hashes,
        'excluded_paper_ids':sorted(excluded),'predictions_deferred':not generate_predictions,
        'selection':'One paper per metadata stratum, deterministic SHA256 ordering; valid original and frozen source context required; no prediction-based selection',
        'gold_policy':'Assistant independently reads exactly the frozen title, abstract and selected original text; gold never enters production rules or labels',
        'generalization':'Ten metadata-stratified cases are a diagnostic pilot, not an unbiased corpus accuracy estimate'})
    rows=[r for r in metadata_rows(catalog_path) if r['id'] not in excluded and r['has_pdf'] and r['metadata'].get('abstract')]
    documents=[];samples=[];used=set();skipped=[]
    for stratum,pattern in STRATA:
        candidates=[r for r in rows if r['id'] not in used and re.search(pattern,r['title']+' '+r['metadata'].get('abstract',''),re.I)]
        candidates.sort(key=lambda r:hashlib.sha256((seed+r['id']).encode()).hexdigest())
        chosen=None
        for start in range(0,min(len(candidates),300),50):
            records={r['id']:r for r in source_records(catalog_path,[r['id'] for r in candidates[start:start+50]])}
            for candidate in candidates[start:start+50]:
                r=records[candidate['id']]
                # Cheap metadata gate before original hash I/O.
                if not r['materials']:continue
                doc=prepare_document(r,budget=budget,fallback_pdf=False)
                if not doc['chunks']:
                    skipped.append({'paper_id':r['id'],'stratum':stratum,'reason':doc['limitations']});continue
                chosen=doc
                samples.append({'index':len(samples)+1,'stratum':stratum,'paper_id':r['id'],'title':r['title'],
                                'doi':r['metadata'].get('doi'),'year':r['metadata'].get('year'),'input_fingerprint':fingerprint(doc)})
                used.add(r['id']);documents.append(doc);break
            if chosen:break
        if not chosen:raise ValueError('无法为分层取得真实有效材料：'+stratum)
    dump(out/'inputs.json',documents);dump(out/'samples.json',samples)
    if generate_predictions:dump(out/'predictions.json',[classify(doc) for doc in documents])
    dump(out/'selection-skips.json',skipped)
    for sample,doc in zip(samples,documents):
        parts=[f"PAPER {sample['index']} | {doc['paper_id']}",f"TITLE: {doc['title']}",f"ABSTRACT: {doc['abstract']}",
               'EXACT LEVEL-2 INPUT (bounded original-text evidence; no hidden fulltext supplied to classifier):']
        for chunk in doc['chunks']:parts.append(f"[{chunk['id']} | PDF p.{chunk['page']} | {chunk['section']}]\n{chunk['text']}")
        parts.append('COVERAGE: '+json.dumps(doc['coverage'],ensure_ascii=False))
        (out/f"read-{sample['index']:02}.txt").write_text('\n\n'.join(parts)+'\n')
    names=['protocol.json','inputs.json','samples.json']+(['predictions.json'] if generate_predictions else [])
    dump(out/'frozen-output-hashes.json',{name:hashlib.sha256((out/name).read_bytes()).hexdigest() for name in names})
    return samples


def compare(output_dir):
    """Gold contains explicit positive label IDs and exact input evidence, per level."""
    out=Path(output_dir);docs=json.loads((out/'inputs.json').read_text());pred=json.loads((out/'predictions.json').read_text());gold=json.loads((out/'gold.json').read_text())
    frozen=json.loads((out/'frozen-output-hashes.json').read_text())
    for name,expected in frozen.items():
        if hashlib.sha256((out/name).read_bytes()).hexdigest()!=expected:raise ValueError('冻结材料或输出发生变化：'+name)
    if 'predictions.json' not in frozen:
        receipt=json.loads((out/'predictions-frozen.json').read_text())
        if hashlib.sha256((out/'predictions.json').read_bytes()).hexdigest()!=receipt['predictions_sha256']:
            raise ValueError('延后生成的预测指纹不一致')
    if len(pred)!=len(docs) or any(p['paper_id']!=d['paper_id'] or p['input_fingerprint']!=fingerprint(d) for d,p in zip(docs,pred)):
        raise ValueError('预测与冻结输入文献及指纹不一致')
    gold_receipt=json.loads((out/'gold-frozen.json').read_text())
    if hashlib.sha256((out/'gold.json').read_bytes()).hexdigest()!=gold_receipt['gold_sha256']:raise ValueError('冻结标准答案发生变化')
    by_id={r['paper_id']:r for r in gold['papers']}
    if len(by_id)!=len(docs) or set(by_id)!={d['paper_id'] for d in docs}:raise ValueError('标准答案文献覆盖不一致')
    semantic={}
    if (out/'semantic-map.json').exists():
        if 'semantic-map.json' not in frozen:raise ValueError('语义对应表必须先冻结')
        mapping=json.loads((out/'semantic-map.json').read_text())['mappings']
        targets=set()
        for entry in mapping:
            ref=entry['reference_id'];target=entry['label_id'];rule=BY_ID.get(target)
            if not ref.startswith('gold.') or ref in semantic or target in targets or not rule:
                raise ValueError('语义对应须为独立参考到正式标签的一对一关系')
            if rule['level']!=entry['level'] or rule['dimension']!=entry['dimension'] or not entry.get('definition'):
                raise ValueError('语义对应层级、维度或定义不合法')
            occurrences=[(level,item) for paper in gold['papers'] for level in ('level1','level2') for item in paper[level] if item['id']==ref]
            if not occurrences or any(int(level[-1])!=entry['level'] or item.get('dimension')!=entry['dimension'] for level,item in occurrences):
                raise ValueError('语义对应与冻结参考概念不一致')
            semantic[ref]=target;targets.add(target)
    report={'gold_author':'assistant independent reading of identical frozen input','scope':gold['scope'],'levels':{},'papers':[]}
    if semantic:report['semantic_id_mapping']=semantic
    totals={level:{'tp':0,'fp':0,'fn':0,'exact':0,'eligible_papers':0} for level in ('level1','level2')}
    for doc,p in zip(docs,pred):
        g=by_id[doc['paper_id']]
        if g['input_fingerprint']!=fingerprint(doc):raise ValueError('标准答案与程序输入不一致')
        row={'paper_id':doc['paper_id'],'title':doc['title']}
        for level in ('level1','level2'):
            expected=set()
            for item in g[level]:
                if item['id'] not in BY_ID:
                    if not item['id'].startswith('gold.') or not item.get('name') or not item.get('dimension'):raise ValueError('词表外标准答案须有独立ID、名称和维度')
                elif BY_ID[item['id']]['level']!=int(level[-1]):raise ValueError('标准答案标签或层级错误')
                if not item.get('evidence'):raise ValueError('标准答案缺证据')
                for e in item['evidence']:
                    if level=='level1':source=doc['title'] if e['scope']=='title' else doc['abstract'] if e['scope']=='abstract' else ''
                    else:
                        chunk=next((c for c in doc['chunks'] if c['id']==e['chunk_id']), None)
                        source=chunk['text'] if chunk else ''
                        if chunk and e.get('page')!=chunk['page']:raise ValueError('标准答案PDF页码不一致')
                    if not e.get('quote') or e['quote'] not in source:raise ValueError('标准答案引文不在相同冻结输入内')
                expected.add(semantic.get(item['id'],item['id']))
            actual={x['id'] for x in p[level]};tp=actual&expected;fp=actual-expected;fn=expected-actual
            eligible=g.get('eligible_levels',{}).get(level,True)
            if eligible:
                totals[level]['tp']+=len(tp);totals[level]['fp']+=len(fp);totals[level]['fn']+=len(fn);totals[level]['exact']+=actual==expected
                totals[level]['eligible_papers']+=1
            row[level]={'eligible':eligible,'expected':sorted(expected),'predicted':sorted(actual),'correct':sorted(tp),'false_positives':sorted(fp),'missed':sorted(fn)}
            if not eligible:row[level]['exclusion_reason']=g.get('exclusion_reason','Input ineligible for this level')
        report['papers'].append(row)
    for level,t in totals.items():
        precision=t['tp']/(t['tp']+t['fp']) if t['tp']+t['fp'] else 0
        recall=t['tp']/(t['tp']+t['fn']) if t['tp']+t['fn'] else 0
        report['levels'][level]={**t,'precision':round(precision,4),'recall':round(recall,4),'f1':round(2*precision*recall/(precision+recall),4) if precision+recall else 0,'exact_papers':t['exact'],'papers':t['eligible_papers'],'selected_papers':len(docs)}
        out_of_vocab=sum(sum(semantic.get(item['id'],item['id']) not in BY_ID for item in paper[level]) for paper in gold['papers'] if paper.get('eligible_levels',{}).get(level,True))
        known_missed=t['fn']-out_of_vocab
        report['levels'][level].update(out_of_vocabulary_gold=out_of_vocab,
            in_vocabulary_recall=round(t['tp']/(t['tp']+known_missed),4) if t['tp']+known_missed else 0,
            in_vocabulary_f1=round(2*t['tp']/(2*t['tp']+t['fp']+known_missed),4) if 2*t['tp']+t['fp']+known_missed else 0)
    dump(out/'metrics.json',report)
    return report
