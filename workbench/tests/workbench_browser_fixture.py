"""Temporary HTTP fixture for browser verification; never starts workers."""
import json
import signal
import tempfile
from core.api import paths__WorkspacePath as Path
from core.catalog import Catalog, ROOT
from workbench.web import create_http_server
from core.services import atomic_json

temp=tempfile.TemporaryDirectory(prefix='paper-browser-access-');root=Path(temp.name)
catalog=Catalog(root/'catalog.db');config=json.loads((ROOT/'config/first_round.json').read_text())
config.update(catalog_path=str(catalog.path),automatic_schedule_enabled=False,workbench_passwordless=False)
source=root/'source.pdf';source.write_bytes(b'%PDF synthetic browser fixture')
ids=[]
for title in ['Synthetic emitter evidence','Distinct molecular report']:
 pid=catalog.upsert({'title':title,'doi':'10.1000/'+str(len(ids)),'venue':'Synthetic venue',
                     'internal_hint':'hidden_storage_marker','channels':['journal']},candidate=True)
 catalog.update(pid,asset_path=str(source),acquisition='available');ids.append(pid)
 catalog.update(pid,assessment={'core_findings':'Synthetic finding','relevance':4,'novelty':'Synthetic novelty','evidence_scope':'Synthetic evidence','tags':[],'recommendation_reason':'Synthetic comparison'})
folder=root/'card';folder.mkdir()
from PIL import Image
image=folder/'figure.png';Image.new('RGB',(400,200),'white').save(image)
card={'title':'Synthetic emitter evidence','meta':{'media_evidence':{'source':{'state':'unavailable'},'figures':[{'index':0,'source_figure_id':None,'pdf_page':1,'original_pdf':{'path':'figure.png'},'pdf_reference':{'path':'figure.png'}}],'equations':[]}},'figures':[{'number':1,'label':'Fig. 1','image_path':str(image),'caption':'Synthetic caption','figure_info':'Synthetic axes','summary':'Synthetic summary','detail':'Synthetic detail','result':'Synthetic result','one_line':'Synthetic','candidates':[]}],'equations':[],'warnings':[]}
atomic_json(folder/'card.json',card);atomic_json(folder/'parsed.json',{'page_texts':['Synthetic PDF evidence'],'paragraphs':[]})
catalog.update(ids[0],card_path=str(folder/'card.json'))
for i in range(35):
 job=catalog.enqueue('screen',ids[i%2]);catalog.finish(job,'failed','Synthetic failure '+str(i))
atomic_json(root/'runtime.json',{'state':'stopped','updated':0})
hosts=set();origins=set();secret='synthetic-browser-access'
server=create_http_server(config,catalog,0,secret,hosts,origins)
host='127.0.0.1:'+str(server.server_port);hosts.add(host);url='http://'+host;origins.add(url)
print(json.dumps({'url':url,'secret':secret,'paper_id':ids[0]}),flush=True)
def stop(*_):raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
try:server.serve_forever()
finally:server.server_close();temp.cleanup()
