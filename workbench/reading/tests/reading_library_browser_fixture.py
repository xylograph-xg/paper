"""Temporary reading UI fixture: synthetic cards, no worker or model calls."""
import hashlib
import json
import os
import signal
import tempfile
from core.api import paths__WorkspacePath as Path
from core.catalog import Catalog, ROOT
from workbench.web import create_http_server

temp=tempfile.TemporaryDirectory(prefix='paper-reading-browser-');root=Path(temp.name)
catalog=Catalog(root/'catalog.db');config=json.loads((ROOT/'config/first_round.json').read_text())
config.update(catalog_path=str(catalog.path),automatic_schedule_enabled=False,local_models_enabled=False)
config['web_cards']={'enabled':True,'provider':'gpt','selection_fraction':.30,'max_pages_per_provider':20}
source=root/'source.pdf';source.write_bytes(b'%PDF synthetic reading source')
source_hash=hashlib.sha256(source.read_bytes()).hexdigest();ids=[]
for title,quality,novelty in [('Highest evidence',95,90),('Second evidence',95,60),('Lower evidence',80,90),('Unscored evidence',None,None)]:
    pid=catalog.upsert({'title':title,'doi':'10.1000/'+str(len(ids)),'venue':'Synthetic venue','year':2026,'channels':['journal']},candidate=True)
    card={'title':title,'meta':{'source_original_sha256':source_hash,'scientific_verified':False,'production_contract_complete':False},'figures':[],'equations':[]}
    card['key_findings']='' if title=='Lower evidence' else '1. 制卡核心结论 findings_search_50%：原文第1页。\n2. 对象与条件保留。\n3. <img src=x onerror="window.findingsUnsafe=true">'
    if title in ('Highest evidence','Second evidence'):
        card['one_line_summary']='本文形成了一个可检验的整体解释，将研究中的主要发现连成一致的贡献。summary_search_50% <img src=x onerror="window.summaryUnsafe=true">'
    if quality is not None:
        card['paper_evaluation']={name:{'score':score,'reason':'Synthetic evidence','source_pages':[1]} for name,score in [('overall_quality',quality),('direction_novelty',novelty)]}
    folder=root/pid;folder.mkdir();path=folder/'card.json';path.write_text(json.dumps(card))
    catalog.update(pid,asset_path=str(source),asset_hash=source_hash,acquisition='available',card_path=str(path));ids.append(pid)
    if title=='Highest evidence':catalog.update(pid,assessment={'core_findings':'旧初筛摘要，不应替代制卡结论','recommendation_reason':'Synthetic screening'})
if os.environ.get('PAPER_REVIEW_FIXTURE')=='1':
    from review.card_review_queue import install, enqueue
    config['studio_library_root']=str(root)
    for pid in ids:
        path=Path(catalog.get(pid)['card_path']);card=json.loads(path.read_text())
        card['tables']=[];card['meta'].update(producer='web_card_service',provider='chatgpt')
        path.write_text(json.dumps(card))
    install(catalog);enqueue(catalog,config)
if os.environ.get('PAPER_RANKING_FIXTURE')=='1':
    from review.card_review_queue import install
    install(catalog)
    with catalog.connect() as db:
        for pid,score in zip(ids,[20,80,95,90]):
            path=Path(catalog.get(pid)['card_path']);fingerprint=hashlib.sha256(path.read_bytes()).hexdigest()
            db.execute('INSERT INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,state,folder,result,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                (pid,pid,fingerprint,source_hash,pid,'needs_user',str(root),json.dumps({'weighted_score':score,'full_source_checked':False}),'test'))
from correction.tests.test_corrected_library import mark_corrected
for pid in ids:mark_corrected(catalog,pid,root)
hosts=set();origins=set();secret='synthetic-reading-access'
server=create_http_server(config,catalog,0,secret,hosts,origins)
host='127.0.0.1:'+str(server.server_port);hosts.add(host);url='http://'+host;origins.add(url)
print(json.dumps({'url':url,'secret':secret,'ids':ids}),flush=True)
def stop(*_):raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
try:server.serve_forever()
finally:server.server_close();temp.cleanup()
