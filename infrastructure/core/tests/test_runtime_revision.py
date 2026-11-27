import json
import tempfile
import time
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
from core.catalog import Catalog
from core.services import acquisition, discover, verify_identity, maybe_daily, maintain_jobs
from core.runtime import queue_drained, alive
import subprocess


class RuntimeRevisionTests(unittest.TestCase):
    def test_exited_unreaped_worker_is_not_considered_alive(self):
        with patch('core.runtime.os.kill'),patch('core.runtime.subprocess.run',return_value=subprocess.CompletedProcess([],0,stdout='Z')):
            self.assertFalse(alive(123))
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.c=Catalog(self.root/'catalog.db')
        self.config={'archive_volume':str(self.root),'archive_root':str(self.root/'archive'),'require_mounted_volume':False,'catalog_path':str(self.c.path),'first_round':{'candidate_limit_total':1},'pdf_only':True,'automatic_schedule_enabled':True,'daily_schedule':{'mode':'on_completion','idle_backoff_minutes':30}}
    def tearDown(self):self.temp.cleanup()

    def test_unrelated_body_words_and_reference_doi_do_not_prove_identity(self):
        with patch('core.services.validate_pdf',return_value='Another title\nIn this study organic light emitting diodes are discussed. DOI 10.1000/expected'):
            with self.assertRaises(ValueError):verify_identity('unused',{'title':'Organic light emitting diodes','doi':'10.1000/expected'})

    def test_latest_arxiv_link_and_actual_version_are_verified(self):
        asset=self.root/'old.pdf';asset.write_bytes(b'old')
        p=self.c.upsert({'title':'Unique organic triplet exciton transport report','doi':'10.48550/arxiv.2406.02703','arxiv_id':'2406.02703','arxiv_version_id':'2406.02703v1','asset_preprint_version':'2406.02703v1','pdf_urls':['https://arxiv.org/pdf/2406.02703v1']})
        self.c.update(p,asset_path=str(asset),acquisition='available')
        self.c.upsert({'title':'Unique organic triplet exciton transport report','doi':'10.48550/arxiv.2406.02703','arxiv_id':'2406.02703','arxiv_version_id':'2406.02703v2','pdf_urls':['https://arxiv.org/pdf/2406.02703v2']})
        used=[]
        def download(url,path):used.append(url);return url
        with patch('core.services.download',side_effect=download),patch('core.services.verify_identity'),patch('core.services.validate_pdf',return_value='arXiv:2406.02703v2'),patch('core.services.store_asset',return_value=(str(asset),'hash')):
            acquisition(self.c,self.config,p)
        self.assertEqual(used,['https://arxiv.org/pdf/2406.02703v2'])
        self.assertEqual(self.c.get(p)['metadata']['asset_preprint_version'],'2406.02703v2')

    def test_old_version_response_cannot_be_labelled_new(self):
        asset=self.root/'old.pdf';asset.write_bytes(b'old')
        p=self.c.upsert({'title':'Unique organic triplet exciton transport report','doi':'10.48550/arxiv.2406.02703','arxiv_id':'2406.02703','arxiv_version_id':'2406.02703v2','asset_preprint_version':'2406.02703v1'})
        self.c.update(p,asset_path=str(asset),acquisition='available')
        with patch('core.services.download',return_value='https://arxiv.org/pdf/2406.02703v2'),patch('core.services.verify_identity'),patch('core.services.validate_pdf',return_value='arXiv:2406.02703v1'):
            acquisition(self.c,self.config,p)
        self.assertEqual(self.c.get(p)['metadata']['asset_preprint_version'],'2406.02703v1')
        self.assertEqual(self.c.get(p)['acquisition'],'available')

    def test_page_remainder_survives_reopen_and_next_round(self):
        records=[{'title':f'Unique OLED emitter report {i}','doi':f'10.1000/{i}','channels':['journal'],'discovery_reasons':['topic']} for i in range(25)]
        self.c.retain_discovery(records,{'arxiv:oled':20,'chemrxiv:oled':30})
        asset=self.root/'asset.pdf';asset.write_bytes(b'fixture')
        def acquire(c,config,p):c.update(p,asset_path=str(asset),acquisition='available')
        with patch('core.services.bridge') as bridge,patch('core.services.acquisition',side_effect=acquire):
            self.assertEqual(len(discover(self.c,self.config)),1)
            self.assertEqual(len(discover(Catalog(self.c.path),self.config)),1)
            bridge.assert_not_called()
        self.assertEqual(len(self.c.pending_discovery()),23)
        self.assertEqual(self.c.cursors(),{'arxiv:oled':20,'chemrxiv:oled':30})

    def test_invalid_list_record_does_not_abort_page_persistence(self):
        self.c.retain_discovery([{'title':'OLED malformed','doi':'10.1000/badlist','pdf_urls':[{}]},{'title':'OLED valid','doi':'10.1000/valid','channels':'journal'}],{'journal:query':2})
        self.assertEqual(len(self.c.pending_discovery()),1)
        self.assertEqual(self.c.cursors()['journal:query'],2)
        with self.c.connect() as db:self.assertEqual(db.execute("SELECT state FROM discovery_pending WHERE key='10.1000/badlist'").fetchone()[0],'quarantined')

    def test_bad_item_is_quarantined_without_stopping_good_item(self):
        self.config['first_round']['candidate_limit_total']=10
        records=[{'title':'OLED invalid year','year':'broken','doi':'10.1000/bad','channels':['journal'],'abstract':['invalid']},{'title':'OLED valid emitter','doi':'10.1000/good','channels':['journal']}]
        asset=self.root/'asset.pdf';asset.write_bytes(b'fixture')
        def acquire(c,config,p):c.update(p,asset_path=str(asset),acquisition='available')
        with patch('core.services.bridge',return_value={'pool':records,'resolved':[],'warnings':[],'positions':{'journal:OLED':2},'raw':[]}),patch('core.services.acquisition',side_effect=acquire):
            chosen=discover(self.c,self.config)
        self.assertEqual(len(chosen),1)
        with self.c.connect() as db:self.assertEqual(db.execute("SELECT state FROM discovery_pending WHERE key='10.1000/bad'").fetchone()[0],'quarantined')

    def test_reading_queue_does_not_block_fetch_below_backpressure_limit(self):
        p=self.c.upsert({'title':'OLED','doi':'10.1000/read'})
        self.c.enqueue('screen',p)
        self.assertIsNotNone(maybe_daily(self.c,self.config))
        read=self.c.claim(('screen',));self.assertEqual(read['kind'],'screen')
        fetch=self.c.claim(('discover',));self.assertEqual(fetch['kind'],'discover')
        self.c.recover(('screen',))
        with self.c.connect() as db:self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?',(fetch['id'],)).fetchone()[0],'running')

    def test_waiting_storage_resumes_and_retries_are_bounded(self):
        job=self.c.enqueue('discover');self.c.finish(job,'waiting_storage','SSD absent')
        maintain_jobs(self.c,self.config)
        with self.c.connect() as db:self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?',(job,)).fetchone()[0],'queued')
        p=self.c.upsert({'title':'OLED','doi':'10.1000/retry'})
        asset=self.root/'asset.pdf';asset.write_bytes(b'fixture');self.c.update(p,asset_path=str(asset),acquisition='available')
        screen=self.c.enqueue('screen',p);self.c.finish(screen,'failed','bad quote')
        with self.c.connect() as db:db.execute('UPDATE jobs SET attempts=3,updated=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),screen))
        with patch('core.services.verify_identity'):maintain_jobs(self.c,self.config)
        with self.c.connect() as db:self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?',(screen,)).fetchone()[0],'failed')

    def test_handover_waits_for_running_and_queued_work(self):
        job=self.c.enqueue('discover');self.assertFalse(queue_drained(self.c))
        self.c.claim();self.assertFalse(queue_drained(self.c))
        self.c.finish(job,'done');self.assertTrue(queue_drained(self.c))
