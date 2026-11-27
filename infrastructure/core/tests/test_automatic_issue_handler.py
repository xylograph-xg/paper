import json
import tempfile
import unittest
from unittest.mock import patch
from core.api import paths__WorkspacePath as Path
from core.catalog import Catalog
from cards import web_card_queue as cards; from correction import card_correction_queue as corrections
from browser.shared_page_backlog import install as install_backlog
from browser.web_page_queue import install as install_materials
from cards.web_card_inputs import digest
from cards.web_card_rework import archived_receipts, submission_history
from core.automatic_issue_handler import recover_preparation, PREPARATION_BLOCK, disposition


class AutomaticIssueTests(unittest.TestCase):
    def test_normalization_keeps_existing_failure_reason_for_both_lanes(self):
        from review.card_review_queue import install as install_reviews
        from core.automatic_issue_handler import normalize_needs_user
        install_reviews(self.cat)
        reason='自动终止：' * 145 + '原始材料阻塞；不能删除'
        with self.cat.connect() as db:
            db.execute("INSERT INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,title,state,folder,result,error,updated) VALUES('r-stable',?,'card','source','test','needs_user',?,'{}',?,'original')",
                       (self.pid,str(self.root/'review'),reason))
            db.execute("UPDATE card_correction_jobs SET error=? WHERE id='c1'",(reason,))
        config={**self.config,'review_standard':{'no_user_state':True}}
        for _ in range(3):
            normalize_needs_user(self.cat,config)
            with self.cat.connect() as db:
                self.assertEqual(db.execute("SELECT error,result FROM card_review_jobs WHERE id='r-stable'").fetchone()[:],(reason,'{}'))
                self.assertEqual(db.execute("SELECT error,fifo_at FROM card_correction_jobs WHERE id='c1'").fetchone()[:],(reason,1))
                # Another guarded workflow can return a task to needs_user.
                db.execute("UPDATE card_review_jobs SET state='needs_user' WHERE id='r-stable'")
                db.execute("UPDATE card_correction_jobs SET state='needs_user' WHERE id='c1'")

    def test_loaded_repair_revision_changes_check_key_without_disk_edit(self):
        from core.automatic_issue_handler import review_preparation_fingerprint
        from review.card_review_repair import repair
        with patch.object(repair,'recovery_revision','legacy'):
            old=review_preparation_fingerprint()
        self.assertNotEqual(old,review_preparation_fingerprint())

    def test_retained_material_check_is_rechecked_once_after_implementation_change(self):
        from review.tests.test_card_review_repair import MaterialRepair
        from core import automatic_issue_handler as handler
        fixture=MaterialRepair();fixture.setUp();self.addCleanup(fixture.doCleanups)
        cards.install(fixture.catalog);corrections.install(fixture.catalog)
        config={**fixture.config,'automatic_issue_handling':{'enabled':True}}
        with patch('core.workflow_recovery.run_once'),patch('core.action_inbox.snapshot',return_value={'items':[]}), \
                patch.object(handler,'review_preparation_fingerprint',return_value='before') as version, \
                patch('review.card_review_repair.repair',side_effect=ValueError('Interrupted candidate')) as repair:
            handler.run_once(fixture.catalog,config);self.assertEqual(repair.call_count,1)
            handler.run_once(fixture.catalog,config);self.assertEqual(repair.call_count,1)
            version.return_value='after';handler.run_once(fixture.catalog,config)
            self.assertEqual(repair.call_count,2)
            handler.run_once(fixture.catalog,config);self.assertEqual(repair.call_count,2)
        ledger=json.loads((fixture.root/'automatic-review-material-checks.json').read_text())
        self.assertEqual(len(ledger),2)
        self.assertEqual({x['preparation_version'] for x in ledger.values()},{'before','after'})
        self.assertEqual(__import__('review.card_review_queue',fromlist=['rows']).rows(fixture.catalog)[0],fixture.job)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name);self.cat = Catalog(self.root/'catalog.sqlite3')
        self.pid = self.cat.upsert({'title':'synthetic'})
        self.source = self.root/'source.pdf';self.source.write_bytes(b'synthetic original')
        self.old = self.root/'card.json';self.old.write_text('{}')
        self.backup = self.root/'backup';self.backup.mkdir();(self.backup/'card.json').write_text('{}')
        self.cat.update(self.pid, card_path=str(self.old),asset_hash=digest(self.source),asset_path=str(self.source))
        self.report = self.root/'feedback.json';self.report.write_text('{}')
        self.folder = self.root/'web_cards'/self.pid
        self.archive = self.folder/'history/source-review-r1';self.archive.mkdir(parents=True)
        prompt = self.archive/'prompt.txt';prompt.write_text('source only')
        packet={'source_original_sha256':digest(self.source),'input_hashes':{'prompt.txt':digest(prompt),
            'source.pdf':digest(self.source),'visual.pdf':digest(self.source),'source-context.json':digest(prompt)}}
        (self.archive/'packet.json').write_text(json.dumps(packet))
        (self.archive/'reset-intent.json').write_text(json.dumps({'review_id':'r1','job':{'paper_id':self.pid}}))
        a = self.archive/'chatgpt';a.mkdir();(a/'prompt-actual.txt').write_text(prompt.read_text());(a/'response-raw.txt').write_text('old answer')
        (a/'attempt.json').write_text(json.dumps({'state':'response_saved','raw_sha256':digest(a/'response-raw.txt'),
            'actual_prompt_sha256':digest(a/'prompt-actual.txt'),'inputs':packet['input_hashes'],'conversation_url':'https://chatgpt.com/c/synthetic'}))
        self.cat.event(self.pid,'card_review_rework',{'review_id':'r1','number':1})
        cards.install(self.cat);corrections.install(self.cat);install_materials(self.cat);install_backlog(self.cat)
        record={'kind':'source_review','review_id':'r1','old_card_path':str(self.old),'old_sha256':digest(self.old),
                'backup':str(self.backup),'review_report':str(self.report),'review_report_sha256':digest(self.report),'correction_id':'c1'}
        task = {'correction_id':'c1','review':{'id':'r1'}}
        task_path = self.root/'task.json';task_path.write_text(json.dumps(task))
        with self.cat.connect() as db:
            db.execute('INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,state,error,updated) VALUES(?,?,?,?,?,?,?)',
                (self.pid,digest(self.source),'synthetic',json.dumps({'rework':record}),'needs_inspection',PREPARATION_BLOCK,'now'))
            db.execute("INSERT INTO web_page_queue VALUES(?,?,'failed',1,?)",(self.pid,'t1',PREPARATION_BLOCK.removeprefix('材料准备：')))
            db.execute("INSERT INTO card_correction_jobs(id,paper_id,review_id,kind,state,title,card_sha256,source_sha256,payload,folder,task_sha256,fifo_at,queued_at,error,created,updated) VALUES(?,?,?,'source_rework','needs_user',?,?,?,?,?,?,1,1,?,'now','now')",
                ('c1',self.pid,'r1','synthetic',digest(self.old),digest(self.source),json.dumps(task),str(self.root),digest(task_path),PREPARATION_BLOCK))
            db.execute("INSERT INTO shared_page_backlog VALUES('correction','c1',?,'t1',1,'claimed')",(self.pid,))
        self.config={'catalog_path':str(self.cat.path),'web_cards':{'enabled':True},'card_correction':{'enabled':True}}

    def test_local_check_age_is_retained_without_claiming_browser_or_resolution(self):
        from core.automatic_issue_handler import run_once
        from core.services import atomic_json
        import time
        item={'id':'job:'+self.pid,'title':'synthetic','action':'原请求待核对','source':str(self.folder)}
        first=time.time()-90000
        atomic_json(self.root/'automatic-issue-status.json',{'items':[{'id':item['id'],'first_observed_at':first}]})
        config={**self.config,'automatic_issue_handling':{'enabled':True}}
        with patch('core.action_inbox.snapshot',return_value={'items':[item]}), \
             patch('core.automatic_issue_handler.recover_preparation',return_value=None), \
             patch('review.card_review_queue.enabled',return_value=False), \
             patch('correction.card_correction_queue.enabled',return_value=False):
            report=run_once(self.cat,config)
        checked=report['items'][0]
        self.assertEqual(checked['first_observed_at'],first)
        self.assertEqual(checked['resolution_state'],'retained')
        self.assertEqual(checked['evidence_scope'],'local_receipt_history')
        self.assertFalse(checked['browser_checked'])
        self.assertEqual(report['retained_over_24h'],1)

    def job(self):
        with self.cat.connect() as db:return dict(db.execute('SELECT * FROM web_card_jobs').fetchone())

    def test_complete_authorized_archive_is_exempt(self):
        self.assertEqual(len(archived_receipts(self.cat,self.job())),1)
        self.assertTrue(submission_history(self.cat,self.job(),self.folder).allowed)

    def test_unknown_nested_receipt_is_never_exempt(self):
        p=self.archive/'chatgpt/history/old';p.mkdir(parents=True)
        (p/'attempt.json').write_text(json.dumps({'state':'deferred'}))
        with self.assertRaises(ValueError):archived_receipts(self.cat,self.job())

    def test_exact_legacy_capacity_guard_is_exempt_without_rewriting_receipt(self):
        packet=json.loads((self.archive/'packet.json').read_text())
        p=self.archive/'chatgpt/history/legacy';p.mkdir(parents=True)
        path=p/'attempt.json';path.write_text(json.dumps({'provider':'chatgpt','state':'deferred',
            'created':1,'finished':2,'inputs':packet['input_hashes'],
            'error':'DeferredWeb: chatgpt 已达20页，等待本任务页收取/关闭'}))
        before=path.read_bytes()
        self.assertEqual(len(archived_receipts(self.cat,self.job())),2)
        self.assertEqual(path.read_bytes(),before)
        record=json.loads(path.read_text());record['target_id']='unknown'
        path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):archived_receipts(self.cat,self.job())

    def test_capacity_deferral_requires_exact_error_and_no_other_artifacts(self):
        from cards.web_card_rework import archived_capacity_deferral
        packet=json.loads((self.archive/'packet.json').read_text())
        p=self.archive/'chatgpt/history/legacy';p.mkdir(parents=True)
        path=p/'attempt.json';path.write_text('{}')
        record={'provider':'chatgpt','state':'deferred','created':1,'finished':2,
            'inputs':packet['input_hashes'],'error':'DeferredWeb: chatgpt 已达20页，等待本任务页收取/关闭'}
        for update in ({'error':'timeout'},{'send_click_started':True},{'finished':20},{'inputs':{}}):
            self.assertFalse(archived_capacity_deferral(path,{**record,**update},packet))
        (p/'response-raw.txt').write_text('unknown')
        self.assertFalse(archived_capacity_deferral(path,record,packet))

    def test_new_active_receipt_still_blocks(self):
        p=self.folder/'chatgpt';p.mkdir();(p/'attempt.json').write_text(json.dumps({'state':'submitted'}))
        self.assertFalse(submission_history(self.cat,self.job(),self.folder).allowed)
        with self.assertRaises(ValueError):recover_preparation(self.cat,self.job(),self.config)

    def test_recovery_releases_only_proven_preparation_claim(self):
        old_bytes=(self.archive/'chatgpt/attempt.json').read_bytes()
        result=recover_preparation(self.cat,self.job(),self.config)
        self.assertEqual(result['state'],'queued')
        self.assertEqual(self.job()['state'],'queued')
        with self.cat.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM shared_page_backlog').fetchone()[0],'queued')
            self.assertEqual(db.execute('SELECT state FROM web_page_queue').fetchone()[0],'waiting')
        self.assertEqual(old_bytes,(self.archive/'chatgpt/attempt.json').read_bytes())

    def test_ready_archive_dispatch_recovers_without_new_attempt_or_fifo_changes(self):
        from core.automatic_issue_handler import recover_archived_dispatch, ARCHIVE_BLOCK
        (self.folder/'packet.json').write_bytes((self.archive/'packet.json').read_bytes())
        with self.cat.connect() as db:
            db.execute('UPDATE web_card_jobs SET error=?',(ARCHIVE_BLOCK,))
            db.execute("UPDATE web_page_queue SET state='ready',error=''")
            db.execute('UPDATE card_correction_jobs SET error=?',(ARCHIVE_BLOCK,))
        old=(self.archive/'chatgpt/attempt.json').read_bytes()
        with patch('cards.web_card_retry.frozen_inputs'):
            result=recover_archived_dispatch(self.cat,self.job(),self.config)
        self.assertEqual(result['state'],'queued')
        with self.cat.connect() as db:
            correction=db.execute('SELECT * FROM card_correction_jobs').fetchone()
            self.assertEqual(correction['state'],'ready');self.assertEqual(correction['fifo_at'],1)
            self.assertEqual(db.execute('SELECT assigned FROM web_page_queue').fetchone()[0],1)
        self.assertFalse(list(self.folder.glob('*/attempt.json')))
        self.assertEqual(old,(self.archive/'chatgpt/attempt.json').read_bytes())

    def test_changed_card_or_human_decision_blocks(self):
        self.cat.event(self.pid,'human_decision',{'keep':True})
        with self.assertRaises(ValueError):recover_preparation(self.cat,self.job(),self.config)

    def test_access_and_scientific_ambiguity_keep_protection(self):
        self.assertEqual(disposition({'id':'channel:chatgpt','action':'登录验证'})[0],'等待访问恢复')
        self.assertEqual(disposition({'id':'review:r1','action':'原文存在冲突或歧义'})[0],'自动保留')
