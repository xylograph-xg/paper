import json,tempfile,unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from core.catalog import Catalog
from cards import web_card_queue as queue
from cards.web_card_inputs import digest
from cards.web_card_service import publish_saved

class ReworkTests(unittest.TestCase):
 def test_backup_replacement_and_human_candidate(self):
  for human in (False,True):
   with self.subTest(human=human),tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);cat=Catalog(root/'catalog.sqlite3');pid=cat.upsert({'title':'test'});queue.install(cat)
    target=root/'library'/pid;target.mkdir(parents=True);old=target/'card.json';old.write_text('{"old":"science"}')
    backup=root/'backup';backup.mkdir();(backup/'card.json').write_bytes(old.read_bytes());cat.update(pid,card_path=str(old))
    if human:cat.event(pid,'human_decision',{'keep':True})
    record={'old_card_path':str(old),'old_sha256':digest(old),'backup':str(backup),'human_protected':human}
    with cat.connect() as db:db.execute('INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,updated) VALUES(?,?,?,?,?)',(pid,'source','test',json.dumps({'rework':record}),'now'))
    import pymupdf
    from cards.web_card_inputs import prepare
    source=root/'original.pdf';quote='A synthetic original observation under explicit source conditions.'
    with pymupdf.open() as doc:
     doc.new_page().insert_text((20,40),quote,fontsize=10);doc.save(source)
    cat.update(pid,acquisition='available',asset_path=str(source),asset_hash=digest(source))
    with cat.connect() as db:db.execute('UPDATE web_card_jobs SET source_sha256=? WHERE paper_id=?',(digest(source),pid))
    folder=root/'web_cards'/pid;prepare(source,folder,pid,'test',digest(source))
    card={'title':'test','key_findings':'synthetic finding\nsecond finding','figures':[{'label':'Fig. 1','source_page':1,'evidence_quote':quote}],'equations':[],'tables':[]};a={'settings':{},'conversation_url':'https://chatgpt.com/c/test','raw_sha256':'raw'}
    with patch('cards.web_card_inputs.parse_card',return_value=card):publish_saved({'catalog_path':str(cat.path),'studio_library_root':str(root/'library')},queue.jobs(cat)[0],'raw',a,'chatgpt')
    self.assertEqual((backup/'card.json').read_text(),'{"old":"science"}')
    output=folder/'gpt-rework-candidate/card.json' if human else Path(cat.get(pid)['card_path'])
    result=json.loads(output.read_text());self.assertEqual(result['meta']['provider'],'chatgpt');self.assertTrue(Path(result['figures'][0]['image_path']).is_file())
    if human:self.assertEqual(old.read_text(),'{"old":"science"}')
 def test_changed_original_blocks_rework(self):
  from cards.web_card_rework import authorization
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);old=root/'card.json';old.write_text('old');backup=root/'backup';backup.mkdir();(backup/'card.json').write_text('old')
   job={'selection':json.dumps({'rework':{'old_card_path':str(old),'old_sha256':digest(old),'backup':str(backup)}})}
   old.write_text('human edit')
   with self.assertRaises(ValueError):authorization(job,{'card_path':str(old)})

if __name__=='__main__':unittest.main()
