"""The probe never creates a session or sends a model request in these tests."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from browser.original_upload_http1 import OriginalPutProbe,matches,forward_headers

class OriginalUploadHTTP1(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.body=b'PK complete frozen ZIP';self.sha=hashlib.sha256(self.body).hexdigest()
        self.context={'lane':'review','job_id':'j','paper_id':'p','target_id':'T',
                      'bundle':{'zip_sha256':self.sha}}
        self.request=SimpleNamespace(method='PUT',url='https://sdmntprwestus.oaiusercontent.com/file?sig=secret',
             post_data_buffer=self.body,all_headers=lambda:{'Authorization':'private','Cookie':'session=private',
                 'Origin':'https://chatgpt.com','x-ms-blob-type':'BlockBlob','Host':'sdmntprwestus.oaiusercontent.com',
                 'Content-Length':str(len(self.body))})
        self.response=Mock(status=201);self.api=Mock();self.api.fetch.return_value=self.response
        self.probe=OriginalPutProbe(self.tmp.name,self.api,'once')
    def handle(self,probe=None,request=None,guard=lambda:None):
        page=Mock();probe=probe or self.probe;probe.arm(page,self.context,guard)
        route=Mock();route.request=request or self.request
        if page.route.called:page.route.call_args.args[1](route)
        return page,route
    def test_complete_original_bytes_headers_tls_identity_and_real_status(self):
        page,route=self.handle();kwargs=self.api.fetch.call_args.kwargs
        self.assertEqual(kwargs['data'],self.body);self.assertEqual(kwargs['method'],'PUT')
        self.assertEqual(kwargs['headers']['Authorization'],'private');self.assertEqual(kwargs['headers']['Cookie'],'session=private')
        self.assertNotIn('Host',kwargs['headers']);self.assertEqual((kwargs['max_retries'],kwargs['max_redirects']),(0,0))
        route.fulfill.assert_called_once_with(response=self.response);self.response.dispose.assert_called_once()
        text=self.probe.path.read_text();self.assertNotIn('secret',text);self.assertNotIn('private',text)
        self.assertEqual(json.loads(text)['status'],201)
        # Same running owner retries its request: no second transfer.
        route2=Mock(request=self.request);page.route.call_args.args[1](route2)
        route2.abort.assert_called_once();self.assertEqual(self.api.fetch.call_count,1)
    def test_restart_and_target_change_cannot_rearm_or_forward_original(self):
        self.handle();api=Mock();after=OriginalPutProbe(self.tmp.name,api,'once')
        self.context['target_id']='different-target'
        with self.assertRaisesRegex(RuntimeError,'持久意图'):self.handle(after)
        api.fetch.assert_not_called()
        original=Mock();after.restore({'T':original});route=Mock(request=self.request)
        original.route.call_args.args[1](route);route.abort.assert_called_once();api.fetch.assert_not_called()
    def test_unknown_response_has_no_fallback_or_retry(self):
        self.api.fetch.side_effect=TimeoutError('unknown receipt');page,route=self.handle()
        self.assertEqual(self.probe.read()['state'],'unknown');route.abort.assert_called_once();route.continue_.assert_not_called()
        self.assertEqual(self.api.fetch.call_count,1)
        route=Mock(request=self.request);page.route.call_args.args[1](route)
        self.assertEqual(self.api.fetch.call_count,1);route.abort.assert_called_once()

    def test_large_material_cannot_consume_small_probe_and_old_intent_still_blocks(self):
        probe=OriginalPutProbe(self.tmp.name,self.api,'small',max_zip_bytes=8_000_000)
        self.context['bundle']['size']=26_000_000
        self.assertFalse(probe.arm(Mock(),self.context,lambda:None));self.assertFalse(probe.reservation.exists())
        self.context['bundle']['size']=6_000_000
        page,route=self.handle(probe);self.assertTrue(probe.read()['fulfilled'])
        self.context['bundle']['size']=26_000_000
        with self.assertRaisesRegex(RuntimeError,'持久意图'):probe.arm(Mock(),self.context,lambda:None)
        self.assertEqual(self.api.fetch.call_count,1)

    def test_cancelled_transport_persists_unknown_and_does_not_replay(self):
        import asyncio
        self.api.fetch.side_effect=asyncio.CancelledError()
        page,route=self.handle();record=self.probe.read()
        self.assertEqual(record['state'],'unknown');self.assertEqual(record['error_type'],'CancelledError')
        route.abort.assert_called_once();self.assertEqual(self.api.fetch.call_count,1)
    def test_partial_unobservable_or_non_upload_request_is_not_experiment_success(self):
        page=Mock();self.probe.arm(page,self.context,lambda:None);handler=page.route.call_args.args[1]
        for body in (None,b'partial'):
            request=SimpleNamespace(**{**vars(self.request),'post_data_buffer':body});route=Mock(request=request)
            handler(route);route.continue_.assert_called_once()
        self.assertIsNone(self.probe.read());self.api.fetch.assert_not_called()
        for url,method in [('https://chatgpt.com/backend-api/conversation','POST'),
                           ('https://sdmntprwestus.oaiusercontent.com/x','POST'),
                           ('https://example.org/x','PUT'),('http://sdmntprwestus.oaiusercontent.com/x','PUT')]:
            self.assertFalse(matches(SimpleNamespace(url=url,method=method)))
    def test_header_mismatch_or_changed_guard_never_uses_transport(self):
        request=SimpleNamespace(**{**vars(self.request),'all_headers':lambda:{'Host':'evil.example'}})
        with self.assertRaises(ValueError):forward_headers(request,self.body)
        _,route=self.handle(request=request);route.abort.assert_called_once();self.api.fetch.assert_not_called()
        def stopped():raise RuntimeError('paused')
        _,route=self.handle(OriginalPutProbe(self.tmp.name,self.api,'stopped'),guard=stopped);route.abort.assert_called_once();self.api.fetch.assert_not_called()
    def test_intent_survives_crash_before_send_and_preserves_real_errors(self):
        self.assertTrue(self.probe.claim({'state':'intent','material_key':'old','target_id':'T','zip_sha256':self.sha}))
        self.assertFalse(OriginalPutProbe(self.tmp.name,self.api,'once').claim({'state':'intent'}))
        page,_=self.handle();page.route.assert_not_called();self.api.fetch.assert_not_called()
        other=OriginalPutProbe(self.tmp.name,self.api,'another-epoch');self.response.status=403
        self.handle(other);self.assertEqual(other.read()['status'],403)

    def test_next_material_is_reserved_even_when_service_worker_body_is_unobservable(self):
        page=Mock();self.assertTrue(self.probe.arm(page,self.context,lambda:None))
        self.context['job_id']='another-job'
        self.assertFalse(self.probe.arm(Mock(),self.context,lambda:None))
        self.api.fetch.assert_not_called();self.assertIsNone(self.probe.read())
        self.assertEqual(json.loads(self.probe.reservation.read_text())['job_id'],'j')

    def test_system_proxy_reuses_existing_https_proxy_and_keeps_bypass(self):
        from browser.original_upload_http1 import system_proxy
        text='''<dictionary> {
          ExceptionsList : <array> {
            0 : localhost,*.local,127.*
          }
          HTTPSEnable : 1
          HTTPSProxy : 127.0.0.1
          HTTPSPort : 7890
        }'''
        self.assertEqual(system_proxy(text),{'server':'http://127.0.0.1:7890','bypass':'localhost,*.local,127.*'})
        self.assertIsNone(system_proxy('<dictionary> {}'))
        with self.assertRaises(ValueError):system_proxy('HTTPSEnable : 1\nHTTPSProxy : bad/user\nHTTPSPort : 0')

    def test_network_error_evidence_never_copies_signed_url_or_auth_headers(self):
        from browser.original_upload_http1 import error_evidence
        detail=error_evidence(RuntimeError('write ECONNRESET https://host/path?sig=private Authorization: secret'))
        self.assertEqual(detail['error_codes'],['ECONNRESET'])
        self.assertNotIn('private',json.dumps(detail));self.assertNotIn('secret',json.dumps(detail))

    def test_unknown_intent_is_blocked_across_different_probe_epochs(self):
        self.api.fetch.side_effect=TimeoutError('ECONNRESET');self.handle()
        different=OriginalPutProbe(self.tmp.name,Mock(),'next-epoch')
        with self.assertRaisesRegex(RuntimeError,'持久意图'):different.arm(Mock(),self.context,lambda:None)
        from browser.original_upload_http1 import material_intent
        self.assertEqual(material_intent(self.tmp.name,'review','j','p',self.sha)['state'],'unknown')
        self.assertEqual(material_intent(self.tmp.name,'review','j','p',self.sha)['path'],str(self.probe.path))

    def test_preflight_blocks_an_armed_reservation_without_a_put(self):
        from browser.original_upload_http1 import material_intent
        self.assertTrue(self.probe.arm(Mock(),self.context,lambda:None))
        before=self.probe.reservation.read_bytes()
        record=material_intent(self.tmp.name,'review','j','p',self.sha)
        self.assertEqual(record['state'],'armed')
        self.assertEqual(record['path'],str(self.probe.reservation))
        self.assertFalse(self.probe.path.exists());self.api.fetch.assert_not_called()
        self.assertEqual(self.probe.reservation.read_bytes(),before)
        # A real intent still blocks the same material across epochs.
        key=hashlib.sha256(json.dumps(['review','j','p',self.sha],sort_keys=True).encode()).hexdigest()
        self.probe.claim({'state':'unknown','material_key':key,'target_id':'T','zip_sha256':self.sha})
        self.assertEqual(material_intent(self.tmp.name,'review','j','p',self.sha)['state'],'unknown')

    def test_old_reservation_does_not_block_a_different_material_identity(self):
        from browser.original_upload_http1 import material_intent
        self.assertTrue(self.probe.arm(Mock(),self.context,lambda:None))
        for lane,job,paper,sha in [('cards','j','p',self.sha),('review','new','p',self.sha),
                ('review','j','different',self.sha),('review','j','p','a'*64)]:
            self.assertIsNone(material_intent(self.tmp.name,lane,job,paper,sha))
        self.api.fetch.assert_not_called()

    def test_promotion_requires_real_response_and_native_settle_before_new_material(self):
        from browser.original_upload_http1 import OriginalPutUploads
        manager=OriginalPutUploads(self.tmp.name,self.api,'bounded-probe','system',promote=True)
        first=manager.for_material(self.context);self.handle(first)
        following={**self.context,'job_id':'another'}
        self.assertIs(manager.for_material(following),first)
        receipt=first.read();receipt['native_settled']=True;first.save(receipt)
        second=manager.for_material(following)
        self.assertIsNot(second,first);self.assertTrue(second.root.name.startswith('material-'))
        page=Mock();second.arm(page,following,lambda:None)
        changed=SimpleNamespace(**{**vars(self.request),'url':self.request.url.replace('secret','another-original')})
        route=Mock(request=changed);page.route.call_args.args[1](route)
        self.assertEqual(self.api.fetch.call_count,2)
        self.assertTrue(second.read()['fulfilled'])
        # A late retry of the first original URL is blocked by the newer handler.
        route=Mock(request=self.request);page.route.call_args.args[1](route)
        route.abort.assert_called_once();self.assertEqual(self.api.fetch.call_count,2)

    def test_multiple_historical_intents_on_one_target_all_get_restart_guards(self):
        from browser.original_upload_http1 import OriginalPutUploads
        one=OriginalPutProbe(self.tmp.name,self.api,'one');self.handle(one)
        two=OriginalPutProbe(self.tmp.name,self.api,'two');other={**self.context,'job_id':'another'}
        page=Mock();two.arm(page,other,lambda:None)
        changed=SimpleNamespace(**{**vars(self.request),'url':self.request.url.replace('secret','other')})
        page.route.call_args.args[1](Mock(request=changed))
        manager=OriginalPutUploads(self.tmp.name,Mock(),'new','system',promote=True);restarted=Mock()
        manager.restore({'T':restarted});handler=restarted.route.call_args.args[1]
        for request in (self.request,changed):
            route=Mock(request=request);handler(route);route.abort.assert_called_once()
        manager.restore({'T':restarted});restarted.route.assert_called_once()
