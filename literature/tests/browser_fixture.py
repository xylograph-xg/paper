"""Disposable workbench serving a tiny synthetic catalog; no worker starts."""
import json
from pathlib import Path
import signal
import tempfile
from core.api import catalog__Catalog as Catalog
from workbench.web import create_http_server

temp=tempfile.TemporaryDirectory(prefix='literature-browser-')
catalog=Catalog(Path(temp.name)/'catalog.db')
ids=[]
for i in range(3):ids.append(catalog.upsert({'title':['Energy transfer study','Organic crystal methods','Missing year'][i],'doi':f'10.1000/browser{i}','year':None if i==2 else 2018+i*6,'abstract':['We report TADF emitters for OLEDs.','We study organic crystals.',''][i]}))
# Real local synthetic PDF plus a version-bound frozen original-text intermediate.
import hashlib,pymupdf
from cards.api import web_card_queue__install as install
install(catalog)
source=Path(temp.name)/'source.pdf';pdf=pymupdf.open();p=pdf.new_page();body='Results and Discussion\nWe measured temperature-dependent photoluminescence spectra and investigated reverse intersystem crossing in TADF molecules.';p.insert_textbox(pymupdf.Rect(40,40,550,750),body,fontsize=11);pdf.save(source);pdf.close()
h=hashlib.sha256(source.read_bytes()).hexdigest();catalog.update(ids[0],acquisition='available',asset_path=str(source),asset_hash=h)
folder=Path(temp.name)/'frozen';folder.mkdir();raw=json.dumps({'source_text':[{'source_page':1,'text':body}]}).encode();(folder/'source-context.json').write_bytes(raw)
(folder/'packet.json').write_text(json.dumps({'paper_id':ids[0],'source_original_sha256':h,'input_hashes':{'source-context.json':hashlib.sha256(raw).hexdigest()}}))
with catalog.connect() as db:db.execute("INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,state,provider,folder,error,attempts,updated) VALUES(?,?,?,'{}','ready','gpt',?,'',0,'')",(ids[0],h,'Synthetic TADF',str(folder)))
hosts=set();origins=set();secret='literature-browser-only'
server=create_http_server({'catalog_path':str(catalog.path)},catalog,0,secret,hosts,origins)
host='127.0.0.1:'+str(server.server_port);hosts.add(host);origins.add('http://'+host)
print(json.dumps({'url':'http://'+host,'secret':secret}),flush=True)
def stop(*_):raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
try:server.serve_forever()
finally:server.server_close();temp.cleanup()
