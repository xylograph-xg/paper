"""Real catalog evidence for the review upload backoff policy and its guards."""
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from core.api import paths__WorkspacePath as Path

from core.catalog import Catalog
from cards.web_card_inputs import digest
from core.services import atomic_json
from review import card_review_queue as reviews
from browser import upload_retry_policy as policy
from browser.web_card_transport import (DeferredWeb, UploadStageFailure, UPLOAD_STAGE_BY_KIND,
                                        wait_gpt_upload_settled)


class UploadRetryPolicyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.catalog = Catalog(self.root/'catalog.sqlite3')
        self.config = {'catalog_path':str(self.catalog.path),
                       'card_review':{'enabled':True,'upload_retry':{'enabled':True}}}
        reviews.install(self.catalog)

    def material(self, name, *, text='synthetic'):
        folder = self.root/'reviews'/name
        folder.mkdir(parents=True, exist_ok=True)
        for label in ('source.pdf','prompt.txt'):
            (folder/label).write_text(text+label)
        (folder/'bundle.zip').write_bytes(('zip '+text).encode())
        packet = {'input_hashes':{label:digest(folder/label) for label in ('source.pdf','prompt.txt')},
            'upload_bundle':{'zip_path':str(folder/'bundle.zip'),'zip_sha256':digest(folder/'bundle.zip')}}
        atomic_json(folder/'packet.json',packet)
        return folder,packet

    def failure(self, packet, *, created=1000.0, finished=1100.0, stage='attach',
                state='not_sent', click=False):
        attempt = {'state':state,'send_click_started':click,'created':created,'finished':finished,
                   'error':'附件上传失败','inputs':packet['input_hashes'],
                   'upload_bundle':packet['upload_bundle']}
        if stage:attempt['upload_failure_stage']=stage
        return attempt

    def receipts(self):
        with self.catalog.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM upload_retry_receipts ORDER BY recorded_at')]

    def rows(self):
        with self.catalog.connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT * FROM upload_retry_policy ORDER BY job_id,inputs_digest')]

    def test_arrival_install_chain_creates_the_evidence_tables(self):
        with self.catalog.connect() as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({'upload_retry_policy','upload_retry_receipts'} <= tables)

    def test_one_receipt_counts_once_across_rescans_and_owner_restarts(self):
        _,packet = self.material('job-a')
        attempt = self.failure(packet)
        first = policy.record_failure(self.catalog,config=self.config,job_id='job-a',attempt=attempt)
        self.assertFalse(first['deduplicated'])
        self.assertEqual(first['next_eligible'],1400.0)
        for _ in range(3):
            again = policy.record_failure(self.catalog,config=self.config,job_id='job-a',attempt=attempt)
            self.assertTrue(again['deduplicated'])
            self.assertEqual(again['next_eligible'],1400.0)
        # A restart reads the same catalog and the same stored receipt; a later
        # scan stamp cannot move the recorded timer.
        restarted = Catalog(self.root/'catalog.sqlite3')
        later = policy.record_failure(restarted,config=self.config,job_id='job-a',attempt=attempt,
                                      at=time.time()+7200)
        self.assertTrue(later['deduplicated'])
        self.assertEqual(len(self.receipts()),1);self.assertEqual(len(self.rows()),1)
        self.assertEqual(self.rows()[0]['consecutive'],1)
        self.assertEqual(self.rows()[0]['last_failure'],1100.0)

    def test_bounded_backoff_stays_automatic_and_needs_no_manual_step(self):
        _,packet = self.material('job-b')
        for index,(created,finished,due) in enumerate(((1.0,10.0,310.0),(2.0,400.0,1300.0),
                (3.0,1400.0,5000.0),(4.0,5100.0,8700.0)),1):
            attempt = self.failure(packet,created=created,finished=finished)
            result = policy.record_failure(self.catalog,config=self.config,job_id='job-b',attempt=attempt)
            self.assertEqual(result['consecutive'],index)
            self.assertEqual(result['next_eligible'],due)
            # Each window is automatic: the instant it arrives the material is
            # eligible again, so no task ever needs a manual step.
            with self.catalog.connect() as db:
                key = policy.material_identity(packet)
                self.assertIsNone(policy.cooling(db,'job-b',config=self.config,identity=key,at=due))
                self.assertEqual(policy.cooling(db,'job-b',config=self.config,identity=key,at=due-1),due)
                with self.assertRaises(policy.PolicyIntegrityError):
                    policy.cooling(db,'job-b',config=self.config,at=due)
        self.assertEqual(self.rows()[0]['total'],4)
        self.assertEqual(self.rows()[0]['consecutive'],4)

    def test_success_clears_only_the_streak_and_keeps_total_evidence(self):
        _,packet = self.material('job-c')
        policy.record_failure(self.catalog,config=self.config,job_id='job-c',
                              attempt=self.failure(packet,created=1.0,finished=2.0))
        policy.record_failure(self.catalog,config=self.config,job_id='job-c',
                              attempt=self.failure(packet,created=3.0,finished=4.0))
        sent = self.failure(packet,created=5.0,finished=6.0,stage=None)
        sent.update(state='submitted',send_click_started=True)
        self.assertTrue(policy.settle_success(self.catalog,config=self.config,job_id='job-c',attempt=sent))
        row = self.rows()[0]
        self.assertEqual((row['consecutive'],row['total'],row['next_eligible']),(0,2,0.0))
        self.assertEqual(len(self.receipts()),2)
        with self.catalog.connect() as db:
            self.assertIsNone(policy.cooling(db,'job-c',config=self.config,
                                             identity=policy.material_identity(packet),at=4.0))
        # The next technical failure starts again at the fifth minute.
        result = policy.record_failure(self.catalog,config=self.config,job_id='job-c',
            attempt=self.failure(packet,created=9.0,finished=10.0))
        self.assertEqual((result['consecutive'],result['next_eligible']),(1,310.0))
        self.assertEqual(self.rows()[0]['total'],3)

    def test_new_material_version_is_independent_and_keeps_old_history(self):
        folder,packet = self.material('job-d')
        policy.record_failure(self.catalog,config=self.config,job_id='job-d',attempt=self.failure(packet))
        with self.catalog.connect() as db:
            self.assertEqual(policy.cooling(db,'job-d',str(folder),config=self.config,at=1200.0),1400.0)
        _,fresh = self.material('job-d',text='repaired')
        with self.catalog.connect() as db:
            self.assertIsNone(policy.cooling(db,'job-d',str(folder),config=self.config,at=1200.0))
            self.assertEqual(len(self.receipts()),1)
        again = policy.record_failure(self.catalog,config=self.config,job_id='job-d',
            attempt=self.failure(fresh,created=5000.0,finished=5100.0))
        self.assertEqual((again['consecutive'],again['next_eligible']),(1,5400.0))
        self.assertEqual(len(self.rows()),2)

    def test_only_never_clicked_finished_upload_receipts_are_counted(self):
        _,packet = self.material('job-e')
        for label,attempt in (('clicked',self.failure(packet,click=True)),
                ('uncertain',self.failure(packet,state='needs_inspection',click=True)),
                ('no stage',self.failure(packet,stage=None)),
                ('open ended',{**self.failure(packet),'finished':None}),
                ('no zip',{**self.failure(packet),'upload_bundle':{'zip_path':'bundle.zip'}}),
                ('no inputs',{**self.failure(packet),'inputs':None})):
            with self.subTest(label):
                self.assertIsNone(policy.record_failure(self.catalog,config=self.config,
                    job_id='job-e',attempt=attempt))
        self.assertEqual(self.receipts(),[]);self.assertEqual(self.rows(),[])

    def test_transport_separates_technical_upload_stages_from_pause_quota_and_verification(self):
        bars = Mock(); bars.count.return_value = 1
        bar = Mock(); bar.is_visible.return_value = True; bars.nth.return_value = bar
        page = Mock(); page.locator.return_value = bars
        with patch('browser.web_card_transport.require_no_verification'), \
             patch('browser.web_card_transport.visible_notice',return_value=None):
            with self.assertRaises(UploadStageFailure) as caught:
                wait_gpt_upload_settled(page,0)
            self.assertEqual(caught.exception.stage,'settle')
            self.assertEqual(str(caught.exception),'附件仍在上传，未点击发送；稍后重试')
            self.assertIsInstance(caught.exception,RuntimeError)
            with self.assertRaises(DeferredWeb) as paused:
                wait_gpt_upload_settled(page,0,stopping=lambda:True)
            self.assertNotIsInstance(paused.exception,UploadStageFailure)
        with patch('browser.web_card_transport.require_no_verification'), \
             patch('browser.web_card_transport.visible_notice',
                   return_value={'notice':'已达上传上限','not_before_utc':'2026-10-15T00:00:00+00:00'}):
            with self.assertRaises(RuntimeError) as quota:
                wait_gpt_upload_settled(page,0)
            self.assertNotIsInstance(quota.exception,UploadStageFailure)
            self.assertEqual(policy.upload_failure({'state':'not_sent','send_click_started':False,
                'finished':1.0,'error':str(quota.exception)}),'')

    def test_recorded_stage_labels_map_to_the_upload_segments(self):
        folder,packet = self.material('job-f')
        for index,stage in enumerate(policy.UPLOAD_STAGES):
            with self.subTest(stage=stage):
                attempt = self.failure(packet,created=index,finished=100.0+index,stage=stage)
                self.assertEqual(policy.upload_failure(attempt),stage)
                self.assertIsNotNone(policy.record_failure(self.catalog,config=self.config,
                    job_id='job-f',attempt=attempt))
        # Every segment of the same frozen ZIP is one material key: the streak
        # grows to the low frequency window without new science counts.
        self.assertEqual(len(self.receipts()),len(policy.UPLOAD_STAGES))
        self.assertEqual(len(self.rows()),1)
        self.assertEqual(self.rows()[0]['consecutive'],len(policy.UPLOAD_STAGES))
        last = 100.0 + len(policy.UPLOAD_STAGES) - 1
        with self.catalog.connect() as db:
            self.assertEqual(policy.cooling(db,'job-f',str(folder),config=self.config,at=last+1.0),last+3600.0)

    def test_write_failure_and_missing_attachment_are_separate_segments(self):
        # The transport names the two halves of the attachment segment apart, and
        # every label it can emit is one the policy is willing to cool on.
        self.assertTrue(set(UPLOAD_STAGE_BY_KIND.values()) <= set(policy.UPLOAD_STAGES))
        self.assertNotEqual(UPLOAD_STAGE_BY_KIND['write_failed'],
                            UPLOAD_STAGE_BY_KIND['attachment_not_shown'])
        _,packet = self.material('job-f2')
        write = self.failure(packet,created=1.0,finished=50.0,stage=UPLOAD_STAGE_BY_KIND['write_failed'])
        shown = self.failure(packet,created=2.0,finished=90.0,stage=UPLOAD_STAGE_BY_KIND['attachment_not_shown'])
        self.assertEqual((policy.upload_failure(write),policy.upload_failure(shown)),
                         ('attach_write','attach_visible'))
        for attempt in (write,shown):
            self.assertIsNotNone(policy.record_failure(self.catalog,config=self.config,
                job_id='job-f2',attempt=attempt))
        self.assertEqual({row['stage'] for row in self.receipts()},{'attach_write','attach_visible'})
        self.assertEqual(self.rows()[0]['consecutive'],2)

    def test_annotate_marks_only_the_cooling_material_and_leaves_other_work_due(self):
        folder,packet = self.material('job-g')
        other,_ = self.material('job-h')
        policy.record_failure(self.catalog,config=self.config,job_id='job-g',attempt=self.failure(packet))
        records = [{'lane':'review','job_id':'job-g','folder':str(folder),'queued_at':1.0,'sequence':1},
                   {'lane':'review','job_id':'job-h','folder':str(other),'queued_at':2.0,'sequence':2},
                   {'lane':'cards','job_id':'paper-g','queued_at':3.0,'sequence':3}]
        with self.catalog.connect() as db:
            annotated = policy.annotate(db,records,self.config,at=1150.0)
        self.assertEqual([record['upload_due'] for record in annotated],[False,True,True])
        self.assertEqual(annotated[0]['upload_cooldown_until'],1400.0)
        self.assertNotIn('upload_cooldown_until',annotated[1])
        self.assertTrue(policy.due(annotated[1]))
        self.assertTrue(policy.due({'lane':'review','job_id':'untouched'}))
        with self.catalog.connect() as db:
            after = policy.annotate(db,[dict(record) for record in annotated],self.config,at=1400.0)
        self.assertTrue(all(record['upload_due'] for record in after))
        self.assertEqual([record['queued_at'] for record in after],[1.0,2.0,3.0])

    def test_unreadable_packet_for_a_recorded_failure_stops_new_claims(self):
        folder,packet = self.material('job-i')
        policy.record_failure(self.catalog,config=self.config,job_id='job-i',attempt=self.failure(packet))
        (folder/'packet.json').unlink()
        with self.catalog.connect() as db:
            annotated = policy.annotate(db,[{'lane':'review','job_id':'job-i','folder':str(folder)}],
                                        self.config,at=1150.0)
            self.assertFalse(annotated[0]['upload_due'])
            self.assertEqual(annotated[0]['upload_policy_error'],'核验冻结材料清单待核对')
            with self.assertRaises(policy.PolicyIntegrityError):
                policy.guard(db,self.config,'job-i',str(folder),at=1150.0)

    def test_corrupt_policy_row_is_never_read_as_zero_failures(self):
        folder,packet = self.material('job-j')
        policy.record_failure(self.catalog,config=self.config,job_id='job-j',attempt=self.failure(packet))
        with self.catalog.connect() as db:
            db.execute('UPDATE upload_retry_policy SET consecutive=-1')
        with self.catalog.connect() as db:
            annotated = policy.annotate(db,[{'lane':'review','job_id':'job-j','folder':str(folder)}],
                                        self.config,at=1150.0)
            self.assertFalse(annotated[0]['upload_due'])
            self.assertEqual(annotated[0]['upload_policy_error'],'核验上传退避记录待核对')
            with self.assertRaises(policy.PolicyIntegrityError):
                policy.guard(db,self.config,'job-j',str(folder),at=1150.0)

    def test_disabled_policy_records_nothing_and_cools_nothing(self):
        folder,packet = self.material('job-k')
        config = {'card_review':{'enabled':True}}
        self.assertIsNone(policy.record_failure(self.catalog,config=config,job_id='job-k',
            attempt=self.failure(packet)))
        self.assertEqual(self.receipts(),[])
        with self.catalog.connect() as db:
            self.assertEqual(policy.annotate(db,[{'lane':'review','job_id':'job-k','folder':str(folder)}],
                                             config,at=0.0)[0]['upload_due'],True)
            self.assertIsNone(policy.cooling(db,'job-k',str(folder),config=config))
            self.assertIs(policy.guard(db,config,'job-k',str(folder)),False)

    def test_malformed_backoff_window_fails_closed_instead_of_defaulting(self):
        for raw in ('300',[],[0],[300,'x'],[300,9010000]):
            with self.subTest(backoff_seconds=raw):
                config = {'card_review':{'upload_retry':{'enabled':True,'backoff_seconds':raw}}}
                with self.assertRaises(policy.PolicyIntegrityError):
                    policy.enabled(config)
        self.assertFalse(policy.enabled({'card_review':{'enabled':True}}))
        self.assertEqual(policy.window(1),300.0);self.assertEqual(policy.window(2),900.0)
        self.assertEqual(policy.window(3),3600.0);self.assertEqual(policy.window(9),3600.0)

    def test_first_eligible_keeps_the_original_order_and_skips_only_cooling_rows(self):
        old,old_packet = self.material('job-l')
        fresh,_ = self.material('job-m')
        rows = [{'id':'job-l','folder':str(old)},{'id':'job-m','folder':str(fresh)}]
        with self.catalog.connect() as db:
            self.assertIs(policy.first_eligible(db,rows,self.config,at=0.0)['id'],'job-l')
            policy.record_failure(self.catalog,config=self.config,job_id='job-l',
                attempt=self.failure(old_packet))
            self.assertIs(policy.first_eligible(db,rows,self.config,at=1150.0)['id'],'job-m')
            self.assertIsNone(policy.first_eligible(db,[dict(rows[0])],self.config,at=1150.0))
            self.assertIs(policy.first_eligible(db,rows,self.config,at=1400.0)['id'],'job-l')

    def test_two_concurrent_scans_count_the_same_receipt_only_once(self):
        _,packet = self.material('job-n')
        attempt = self.failure(packet)
        results = []
        threads = [threading.Thread(target=lambda: results.append(policy.record_failure(
            self.catalog,config=self.config,job_id='job-n',attempt=attempt))) for _ in range(4)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(sorted(result['deduplicated'] for result in results),[False,True,True,True])
        self.assertEqual(len(self.receipts()),1)
        self.assertEqual(self.rows()[0]['consecutive'],1)

    def test_summary_counts_tracked_and_waiting_jobs_without_changing_evidence(self):
        _,packet = self.material('job-o')
        policy.record_failure(self.catalog,config=self.config,job_id='job-o',attempt=self.failure(packet))
        with self.catalog.connect() as db:
            waiting = policy.summary(db,self.config,at=1150.0)
            ready = policy.summary(db,self.config,at=1400.0)
        self.assertEqual(waiting,{'enabled':True,'tracked_jobs':1,'cooling_jobs':1,'total_failures':1})
        self.assertEqual(ready['cooling_jobs'],0)
        self.assertEqual(ready['total_failures'],1)
        self.assertEqual(len(self.receipts()),1)


if __name__ == '__main__':
    unittest.main()
