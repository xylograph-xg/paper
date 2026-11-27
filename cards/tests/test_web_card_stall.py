"""Upload waiting budgets and unreadable-state guards; no real browser upload."""
import contextlib
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

from browser import upload_trace

UPLOAD_OK = {'ok': True, 'receipt_sufficient': True, 'failure_kind': None,
             'retryable_upload': False, 'stage': 'full_page_recheck', 'stages': [],
             'bundle': {}, 'settle': {}, 'attachment': {}}
UPLOAD_FAIL = {'ok': False, 'receipt_sufficient': False, 'failure_kind': 'write_failed',
               'retryable_upload': True, 'stage': 'attachment_write', 'stages': [],
               'bundle': {}, 'settle': {}, 'attachment': {}}

def _trace_temp(test):
    folder = tempfile.TemporaryDirectory()
    test.addCleanup(folder.cleanup)
    test.addCleanup(upload_trace.reset)
    upload_trace.configure(Path(folder.name))

class UploadWaiting(unittest.TestCase):
    def setUp(self):
        _trace_temp(self)
    def test_shared_upload_wait_uses_callers_budget(self):
        from web_gpt import core
        page=Mock();scope=Mock();file_input=Mock();file_input.is_disabled.return_value=False
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'synthetic.zip';path.write_bytes(b'synthetic package')
            with (patch('web_gpt.zip_uploads.prepare_upload_bundle',return_value={'zip_path':str(path)}),
                  patch.object(core,'wait_prompt_box'),patch.object(core,'_composer',return_value=scope),
                  patch.object(core,'_file_input',return_value=file_input),patch.object(core,'_probe_attachments',return_value=[]),
                  patch.object(core,'_wait_attachment_state',return_value=(object(),{'confirmed_new':True})),
                  patch.object(core,'_uploads_settled_state',return_value=(True,{'result':'settled'})) as settled,
                  patch.object(core,'_visible_progress',return_value=(0,False))):
                self.assertTrue(core.upload_files(page,[str(path)],timeout=180000))
                settled.assert_called_once_with(page,scope,timeout=180000)
    def test_hidden_first_progress_does_not_hide_a_visible_upload(self):
        from web_gpt import core
        page=Mock();scope=Mock();bars=Mock();bars.count.return_value=2
        bars.nth.side_effect=lambda i:SimpleNamespace(is_visible=lambda:False if i==0 else page.wait_for_timeout.call_count==0)
        scope.locator.return_value=bars
        self.assertTrue(core._uploads_settled(page,scope,timeout=1000))
        page.wait_for_timeout.assert_called_once_with(500)
    def test_upload_timeout_and_unreadable_state_are_not_ready(self):
        from web_gpt import core
        page=Mock();scope=Mock();bars=Mock();bars.count.return_value=1;bars.nth.return_value.is_visible.return_value=True;scope.locator.return_value=bars
        with patch.object(core.time,'monotonic',side_effect=[0,0,999999]):
            self.assertFalse(core._uploads_settled(page,scope,timeout=1000))
        scope.locator.side_effect=RuntimeError('Connection closed')
        settled,detail=core._uploads_settled_state(page,scope,timeout=60000)
        self.assertFalse(settled)
        self.assertEqual(detail['result'],'settle_unreadable')
        self.assertEqual(detail['rechecks'],core.SETTLE_READ_RECHECKS)
        self.assertFalse(core._uploads_settled(page,scope,timeout=60000))
    def test_pipeline_upload_failure_preserves_pre_click_boundary_and_budget(self):
        from browser.web_card_transport import submit_gpt_background
        callback=Mock();session=SimpleNamespace(_pending_answer=None,page=object(),verify_settings=lambda:None)
        with (patch('web_gpt.submission.submission_lock',return_value=contextlib.nullcontext()),
              patch('browser.web_card_transport.wait_gpt_upload_ready'),patch('web_gpt.core.upload_files_detailed',return_value=UPLOAD_FAIL) as upload):
            with self.assertRaisesRegex(RuntimeError,'附件上传失败'):
                submit_gpt_background(session,'prompt',['synthetic.zip'],on_before_send=callback,upload_timeout=180000)
        upload.assert_called_once_with(session.page,['synthetic.zip'],timeout=180000)
        callback.assert_not_called();self.assertIsNone(session._pending_answer)


if __name__=='__main__':unittest.main()
