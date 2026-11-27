"""Read the article index and cite the original PDF for each matched web result."""
import argparse
import json
from pathlib import Path
import sqlite3

ROOT = Path('/Volumes/ssd-1t-1/paper-library/oled-formulas-20261125/web-organization')
def search(query,limit):
    needle=query.casefold()
    found=0
    with sqlite3.connect((ROOT/'jobs.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        for pid,title,src,sha,path in db.execute('SELECT id,title,source_path,source_hash,path FROM articles ORDER BY title'):
            doc=json.loads(Path(path).read_text())
            matches=[]
            for part,rec in doc['web_results'].items():
                for item in rec['items']:
                    if item['type']!='equation':continue
                    if needle in json.dumps(item,ensure_ascii=False).casefold():
                        matches.append(dict(item,part=part,pdf_page=Path(src).as_uri()+'#page='+str(item['page'])))
            if matches or needle in title.casefold() or needle==pid.casefold():
                yield dict(paper_id=pid,title=title,source_path=src,source_sha256=sha,
                           article=path,status=doc['status'],matches=matches)
                found+=1
                if found>=limit:return

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('query');ap.add_argument('--limit',type=int,default=10)
    args=ap.parse_args()
    if not args.query.strip() or args.limit<=0:ap.error('nonempty query and positive limit required')
    for row in search(args.query,args.limit):print(json.dumps(row,ensure_ascii=False))
