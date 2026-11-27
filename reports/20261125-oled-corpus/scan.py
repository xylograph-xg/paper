"""One-shot local OLED evidence scan. Run from the paper root with the test Python."""
import hashlib
import json
import os
import re
import time
import zipfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pymupdf as pdf
from oled_formulas.api import oled_candidate
from core.api import literature_catalog__metadata_rows, literature_catalog__source_records, paths__WorkspacePath

REPORT = Path(__file__).resolve().parent
ROOT = Path('/Volumes/ssd-1t-1/paper-library/oled-formulas-20261125')
CAT = Path('infrastructure/data/catalog.sqlite3')
REL = re.compile(r'[=≠≈≃≡≤≥∝≅≔↔⇌]|[∑∏∫∂∇√]')
NUMBER = re.compile(r'\(\s*([A-Za-z]?\d{1,3}(?:[.\-]\d+)?[a-z]?)\s*\)\s*[.,]?\s*$')
SI = re.compile(r'^\s*(?:S\s*1\s*)?(?:electronic\s+)?(?:supporting|supplementary|supplemental)\s+(?:information|materials?|data)\b', re.I)
PILOT = json.loads((REPORT.parent/'20261125-oled-equations/results.json').read_text())
PRIOR = {r['sha256']: r['hits'] for r in PILOT}

def write(path, data):
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False))
    temp.replace(path)

def inventory():
    frozen = ROOT/'inventory.json'
    if frozen.exists(): return json.loads(frozen.read_text())
    items = {}
    for r in literature_catalog__metadata_rows(CAT):
        if not oled_candidate(r['title'],r['metadata'].get('abstract')): continue
        items[r['id']] = dict(id=r['id'],title=r['title'],state='missing_pdf',has_pdf=r['has_pdf'])
    ids = [k for k,v in items.items() if v['has_pdf']]
    for pos in range(0,len(ids),100):
        for r in literature_catalog__source_records(CAT,ids[pos:pos+100]):
            protected = [k for k in ('identity_review_required','version_review_required','out_of_scope') if r['metadata'].get(k)]
            items[r['id']].update(state='protected' if protected else 'ready',protected=protected,
                                  path=str(paths__WorkspacePath(r['asset_path'])) if r.get('asset_path') else '',
                                  sha256=r.get('asset_hash'),doi=r['metadata'].get('doi'))
    write(frozen,list(items.values()))
    return list(items.values())

def page_regions(page, previous):
    blocks = page.get_text('dict',flags=pdf.TEXTFLAGS_DICT & ~pdf.TEXT_PRESERVE_IMAGES)['blocks']
    lines = []
    groups = []
    for block in blocks:
        group=[]
        for line in block.get('lines',[]):
            t=''.join(s['text'] for s in line['spans']).strip()
            if not t: continue
            b=pdf.Rect(line['bbox'])
            if b.is_empty or b.is_infinite: continue
            group.append((t,b))
        lines.extend(group)
        groups.append(group)
    rows={}
    def add(box,kind,t,num=None):
        key=(kind,tuple(round(x,1) for x in box),num)
        rows[key]=(box,kind,t,num)
    for group in groups:
        for t,b in group:
            match=NUMBER.search(t)
            math=bool(REL.search(t))
            short=len(re.findall(r'[A-Za-z]{3,}',t))<=5
            if match and (math or NUMBER.fullmatch(t)) and short:
                # Collect the expression to the left of a separate column-end label.
                near=[box for txt,box in lines if box.x1<=b.x0+3 and b.x0-box.x0<page.cropbox.width*.5
                      and abs((b.y0+b.y1-box.y0-box.y1)/2)<max(8,b.height*.8) and len(re.findall(r'[A-Za-z]{3,}',txt))<7]
                box=pdf.Rect(b)
                if NUMBER.fullmatch(t) and near:
                    for nb in near: box|=nb
                add(box,'numbered' if math or near else 'isolated_label',t,match[1])
            elif math or (short and re.search(r'[α-ωΑ-Ωa-zA-Z]\s*[<>±]\s*[-+\dα-ωa-zA-Z]',t)):
                add(b,'relation_line' if short else 'inline_context',t)
        if group and len(group)>1:
            joined=' '.join(t for t,b in group)
            if REL.search(joined) and len(re.findall(r'[A-Za-z]{3,}',joined))<=6:
                box=pdf.Rect(group[0][1])
                for _,b in group[1:]: box|=b
                add(box,'multiline_context',joined)
    for h in previous:
        add(pdf.Rect(h['box']),'pilot_candidate',h['text'],h['number'])
    chars=sum(len(t) for t,b in lines)
    if chars<40: add(page.rect*page.derotation_matrix,'sparse_page','')
    return list(rows.values()),lines,chars

