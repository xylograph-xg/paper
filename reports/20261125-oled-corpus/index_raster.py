"""Verify alternate-renderer archives and expose their bands and full images in SQLite."""
import json
import sqlite3
import zipfile
from scan import ROOT, REPORT, write

with sqlite3.connect(ROOT/'formulas.sqlite3') as db:
    db.execute('BEGIN')
    db.execute('CREATE TABLE IF NOT EXISTS raster_pages(paper_id TEXT,page INTEGER,status TEXT,archive TEXT,image TEXT,size_px TEXT,warning TEXT,PRIMARY KEY(paper_id,page))')
    db.execute('CREATE TABLE IF NOT EXISTS raster_bands(paper_id TEXT,page INTEGER,image TEXT,pixel_box TEXT,archive TEXT, PRIMARY KEY(paper_id,image))')
    for f in sorted((ROOT/'raster_recheck').glob('*.zip')):
        pid=f.stem
        filename=f.relative_to(ROOT).as_posix()
        with zipfile.ZipFile(f) as z:
            assert z.testzip() is None
            source_sha=db.execute('SELECT source_sha256 FROM papers WHERE id=?',(pid,)).fetchone()[0]
            for r in json.loads(z.read('pages.json')):
                assert r['source_sha256']==source_sha
                if r['status']=='rendered':assert z.getinfo(r['image']).file_size>0
                db.execute('INSERT OR REPLACE INTO raster_pages VALUES(?,?,?,?,?,?,?)',
                    (pid,r['page'],r['status'],filename,r.get('image'),json.dumps(r.get('size')),r['warning']))
                for b in r['bands']:
                    assert z.getinfo(b['image']).file_size>0
                    db.execute('INSERT OR REPLACE INTO raster_bands VALUES(?,?,?,?,?)',(pid,r['page'],b['image'],json.dumps(b['pixel_box']),filename))
    expected=db.execute("SELECT count(*) FROM pages WHERE text_chars<40 OR decoder_warning<>''").fetchone()[0]
    actual=db.execute("SELECT count(*) FROM raster_pages").fetchone()[0]
    assert actual==expected,(actual,expected)
    db.execute('CREATE VIEW IF NOT EXISTS printed_labels AS SELECT paper_id,page,equation_number,count(*) AS crop_variants FROM numbered_candidates GROUP BY paper_id,page,equation_number')
    summ=json.loads((REPORT/'summary.json').read_text())
    summ.update(raster_page_status=dict(db.execute('SELECT status,count(*) FROM raster_pages GROUP BY status')),
                raster_bands=db.execute('SELECT count(*) FROM raster_bands').fetchone()[0],
                printed_labels=db.execute('SELECT count(*) FROM printed_labels').fetchone()[0])
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
write(REPORT/'summary.json',summ)
print(summ)
