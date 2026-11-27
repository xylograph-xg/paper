import os,tempfile,unittest,zipfile
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch,MagicMock
from browser.web_upload_bundle import prepare_web_upload
from cards.web_card_inputs import digest

class WebBundleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  for name in ('source.pdf','visual.pdf','source-context.json','prompt.txt'):(self.root/name).write_text('synthetic '+name)
  self.packet={'files':['source.pdf','visual.pdf','source-context.json'],'input_hashes':{n:digest(self.root/n) for n in ('source.pdf','visual.pdf','source-context.json','prompt.txt')}}
 def test_shared_bundle_and_original_input_preserved(self):
  with patch.dict(os.environ,{'CODEX_CHAT_ZIP_DIR':str(self.root/'zips')}):bundle,prompt=prepare_web_upload(self.root,self.packet)
  self.assertIn('ZIP',prompt);self.assertEqual((self.root/'prompt.txt').read_text(),'synthetic prompt.txt')
  self.assertEqual(len(list((self.root/'zips').glob('*.zip'))),1)
  with zipfile.ZipFile(bundle['zip_path']) as z:
   for name in self.packet['files']:self.assertEqual(z.read(name),(self.root/name).read_bytes())
 def test_changed_frozen_input_blocks_pack(self):
  (self.root/'source.pdf').write_text('changed')
  with self.assertRaises(ValueError):prepare_web_upload(self.root,self.packet)
 def test_oversized_frozen_zip_is_rejected_before_browser_transfer(self):
  original={n:(self.root/n).read_bytes() for n in self.packet['input_hashes']}
  with patch('browser.web_upload_bundle.prepare_upload_bundle',return_value={'size':50*1024*1024+1}):
   with self.assertRaisesRegex(ValueError,'50MiB'):prepare_web_upload(self.root,self.packet)
  self.assertEqual(original,{n:(self.root/n).read_bytes() for n in self.packet['input_hashes']})
 def test_local_size_failure_cannot_pause_account_or_read_page(self):
  from browser.web_upload_bundle import UploadSizeError
  from browser.web_card_pool import record_channel_failure
  from unittest.mock import Mock
  router=Mock();page=Mock()
  record_channel_failure(router,UploadSizeError('local size capacity exceeded'),page)
  router.block.assert_not_called();page.locator.assert_not_called();page.evaluate.assert_not_called()
 def test_web_native_upload_receives_exactly_one_shared_zip(self):
  from web_gpt import core
  page=MagicMock();input=MagicMock();input.is_disabled.return_value=False
  with patch.dict(os.environ,{'CODEX_CHAT_ZIP_DIR':str(self.root/'zips')}),patch.object(core,'wait_prompt_box'),patch.object(core,'_composer'),patch.object(core,'_file_input',return_value=input),patch.object(core,'_probe_attachments'),patch.object(core,'_wait_attachment_state',return_value=('ready',{'confirmed_new':True})),patch.object(core,'_uploads_settled_state',return_value=(True,{'result':'settled'})),patch.object(core,'_visible_progress',return_value=(0,False)):
   self.assertTrue(core.upload_files(page,[str(self.root/n) for n in self.packet['files']]))
  input.set_input_files.assert_called_once()
  path=Path(input.set_input_files.call_args.args[0]);self.assertEqual(path.parent,(self.root/'zips').resolve());self.assertEqual(path.suffix,'.zip')
  self.assertEqual(page._web_gpt_upload_bundle['zip_path'],str(path))

class SettlingGuardTests(WebBundleTests):
 def test_zip_progress_timeout_blocks_send(self):
  from web_gpt import core
  page=MagicMock();input=MagicMock();input.is_disabled.return_value=False
  with patch.dict(os.environ,{'CODEX_CHAT_ZIP_DIR':str(self.root/'zips')}),patch.object(core,'wait_prompt_box'),patch.object(core,'_composer'),patch.object(core,'_file_input',return_value=input),patch.object(core,'_probe_attachments'),patch.object(core,'_wait_attachment_state',return_value=('ready',{'confirmed_new':True})),patch.object(core,'_uploads_settled_state',return_value=(False,{'result':'settle_timeout'})):
   self.assertFalse(core.upload_files(page,[str(self.root/'source.pdf')]))
  with patch.dict(os.environ,{'CODEX_CHAT_ZIP_DIR':str(self.root/'zips')}),patch.object(core,'wait_prompt_box'),patch.object(core,'_composer'),patch.object(core,'_file_input',return_value=input),patch.object(core,'_probe_attachments'),patch.object(core,'_wait_attachment_state',return_value=('ready',{'confirmed_new':True})),patch.object(core,'_uploads_settled_state',return_value=(True,{'result':'settled'})),patch.object(core,'_visible_progress',return_value=(1,True)):
   result=core.upload_files_detailed(page,[str(self.root/n) for n in self.packet['files']])
   self.assertTrue(result['ok']);self.assertFalse(result['receipt_sufficient'])

if __name__=='__main__':unittest.main()
