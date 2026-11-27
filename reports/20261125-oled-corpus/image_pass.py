"""Alternate renderer for sparse or decoder-warning pages; locate equals-like pixel pairs."""
import hashlib
import io
import json
import os
import tempfile
import pymupdf
import sqlite3
import subprocess
import zipfile
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage
from scan import ROOT, write

def equal_pairs(gray):
    ink=gray<125
    # Equal-sign strokes are small, horizontal connected components of similar size.
    cc,_=ndimage.label(ink)
    by_row=defaultdict(list)
    for slices in ndimage.find_objects(cc):
        if not slices:continue
        ys,xs=slices
        w=xs.stop-xs.start; h=ys.stop-ys.start
        if 5<=w<=30 and 1<=h<=4 and w>=3*h and ink[ys,xs].mean()>=.64:
            by_row[ys.start].append((xs.start,w,h))
    for y,bars in by_row.items():
        for x,w,h in bars:
            if any(abs(x-x2)<=2 and abs(w-w2)<=max(2,w*.2) for yy in range(y+h+1,y+h+8)
                   for x2,w2,h2 in by_row.get(yy,())):
                yield x,y,w

def render(job):
    pid,src,digest,pages=job
    target=ROOT/'raster_recheck'/(pid+'.zip')
    if target.exists():
        with zipfile.ZipFile(target) as existing:
            if all(p['status']=='rendered' for p in json.loads(existing.read('pages.json'))):return
    with open(src,'rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=digest:raise RuntimeError('changed source')
    tmp=target.with_suffix('.tmp')
    info=[]
    with zipfile.ZipFile(tmp,'w') as z:
        for n in pages:
            args=['pdftoppm','-f',str(n),'-l',str(n),'-singlefile','-gray','-scale-to','1500',src]
            proc=subprocess.run(args,capture_output=True,timeout=90)
            entry=dict(page=n,source_sha256=digest,warning=proc.stderr.decode(errors='replace')[:500],bands=[])
            info.append(entry)
            if proc.returncode or not proc.stdout:
                # Retry Poppler against a temporary copy with a rebuilt cross-reference table.
                with tempfile.TemporaryDirectory() as folder:
                    repaired=Path(folder)/'rebuilt.pdf'
                    with pymupdf.open(src) as original:
                        original.save(repaired,garbage=1)
                    proc=subprocess.run(args[:-1]+[str(repaired)],capture_output=True,timeout=90)
                entry['renderer_input']='temporary_rebuilt_xref'
                entry['retry_warning']=proc.stderr.decode(errors='replace')[:500]
                if proc.returncode or not proc.stdout:
                    entry['status']='render_error';continue
            im=Image.open(io.BytesIO(proc.stdout)).convert('L')
            full=io.BytesIO();im.save(full,'PNG')
            entry.update(status='rendered',image=f'p{n:04d}.png',size=im.size)
            z.writestr(entry['image'],full.getvalue())
            arr=np.asarray(im)
            for i,(x,y,w) in enumerate(equal_pairs(arr)):
                # Preserve context to both sides and above/below the mark for fractions.
                box=(max(0,x-14*w),max(0,y-3*w),min(im.width,x+17*w),min(im.height,y+4*w))
                key=f'p{n:04d}-eq{i+1:04d}.png'
                buf=io.BytesIO();im.crop(box).save(buf,'PNG')
                z.writestr(key,buf.getvalue())
                entry['bands'].append(dict(image=key,pixel_box=box,anchor=[x,y],kind='parallel_strokes'))
    # Close and atomically publish the archive with its manifest.
    with zipfile.ZipFile(tmp,'a') as z:
        z.writestr('pages.json',json.dumps(info),compress_type=zipfile.ZIP_DEFLATED)
    tmp.replace(target)

if __name__=='__main__':
    (ROOT/'raster_recheck').mkdir(exist_ok=True)
    with sqlite3.connect((ROOT/'formulas.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        groups=defaultdict(list)
        for pid,src,digest,n in db.execute("SELECT p.id,p.source_path,p.source_sha256,g.page FROM pages g JOIN papers p ON p.id=g.paper_id WHERE g.text_chars<40 OR g.decoder_warning<>'' ORDER BY p.id,g.page"):
            groups[(pid,src,digest)].append(n)
    with ProcessPoolExecutor(max_workers=8) as pool:
        for i,_ in enumerate(pool.map(render,[(*k,v) for k,v in groups.items()]),1):
            if i%100==0:print(i,flush=True)
