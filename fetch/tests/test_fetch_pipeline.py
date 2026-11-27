"""Fetch failure, pagination and real process integration using synthetic data."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime,timezone
import io
import json
import os
from core.api import paths__WorkspacePath as Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest.mock import patch
from core.catalog import ROOT, Catalog
from fetch.network import ProviderClient, DeferredRequest, ready, failed, retry_seconds
from fetch.discovery_bridge import discover as metadata_discover, page_state
from fetch.preprints import discover as preprint_discover
from fetch.fetching import discover_and_queue, schedule_discovery, queue_pending, fetch_loop, restore_checkpoints
from core.services import acquisition


class FetchFixtures(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.catalog=Catalog(self.root/'catalog.sqlite3')
        self.config=json.loads((ROOT/'config/first_round.json').read_text())
        self.config.update(catalog_path=str(self.catalog.path),archive_volume=str(self.root),archive_root=str(self.root/'archive'),
                           studio_library_root=str(self.root/'library'),seed_input_dir=str(self.root/'seeds'),
                           require_mounted_volume=False,automatic_schedule_enabled=False)
        self.config['fetch_pipeline']['prevent_idle_sleep']=False
        self.config['fetch_pipeline']['oa_only']=False
        self.config['pdf_retrieval']['enabled']=False

    def tearDown(self):self.temp.cleanup()

    def record(self,index=0):return {'title':f'Organic triplet emitter measurement {index}',
                                   'doi':f'10.1000/synthetic{index}','channels':['journal'],
                                   'discovery_reasons':['synthetic topic'],'pdf_urls':[]}


class NetworkPolicyTests(FetchFixtures):
    def test_retry_after_day_is_persisted_without_sleep_or_followup_request(self):
        err=urllib.error.HTTPError('https://example.test',429,'rate limit',{'Retry-After':'86400'},None)
        client=ProviderClient(self.root)
        with (patch('fetch.network.urllib.request.urlopen',side_effect=err) as call,
              patch('fetch.network.time.sleep') as sleep):
            with self.assertRaises(DeferredRequest) as failure:client.get('https://example.test',provider='synthetic')
            self.assertGreater(failure.exception.retry_at,time.time()+86390)
            with self.assertRaises(DeferredRequest):client.get('https://example.test',provider='synthetic')
            self.assertEqual(call.call_count,1)
            self.assertTrue(all(c.args[0]<1 for c in sleep.call_args_list))
        with self.assertRaises(DeferredRequest):ready('synthetic',self.root)

    def test_http_date_retry_after_and_transient_backoff(self):
        from email.utils import format_datetime
        future=datetime.fromtimestamp(time.time()+120,timezone.utc)
        self.assertGreater(retry_seconds({'Retry-After':format_datetime(future)}),118)
        first=failed('synthetic',503,folder=self.root);second=failed('synthetic',503,folder=self.root)
        self.assertGreater(second,first)

    def test_provider_failure_does_not_close_other_provider(self):
        failed('openalex',429,{'Retry-After':'3600'},self.root)
        ready('crossref',self.root)
        with self.assertRaises(DeferredRequest):ready('openalex',self.root)

    def test_credentials_use_aliases_and_are_not_written_to_state(self):
        client=ProviderClient(self.root)
        response=io.BytesIO(b'{"results":[]}')
        with (patch.dict(os.environ,{'SEMANTIC_SCHOLAR_API_KEY':'private-test-key','OPENALEX_EMAIL':'test@example.test'},clear=True),
              patch('fetch.network.urllib.request.urlopen',return_value=response) as call):
            client.get('https://example.test',provider='s2')
            self.assertEqual(call.call_args.args[0].get_header('X-api-key'),'private-test-key')
        self.assertNotIn('private-test-key',(self.root/'network-state.json').read_text())


class PaginationTests(FetchFixtures):
    def test_crossref_topic_survives_both_openalex_and_s2_outages(self):
        def get(client,url,params=None,provider=None,xml=False):
            if provider in ('openalex','s2'):raise DeferredRequest(provider,time.time()+3600,429)
            return {'message':{'items':[{'DOI':'10.1000/backstop','title':['Organic triplet OLED emitter'],'container-title':['Synthetic Journal']}], 'next-cursor':None}}
        with patch('fetch.network.ProviderClient.get',new=get):
            output=metadata_discover({'queries':['OLED'],'state_dir':str(self.root),'seeds':[],'preprints':{}})
        self.assertEqual(len(output['pool']),1)
        self.assertEqual(output['pool'][0]['source'],['crossref'])
        self.assertIn('v2:crossref-topic:OLED',output['positions'])

    def test_openalex_uses_opaque_cursor_and_checkpoints_each_success(self):
        checkpoint=self.root/'checkpoint.json';seen=[]
        def get(client,url,params=None,provider=None,xml=False):
            seen.append(params)
            return {'results':[{'id':'https://openalex.org/W1','doi':'https://doi.org/10.1000/synthetic','title':'Organic triplet emitter','publication_year':2025}],
                    'meta':{'next_cursor':'opaque-next-cursor'}}
        request={'queries':['synthetic topic'],'seeds':[],'preprints':{},'state_dir':str(self.root),
                 'checkpoint_path':str(checkpoint),'positions':{'v2:oa-topic:synthetic topic':{'cursor':'opaque-current','snapshot':'2026-10-05'}},'network':{'page_size':100}}
        with patch('fetch.network.ProviderClient.get',new=get):result=metadata_discover(request)
        self.assertEqual(seen[0]['cursor'],'opaque-current');self.assertNotIn('page',seen[0])
        state=result['positions']['v2:oa-topic:synthetic topic']
        self.assertEqual(state['cursor'],'opaque-next-cursor');self.assertFalse(state['done'])
        self.assertEqual(json.loads(checkpoint.read_text())['pool'],result['pool'])

    def test_completed_source_pauses_and_expired_source_restarts(self):
        state={'done':True,'next_scan_at':time.time()+3600,'cursor':'terminal'}
        self.assertIsNone(page_state({'key':state},'key'))
        self.assertEqual(page_state({'key':{**state,'next_scan_at':0}},'key'),{})

    def test_crossref_cursor_has_no_published_sort_and_keeps_original_filters(self):
        seen=[]
        def get(client,url,params=None,provider=None,xml=False):
            seen.append(params)
            return {'message':{'items':[{'DOI':'10.26434/chemrxiv-synthetic-v1','title':['OLED emitter']}],'next-cursor':'next-opaque'}}
        settings={'chemrxiv_queries':['OLED'],'state_dir':str(self.root),'network':{'page_size':1},
                  'positions':{'v2:chemrxiv:OLED':{'cursor':'prior-opaque','snapshot':'2026-10-05'}}}
        with patch('fetch.network.ProviderClient.get',new=get):result=preprint_discover(settings)
        self.assertEqual(seen[0]['cursor'],'prior-opaque');self.assertNotIn('sort',seen[0]);self.assertNotIn('offset',seen[0])
        self.assertTrue(seen[0]['filter'].startswith('from-created-date:2026-10-05'))
        self.assertIn('until-created-date:',seen[0]['filter'])
        self.assertEqual(result['positions']['v2:chemrxiv:OLED']['cursor'],'next-opaque')

    def test_arxiv_uses_bounded_window_and_resets_after_short_page(self):
        seen=[]
        xml=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>https://arxiv.org/abs/2401.00001v1</id><title>OLED emitter</title><summary>Organic excitons</summary></entry></feed>'
        def get(client,url,params=None,provider=None,xml=False):
            seen.append(params);return globals_xml
        globals_xml=xml
        state={'offset':100,'snapshot':'202610050100'}
        settings={'arxiv_queries':['ti:OLED'],'state_dir':str(self.root),'positions':{'v2:arxiv:ti:OLED':state}}
        with patch('fetch.network.ProviderClient.get',new=get):result=preprint_discover(settings)
        self.assertEqual(seen[0]['start'],100);self.assertEqual(seen[0]['sortBy'],'submittedDate')
        self.assertIn('202610050100',seen[0]['search_query']);self.assertIn(' TO ',seen[0]['search_query'])
        position=result['positions']['v2:arxiv:ti:OLED']
        self.assertEqual(position['offset'],0);self.assertTrue(position['done']);self.assertIn('since',position)


class DurableFetchTests(FetchFixtures):
    def test_new_pdf_location_reopens_pending_retry_without_reopening_excluded(self):
        record=self.record();self.catalog.retain_discovery([record],{})
        self.catalog.pending_result(record['doi'],'pending',retry_at=time.time()+86400)
        record['pdf_urls']=['https://example.test/first.pdf'];self.catalog.retain_discovery([record],{})
        self.assertEqual(len(self.catalog.pending_discovery()),1)
        self.catalog.pending_result(record['doi'],'excluded')
        record['pdf_urls'].append('https://example.test/second.pdf');self.catalog.retain_discovery([record],{})
        self.assertEqual(self.catalog.pending_discovery(),[])

    def test_fast_failures_cannot_fill_reserved_capacity_with_fallbacks(self):
        from fetch.fetching import complete_acquisition
        self.config['pdf_retrieval']['enabled']=True
        self.config['fetch_pipeline']['fallback_queue_limit']=1
        slow=self.catalog.upsert(self.record(99));self.catalog.enqueue('acquire_fallback',slow)
        record=self.record();record['pdf_urls']=['https://example.test/source.pdf']
        self.catalog.retain_discovery([record],{});queue_pending(self.catalog,self.config)
        job=self.catalog.claim(('acquire',));complete_acquisition(self.catalog,self.config,job,{})
        self.assertEqual(sum(j['kind']=='acquire_fallback' for j in self.catalog.jobs()),1)
        with self.catalog.connect() as db:
            pending=db.execute('SELECT state,retry_at FROM discovery_pending').fetchone()
        self.assertEqual(pending['state'],'pending');self.assertGreater(pending['retry_at'],time.time())

    def test_crossref_unspecified_pdf_links_are_retained_but_html_is_not(self):
        from fetch.preprints import crossref_record, parse_chemrxiv
        work={'DOI':'10.26434/chemrxiv-synthetic-v1','title':['Organic OLED emitter'],
              'link':[{'URL':'https://example.test/doi/pdf/10.1000/synthetic','content-type':'unspecified'},
                      {'URL':'https://example.test/paper.pdf?download=1'},
                      {'URL':'https://example.test/doi/full/10.1000/synthetic','content-type':'text/html'}]}
        expected=[x['URL'] for x in work['link'][:2]]
        self.assertEqual(crossref_record(work)['pdf_urls'],expected)
        self.assertEqual(parse_chemrxiv([work])[0]['pdf_urls'],expected)

    def test_unpaywall_without_email_does_not_perform_a_request(self):
        import requests
        from fetch.fetchpdf_bridge import install_http_guards
        original=requests.sessions.Session.send
        try:
            with patch.object(requests.sessions.Session,'send') as send:
                install_http_guards(False)
                request=requests.Request('GET','https://api.unpaywall.org/v2/10.1000/synthetic?email=None').prepare()
                with self.assertRaisesRegex(ValueError,'跳过请求'):requests.Session().send(request)
                send.assert_not_called()
        finally:requests.sessions.Session.send=original

    def test_failed_checkpoint_replace_preserves_previous_and_cleans_temp(self):
        from core.services import atomic_json
        path=self.root/'checkpoint.json';atomic_json(path,{'old':True})
        before=set(self.root.iterdir())
        with patch('core.services.os.replace',side_effect=OSError('injected replace failure')):
            with self.assertRaises(OSError):atomic_json(path,{'new':True})
        self.assertEqual(json.loads(path.read_text()),{'old':True})
        self.assertEqual(set(self.root.iterdir()),before)
    def test_ambiguous_title_cannot_silently_create_third_identity(self):
        self.catalog.upsert({'title':'Synthetic equal title','doi':'10.1000/a'})
        self.catalog.upsert({'title':'Synthetic equal title','doi':'10.1000/b'})
        with self.assertRaisesRegex(ValueError,'多个身份'):
            self.catalog.upsert({'title':'Synthetic equal title'})

    def test_no_url_jobs_go_to_bounded_fallback_without_occupying_fast_slots(self):
        self.config['pdf_retrieval']['enabled']=True
        self.config['fetch_pipeline']['fallback_queue_limit']=2
        self.catalog.retain_discovery([self.record(i) for i in range(10)],{})
        added=queue_pending(self.catalog,self.config)
        self.assertEqual(len(added),2)
        self.assertTrue(all(j['kind']=='acquire_fallback' for j in self.catalog.jobs()))

    def test_discovery_timeout_restores_successful_pages_and_still_queues(self):
        def interrupted(module,payload,**kwargs):
            Path(payload['checkpoint_path']).write_text(json.dumps({'pool':[self.record()],
                'positions':{'v2:oa-topic:synthetic':{'cursor':'next'}},'raw':[],'warnings':[],'resolved':[]}))
            raise subprocess.TimeoutExpired(module,1)
        with patch('core.services.bridge',side_effect=interrupted):queued=discover_and_queue(self.catalog,self.config)
        self.assertEqual(len(queued),1)
        self.assertEqual(self.catalog.cursors()['v2:oa-topic:synthetic'],{'cursor':'next'})
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM discovery_pending').fetchone()[0],'queued')
        self.assertFalse(list((self.root/'discovery-checkpoints').glob('*.json')))

    def test_killed_process_checkpoint_survives_and_is_idempotent(self):
        path=self.root/'discovery-checkpoints/restart.json';path.parent.mkdir()
        path.write_text(json.dumps({'pool':[self.record()],'positions':{'opaque':'cursor'},'raw':[]}))
        restore_checkpoints(self.catalog,self.config);restore_checkpoints(self.catalog,self.config)
        self.assertEqual(len(self.catalog.pending_discovery()),1)
        self.assertEqual(Catalog(self.catalog.path).cursors()['opaque'],'cursor')

    def test_queue_bound_and_no_duplicate_download_jobs(self):
        self.config['fetch_pipeline']['queue_high_water']=2
        self.catalog.retain_discovery([self.record(i) for i in range(10)],{})
        self.assertEqual(len(queue_pending(self.catalog,self.config)),2)
        self.assertEqual(queue_pending(self.catalog,self.config),[])
        self.assertEqual(sum(j['kind']=='acquire' for j in self.catalog.jobs()),2)

    def test_fetch_schedule_is_independent_of_model_and_existing_downloads(self):
        pid=self.catalog.upsert(self.record());self.catalog.enqueue('screen',pid);self.catalog.enqueue('acquire',pid)
        scheduled=schedule_discovery(self.catalog,self.config)
        self.assertIsNotNone(scheduled);self.assertIsNone(schedule_discovery(self.catalog,self.config))

    def test_manual_rejection_cannot_be_requeued(self):
        record=self.record();pid=self.catalog.upsert(record);self.catalog.decide(pid,'reject')
        self.catalog.retain_discovery([record],{})
        self.assertEqual(queue_pending(self.catalog,self.config),[])

    def test_two_real_import_processes_safely_share_one_content_address(self):
        import pymupdf
        source=self.root/'source.pdf';doc=pymupdf.open();page=doc.new_page();page.insert_text((50,50),'Synthetic PDF with readable original evidence.');doc.save(source);doc.close()
        ids=[]
        for i in range(2):
            pid=self.catalog.upsert(self.record(i));ids.append(pid)
            self.catalog.enqueue('import',pid,{'source':str(source),'manual':True})
        fetch_loop(self.catalog,self.config,False,lambda:False)
        paths=[self.catalog.get(pid)['asset_path'] for pid in ids]
        self.assertTrue(all(paths));self.assertEqual(paths[0],paths[1])
        self.assertEqual(sum(j['kind']=='screen' for j in self.catalog.jobs()),2)
        self.assertFalse(list((self.root/'archive').rglob('*.part')))

    def test_slow_fallback_does_not_block_fast_slot(self):
        direct=self.catalog.upsert(self.record(1));slow=self.catalog.upsert(self.record(2))
        self.catalog.enqueue('acquire',direct);self.catalog.enqueue('acquire_fallback',slow)
        reached=threading.Event();release=threading.Event();source=self.root/'download.pdf';source.write_bytes(b'fixture')
        def run(catalog,config,job):
            if job['kind']=='acquire_fallback':
                reached.set();self.assertTrue(release.wait(4))
            else:
                self.assertTrue(reached.wait(4));release.set()
                catalog.update(job['paper_id'],asset_path=str(source),acquisition='available')
            return {'available':job['kind']=='acquire'}
        with patch('fetch.fetching.run_acquisition',side_effect=run):fetch_loop(self.catalog,self.config,False,lambda:False)
        self.assertTrue(reached.is_set());self.assertEqual(self.catalog.get(direct)['acquisition'],'available')

    def test_catalog_list_uses_one_connection_and_wal(self):
        for i in range(10):self.catalog.upsert(self.record(i))
        with patch.object(self.catalog,'connect',wraps=self.catalog.connect) as call:
            papers=self.catalog.list();self.assertEqual(call.call_count,1)
        self.assertEqual(len(papers),10)
        with self.catalog.connect() as db:self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'wal')


class VersionEvidenceTests(FetchFixtures):
    def test_versioned_arxiv_response_with_verified_identity_does_not_require_text_stamp(self):
        source=self.root/'arxiv.pdf';source.write_bytes(b'fixture')
        pid=self.catalog.upsert({**self.record(),'arxiv_id':'2401.00001','arxiv_version_id':'2401.00001v2'})
        with (patch('core.services.download',return_value='https://arxiv.org/pdf/2401.00001v2'),
              patch('core.services.verify_identity'),patch('core.services.validate_pdf',return_value='Organic triplet emitter measurement'),
              patch('core.services.store_asset',return_value=(str(source),'hash'))):
            acquisition(self.catalog,self.config,pid,stage='fast')
        paper=self.catalog.get(pid)
        self.assertEqual(paper['acquisition'],'available');self.assertEqual(paper['metadata']['asset_preprint_version'],'2401.00001v2')
        self.assertEqual(paper['metadata']['asset_version_basis'],'versioned_arxiv_url_and_verified_identity')

    def test_unversioned_final_url_keeps_pdf_and_explicit_version_uncertainty(self):
        source=self.root/'arxiv.pdf';source.write_bytes(b'fixture')
        pid=self.catalog.upsert({**self.record(),'arxiv_id':'2401.00001','arxiv_version_id':'2401.00001v2'})
        with (patch('core.services.download',return_value='https://repository.example/paper.pdf'),
              patch('core.services.verify_identity'),patch('core.services.validate_pdf',return_value='Original readable paper'),
              patch('core.services.store_asset',return_value=(str(source),'hash'))):
            acquisition(self.catalog,self.config,pid,stage='fast')
        paper=self.catalog.get(pid)
        self.assertEqual(paper['acquisition'],'available');self.assertEqual(paper['metadata']['asset_preprint_version'],'版本未核验')
        self.assertTrue(paper['metadata']['version_review_required'])


class KeeperTests(FetchFixtures):
    def test_python_keeper_restarts_killed_supervisor_and_can_stop(self):
        from fetch.fetch_service import start, status, request_stop
        from core.runtime import alive
        # No discovery is scheduled, and there are no candidate records or URLs.
        self.config['automatic_schedule_enabled']=False
        self.config['fetch_pipeline']['enabled']=True
        path=self.root/'config.json';path.write_text(json.dumps(self.config))
        def wait_for(test,timeout=15):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                if test():return
                time.sleep(.1)
            self.fail('isolated keeper condition timed out')
        try:
            result=start(self.config,path)
            self.assertEqual(result['state'],'running')
            self.assertTrue(start(self.config,path)['reused'])
            wait_for(lambda:status(self.config)['runtime'].get('state')=='running')
            original=status(self.config)['runtime']['pid']
            os.kill(original,signal.SIGKILL)
            wait_for(lambda:status(self.config)['runtime'].get('state')=='running' and status(self.config)['runtime'].get('pid')!=original)
            new=status(self.config)['runtime']['pid']
            self.assertNotEqual(new,original)
            request_stop(self.config)
            wait_for(lambda:status(self.config)['state']=='stopped')
            self.assertFalse(alive(new))
        finally:
            request_stop(self.config)
            try:owner=json.loads((self.root/'fetch-service.json').read_text())
            except (OSError,ValueError):owner={}
            for _ in range(40):
                if not owner.get('pid') or not alive(owner['pid']):break
                time.sleep(.1)
            if owner.get('pid') and alive(owner['pid']):os.kill(owner['pid'],signal.SIGTERM)


if __name__=='__main__':unittest.main()
