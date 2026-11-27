"""Read one frozen package; render disposable visual candidates, never repack it."""
import hashlib,json,tempfile,zipfile
from pathlib import Path
import pymupdf
from review.card_review_queue import render_review_visual
report=Path(__file__).parent
rows=json.loads((report/'owner-zip-cohort.json').read_text())['records']
r=max(rows,key=lambda row:row.get('bytes') or 0)
bundle=Path(r['zip_path'].replace('/paper/data/','/paper/infrastructure/data/'))
original_hash=hashlib.sha256(bundle.read_bytes()).hexdigest()
with zipfile.ZipFile(bundle) as z:
    infos=z.infolist();source_name=next(i.filename for i in infos if i.filename.endswith('/source.pdf') or i.filename=='source.pdf')
    visual_name=next(i.filename for i in infos if i.filename.endswith('/visual.pdf') or i.filename=='visual.pdf')
    source=z.read(source_name);nonvisual_compressed=sum(i.compress_size for i in infos if i.filename!=visual_name)
    before_visual=next(i.compress_size for i in infos if i.filename==visual_name)
    result={'original_zip_sha256':original_hash,'original_zip_bytes':bundle.stat().st_size,
            'source_pdf_sha256':hashlib.sha256(source).hexdigest(),'original_visual_zip_bytes':before_visual,
            'nonvisual_zip_bytes':nonvisual_compressed,'policy_target_bytes':24_000_000,
            'note':'counterfactual visual-only measurement; original ZIP and frozen packet unchanged','candidates':[]}
    with tempfile.TemporaryDirectory(prefix='paper-new-visual-') as td:
        root=Path(td);p=root/'source.pdf';p.write_bytes(source)
        for dpi in (220,180,150):
            visual=root/f'visual-{dpi}.pdf';manifest=render_review_visual(p,visual,dpi)
            # Measure exact deflate payload bytes without saving another ZIP.
            import zlib
            compressed=zlib.compressobj(6,zlib.DEFLATED,-15)
            data=visual.read_bytes();size=len(compressed.compress(data)+compressed.flush())
            with pymupdf.open(visual) as doc:count=len(doc)
            result['candidates'].append({'dpi':dpi,'pages':count,'manifest_pages':len(manifest),
                'visual_pdf_bytes':len(data),'visual_deflate_bytes':size,
                'estimated_zip_bytes':nonvisual_compressed+size,'soft_target_met':nonvisual_compressed+size<=24_000_000})
        assert p.read_bytes()==source
assert hashlib.sha256(bundle.read_bytes()).hexdigest()==original_hash
result['original_unchanged']=True
(report/'zip-visual-measurement.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
print(json.dumps(result,ensure_ascii=False))
