"""Preparation evidence releases only an unused lease, never retry eligibility."""
import json
from core.api import paths__WorkspacePath as Path
from core.services import atomic_json
from browser.shared_claim_recovery import recover_claims
from core.automatic_issue_handler import PREPARATION_BLOCK
from browser.tests.test_shared_page_backlog import SharedPageBacklogTests


class PreparationRecoveryTests(SharedPageBacklogTests):
    def _add_retired_evidence_claim(self):
        item=self.card()
        self.entries['retired-target']={'state':'retired_replaced'}
        with self.catalog.connect() as db:
            db.execute("INSERT INTO shared_page_backlog VALUES(?,?,?,?,1,'claimed')",(*item,'retired-target'))

    def test_never_used_blank_slot_releases_only_failed_preparation_lease(self):
        pid,old,_=self.fixture();raw=old.read_bytes()
        self.entries['t00']['never_submitted']=True
        health={'state':'checked','checked_at':100,'pages':{'t00':{'health':'healthy_blank',
            'evidence':{'checked_at':100,'never_submitted_verified':True}}}}
        result=recover_claims(self.catalog,self.entries,health,at=100)
        self.assertEqual(len(result),1);self.assertEqual(old.read_bytes(),raw)
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone()[0],'needs_inspection')

    def test_blank_slot_without_complete_history_assertion_remains_protected(self):
        _,_,_=self.fixture();self.entries['t00']['never_submitted']=True
        health={'state':'checked','checked_at':100,'pages':{'t00':{'health':'healthy_blank','evidence':{'checked_at':100}}}}
        self.assertEqual(recover_claims(self.catalog,self.entries,health,at=100),[])

    def test_archived_retired_receipt_does_not_abort_other_page_recovery(self):
        import hashlib
        pid, old, health = self.fixture()
        self._add_retired_evidence_claim()
        folder = self.root/'shared-page-repairs'/'retired'
        diagnostics = folder/'diagnostics'
        diagnostics.mkdir(parents=True)
        hashes = {}
        for name in ('health.json', 'body.txt', 'page.html', 'ledger-before.json', 'page.png'):
            (diagnostics/name).write_bytes(b'original evidence')
            hashes[name] = hashlib.sha256(b'original evidence').hexdigest()
        atomic_json(folder/'journal.json', {
            'state': 'ready', 'health': {'replace_allowed': True},
            'archive_hashes': hashes, 'old_target_id': 'retired-target',
            'record': {'_ledger_path': str(self.root/'archived-away'/'attempt.json'),
                       '_ledger_sha256': 'original-hash'}})
        before = old.read_bytes()
        released = recover_claims(self.catalog, self.entries, health, at=100)
        self.assertEqual([item['paper_id'] for item in released], [pid])
        self.assertEqual(old.read_bytes(), before)
        self.assertEqual(health['recovery_errors'][0]['stage'], 'retired_receipt_evidence')

    def test_corrupt_retired_journal_preserves_evidence_and_recovers_other_page(self):
        pid, old, health = self.fixture()
        self._add_retired_evidence_claim()
        path = self.root/'shared-page-repairs'/'corrupt'/'journal.json'
        path.parent.mkdir(parents=True)
        path.write_text('{broken original evidence')
        before = path.read_bytes()
        released = recover_claims(self.catalog, self.entries, health, at=100)
        self.assertEqual([item['paper_id'] for item in released], [pid])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(health['recovery_errors'][0]['path'], str(path.resolve()))

    def fixture(self):
        lane, jid, pid = self.correction()
        folder = self.root/'web_cards'/pid
        old = folder/'history'/'old'/'attempt.json'
        old.parent.mkdir(parents=True)
        atomic_json(old, {'target_id':'old-target','state':'needs_inspection','send_click_started':True})
        saved = self.root/'web_cards'/'other'/'chatgpt'/'attempt.json'
        saved.parent.mkdir(parents=True)
        atomic_json(saved, {'target_id':'t00','state':'response_saved','raw_sha256':'saved-hash',
                           'conversation_url':'https://chatgpt.com/c/original'})
        with self.catalog.connect() as db:
            db.execute("INSERT INTO shared_page_backlog VALUES(?,?,?,?,?,'claimed')", (lane,jid,pid,'t00',1))
            db.execute("INSERT INTO web_page_queue VALUES(?,?,'failed',?,?)", (pid,'t00',1,PREPARATION_BLOCK.removeprefix('材料准备：')))
            db.execute("UPDATE web_card_jobs SET state='needs_inspection',error=? WHERE paper_id=?", (PREPARATION_BLOCK,pid))
            db.execute("UPDATE card_correction_jobs SET state='needs_user',error=? WHERE id=?", (PREPARATION_BLOCK,jid))
        self.entries['t00'].update(raw_sha256='saved-hash',conversation_url='https://chatgpt.com/c/original')
        health={'state':'checked','checked_at':100,'pages':{'t00':{'health':'completed_saved','matched_record_path':str(saved)}}}
        return pid, old, health

    def test_preparation_lease_release_keeps_old_unknown_receipt_and_source_state(self):
        pid, old, health=self.fixture();before=old.read_bytes()
        result=recover_claims(self.catalog,self.entries,health,at=100)
        self.assertEqual(len(result),1);self.assertEqual(old.read_bytes(),before)
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM web_card_jobs WHERE paper_id=?',(pid,)).fetchone()[0],'needs_inspection')
            self.assertEqual(db.execute("SELECT count(*) FROM shared_page_backlog WHERE state='claimed'").fetchone()[0],0)

    def test_old_use_of_same_target_prevents_release(self):
        _,old,health=self.fixture()
        record=json.loads(old.read_text());record['target_id']='t00';atomic_json(old,record)
        self.assertEqual(recover_claims(self.catalog,self.entries,health,at=100),[])

    def test_absence_of_history_without_preparation_failure_proof_never_releases(self):
        pid,old,health=self.fixture();old.unlink()
        with self.catalog.connect() as db:db.execute("UPDATE web_page_queue SET state='waiting' WHERE paper_id=?",(pid,))
        self.assertEqual(recover_claims(self.catalog,self.entries,health,at=100),[])

    def test_card_producer_failure_releases_unused_lease_without_granting_retry(self):
        item=self.card(target='t00',material_state='failed',state='needs_inspection')
        saved=self.root/'web_cards'/'other'/'chatgpt'/'attempt.json';saved.parent.mkdir(parents=True)
        atomic_json(saved,{'state':'response_saved','target_id':'t00','raw_sha256':'saved-hash','conversation_url':'https://chatgpt.com/c/original'})
        with self.catalog.connect() as db:
            db.execute("INSERT INTO shared_page_backlog VALUES(?,?,?,?,1,'claimed')",(*item,'t00'))
            db.execute("UPDATE web_card_jobs SET error='材料准备：synthetic deterministic preparation failure' WHERE paper_id=?",(item[2],))
            db.execute("UPDATE web_page_queue SET error='synthetic deterministic preparation failure' WHERE paper_id=?",(item[2],))
        self.entries['t00'].update(raw_sha256='saved-hash',conversation_url='https://chatgpt.com/c/original')
        health={'state':'checked','checked_at':100,'pages':{'t00':{'health':'completed_saved','matched_record_path':str(saved)}}}
        self.assertEqual(len(recover_claims(self.catalog,self.entries,health,at=100)),1)
        with self.catalog.connect() as db:self.assertEqual(db.execute('SELECT state FROM web_card_jobs WHERE paper_id=?',(item[2],)).fetchone()[0],'needs_inspection')

    def test_current_attempt_or_stale_health_prevents_release(self):
        pid,_,health=self.fixture()
        current=self.root/'web_cards'/pid/'chatgpt'/'attempt.json';current.parent.mkdir()
        atomic_json(current,{'target_id':'other','state':'ready','send_click_started':False})
        self.assertEqual(recover_claims(self.catalog,self.entries,health,at=100),[])
        current.unlink()
        self.assertEqual(recover_claims(self.catalog,self.entries,health,at=161),[])

    def test_review_preparation_failure_releases_only_with_input_and_live_page_proof(self):
        import hashlib
        lane,jid,pid=self.review(target='t00')
        with self.catalog.connect() as db:
            folder=self.root/'card_reviews'/pid/jid
            db.execute('UPDATE card_review_jobs SET folder=? WHERE id=?',(str(folder),jid))
            db.execute("UPDATE card_review_jobs SET state='needs_user',error='deterministic preparation failure',source_sha256='original' WHERE id=?",(jid,))
            db.execute("UPDATE shared_page_backlog SET state='claimed' WHERE job_id=?",(jid,))
        folder.mkdir(parents=True);(folder/'prepare.log').write_text('preparation')
        source=self.root/'input';source.mkdir();(folder/'source.pdf').write_bytes(b'bound source')
        atomic_json(source/'packet.json',{'source_original_sha256':'original','input_hashes':{'source.pdf':hashlib.sha256(b'bound source').hexdigest()}})
        atomic_json(folder/'visual-request.json',{'output_folder':str(folder),'input_folder':str(source)})
        saved=self.root/'ended'/'attempt.json';saved.parent.mkdir()
        atomic_json(saved,{'target_id':'t00','state':'response_saved','raw_sha256':'saved','conversation_url':'https://chatgpt.com/c/other'})
        self.entries['t00'].update(raw_sha256='saved',conversation_url='https://chatgpt.com/c/other')
        health={'state':'checked','checked_at':100,'pages':{'t00':{'health':'completed_saved','matched_record_path':str(saved)}}}
        atomic_json(folder/'packet.json',{})
        self.assertEqual(recover_claims(self.catalog,self.entries,health,at=100),[])
        (folder/'packet.json').unlink()
        atomic_json(folder/'attempt.json',{'state':'needs_inspection','target_id':'t00','send_click_started':True})
        self.assertEqual(recover_claims(self.catalog,self.entries,health,at=100),[])
        (folder/'attempt.json').unlink()
        self.assertEqual(len(recover_claims(self.catalog,self.entries,health,at=100)),1)
