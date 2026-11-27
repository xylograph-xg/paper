import os,tempfile,unittest
from pathlib import Path
from maintenance.runtime_link_migration import plan,apply_plan

class RuntimeLinkMigration(unittest.TestCase):
 def test_nested_retry_diagnostic_rebases_exact_original_alias_without_capture_claim(self):
  with tempfile.TemporaryDirectory() as td:
   host=Path(td).resolve();archive=host/'ssd';target=archive/'web-inputs'/'paper-a'/'chatgpt'/'error-page.png'
   target.parent.mkdir(parents=True);target.write_bytes(b'original diagnostic')
   old=host/'paper/data';new=host/'paper/infrastructure/data'
   directory=new/'web_cards/paper-a/history/automatic-retry-1-123/chatgpt';directory.mkdir(parents=True)
   link=directory/'error-page.png'
   link.symlink_to('../../../../../../../../'+str(target).lstrip('/'))
   wrong=directory/'user.png';wrong.symlink_to(os.readlink(link))
   proposal=plan(old,new,archive);self.assertEqual(len(proposal['entries']),1)
   self.assertIn('not_attempt_capture_proof',proposal['entries'][0]['binding'])
   self.assertEqual(apply_plan(proposal)['errors'],[]);self.assertEqual(link.read_bytes(),b'original diagnostic')
   self.assertFalse(wrong.exists())
 def test_moved_relative_link_restores_same_original_bytes_and_valid_links_stay(self):
  with tempfile.TemporaryDirectory() as td:
   host=Path(td);archive=host/'ssd';archive.mkdir();target=archive/'original.pdf';target.write_bytes(b'original frozen bytes')
   old=host/'paper/data';old.mkdir(parents=True);link=old/'source.pdf';link.symlink_to(os.path.relpath(target,old))
   new=host/'paper/infrastructure/data';new.parent.mkdir();old.rename(new)
   valid=new/'valid.pdf';valid.symlink_to(target)
   self.assertFalse((new/'source.pdf').exists());before=target.read_bytes();proposal=plan(old,new,archive)
   self.assertEqual(len(proposal['entries']),1);result=apply_plan(proposal)
   self.assertEqual(result['errors'],[]);self.assertEqual((new/'source.pdf').read_bytes(),before)
   self.assertEqual(target.read_bytes(),before);self.assertEqual(os.readlink(valid),str(target))
   self.assertEqual(len(plan(old,new,archive)['entries']),0)
 def test_changed_target_and_changed_link_are_preserved(self):
  with tempfile.TemporaryDirectory() as td:
   host=Path(td);archive=host/'ssd';archive.mkdir();target=archive/'original';target.write_bytes(b'old')
   old=host/'paper/data';old.mkdir(parents=True);(old/'input').symlink_to(os.path.relpath(target,old))
   new=host/'paper/infrastructure/data';new.parent.mkdir();old.rename(new);proposal=plan(old,new,archive)
   target.write_bytes(b'changed');self.assertEqual(len(apply_plan(proposal)['errors']),1)
   proposal=plan(old,new,archive);(new/'input').unlink();(new/'input').symlink_to('user-choice')
   self.assertEqual(len(apply_plan(proposal)['errors']),1);self.assertEqual(os.readlink(new/'input'),'user-choice')

class LinkBlockedMaterials(unittest.TestCase):
 def fixture(self):
  import json
  from core.tests.test_automatic_issue_handler import AutomaticIssueTests
  from maintenance.runtime_link_migration import resume_link_blocked_materials
  case=AutomaticIssueTests();case.setUp();self.addCleanup(case.doCleanups)
  folder=case.folder;packet=json.loads((case.archive/'packet.json').read_text());packet['page_manifest']=[]
  source=case.source.read_bytes();prompt=(case.archive/'prompt.txt').read_bytes()
  for name,data in [('source.pdf',source),('visual.pdf',source),('source-context.json',prompt),('prompt.txt',prompt)]:
   (folder/name).write_bytes(data)
  (folder/'packet.json').write_text(json.dumps(packet))
  error='[Errno 2] No such file or directory: source.pdf'
  with case.cat.connect() as db:
   db.execute('UPDATE web_card_jobs SET error=?',(error,));db.execute('UPDATE card_correction_jobs SET error=?',(error,))
  return case,{'changed':[{'path':str(folder/'source.pdf')}]},resume_link_blocked_materials
 def test_local_failure_recovers_once_with_original_inputs_fifo_and_archived_receipt(self):
  case,result,recover=self.fixture();receipt=(case.archive/'chatgpt/attempt.json').read_bytes()
  answer=recover(case.config,result);self.assertEqual(answer['recovered'],[case.pid]);self.assertEqual(case.job()['state'],'queued')
  with case.cat.connect() as db:
   self.assertEqual(db.execute('SELECT state FROM card_correction_jobs').fetchone()[0],'ready')
   self.assertEqual(tuple(db.execute('SELECT assigned,state FROM shared_page_backlog').fetchone()),(1.0,'queued'))
  self.assertEqual((case.archive/'chatgpt/attempt.json').read_bytes(),receipt)
  self.assertEqual(recover(case.config,result)['recovered'],[])
 def test_current_unknown_receipt_blocks_recovery_without_rewrite(self):
  import json
  case,result,recover=self.fixture();folder=case.folder/'chatgpt';folder.mkdir()
  path=folder/'attempt.json';path.write_text(json.dumps({'state':'submitted'}));before=path.read_bytes()
  answer=recover(case.config,result);self.assertEqual(answer['recovered'],[]);self.assertEqual(len(answer['held']),1)
  self.assertEqual(path.read_bytes(),before);self.assertEqual(case.job()['state'],'needs_inspection')
