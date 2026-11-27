import json
import tempfile
import unittest
from contextlib import nullcontext
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

from core.catalog import Catalog
from review.card_review_lane import ReviewLane
from review import card_review_queue as queue
from core.services import atomic_json


class ReviewLaneTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.config={'catalog_path':str(self.root/'catalog.db'),'card_review':{'enabled':True,'parallel_jobs':4},
            'web_cards':{'enabled':True,'upload_settle_timeout_seconds':180}}
        self.catalog=Catalog(self.config['catalog_path']);queue.install(self.catalog)
        self.lane=ReviewLane.__new__(ReviewLane);self.lane.config=self.config;self.lane.catalog=self.catalog
        self.router=Mock();self.router.choose.return_value='chatgpt'
        self.entries={'target':{'state':'ready_blank'}};self.page=Mock();self.page.url='https://chatgpt.com/'
        empty=Mock();empty.count.return_value=0;self.page.locator.return_value=empty
        self.job={'id':'review-id','paper_id':'paper-id','card_sha256':'hash','source_sha256':'source','priority':90,
            'novelty':80,'title':'Synthetic','state':'ready','folder':str(self.root/'review')}
        folder=Path(self.job['folder']);folder.mkdir();(folder/'prompt-actual.txt').write_text('Synthetic review prompt')
        self.packet={'input_hashes':{'source.pdf':'source-hash'},'actual_prompt_sha256':'prompt-hash','upload_bundle':{'zip_path':'bundle.zip'}}
        atomic_json(folder/'packet.json',{'review_images_version':1})
        with self.catalog.connect() as db:
            db.execute('INSERT INTO card_review_jobs(id,paper_id,card_sha256,source_sha256,priority,novelty,title,state,folder,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',
                tuple(self.job[k] for k in ('id','paper_id','card_sha256','source_sha256','priority','novelty','title','state','folder'))+('now',))

    def state(self):return queue.rows(self.catalog)[0]['state']

    def test_historical_review_never_reads_or_overwrites_a_card_owned_page(self):
        path=Path(self.job['folder'])/'attempt.json'
        atomic_json(path,{'state':'needs_inspection','target_id':'target'})
        queue.update(self.catalog,self.job['id'],'needs_user')
        for entry in ({'state':'busy','kind':'cards','active_paper_id':'different'},
                      {'state':'busy','kind':'review','review_id':'different'},
                      {'state':'ready_blank'}):
            with self.subTest(entry=entry):
                self.entries['target']=dict(entry)
                before=path.read_bytes()
                with patch('browser.web_card_transport.require_no_verification') as inspect:
                    self.lane.collect({'target':self.page},self.entries,{},self.router,lambda **kw:nullcontext(),lambda:False)
                inspect.assert_not_called()
                self.assertEqual(self.entries['target'],entry)
                self.assertEqual(path.read_bytes(),before)

    def test_automatic_handler_collects_original_pending_receipt_without_sending(self):
        from cards.web_card_inputs import digest
        from browser.web_card_pool import USER
        from web_gpt.core import ANSWER, STOP_BUTTON
        self.config['automatic_issue_handling']={'enabled':True}
        folder=Path(self.job['folder']);path=folder/'attempt.json'
        self.page.url='https://chatgpt.com/c/original-review'
        atomic_json(path,{'state':'needs_inspection','target_id':'target',
            'actual_prompt_sha256':digest(folder/'prompt-actual.txt'),'conversation_url':self.page.url})
        queue.update(self.catalog,self.job['id'],'needs_user','原回执待核对')
        self.entries['target']={'state':'needs_inspection','kind':'review','review_id':self.job['id']}
        users=Mock();users.count.return_value=1;users.first.evaluate.return_value=[(folder/'prompt-actual.txt').read_text()]
        stops=Mock();stops.count.return_value=0
        answers=Mock()
        self.page.locator.side_effect=lambda selector: {USER:users,STOP_BUTTON:stops,ANSWER:answers}[selector]
        with patch('browser.web_card_transport.require_no_verification'), \
             patch('browser.web_card_transport.collect_owned',return_value='complete original response'), \
             patch('web_gpt.core._message_text',return_value='complete original response'), \
             patch('review.card_review_queue.check_packet'), \
             patch('browser.web_card_transport.submit_gpt_background') as send:
            self.lane.collect({'target':self.page},self.entries,{'target':{'complete':True}},
                self.router,lambda **kw:nullcontext(),lambda:False)
        self.assertEqual(self.state(),'response_saved')
        self.assertEqual(json.loads(path.read_text())['state'],'response_saved')
        self.assertEqual((folder/'response-raw.txt').read_text(),'complete original response')
        send.assert_not_called();self.page.goto.assert_not_called()

    def test_pool_cas_conflict_prevents_review_navigation(self):
        from browser.shared_pool_store import PoolConflict
        with self.dependencies(),patch('browser.web_card_transport.submit_gpt_background') as send:
            persist=Mock(side_effect=PoolConflict('changed target'))
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,
                lambda **kw:nullcontext(),lambda:False,persist_pool=persist))
        self.page.goto.assert_not_called();send.assert_not_called()

    def test_old_unsent_packet_is_retained_without_repeating_the_preparation_cycle(self):
        folder=Path(self.job['folder']);atomic_json(folder/'packet.json',{})
        frozen=(folder/'packet.json').read_bytes()
        with self.dependencies(),patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,lambda **kw:nullcontext(),lambda:False))
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,lambda **kw:nullcontext(),lambda:False))
        self.assertEqual(self.state(),'needs_user');send.assert_not_called()
        self.assertEqual((folder/'packet.json').read_bytes(),frozen)
        self.assertFalse((folder/'attempt.json').exists())

    def test_failed_navigation_cannot_keep_previous_saved_response_as_current_request(self):
        original={'state':'ready','slot':3,'kind':'cards','paper_id':'old-paper',
                  'raw_path':'old-reply','raw_sha256':'old-hash','conversation_url':'https://chatgpt.com/c/old'}
        self.entries['target']=dict(original)
        self.page.goto.side_effect=RuntimeError('navigation interrupted before upload')
        with self.dependencies(),patch('browser.shared_window_owner.require_reusable'),patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,lambda **kw:nullcontext(),lambda:False))
        entry=self.entries['target']
        self.assertEqual(entry['state'],'needs_inspection');self.assertEqual(entry['review_id'],self.job['id'])
        self.assertEqual(entry['previous_saved_response']['raw_path'],'old-reply')
        self.assertNotIn('raw_sha256',entry);self.assertNotIn('conversation_url',entry)
        a=json.loads((Path(self.job['folder'])/'attempt.json').read_text())
        self.assertEqual(a['state'],'not_sent');self.assertFalse(a['send_click_started'])
        send.assert_not_called();self.page.close.assert_not_called()

    def dependencies(self):
        from contextlib import ExitStack
        stack=ExitStack()
        for name in ['current','check_packet']:stack.enter_context(patch('review.card_review_queue.'+name,return_value=self.packet))
        stack.enter_context(patch('browser.page_retirement.may_retire',return_value=True))
        stack.enter_context(patch('browser.gpt_model_policy.configure_session',return_value=SimpleNamespace(settings={'model':'GPT-6','effort':'High'})))
        stack.enter_context(patch('web_gpt.core.wait_prompt_box',return_value=Mock()))
        stack.enter_context(patch('browser.reusable_home.snapshot_page',return_value={
            'inspection_complete':True,'url':'https://chatgpt.com/c/saved','draft':'',
            'composer_available':True}))
        stack.enter_context(patch('web_gpt.core._box_text',return_value=''))
        stack.enter_context(patch('browser.web_card_pool.record_channel_failure'))
        return stack

    def test_submit_uses_timeout_records_pre_click_receipt_and_does_not_collect_synchronously(self):
        def send(session,prompt,files,**options):
            a=json.loads((Path(self.job['folder'])/'attempt.json').read_text())
            self.assertFalse(a['send_click_started']);self.assertEqual(a['state'],'ready')
            self.assertEqual(options['upload_timeout'],180000)
            options['on_before_send']();self.page.url='https://chatgpt.com/c/synthetic-review'
            return 0
        with self.dependencies(),patch('browser.web_card_transport.submit_gpt_background',side_effect=send) as send:
            self.assertTrue(self.lane.submit({'target':self.page},self.entries,0,self.router,lambda **kw:nullcontext(),lambda:False))
            send.assert_called_once()
        a=json.loads((Path(self.job['folder'])/'attempt.json').read_text())
        self.assertEqual(a['state'],'submitted');self.assertTrue(a['send_click_started'])
        self.assertEqual(self.entries['target']['kind'],'review');self.assertEqual(self.state(),'submitted')

    def test_existing_unknown_receipt_is_never_overwritten_or_sent_again(self):
        path=Path(self.job['folder'])/'attempt.json';original={'state':'needs_inspection','target_id':'old','raw_sha256':'keep'}
        atomic_json(path,original)
        with patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,lambda **kw:nullcontext(),lambda:False))
            send.assert_not_called()
        self.assertEqual(json.loads(path.read_text()),original);self.page.goto.assert_not_called()

    def test_paused_or_full_lane_cannot_claim_or_send(self):
        with patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,4,self.router,lambda **kw:nullcontext(),lambda:False))
            atomic_json(self.root/'card-review-control.json',{'paused_by_user':True})
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,lambda **kw:nullcontext(),lambda:False))
            send.assert_not_called()
        self.assertEqual(self.state(),'ready');self.page.goto.assert_not_called()

    def test_uncertain_send_exception_preserves_original_page_and_blocks_repeat(self):
        def send(session,prompt,files,**options):options['on_before_send']();raise RuntimeError('Unknown receipt')
        with self.dependencies(),patch('browser.web_card_transport.submit_gpt_background',side_effect=send):
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,lambda **kw:nullcontext(),lambda:False))
        a=json.loads((Path(self.job['folder'])/'attempt.json').read_text())
        self.assertTrue(a['send_click_started']);self.assertEqual(a['state'],'needs_inspection')
        self.assertEqual(self.entries['target']['state'],'needs_inspection');self.assertEqual(self.state(),'needs_user')
        self.page.close.assert_not_called()

    def test_page_with_changed_saved_reply_or_draft_is_never_navigated(self):
        with self.dependencies(),patch('browser.page_retirement.may_retire',return_value=False),patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,lambda **kw:nullcontext(),lambda:False))
            send.assert_not_called()
        self.page.goto.assert_not_called();self.page.close.assert_not_called()

    def test_collect_original_reply_and_observer_saved_reply_without_resending(self):
        from cards.web_card_inputs import digest
        from browser.web_card_pool import USER
        from web_gpt.core import ANSWER,STOP_BUTTON
        for observer_saved in (False,True):
            with self.subTest(observer_saved=observer_saved):
                folder=Path(self.job['folder']);raw='Complete synthetic review response';self.page.url='https://chatgpt.com/c/review'
                users=Mock();users.count.return_value=1;users.first.evaluate.return_value=[(folder/'prompt-actual.txt').read_text()]
                answers=Mock();answers.count.return_value=1;stops=Mock();stops.count.return_value=0
                self.page.locator.side_effect=lambda s:{USER:users,ANSWER:answers,STOP_BUTTON:stops}[s]
                a={'state':'response_saved' if observer_saved else 'submitted','target_id':'target',
                    'actual_prompt_sha256':digest(folder/'prompt-actual.txt'),'conversation_url':self.page.url}
                if observer_saved:
                    (folder/'response-raw.txt').write_text(raw);a['raw_sha256']=digest(folder/'response-raw.txt')
                atomic_json(folder/'attempt.json',a);queue.update(self.catalog,self.job['id'],'submitted')
                self.entries['target']={'state':'busy','kind':'review','review_id':self.job['id']}
                with patch('browser.web_card_transport.require_no_verification'),patch('review.card_review_queue.check_packet'),patch('web_gpt.core._message_text',return_value=raw),patch('browser.web_card_transport.collect_owned',return_value=raw) as collect:
                    self.assertEqual(self.lane.collect({'target':self.page},self.entries,{'target':{'complete':True}},self.router,lambda **kw:nullcontext(),lambda:False),0)
                    self.assertEqual(collect.call_count,0 if observer_saved else 1)
                self.assertEqual(self.state(),'response_saved');self.assertEqual(self.entries['target']['state'],'ready')
                self.assertEqual((folder/'response-raw.txt').read_text(),raw)
                self.page.goto.assert_not_called();self.page.close.assert_not_called()

    def test_observer_review_material_identity_and_duplicate_url_guards(self):
        import hashlib
        from browser.web_page_observer import response_identity
        rid='a'*24;prompt='Only synthetic data card-review-'+rid
        a={'review_id':rid,'target_id':'own','actual_prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
        url='https://chatgpt.com/c/own'
        self.assertTrue(response_identity(a,prompt,prompt,url,[url],'own'))
        self.assertFalse(response_identity(a,prompt,prompt,url,[url,url],'own'))
        self.assertFalse(response_identity(a,prompt,prompt.replace(rid,'b'*24),url,[url],'own'))
        self.assertFalse(response_identity(a,prompt,prompt,url,[url],'other'))

    def backlog_fixture(self,target='target'):
        from browser.shared_page_backlog import install
        install(self.catalog)
        with self.catalog.connect() as db:
            db.execute('INSERT INTO shared_page_backlog(lane,job_id,paper_id,target_id,assigned,state) VALUES(?,?,?,?,?,?)',
                ('review',self.job['id'],self.job['paper_id'],target,10,'queued'))
        self.config['web_cards']['shared_window']={'enabled':True,'backlog':{'enabled':True}}

    def backlog_binding(self):
        with self.catalog.connect() as db:
            row=db.execute('SELECT * FROM shared_page_backlog WHERE lane=? AND job_id=?',('review',self.job['id'])).fetchone()
            return dict(row) if row else None

    def backlog_options(self):
        return dict(job_id=self.job['id'],assigned_target_id='target',use_backlog=True,allowed_targets={'target'})

    def test_assigned_review_claim_retains_exact_target_through_send(self):
        self.backlog_fixture();other=Mock();other.url='https://chatgpt.com/'
        entries={'other':{'state':'ready_blank'},**self.entries}
        def send(session,prompt,files,**options):
            self.assertEqual(self.backlog_binding()['state'],'claimed')
            self.assertEqual(self.backlog_binding()['target_id'],'target')
            options['on_before_send']();self.page.url='https://chatgpt.com/c/assigned';return 0
        with self.dependencies(),patch('browser.shared_page_backlog.check_head_binding',return_value=True),patch('browser.web_card_transport.submit_gpt_background',side_effect=send):
            self.assertTrue(self.lane.submit({'other':other,'target':self.page},entries,0,self.router,lambda **kw:nullcontext(),lambda:False,**self.backlog_options()))
        other.goto.assert_not_called();self.page.goto.assert_called_once()
        self.assertEqual(self.backlog_binding()['target_id'],'target');self.assertEqual(self.state(),'submitted')

    def test_assigned_review_head_changed_cannot_claim_or_consume_other_page(self):
        self.backlog_fixture()
        with self.dependencies(),patch('browser.shared_page_backlog.check_head_binding',return_value=False),patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,lambda **kw:nullcontext(),lambda:False,**self.backlog_options()))
        self.assertEqual(self.state(),'ready');self.assertEqual(self.backlog_binding()['state'],'queued')
        send.assert_not_called();self.page.goto.assert_not_called()

    def test_assigned_review_binding_changed_inside_submit_lock_blocks_navigation(self):
        self.backlog_fixture()
        from contextlib import contextmanager
        @contextmanager
        def changed_lock(**kw):
            with self.catalog.connect() as db:
                db.execute('UPDATE shared_page_backlog SET target_id=? WHERE job_id=?',('other',self.job['id']))
            yield
        with self.dependencies(),patch('browser.shared_page_backlog.check_head_binding',return_value=True),patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,changed_lock,lambda:False,**self.backlog_options()))
        send.assert_not_called();self.page.goto.assert_not_called();self.assertEqual(self.state(),'needs_user')

    def test_assigned_review_late_pause_before_page_use_preserves_queue_and_receipt_history(self):
        self.backlog_fixture()
        from contextlib import contextmanager
        @contextmanager
        def pause_lock(**kw):
            atomic_json(self.root/'card-review-control.json',{'paused_by_user':True})
            yield
        with self.dependencies(),patch('browser.shared_page_backlog.check_head_binding',return_value=True),patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,pause_lock,lambda:False,**self.backlog_options()))
        self.assertEqual(self.state(),'ready');binding=self.backlog_binding()
        self.assertEqual((binding['state'],binding['target_id']),('queued','target'))
        self.assertFalse((Path(self.job['folder'])/'attempt.json').exists())
        history=list((Path(self.job['folder'])/'history').glob('*/attempt.json'));self.assertEqual(len(history),1)
        self.assertEqual(json.loads(history[0].read_text())['state'],'not_sent')
        send.assert_not_called();self.page.goto.assert_not_called()

    def test_nonpause_deferred_before_page_use_releases_only_unused_claim(self):
        from browser.web_card_transport import DeferredWeb
        self.backlog_fixture()
        with self.dependencies(),patch('browser.shared_page_backlog.check_head_binding',return_value=True), \
                patch('review.card_review_queue.current',side_effect=DeferredWeb('材料暂不可用')), \
                patch('browser.web_card_transport.submit_gpt_background') as send:
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,
                lambda **kw:nullcontext(),lambda:False,**self.backlog_options()))
        self.assertIsNone(self.backlog_binding())
        self.assertEqual(self.state(),'needs_user')
        send.assert_not_called();self.page.goto.assert_not_called()

    def test_assigned_review_unknown_send_retains_claim_and_does_not_repeat(self):
        self.backlog_fixture()
        def send(session,prompt,files,**options):
            options['on_before_send']();raise RuntimeError('Unknown original send receipt')
        with self.dependencies(),patch('browser.shared_page_backlog.check_head_binding',return_value=True),patch('browser.web_card_transport.submit_gpt_background',side_effect=send) as submit:
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,lambda **kw:nullcontext(),lambda:False,**self.backlog_options()))
            self.assertFalse(self.lane.submit({'target':self.page},self.entries,0,self.router,lambda **kw:nullcontext(),lambda:False,**self.backlog_options()))
        self.assertEqual(submit.call_count,1);binding=self.backlog_binding()
        self.assertEqual((binding['state'],binding['target_id']),('claimed','target'))
        self.assertTrue(json.loads((Path(self.job['folder'])/'attempt.json').read_text())['send_click_started'])


if __name__=='__main__':unittest.main()
