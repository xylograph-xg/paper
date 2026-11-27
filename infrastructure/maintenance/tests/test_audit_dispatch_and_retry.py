import json
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from correction.tests import test_card_correction_queue as fixtures
from correction import card_correction_queue as correction
from review import card_review_queue as review
from cards import web_card_queue as cards
from browser.shared_workflow_queue import backlog_dispatch
from core.services import atomic_json
from cards.web_card_inputs import digest


class DispatchRetrySafety(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.CorrectionQueue();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.catalog=self.fixture.catalog;self.config=self.fixture.config

    def retry(self):
        original,path,card=self.fixture.card();self.fixture.receipt(original,card,'rework')
        root=self.fixture.original_card_receipt(original,path)
        job=correction.enqueue_review(self.catalog,original,self.config);correction.process(self.catalog,job,self.config)
        history=root/'history'/('source-review-'+original['id'])
        packet=json.loads((history/'packet.json').read_text());packet['page_manifest']=[]
        atomic_json(root/'packet.json',packet)
        retry=root/'history'/'automatic-retry-1-1234';provider=retry/'chatgpt';provider.mkdir(parents=True)
        (provider/'response-raw.txt').write_text('Complete structurally invalid answer, unchanged.')
        (provider/'prompt-actual.txt').write_text((root/'prompt.txt').read_text())
        atomic_json(provider/'attempt.json',{'state':'response_saved','inputs':packet['input_hashes'],
            'raw_sha256':digest(provider/'response-raw.txt'),'actual_prompt_sha256':digest(provider/'prompt-actual.txt'),
            'conversation_url':'https://chatgpt.com/c/retry-synthetic'})
        atomic_json(root/'retry.json',{'state':'scheduled','external_retries':1,'retry_at':1,'history':str(retry),'input_hashes':packet['input_hashes']})
        with self.catalog.connect() as db:
            db.execute("UPDATE web_card_jobs SET state='queued',retry_at=1 WHERE paper_id=?",(job['paper_id'],))
            db.execute("UPDATE card_correction_jobs SET state='submitted' WHERE id=?",(job['id'],))
        return correction.rows(self.catalog)[0],cards.jobs(self.catalog)[0],root,path,provider

    def test_archived_authorized_retry_mirrors_ready_without_new_retry_or_science_change(self):
        job,webjob,root,path,provider=self.retry();sha=digest(path);raw=digest(provider/'response-raw.txt');ledger=digest(root/'retry.json')
        self.assertTrue(correction.resume_scheduled_retry(self.catalog,job,webjob,self.config))
        self.assertEqual(correction.rows(self.catalog)[0]['state'],'ready')
        self.assertEqual(digest(path),sha);self.assertEqual(digest(provider/'response-raw.txt'),raw);self.assertEqual(digest(root/'retry.json'),ledger)
        self.assertFalse(correction.resume_scheduled_retry(self.catalog,correction.rows(self.catalog)[0],webjob,self.config))

    def test_current_unknown_or_changed_archive_never_becomes_ready(self):
        job,webjob,root,path,provider=self.retry()
        current=root/'chatgpt';current.mkdir();atomic_json(current/'attempt.json',{'state':'submitted','send_click_started':True})
        with self.assertRaisesRegex(ValueError,'当前请求'):correction.resume_scheduled_retry(self.catalog,job,webjob,self.config)
        (current/'attempt.json').unlink();current.rmdir()
        (provider/'response-raw.txt').write_text('changed')
        with self.assertRaises(ValueError):correction.resume_scheduled_retry(self.catalog,job,webjob,self.config)
        self.assertEqual(correction.rows(self.catalog)[0]['state'],'submitted')

    def test_pause_blocks_retry_state_restoration(self):
        job,webjob,root,path,provider=self.retry()
        atomic_json(self.fixture.root/'card-correction-control.json',{'paused_by_user':True})
        self.assertFalse(correction.resume_scheduled_retry(self.catalog,job,webjob,self.config))
        self.assertEqual(correction.rows(self.catalog)[0]['state'],'submitted')

    def test_unscored_cards_minimum_and_lane_balance_precede_shared_score(self):
        self.config['web_cards']['shared_window']['backlog']={'queue_order':'paper_score'}
        self.config['web_cards']['min_reserved_pages']=8;self.config['card_review']['min_reserved_pages']=4
        entries={'c':{'state':'ready_blank'},'r':{'state':'ready_blank'},'active-review':{'state':'busy','kind':'review'}}
        heads={'c':{'lane':'cards','job_id':'card','paper_id':'card','score_order':True,'article_total_score':None},
               'r':{'lane':'review','job_id':'review','paper_id':'review','score_order':True,'article_total_score':190}}
        with patch('browser.shared_page_backlog.fixed_reservations',return_value={'cards':['c'],'review':['r'],'correction':[]}),patch('browser.shared_page_backlog.head_ready',side_effect=lambda cat,conf,target:heads.get(target)):
            allocation=backlog_dispatch(self.catalog,self.config,entries,list(entries),{'reserved_targets':['c']})
        self.assertEqual(allocation['claim_order'][0]['lane'],'cards')
        self.assertEqual(allocation['active']['review'],1)

    def test_status_counts_all_jobs_before_list_limit(self):
        job,webjob,root,path,provider=self.retry()
        with self.catalog.connect() as db:
            columns=list(job);sql='INSERT INTO card_correction_jobs('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')'
            for i in range(150):
                cloned={**job,'id':'queued'+str(i),'review_id':'synthetic-review'+str(i),'state':'queued','kind':'formatting'}
                db.execute(sql,[cloned[c] for c in columns])
        snapshot=correction.status(self.config)
        self.assertEqual(len(snapshot['jobs']),100);self.assertEqual(snapshot['local_pending'],150)

    def test_after_minimums_are_filled_article_scores_still_decide_shared_claims(self):
        self.config['web_cards']['shared_window']['backlog']={'queue_order':'paper_score'}
        self.config['web_cards']['min_reserved_pages']=8
        self.config['card_review'].update(min_reserved_pages=4,parallel_jobs=20)
        entries={**{'c'+str(i):{'state':'busy','kind':'cards'} for i in range(8)},
                 **{'r'+str(i):{'state':'busy','kind':'review'} for i in range(4)},
                 'c':{'state':'ready_blank'},'r':{'state':'ready_blank'}}
        heads={'c':{'lane':'cards','job_id':'card','paper_id':'card','score_order':True,'article_total_score':None},
               'r':{'lane':'review','job_id':'review','paper_id':'review','score_order':True,'article_total_score':190}}
        with patch('browser.shared_page_backlog.fixed_reservations',return_value={'cards':['c'],'review':['r'],'correction':[]}),patch('browser.shared_page_backlog.head_ready',side_effect=lambda cat,conf,target:heads.get(target)):
            allocation=backlog_dispatch(self.catalog,self.config,entries,list(entries),{'reserved_targets':['c']})
        self.assertEqual(allocation['claim_order'][0]['lane'],'review')
        self.assertEqual(allocation['active']['cards'],8)

    def test_history_proof_is_explicit_and_draft_or_unknown_cannot_receive_it(self):
        from browser.shared_page_health import classify
        snapshot={'target_id':'t','url':'https://chatgpt.com/','inspection_complete':True,
                  'user_texts':[],'answer_texts':[],'draft':'','attachments':0,'streaming':False}
        entry={'state':'ready_blank','never_submitted':True}
        self.assertNotIn('never_submitted_verified',classify(snapshot,entry)['evidence'])
        checked=classify(snapshot,entry,target_history_complete=True)
        self.assertTrue(checked['evidence']['never_submitted_verified'])
        for altered in ({**snapshot,'draft':'protected draft'},):
            self.assertNotIn('never_submitted_verified',classify(altered,entry,target_history_complete=True)['evidence'])
        self.assertNotIn('never_submitted_verified',classify(snapshot,{**entry,'submission_unknown':True},target_history_complete=True)['evidence'])


if __name__=='__main__':unittest.main()