def scan(r):
    archive=ROOT/'papers'/(r['id']+'.zip')
    if archive.exists():
        with zipfile.ZipFile(archive) as z: return json.loads(z.read('paper.json'))
    summary=dict(id=r['id'],state=r['state'])
    if r['state']!='ready':return summary
    tmp=archive.with_suffix('.tmp')
    try:
        path=Path(r['path'])
        with path.open('rb') as f:
            if hashlib.file_digest(f,'sha256').hexdigest()!=r['sha256']: return dict(summary,state='source_hash_mismatch')
        with pdf.open(path) as doc:
            if doc.needs_pass or not len(doc): return dict(summary,state='unreadable')
            first=doc[0].get_text()[:1800]
            scope='supplementary_only' if SI.search(first) else 'registered_original'
            if re.search(r'(?im)^\s*(?:electronic )?(?:supporting|supplementary) (?:information|material)\s*$',first[:500]):
                if scope=='registered_original': scope='possible_supplement'
            counts=Counter()
            with zipfile.ZipFile(tmp,'w',allowZip64=True) as z:
                rows=[]; pages=[]
                for n,page in enumerate(doc,1):
                    hits,lines,chars=page_regions(page,[h for h in PRIOR.get(r['sha256'],[]) if h['page']==n])
                    display=page.get_displaylist() if hits else None
                    pages.append(dict(page=n,text_chars=chars,regions=len(hits)))
                    for bbox,kind,t,num in hits:
                        clip=((bbox+(-5,-5,5,5))*page.rotation_matrix)&page.rect
                        if clip.is_empty:continue
                        scale=min(2,2400/max(clip.width,clip.height))
                        pix=display.get_pixmap(matrix=pdf.Matrix(scale,scale),clip=clip,alpha=False)
                        if not pix.width or not pix.height:continue
                        key=f'p{n:04d}-{len(rows)+1:06d}'
                        img='images/'+key+'.png'
                        z.writestr(img,pix.tobytes('png'))
                        ctx=bbox+(-6,-18,6,18)
                        rows.append(dict(key=key,page=n,kind=kind,number=num,text=t,bbox=list(bbox),
                                         clip_rotated=list(clip),scale=scale,image=img,
                                         nearby=' '.join(v for v,b in lines if ctx.intersects(b))))
                        counts[kind]+=1
                summary.update(state='scanned',source_scope=scope,pages=len(doc),counts=dict(counts),records=len(rows),archive=archive.name)
                z.writestr('regions.jsonl',''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),compress_type=zipfile.ZIP_DEFLATED)
                z.writestr('pages.json',json.dumps(pages))
                z.writestr('paper.json',json.dumps(dict(summary,title=r['title'],sha256=r['sha256'],source=r['path']),ensure_ascii=False))
            tmp.replace(archive)
        return summary
    except Exception as e:
        tmp.unlink(missing_ok=True)
        return dict(summary,state='error',detail=f'{type(e).__name__}: {e}')

if __name__=='__main__':
    ROOT.mkdir(exist_ok=True)
    (ROOT/'papers').mkdir(exist_ok=True)
    data=inventory()
    ready=[r for r in data if r['state']=='ready']
    states=[dict(id=r['id'],state=r['state']) for r in data if r['state']!='ready']
    start=time.monotonic()
    print('inventory',len(data),'ready',len(ready),flush=True)
    with ProcessPoolExecutor(max_workers=8) as pool:
        for i,r in enumerate(pool.map(scan,ready,chunksize=1),1):
            states.append(r)
            if i%100==0:print(i,round(time.monotonic()-start,1),flush=True)
    write(ROOT/'coverage.json',states)
    print(Counter(r['state'] for r in states),flush=True)
