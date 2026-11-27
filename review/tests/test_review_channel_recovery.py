import json
from core.api import paths__WorkspacePath as Path
from review.tests.test_card_review_queue import ReviewQueue
from review.review_channel_recovery import recover
from review import card_review_queue as review
from browser.shared_page_backlog import install
from core.services import atomic_json

class Recovery(ReviewQueue):
    def setup_failure(self, state='not_sent', click=False):
        job,_,card=self.card();folder,packet=self.packet(job,card)
        install(self.catalog)
        from correction.card_correction_queue import install as install_corrections
        install_corrections(self.catalog)
        atomic_json(folder/'attempt.json',{'state':state,'send_click_started':click,'review_id':job['id'],
            'inputs':packet['input_hashes'],'actual_prompt_sha256':packet['actual_prompt_sha256']})
        review.update(self.catalog,job['id'],'needs_user','复用页有草稿')
        return job,folder

    def test_explicit_unsent_requeues_and_preserves_receipt(self):
        job,folder=self.setup_failure()
        r=recover(self.catalog,self.config)
        self.assertEqual(r['recovered'],[job['id']])
        self.assertFalse((folder/'attempt.json').exists())
        self.assertEqual(len(list(folder.glob('history/*/attempt.json'))),1)
        self.assertEqual(review.rows(self.catalog)[0]['state'],'ready')
        self.assertEqual(recover(self.catalog,self.config)['recovered'],[])

    def test_unknown_click_does_not_requeue(self):
        job,folder=self.setup_failure('needs_inspection',True)
        self.assertEqual(recover(self.catalog,self.config)['recovered'],[])
        self.assertTrue((folder/'attempt.json').exists())

    def test_changed_inputs_do_not_requeue(self):
        job,folder=self.setup_failure()
        (folder/'prompt.txt').write_text('changed')
        self.assertEqual(recover(self.catalog,self.config)['recovered'],[])
        self.assertTrue((folder/'attempt.json').exists())

    def test_same_oversize_zip_keeps_the_unsent_receipt_and_queue_state(self):
        from cards.api import web_card_inputs__digest as digest
        job,folder=self.setup_failure()
        packet=json.loads((folder/'packet.json').read_text())
        bundle=Path(packet['upload_bundle']['zip_path'])
        with bundle.open('r+b') as stream:
            stream.truncate(50*1024*1024+1)
        packet['upload_bundle']['zip_sha256']=digest(bundle)
        atomic_json(folder/'packet.json',packet)
        before=(folder/'attempt.json').read_bytes()
        result=recover(self.catalog,self.config)
        self.assertEqual(result['recovered'],[])
        self.assertIn('50MiB',next(row['reason'] for row in result['retained'] if row['id']==job['id']))
        self.assertEqual((folder/'attempt.json').read_bytes(),before)
        self.assertEqual(review.rows(self.catalog)[0]['state'],'needs_user')

    def test_pause_does_not_requeue(self):
        job,folder=self.setup_failure()
        atomic_json(self.root/'card-review-control.json',{'paused_by_user':True})
        self.assertEqual(recover(self.catalog,self.config)['recovered'],[])
        self.assertTrue((folder/'attempt.json').exists())

    def test_repaired_materials_keep_previous_report_and_requeue_unsent(self):
        job,folder=self.setup_failure()
        previous={'material_recheck_pending':True,'previous_report':'preserved/feedback.json','weighted_score':42,'full_source_checked':False}
        review.update(self.catalog,job['id'],'needs_user','旧草稿占位',previous)
        r=recover(self.catalog,self.config)
        self.assertEqual(r['recovered'],[job['id']])
        row=review.rows(self.catalog)[0]
        self.assertEqual(row['state'],'ready');self.assertEqual(json.loads(row['result']),previous)

    def test_scientific_report_without_pending_new_materials_is_not_resent(self):
        job,folder=self.setup_failure()
        review.update(self.catalog,job['id'],'needs_user','科学歧义',{'verdict':'cannot_evaluate','full_source_checked':True})
        self.assertEqual(recover(self.catalog,self.config)['recovered'],[])
        self.assertTrue((folder/'attempt.json').exists())

    def test_failed_technical_job_uses_same_guards_without_error_whitelist(self):
        job,folder=self.setup_failure()
        review.update(self.catalog,job['id'],'failed','TimeoutError: synthetic')
        self.assertEqual(recover(self.catalog,self.config)['recovered'],[job['id']])
        row=next(r for r in review.rows(self.catalog) if r['id']==job['id'])
        self.assertEqual(row['state'],'ready')

    def test_failed_unknown_job_remains_protected(self):
        job,folder=self.setup_failure('needs_inspection',True)
        review.update(self.catalog,job['id'],'failed','TimeoutError: synthetic')
        self.assertEqual(recover(self.catalog,self.config)['recovered'],[])
        self.assertTrue((folder/'attempt.json').exists())
