"""Supplement the fast scan with layout, math-font and raster-region evidence."""
import hashlib
import json
import re
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import pymupdf as pdf
from scan import ROOT, NUMBER, REL, write

MATH_FONT=re.compile(r'math|cmsy|cmmi|cmex|mt.?extra|euclid|mathematica',re.I)
MATH_MARK=re.compile(r'[∏∑∫∇∂√∞⟨⟩⊗⊕↔⇒∈∉∼≪≫]')
PROSE=re.compile(r'[A-Za-z]{3,}')
def words(s):
    return set(re.findall(r'[^\W_]{2,}',s.casefold()))
def layout(r):
    dst=ROOT/'layout'/(r['id']+'.zip')
    if dst.exists(): return
    src=Path(r.get('path',''))
    with src.open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=r['sha256']:raise RuntimeError('source changed')
    tmp=dst.with_suffix('.tmp')
    pdf.TOOLS.mupdf_display_errors(False)
    pdf.TOOLS.mupdf_display_warnings(False)
    pdf.TOOLS.mupdf_warnings(reset=True)
    with pdf.open(src) as doc,zipfile.ZipFile(tmp,'w') as z:
        evidence=[]; page_notes=[]
        cover=' '.join(p.get_text()[:6000] for p in list(doc.pages(0,min(2,len(doc)))))
        title_words=words(r['title'])
        cover_match=len(title_words & words(cover))/max(1,len(title_words))
        for n,p in enumerate(doc,1):
            display=None; regions={}
            def add(box,kind,txt='',num=None):
                if box.is_empty or box.is_infinite:return
                regions[(tuple(round(a,1) for a in box),kind)]=(box,kind,txt,num)
            lines=[]
            for block in p.get_text('dict',flags=pdf.TEXTFLAGS_DICT & ~pdf.TEXT_PRESERVE_IMAGES)['blocks']:
                for l in block.get('lines',[]):
                    spans=l['spans']
                    t=''.join(s['text'] for s in spans).strip()
                    if not t:continue
                    b=pdf.Rect(l['bbox'])
                    if b.is_empty or b.is_infinite:continue
                    lines.append((t,b))
                    math_spans=[s for s in spans if MATH_FONT.search(s['font']) or MATH_MARK.search(s['text'])]
                    if math_spans:
                        add(b,'math_typesetting',t)
            for t,b in lines:
                m=NUMBER.fullmatch(t)
                if not m:continue
                # Clip in the numbered equation's column, bounded above/below by prose.
                width=p.cropbox.width
                leftcol=any(x.x1<width*.58 and len(PROSE.findall(v))>=6 for v,x in lines)
                rightcol=any(x.x0>width*.46 and len(PROSE.findall(v))>=6 for v,x in lines)
                left=width*.48 if leftcol and rightcol and b.x0>width*.68 else 0
                prose=[x for v,x in lines if left<=x.x0<b.x0 and len(PROSE.findall(v))>=6]
                top=max([b.y0-36]+[x.y1 for x in prose if x.y1<=b.y0-1])
                bottom=min([b.y1+36]+[x.y0 for x in prose if x.y0>=b.y1+1])
                add(pdf.Rect(left,top,b.x1+1,bottom),'numbered_band',t,m[1])
            image_boxes=[]
            for im in p.get_image_info():
                box=pdf.Rect(im['bbox'])
                if box.is_empty or box.is_infinite:continue
                image_boxes.append(list(box))
                if box.width>=15 and 3<=box.height<=100 and box.width>=1.3*box.height:
                    add(box,'raster_strip')
            for b,kind,t,num in regions.values():
                clip=((b+(-4,-4,4,4))*p.rotation_matrix)&p.rect
                if clip.is_empty:continue
                display=display or p.get_displaylist()
                scale=min(2,2400/max(clip.width,clip.height))
                pix=display.get_pixmap(matrix=pdf.Matrix(scale,scale),clip=clip,alpha=False)
                if not pix.width or not pix.height:continue
                key=f'l{n:04d}-{len(evidence)+1:06d}'
                img='images/'+key+'.png'
                z.writestr(img,pix.tobytes('png'))
                evidence.append(dict(key=key,page=n,kind=kind,number=num,text=t,bbox=list(b),
                                     clip_rotated=list(clip),scale=scale,image=img))
            msg=pdf.TOOLS.mupdf_warnings(reset=True)
            page_notes.append(dict(page=n,raster_boxes=image_boxes,warning=msg[:1500]))
        z.writestr('regions.jsonl',''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in evidence),compress_type=zipfile.ZIP_DEFLATED)
        z.writestr('layout.json',json.dumps(dict(title_overlap=cover_match,pages=page_notes,sha256=r['sha256'])),compress_type=zipfile.ZIP_DEFLATED)
    tmp.replace(dst)

if __name__=='__main__':
    (ROOT/'layout').mkdir(exist_ok=True)
    rows=[r for r in json.loads((ROOT/'inventory.json').read_text()) if (ROOT/'papers'/(r['id']+'.zip')).exists()]
    with ProcessPoolExecutor(max_workers=8) as pool:
        for i,_ in enumerate(pool.map(layout,rows),1):
            if i%250==0:print(i,flush=True)
