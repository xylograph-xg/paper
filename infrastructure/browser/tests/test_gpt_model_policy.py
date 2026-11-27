import unittest,tempfile,json
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from browser.gpt_model_policy import configure_session, model_quota, PRIMARY, FALLBACK

class ModelPolicyTests(unittest.TestCase):
 def test_native_temporary_home_requires_chat_menu_name(self):
  from browser.gpt_model_policy import verify_picker_mode
  page=Mock(url='https://chatgpt.com/?temporary-chat=true');picker=Mock()
  with patch('web_gpt.settings._chat') as chat,patch('web_gpt.settings._verify_mode') as ordinary,patch('playwright.sync_api.expect') as expect:
   chat.return_value.count.return_value=0
   verify_picker_mode(page,picker,True)
   rule=expect.return_value.to_have_accessible_name.call_args.args[0]
   self.assertTrue(rule.fullmatch('Select ChatGPT model'))
   self.assertFalse(rule.fullmatch('Choose model'))
   ordinary.assert_not_called()
   verify_picker_mode(page,picker,False)
   ordinary.assert_called_once_with(page,picker,15000)
 def test_file_quota_is_not_a_model_fallback(self):
  self.assertFalse(model_quota('GPT-6 你已达到文件附件数量限制'))
  self.assertTrue(model_quota('GPT-6 usage limit reached'))
 def test_primary_high_is_requested(self):
  with tempfile.TemporaryDirectory() as d,patch('browser.gpt_model_policy.configure',return_value={'model':PRIMARY,'effort':'High'}) as configure:
   s=configure_session(Mock(),d);configure.assert_called_once();self.assertEqual(configure.call_args.args[1],PRIMARY);self.assertEqual(s.settings['effort'],'High')
 def test_only_explicit_primary_model_quota_falls_back(self):
  page=Mock();page.locator.return_value.inner_text.return_value='GPT-6 usage limit reached'
  with tempfile.TemporaryDirectory() as d,patch('browser.gpt_model_policy.configure',side_effect=[RuntimeError('quota'),{'model':FALLBACK,'effort':'High'}]) as configure:
   s=configure_session(page,d);self.assertEqual(s.settings['model'],FALLBACK);self.assertEqual([c.args[1] for c in configure.call_args_list],[PRIMARY,FALLBACK])
   evidence=json.loads((Path(d)/'gpt-model-control.json').read_text());self.assertTrue(evidence['primary_quota']['probe_is_cooldown_not_website_reset'])
 def test_missing_model_or_generic_errors_do_not_silently_fall_back(self):
  page=Mock();page.locator.return_value.inner_text.return_value='home'
  with tempfile.TemporaryDirectory() as d,patch('browser.gpt_model_policy.configure',side_effect=RuntimeError('missing GPT-6')) as configure:
   with self.assertRaises(RuntimeError):configure_session(page,d)
   self.assertEqual(configure.call_count,1)
