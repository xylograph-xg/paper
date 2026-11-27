"""Old-owner recovery cannot adopt an active or unknown original request."""
import os
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from core.services import atomic_json
from browser.shared_claim_recovery import recover_claims
from browser.tests.test_shared_page_backlog import SharedPageBacklogTests


class AbandonedUnsentClaims(SharedPageBacklogTests):
    def receipt_fixture(self,lane):
        item=self.card(target='t00') if lane=='cards' else self.correction() if lane=='correction' else self.review(state='submitting',target='t00')
        lane,jid,pid=item
        with self.catalog.connect() as db:
            if lane=='review':
                folder=Path(db.execute('SELECT folder FROM card_review_jobs WHERE id=?',(jid,)).fetchone()[0])
                db.execute("UPDATE shared_page_backlog SET state='claimed' WHERE job_id=?",(jid,))
            else:
                folder=self.root/'web_cards'/pid
                db.execute("UPDATE web_card_jobs SET state='preparing' WHERE paper_id=?",(pid,))
                if lane=='correction':
                    db.execute("INSERT INTO web_page_queue VALUES(?,?,'ready',1,'')",(pid,'t00'))
                    db.execute("UPDATE card_correction_jobs SET state='submitting' WHERE id=?",(jid,))
                db.execute("INSERT INTO shared_page_backlog VALUES(?,?,?,?,1,'claimed')",(lane,jid,pid,'t00'))
        current=folder/('attempt.json' if lane=='review' else 'chatgpt/attempt.json');current.parent.mkdir(parents=True,exist_ok=True)
        old=folder/'history/old/attempt.json';old.parent.mkdir(parents=True)
        atomic_json(old,{'state':'response_saved','target_id':'t00','conversation_url':'https://chatgpt.com/c/old','raw_sha256':'old'})
        atomic_json(current,{'state':'ready','send_click_started':False,'target_id':'t00','created':100,
            'owner_pid':99999999,'owner_token':'old','review_id':jid if lane=='review' else None})
        atomic_json(self.root/'web-card-service.json',{'pid':os.getpid(),'token':'new'})
        self.entries['t00']['state']='ready_blank'
        health={'state':'checked','checked_at':100,'pages':{'t00':{'health':'healthy_blank',
            'evidence':{'checked_at':300,'completed_history_paths':[str(current.resolve()),str(old.resolve())]}}}}
        return item,current,health

    def test_all_three_lanes_restore_only_dead_owner_explicit_unsent_preparation(self):
        for lane in ('cards','review','correction'):
            with self.subTest(lane=lane):
                item,path,health=self.receipt_fixture(lane)
                with patch('browser.shared_claim_recovery.os.kill',side_effect=ProcessLookupError):
                    result=recover_claims(self.catalog,self.entries,health,at=300)
                self.assertEqual(len(result),1);self.assertEqual(result[0]['reason'],'dead_owner_explicit_unsent')
                self.assertFalse(path.exists())
                with self.catalog.connect() as db:
                    self.assertEqual(db.execute('SELECT state FROM shared_page_backlog WHERE lane=? AND job_id=?',item[:2]).fetchone()[0],'queued')
                # Free the synthetic target before the next independent lane.
                with self.catalog.connect() as db:db.execute('DELETE FROM shared_page_backlog')

    def test_live_owner_and_started_send_never_requeue(self):
        _,path,health=self.receipt_fixture('cards')
        with patch('browser.shared_claim_recovery.os.kill',return_value=None):
            self.assertEqual(recover_claims(self.catalog,self.entries,health,at=300),[])
        import json
        record=json.loads(path.read_text());record['send_click_started']=True;atomic_json(path,record)
        with patch('browser.shared_claim_recovery.os.kill',side_effect=ProcessLookupError):
            self.assertEqual(recover_claims(self.catalog,self.entries,health,at=300),[])

    def test_missing_owner_or_stale_single_page_evidence_never_requeue(self):
        _,path,health=self.receipt_fixture('cards')
        import json
        record=json.loads(path.read_text());record.pop('owner_pid');atomic_json(path,record)
        self.assertEqual(recover_claims(self.catalog,self.entries,health,at=300),[])
        record['owner_pid']=99999999;atomic_json(path,record)
        health['pages']['t00']['evidence']['checked_at']=100
        self.assertEqual(recover_claims(self.catalog,self.entries,health,at=300),[])

    def test_unsent_review_technical_failure_recovers_old_claim(self):
        item,path,health=self.receipt_fixture('review')
        with self.catalog.connect() as db:
            db.execute("UPDATE card_review_jobs SET state='needs_user',error='附件上传失败',result='{}' WHERE id=?",(item[1],))
        with patch('browser.shared_claim_recovery.os.kill',side_effect=ProcessLookupError):
            result=recover_claims(self.catalog,self.entries,health,at=300)
        self.assertEqual(result[0]['reason'],'dead_owner_explicit_unsent')
        self.assertFalse(path.exists())
