import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from browser import upload_trace
from browser.local_file_upload import writer_for


class LocalFileUploadTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.path=self.root/'material.zip';self.path.write_bytes(b'original ZIP bytes')
        upload_trace.configure(self.root);self.addCleanup(upload_trace.reset)
        self.context={'local_file_paths':True,'target_id':'own','upload_attempt_id':'attempt',
            'bundle':{'zip_path':str(self.path),'size':self.path.stat().st_size,
                'zip_sha256':hashlib.sha256(self.path.read_bytes()).hexdigest()},'upload_diagnostic':{}}
        self.session=Mock();self.calls=[]
        def send(method,params=None):
            self.calls.append((method,params))
            if method=='Target.getTargetInfo':return {'targetInfo':{'targetId':'own'}}
            if method=='DOM.getDocument':return {'root':{'nodeId':1}}
            if method=='DOM.querySelector':return {'nodeId':7}
            return {}
        self.session.send.side_effect=send
        self.page=SimpleNamespace(context=Mock());self.page.context.new_cdp_session.return_value=self.session
        self.locator=Mock();self.guard=Mock()
        local=patch('browser.local_file_upload._local_browser');self.local=local.start();self.addCleanup(local.stop)

    def test_exact_input_gets_only_path_and_native_bytes_never_enter_protocol(self):
        writer_for(self.page,self.context,self.guard)(self.locator,str(self.path))
        assignments=[p for m,p in self.calls if m=='DOM.setFileInputFiles']
        self.assertEqual(assignments,[{'nodeId':7,'files':[str(self.path.resolve())]}])
        self.assertNotIn('original ZIP bytes',str(self.calls));self.locator.set_input_files.assert_not_called()
        self.assertEqual(self.guard.call_count,2);self.session.detach.assert_called_once()
        states=[json.loads(l)['state'] for l in (self.root/upload_trace.EVENTS_FILE).read_text().splitlines()]
        self.assertEqual(states,['intent','written'])

    def test_wrong_target_never_marks_or_writes_another_page(self):
        self.session.send.side_effect=lambda *a:{'targetInfo':{'targetId':'other'}}
        with self.assertRaisesRegex(ValueError,'target'):writer_for(self.page,self.context,self.guard)(self.locator,str(self.path))
        self.locator.evaluate.assert_not_called();self.locator.set_input_files.assert_not_called()

    def test_changed_zip_or_path_never_touches_browser(self):
        self.path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'指纹'):writer_for(self.page,self.context,self.guard)(self.locator,str(self.path))
        self.page.context.new_cdp_session.assert_not_called()

    def test_last_guard_pause_has_no_assignment_or_fallback(self):
        self.guard.side_effect=[None,RuntimeError('paused')]
        with self.assertRaisesRegex(RuntimeError,'paused'):writer_for(self.page,self.context,self.guard)(self.locator,str(self.path))
        self.assertFalse([m for m,p in self.calls if m=='DOM.setFileInputFiles'])
        self.locator.set_input_files.assert_not_called()

    def test_shadow_root_input_uses_object_id_when_light_dom_query_is_empty(self):
        def send(method,params=None):
            self.calls.append((method,params))
            if method=='Target.getTargetInfo':return {'targetInfo':{'targetId':'own'}}
            if method=='Runtime.evaluate':return {'result':{'objectId':'shadow-object'}}
            if method=='DOM.querySelector':return {'nodeId':0}
            return {}
        self.session.send.side_effect=send
        writer_for(self.page,self.context,self.guard)(self.locator,str(self.path))
        assignments=[p for m,p in self.calls if m=='DOM.setFileInputFiles']
        self.assertEqual(assignments,[{'files':[str(self.path.resolve())],'objectId':'shadow-object'}])
        self.assertNotIn('nodeId',assignments[0])
        self.assertEqual(self.context['upload_diagnostic']['local_file_write_node'],'objectId')

    def test_missing_node_and_object_use_bounded_playwright_fallback_before_write(self):
        def send(method,params=None):
            self.calls.append((method,params))
            if method=='Target.getTargetInfo':return {'targetInfo':{'targetId':'own'}}
            if method=='Runtime.evaluate':return {}
            if method=='DOM.getDocument':return {'root':{'nodeId':1}}
            if method=='DOM.querySelector':return {'nodeId':0}
            return {}
        self.session.send.side_effect=send
        writer_for(self.page,self.context,self.guard)(self.locator,str(self.path))
        self.locator.set_input_files.assert_called_once_with(str(self.path.resolve()))
        self.assertFalse([m for m,p in self.calls if m=='DOM.setFileInputFiles'])
        self.assertEqual(self.context['upload_diagnostic']['local_file_write_node'],'locator')

    def test_unknown_assignment_is_persisted_and_never_repeated(self):
        original=self.session.send.side_effect
        def send(method,params=None):
            if method=='DOM.setFileInputFiles':raise TimeoutError('unknown CDP receipt')
            return original(method,params)
        self.session.send.side_effect=send
        with self.assertRaises(TimeoutError):writer_for(self.page,self.context,self.guard)(self.locator,str(self.path))
        self.assertEqual(self.context['upload_diagnostic']['local_file_write_state'],'unknown')
        self.assertEqual(json.loads((self.root/upload_trace.EVENTS_FILE).read_text().splitlines()[-1])['state'],'unknown')
        self.locator.set_input_files.assert_not_called();self.session.detach.assert_called_once()

    def test_unconfirmed_local_process_does_not_disclose_path_to_browser(self):
        self.local.side_effect=ValueError('not local')
        with self.assertRaisesRegex(ValueError,'not local'):writer_for(self.page,self.context,self.guard)(self.locator,str(self.path))
        self.page.context.new_cdp_session.assert_not_called()

    def test_disabled_legacy_call_keeps_original_writer(self):
        self.assertIsNone(writer_for(self.page,{},self.guard))

    def kernel(self, writer, *, settled):
        from web_gpt import core
        locator=Mock();locator.is_disabled.return_value=False
        with (patch('web_gpt.zip_uploads.prepare_upload_bundle',return_value=self.context['bundle']),
                patch.object(core,'wait_prompt_box'),patch.object(core,'_composer'),
                patch.object(core,'_file_input',return_value=locator),
                patch.object(core,'_probe_attachments'),patch.object(core,'_dump_composer'),
                patch.object(core,'_wait_attachment_state',return_value=('ready',{'confirmed_new':True})),
                patch.object(core,'_uploads_settled_state',return_value=(settled,{'result':'settle_timeout'})) as settle,
                patch.object(core,'_visible_progress',return_value=(0,False))):
            result=core.upload_files_detailed(Mock(),[str(self.path)],timeout=180000,file_writer=writer)
        return result,locator,settle

    def test_custom_assignment_does_not_bypass_native_settlement(self):
        writer=Mock();result,locator,settle=self.kernel(writer,settled=False)
        self.assertFalse(result['ok']);self.assertEqual(result['failure_kind'],'settle_timeout')
        writer.assert_called_once();locator.set_input_files.assert_not_called()
        self.assertEqual(settle.call_args.kwargs['timeout'],180000)

    def test_kernel_never_falls_back_after_uncertain_custom_assignment(self):
        writer=Mock(side_effect=TimeoutError('unknown'))
        result,locator,settle=self.kernel(writer,settled=False)
        self.assertFalse(result['ok']);self.assertEqual(result['failure_kind'],'write_failed')
        writer.assert_called_once();locator.set_input_files.assert_not_called();settle.assert_not_called()
