"""Prepare read-only corpus evidence as bounded, per-paper web attachments."""
import contextlib
import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

ROOT = Path('/Volumes/ssd-1t-1/paper-library/oled-formulas-20261125')
OUT = ROOT/'web-organization'
def sha(data):return hashlib.sha256(data).hexdigest()
def dump(obj):return json.dumps(obj,ensure_ascii=False,separators=(',',':')).encode()
def main():
    OUT.mkdir(exist_ok=True)
    for name in ('bundles','articles','receipts'): (OUT/name).mkdir(exist_ok=True)
    if (OUT/'jobs.sqlite3').exists():raise SystemExit('Frozen queue already exists')
    with sqlite3.connect((ROOT/'formulas.sqlite3').as_uri()+'?mode=ro',uri=True) as db, sqlite3.connect(OUT/'jobs.build') as q:
        db.row_factory=sqlite3.Row
        q.executescript("""CREATE TABLE jobs(id TEXT PRIMARY KEY,paper TEXT,part INTEGER,state TEXT,path TEXT,sha TEXT,keys_json TEXT,detail TEXT);
          CREATE INDEX job_status ON jobs(state,paper,part);
          CREATE TABLE articles(id TEXT PRIMARY KEY,title TEXT,source_path TEXT,source_hash TEXT,scope TEXT,path TEXT,parts INTEGER);""")
        for r in db.execute("select * from papers where state='scanned' order by id"):
            pid=r['id']; src=Path(r['source_path']); scope=r['source_scope']; hold=r['title_word_overlap']<.65 or scope!='registered_original'
            with src.open('rb') as f:hold=hold or hashlib.file_digest(f,'sha256').hexdigest()!=r['source_sha256']
            files={};meta=[];part=0;images={};size=0
            def flush():
                nonlocal files,meta,part,size
                if not meta:return
                part+=1;job=f'{pid}-{part:04d}'
                packet=dict(job=job,paper=pid,title=r['title'],source_sha256=r['source_sha256'],scope=scope,images=meta)
                target=OUT/'bundles'/(job+'.zip')
                with zipfile.ZipFile(target,'w') as z:
                    z.writestr('manifest.json',dump(packet),compress_type=zipfile.ZIP_DEFLATED)
                    for k,data in files.items():z.writestr(k,data)
                q.execute('insert into jobs values(?,?,?,?,?,?,?,?)',(job,pid,part,'hold_source' if hold else 'prepared',str(target),sha(target.read_bytes()),json.dumps([v['id'] for v in meta]),None))
                files={};meta=[];size=0
            with contextlib.ExitStack() as stack:
                opened={}
                def read(zname,member):
                    if zname not in opened:opened[zname]=stack.enter_context(zipfile.ZipFile(ROOT/zname))
                    return opened[zname].read(member)
                queries=[("select region_id,page,kind,archive,image,bbox,nearby from regions where paper_id=? order by page,region_id",'pdf_points'),
                         ("select image,page,'parallel_strokes',archive,image,pixel_box,'' from raster_bands where paper_id=? order by page,image",'page_pixels')]
                for sql,coords in queries:
                    for key,page,kind,archive,img,bbox,near in db.execute(sql,(pid,)):
                        data=read(archive,img);finger=sha(data);key=key.removesuffix('.png')
                        # Equal images on the same PDF page point back to the same bytes.
                        ident=(page,finger)
                        if ident in images:
                            images[ident]['aliases'].append(key);continue
                        if len(meta)>=48 or size+len(data)>20_000_000:flush()
                        filename=key+'.png'
                        item=dict(id=key,page=page,kind=kind,image=filename,sha256=finger,bbox=json.loads(bbox),units=coords)
                        if near:item['context']=near
                        meta.append(item);files[filename]=data;size+=len(data)
                        images[ident]=dict(id=key,page=page,archive=archive,image=img,aliases=[],part=part+1)
                flush()
            path=OUT/'articles'/(pid+'.json')
            article=dict(paper_id=pid,title=r['title'],doi=r['doi'],source_path=str(src),source_sha256=r['source_sha256'],source_scope=scope,
                         status='source_review' if hold else ('awaiting_web' if part else 'no_candidate_images'),
                         input_parts=part,evidence=list(images.values()),web_results={})
            path.write_bytes(dump(article))
            q.execute('insert into articles values(?,?,?,?,?,?,?)',(pid,r['title'],str(src),r['source_sha256'],scope,str(path),part))
        q.commit()
        print(q.execute('select state,count(*) from jobs group by state').fetchall(),flush=True)
    (OUT/'jobs.build').replace(OUT/'jobs.sqlite3')
if __name__=='__main__':main()
