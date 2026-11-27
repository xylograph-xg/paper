"""Run from the paper workspace using the test environment and PYTHONPATH=infrastructure:workbench."""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pymupdf
from core.api import literature_catalog__metadata_rows, literature_catalog__source_records, paths__WorkspacePath
from read.api import parser, parser__parse_pdf, evidence_preparation__recover_numbered_equations, evidence_preparation__filter_equation_candidates

out = Path(__file__).parent
catalog = 'infrastructure/data/catalog.sqlite3'
oled = re.compile(r'\bOLEDs?\b|organic light.emitting (?:diodes?|devices?)', re.I)
model = re.compile(r'model(?:l?ing)?|theor(?:y|etical)|simulation|computational|drift.diffusion|monte carlo', re.I)
refs = re.compile(r'^\s*(?:(?:[IVX]+|\d+)\.?\s+)?(?:references(?: and notes)?|bibliography)\s*$', re.I)
words = lambda t: set(re.findall(r'[a-z0-9]{2,}', t.lower()))
skips = Counter()
pool = [r for r in literature_catalog__metadata_rows(catalog) if r['has_pdf'] and oled.search(r['title'])]
pool.sort(key=lambda r: hashlib.sha256(('oled-equations-1'+r['id']).encode()).digest())
samples = []
for enriched in [True, False]:
    ids = [r['id'] for r in pool if bool(model.search(r['title'])) == enriched]
    added = 0
    for i in range(0,len(ids),50):
        records = {r['id']:r for r in literature_catalog__source_records(catalog,ids[i:i+50])}
        for pid in ids[i:i+50]:
            r = records[pid]
            if any(r['metadata'].get(k) for k in ['identity_review_required','version_review_required','out_of_scope']):
                skips['protected'] += 1
                continue
            path = paths__WorkspacePath(r['asset_path'])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=r['asset_hash']:
                skips['unavailable_or_changed'] += 1
                continue
            if any(s['sha256']==r['asset_hash'] or s['title'].casefold()==r['title'].casefold() for s in samples):
                skips['duplicate'] += 1
                continue
            with pymupdf.open(path) as doc:
                if not 2<=len(doc)<=14:
                    skips['outside_2_to_14_pages'] += 1
                    continue
                first = doc[0].get_text()
                if len(words(first) & words(r['title'])) < .8*len(words(r['title'])) or re.search(r'(?i)(supporting|supplementary) (information|material)', first[:400]):
                    skips['cover_title_or_si'] += 1
                    continue
            samples.append(dict(id=pid,title=r['title'],path=str(path),sha256=r['asset_hash'],model_title=enriched))
            added += 1
            if added==15: break
        if added==15: break
    assert added==15
(out/'sample.json').write_text(json.dumps(dict(sample=samples,skipped=skips),indent=2))
for r in samples:
    parsed=parser__parse_pdf(r['path'])
    evidence_preparation__recover_numbered_equations(parsed,parser)
    evidence_preparation__filter_equation_candidates(parsed)
    end=next((i+1 for i,t in enumerate(parsed.page_texts) if any(refs.fullmatch(line) for line in t.splitlines())),parsed.page_count)
    hits=[]
    for eq in parsed.equations:
        for m in eq.members:
            text=m['text']
            if m['page']>end: continue
            if m.get('number') is None and (not re.search(r'[=≡≈∝]',text) or not re.search(r'[+−*/∫∑∂√×]',text)): continue
            hits.append(dict(page=m['page'],box=m['bbox'],number=m.get('number'),text=text))
    r.update(pages=parsed.page_count,body_end_estimate=end,hits=hits,count=len(hits),density=len(hits)/end,
             sparse_pages=parsed.extraction_audit.get('sparse_text_pages',[]))
samples.sort(key=lambda r:(-r['count'],-r['density'],r['id']))
(out/'results.json').write_text(json.dumps(samples,ensure_ascii=False,indent=2))
for i,r in enumerate(samples,1): print(i,r['count'],r['pages'],r['title'])
