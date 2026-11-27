"""Build the standalone SQLite index and audit every image against its ZIP CRC."""
import json
import sqlite3
import zipfile
from collections import Counter
from pathlib import Path
from scan import ROOT, REPORT, write

def main():
    inventory=json.loads((ROOT/'inventory.json').read_text())
    coverage={r['id']:r for r in json.loads((ROOT/'coverage.json').read_text())}
    target=ROOT/'formulas.sqlite3'
    temp=target.with_suffix('.build')
    if temp.exists(): raise FileExistsError(temp)
    db=sqlite3.connect(temp)
    db.executescript("""
    CREATE TABLE papers(id TEXT PRIMARY KEY,title TEXT,doi TEXT,state TEXT,source_scope TEXT,
      title_word_overlap REAL,source_path TEXT,source_sha256 TEXT,pdf_pages INTEGER);
    CREATE TABLE pages(paper_id TEXT,page INTEGER,text_chars INTEGER,raster_boxes TEXT,
      decoder_warning TEXT, PRIMARY KEY(paper_id,page));
    CREATE TABLE regions(paper_id TEXT,region_id TEXT,page INTEGER,kind TEXT,equation_number TEXT,
      text TEXT,nearby TEXT,bbox TEXT,render_clip TEXT,pixels_per_point REAL,archive TEXT,image TEXT,
      PRIMARY KEY(paper_id,region_id));
    CREATE TABLE code_examples(paper_id TEXT,region_id TEXT,equation_number INTEGER,latex TEXT,python_rhs TEXT,
      variables TEXT,domain TEXT,tests TEXT, PRIMARY KEY(paper_id,region_id));
    """)
    stats=Counter()
    for r in inventory:
        pid=r['id'];s=coverage[pid];scope=None;overlap=None;num=None
        if s['state']=='scanned':
            scope=s.get('source_scope','registered_original')
            num=s['pages']
            with zipfile.ZipFile(ROOT/'layout'/(pid+'.zip')) as z:
                layout=json.loads(z.read('layout.json'))
                assert layout['sha256']==r['sha256']
                overlap=layout['title_overlap']
            with zipfile.ZipFile(ROOT/'papers'/(pid+'.zip')) as z:
                meta=json.loads(z.read('paper.json'))
                assert meta['id']==pid and meta['sha256']==r['sha256']
                pages=json.loads(z.read('pages.json'))
            assert num==len(pages)==len(layout['pages'])
            for a,b in zip(pages,layout['pages']):
                assert a['page']==b['page']
                db.execute('INSERT INTO pages VALUES(?,?,?,?,?)',(pid,a['page'],a['text_chars'],json.dumps(b['raster_boxes']),b['warning']))
            for folder in ('papers','layout'):
                filename=f'{folder}/{pid}.zip'
                with zipfile.ZipFile(ROOT/filename) as z:
                    assert z.testzip() is None
                    names=set(z.namelist())
                    for line in z.read('regions.jsonl').splitlines():
                        h=json.loads(line)
                        assert 1<=h['page']<=num and h['image'] in names
                        db.execute('INSERT INTO regions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                                   (pid,h['key'],h['page'],h['kind'],h['number'],h['text'],h.get('nearby'),json.dumps(h['bbox']),
                                    json.dumps(h['clip_rotated']),h['scale'],filename,h['image']))
        db.execute('INSERT INTO papers VALUES(?,?,?,?,?,?,?,?,?)',(pid,r['title'],r.get('doi'),s['state'],scope,overlap,r.get('path'),r.get('sha256'),num))
    for f in json.loads((REPORT/'examples/formulas.json').read_text()):
        assert db.execute('SELECT 1 FROM regions WHERE paper_id=? AND region_id=?',(f['paper'],f['region'])).fetchone()
        db.execute('INSERT INTO code_examples VALUES(?,?,?,?,?,?,?,?)',(f['paper'],f['region'],f['equation'],f['latex'],f['python_rhs'],json.dumps(f['variables']),f['domain'],json.dumps(f['tests'])))
    db.executescript("""
    CREATE INDEX regions_by_kind ON regions(kind,paper_id,page);
    CREATE VIEW numbered_candidates AS SELECT * FROM regions WHERE kind IN ('numbered','numbered_band','pilot_candidate') AND equation_number IS NOT NULL;
    """)
    db.commit()
    assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
    summary={
        'states':dict(db.execute('select state,count(*) from papers group by state')),
        'scopes':dict(db.execute("select source_scope,count(*) from papers where state='scanned' group by source_scope")),
        'page_count':db.execute('select count(*) from pages').fetchone()[0],
        'region_counts':dict(db.execute('select kind,count(*) from regions group by kind')),
        'sparse_pages':db.execute('select count(*) from pages where text_chars<40').fetchone()[0],
        'warning_pages':db.execute("select count(*) from pages where decoder_warning<>''").fetchone()[0],
        'weak_title_overlap':db.execute('select count(*) from papers where title_word_overlap<0.65').fetchone()[0],
        'documents_with_numbered_candidates':db.execute('select count(distinct paper_id) from numbered_candidates').fetchone()[0],
        'example_count':db.execute('select count(*) from code_examples').fetchone()[0],
        'region_count':db.execute('select count(*) from regions').fetchone()[0],
    }
    db.close()
    temp.replace(target)
    write(REPORT/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':
    main()
