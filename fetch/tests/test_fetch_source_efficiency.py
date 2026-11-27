"""Cross-channel cooldown, cache and retry regressions. No live DB or HTTP."""
import io
import json
import os
import time
import unittest
from unittest.mock import Mock,patch

from fetch.tests.test_fetch_pipeline import FetchFixtures
from fetch import network; from fetch import metadata_cache
from fetch.fetchpdf_bridge import install_http_guards
from fetch.fetch_policy import begin, finish, record_url
from fetch.fetching import queue_pending


class SourceEfficiencyTests(FetchFixtures):
    def setUp(self):
        super().setUp()
        env=patch.dict(os.environ,{'PAPER_NETWORK_STATE_DIR':str(self.root),'PAPER_METADATA_CACHE_ENABLED':'1'})
        env.start();self.addCleanup(env.stop)

    def send(self,url,response=None,*,pace_error=None):
        import requests
        response=response or Mock(status_code=200,headers={},content=b'{"title":"Organic triplet emitter"}')
        response.iter_content.return_value=[response.content] if isinstance(response.content,bytes) else []
        attempts=[];stats={}
        with patch('core.services.public_url'),patch('fetch.public_http.requests_adapter'),patch('fetch.network.pace'), \
             patch('fetch.net_limits.pace_arxiv',side_effect=pace_error),patch('fetch.acquisition_budget.remaining',return_value=120), \
             patch('requests.sessions.Session.send',return_value=response) as transport:
            original=install_http_guards(True,attempts,stats)
            try:
                try:result=requests.Session().send(requests.Request('GET',url).prepare())
                except network.DeferredRequest:result=None
            finally:requests.sessions.Session.send=original
        return result,attempts,stats,transport.call_count

    def target(self,errors):
        record=self.record();self.catalog.retain_discovery([record],{})
        pid=self.catalog.upsert(record);begin(self.catalog,self.catalog.get(pid),self.config,record['doi'])
        self.catalog.event(pid,'acquisition_pending',{'attempts':errors})
        finish(self.catalog,pid,False,'fallback',self.config)
        with self.catalog.connect() as db:return dict(db.execute('SELECT * FROM fetch_targets WHERE paper_id=?',(pid,)).fetchone())

    def test_fallback_429_blocks_native_discovery_and_records_actual_request(self):
        response=Mock(status_code=429,headers={'Retry-After':'3600'})
        _,errors,stats,calls=self.send('https://api.crossref.org/works/10.1000/test',response)
        self.assertEqual(calls,1);self.assertEqual(stats['requests_started'],1)
        self.assertTrue(errors[0]['request_started']);self.assertGreater(errors[0]['retry_at'],time.time()+3500)
        with self.assertRaises(network.DeferredRequest):network.ready('crossref',self.root)
        with patch('fetch.network.urllib.request.urlopen') as get:
            with self.assertRaises(network.DeferredRequest):network.ProviderClient(self.root).get('https://api.crossref.org/works/10.1000/other',provider='crossref')
            get.assert_not_called()

    def test_legacy_api_cooldown_and_slot_are_respected_without_shortening(self):
        until=time.time()+86400
        (self.root/'network-state.json').write_text(json.dumps({'pdf:api.openalex.org':{'retry_at':until,'failures':4,'updated':time.time(),'slot':time.time()+10}}))
        with self.assertRaises(network.DeferredRequest):network.ready('openalex',self.root)
        self.assertGreaterEqual(network.failed('openalex',503,folder=self.root),until)
        with patch('fetch.network.time.sleep') as sleep:
            with self.assertRaises(network.DeferredRequest):network.pace('openalex',1,self.root)
            sleep.assert_not_called()

    def test_success_cannot_clear_newer_failure_under_other_alias(self):
        started=time.time()-10;network.failed('pdf:api.crossref.org',403,folder=self.root)
        network.succeeded('crossref',self.root,started)
        with self.assertRaises(network.DeferredRequest):network.ready('crossref',self.root)

    def test_publisher_subdomains_are_independent(self):
        network.failed('pdf:api.publisher.test',403,folder=self.root)
        network.ready('pdf:publisher.test',self.root)

    def test_host_pacing_is_recorded_without_network_or_budget_consumption(self):
        wait=network.DeferredRequest('pdf:publisher.test',time.time()+3,reason='pacing')
        _,errors,stats,calls=self.send('https://publisher.test/a.pdf',pace_error=wait)
        self.assertEqual(calls,0);self.assertFalse(stats.get('requests_started',0))
        self.assertEqual(errors[0]['kind'],'resource_wait');self.assertFalse(errors[0]['request_started'])

    def test_metadata_uses_one_provider_pace_and_not_pdf_host_pace(self):
        import requests
        response=Mock(status_code=200,headers={},content=b'{}');response.iter_content.return_value=[b'{}']
        with patch('core.services.public_url'),patch('fetch.public_http.requests_adapter'), \
             patch('fetch.network.pace') as pace,patch('fetch.net_limits.pace_arxiv') as pdf_pace, \
             patch('requests.sessions.Session.send',return_value=response):
            original=install_http_guards()
            try:requests.Session().send(requests.Request('GET','https://api.crossref.org/works/10.1000/test').prepare())
            finally:requests.sessions.Session.send=original
        pace.assert_called_once_with('crossref',1.1);pdf_pace.assert_not_called()

    def test_pure_source_wait_with_summary_consumes_no_target_attempt(self):
        at=time.time();target=self.target([
            {'kind':'deferred','request_started':False,'code':429,'retry_at':at+120,'provider':'s2'},
            {'kind':'deferred','request_started':False,'code':403,'retry_at':at+86400,'provider':'pdf:publisher.test'},
            {'kind':'not_found','aggregate':True,'request_started':False}])
        self.assertEqual(target['attempts'],0);self.assertEqual(target['state'],'ready')
        self.assertAlmostEqual(target['retry_at'],at+120,places=3)
        with self.assertRaises(network.DeferredRequest):
            network.failed('pdf:publisher.test',403,folder=self.root);network.ready('pdf:publisher.test',self.root)

    def test_actual_failed_request_keeps_attempt_and_uses_earlier_eligible_source(self):
        at=time.time();target=self.target([
            {'kind':'http_error','request_started':True,'code':429,'retry_at':at+3600},
            {'kind':'deferred','request_started':False,'code':403,'retry_at':at+86400},
            {'kind':'not_found','aggregate':True,'request_started':True}])
        self.assertEqual(target['attempts'],1);self.assertEqual(target['state'],'ready')
        self.assertAlmostEqual(target['retry_at'],at+3600,places=3)

    def test_unknown_or_legacy_receipt_retains_latest_clock_and_attempt(self):
        at=time.time();target=self.target([
            {'kind':'deferred','code':429,'retry_at':at+86400},
            {'kind':'deferred','request_started':False,'code':429,'retry_at':at+120}])
        self.assertEqual(target['attempts'],1);self.assertGreaterEqual(target['retry_at'],at+86400)

    def test_unobserved_other_source_prevents_no_request_budget_refund(self):
        target=self.target([
            {'kind':'deferred','request_started':False,'code':429,'retry_at':time.time()+120},
            {'kind':'not_found','aggregate':True,'url':'osti:doi'},
            {'kind':'not_found','aggregate':True,'request_started':False,'url':'fetchpdf:multi-source'}])
        self.assertEqual(target['attempts'],1);self.assertEqual(target['state'],'ready')

    def test_pure_permission_wait_does_not_unpause_source_or_probe_early(self):
        at=time.time();target=self.target([{'kind':'deferred','code':403,'retry_at':at+86400,'request_started':False}])
        self.assertEqual(target['attempts'],0);self.assertGreaterEqual(target['retry_at'],at+86400)

    def test_actual_not_found_is_still_terminal(self):
        target=self.target([{'kind':'not_found','request_started':True}])
        self.assertEqual(target['state'],'terminal');self.assertEqual(target['attempts'],1)

    def test_terminal_changed_after_claim_is_not_revived_by_wait(self):
        pid=self.catalog.upsert(self.record());begin(self.catalog,self.catalog.get(pid),self.config)
        self.catalog.event(pid,'acquisition_pending',{'attempts':[{'kind':'resource_wait','request_started':False,'retry_at':time.time()+3}]})
        with self.catalog.connect() as db:db.execute("UPDATE fetch_targets SET state='terminal',retry_at=12345678999 WHERE paper_id=?",(pid,))
        finish(self.catalog,pid,False,'fallback',self.config)
        with self.catalog.connect() as db:row=db.execute('SELECT * FROM fetch_targets').fetchone()
        self.assertEqual(row['state'],'terminal');self.assertEqual(row['retry_at'],12345678999);self.assertEqual(row['attempts'],1)

    def test_actual_direct_429_is_not_misclassified_as_pre_request_wait(self):
        import urllib.error
        from core.services import _download
        error=urllib.error.HTTPError('https://publisher.test/a.pdf',429,'limited',{'Retry-After':'120'},None)
        with patch('core.services.public_url'),patch('fetch.net_limits.pace_arxiv'),patch('fetch.public_http.opener') as opener:
            opener.return_value.open.side_effect=error
            with self.assertRaises(network.DeferredRequest) as failure:_download(error.url,self.root/'file.pdf')
        self.assertTrue(failure.exception.request_started);self.assertEqual(failure.exception.reason,'http')

    def test_pre_request_url_wait_does_not_count_as_actual_permission_failure(self):
        pid=self.catalog.upsert(self.record());begin(self.catalog,self.catalog.get(pid),self.config)
        record_url(self.catalog,pid,'https://publisher.test/a.pdf','prior host cooldown',kind='deferred',code=403,request_started=False,retry_at=time.time()+10)
        with self.catalog.connect() as db:row=db.execute('SELECT * FROM fetch_urls').fetchone()
        self.assertEqual(row['attempts'],0);self.assertEqual(row['failure_class'],'transient')

    def test_terminal_is_blocked_before_insert_without_changing_ledger(self):
        record=self.record();self.catalog.retain_discovery([record],{});pid=self.catalog.upsert(record)
        begin(self.catalog,self.catalog.get(pid),self.config,record['doi'])
        with self.catalog.connect() as db:db.execute("UPDATE fetch_targets SET state='terminal',retry_at=? WHERE paper_id=?",(time.time()+86400,pid))
        self.assertEqual(queue_pending(self.catalog,self.config),[])
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM discovery_pending').fetchone()[0],'blocked_fetch')
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)

    def test_ready_exhausted_same_input_is_not_repeatedly_queued(self):
        record=self.record();self.catalog.retain_discovery([record],{});pid=self.catalog.upsert(record)
        begin(self.catalog,self.catalog.get(pid),self.config,record['doi'])
        with self.catalog.connect() as db:db.execute("UPDATE fetch_targets SET state='ready',attempts=6,retry_at=0 WHERE paper_id=?",(pid,))
        self.assertEqual(queue_pending(self.catalog,self.config),[]);self.assertEqual(queue_pending(self.catalog,self.config),[])
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT state FROM discovery_pending').fetchone()[0],'blocked_fetch')
            row=db.execute('SELECT state,attempts,retry_at FROM fetch_targets').fetchone()
            self.assertEqual(tuple(row),('ready',6,0))

    def test_new_input_can_still_reach_original_policy_reset(self):
        record=self.record();self.catalog.retain_discovery([record],{});pid=self.catalog.upsert(record)
        begin(self.catalog,self.catalog.get(pid),self.config,record['doi'])
        with self.catalog.connect() as db:db.execute("UPDATE fetch_targets SET attempts=6,retry_at=0 WHERE paper_id=?",(pid,))
        queue_pending(self.catalog,self.config)
        record['pdf_urls']=['https://publisher.test/new.pdf'];self.catalog.retain_discovery([record],{})
        self.assertEqual(len(queue_pending(self.catalog,self.config)),1)

    def test_insert_race_cancellation_is_not_reported_or_overwritten_as_queued(self):
        record=self.record();self.catalog.retain_discovery([record],{});pid=self.catalog.upsert(record)
        enqueue=self.catalog.enqueue
        def cancelled(*args,**kwargs):
            jid=enqueue(*args,**kwargs)
            with self.catalog.connect() as db:
                db.execute("UPDATE jobs SET state='cancelled' WHERE id=?",(jid,))
                db.execute("UPDATE discovery_pending SET state='blocked_fetch' WHERE key=?",(record['doi'],))
            return jid
        with patch.object(self.catalog,'enqueue',side_effect=cancelled):self.assertEqual(queue_pending(self.catalog,self.config),[])
        with self.catalog.connect() as db:self.assertEqual(db.execute('SELECT state FROM discovery_pending').fetchone()[0],'blocked_fetch')

    def test_native_success_is_reused_by_fallback_even_during_cooldown(self):
        url='https://api.crossref.org/works/10.1000/test';body=b'{"message":{"DOI":"10.1000/test"}}'
        with patch('fetch.network.pace'),patch('fetch.network.urllib.request.urlopen',return_value=io.BytesIO(body)) as get:
            result=network.ProviderClient(self.root).get(url,provider='crossref');self.assertEqual(result['message']['DOI'],'10.1000/test')
            get.assert_called_once()
        network.failed('crossref',429,{'Retry-After':'3600'},self.root)
        response,errors,stats,calls=self.send(url+'?mailto=secret@example.test')
        self.assertEqual(calls,0);self.assertEqual(stats['cache_hits'],1);self.assertEqual(errors,[])
        self.assertEqual(response.json()['message']['DOI'],'10.1000/test')
        with self.assertRaises(network.DeferredRequest):network.ready('crossref',self.root)

    def test_fallback_success_is_reused_by_native_with_no_extra_http(self):
        url='https://api.openalex.org/works/W1';self.send(url)
        with patch('fetch.network.urllib.request.urlopen') as get:
            value=network.ProviderClient(self.root).get(url,provider='openalex')
            get.assert_not_called();self.assertIn('title',value)

    def test_failed_http_never_populates_cache(self):
        url='https://api.crossref.org/works/10.1000/test'
        self.send(url,Mock(status_code=403,headers={},content=b'{"error":"denied"}'))
        self.assertIsNone(metadata_cache.read(url,self.root))

    def test_cache_rejects_corruption_expiry_and_other_doi(self):
        url='https://api.crossref.org/works/10.1000/test';self.assertTrue(metadata_cache.write(url,b'{"message":{}}',self.root))
        self.assertIsNone(metadata_cache.read('https://api.crossref.org/works/10.1000/other',self.root))
        path=metadata_cache.location(metadata_cache.identity(url),self.root);saved=json.loads(path.read_text())
        path.write_text(json.dumps({**saved,'body':'{"message":{"DOI":"wrong"}}'}));self.assertIsNone(metadata_cache.read(url,self.root))
        path.write_text(json.dumps({**saved,'created':time.time()-86401}));self.assertIsNone(metadata_cache.read(url,self.root))

    def test_cache_excludes_credentials_pdf_and_non_json_and_respects_switch(self):
        url='https://api.crossref.org/works/10.1000/test?api_key=private&mailto=secret&select=DOI'
        self.assertTrue(metadata_cache.write(url,b'{"message":{}}',self.root))
        content=''.join(p.read_text() for p in (self.root/'metadata-response-cache').glob('*.json'))
        self.assertNotIn('private',content);self.assertNotIn('secret',content)
        self.assertFalse(metadata_cache.write('https://publisher.test/a.pdf',b'%PDF',self.root))
        self.assertFalse(metadata_cache.write(url,b'<html>login</html>',self.root))
        with patch.dict(os.environ,{'PAPER_METADATA_CACHE_ENABLED':'0'}):self.assertIsNone(metadata_cache.read(url,self.root))

    def test_cache_honors_server_no_store_and_shorter_expiration(self):
        url='https://api.crossref.org/works/10.1000/test'
        for control in ('no-store','private, max-age=600','no-cache','max-age=0'):
            self.assertFalse(metadata_cache.write(url,b'{}',self.root,{'Cache-Control':control}))
        self.assertTrue(metadata_cache.write(url,b'{}',self.root,{'Cache-Control':'max-age=5'}))
        with patch('fetch.metadata_cache.time.time',return_value=time.time()+6):self.assertIsNone(metadata_cache.read(url,self.root))

    def test_cache_cleanup_uses_only_cache_directory_and_keeps_newest_under_budget(self):
        folder=self.root/'metadata-response-cache';folder.mkdir();raw=self.root/'original.pdf';raw.write_bytes(b'protected')
        old=folder/'old.json';new=folder/'new.json';old.write_bytes(b'1234');new.write_bytes(b'5678')
        os.utime(old,(time.time()-86401,time.time()-86401))
        with patch('fetch.metadata_cache.CACHE_BYTES',4):metadata_cache.prune(folder)
        self.assertFalse(old.exists());self.assertTrue(new.exists());self.assertEqual(raw.read_bytes(),b'protected')


if __name__=='__main__':unittest.main()
