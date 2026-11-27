import unittest,tempfile
from core.api import paths__WorkspacePath as Path
from browser.stall_timeouts import timeout_seconds
from browser.collective_page_restart import timed_unsent_restart
from unittest.mock import patch

class DistributionTimeout(unittest.TestCase):
 def setUp(self):self.policy={'stalled_after_seconds_by_lane':{'cards':210,'review':150,'correction':300}}
 def test_each_lane_uses_its_own_threshold_and_not_fixed_sixty_seconds(self):
  snap={'target_id':'t','url':'https://chatgpt.com/','inspection_complete':True,'streaming':False,'draft':'\n'}
  record={'state':'not_sent','send_click_started':False,'target_id':'t','finished':100}
  with patch('browser.collective_page_restart._uncollected_history',return_value=[]):
   for lane,limit in self.policy['stalled_after_seconds_by_lane'].items():
    h={'health':'dirty','evidence':{'snapshot':snap,'fingerprint':'same'}}
    self.assertFalse(timed_unsent_restart(self.policy,h,{'kind':lane},record,[],None,100+limit))
    self.assertTrue(timed_unsent_restart(self.policy,h,{'kind':lane},record,[],None,101+limit))
 def test_review_identity_fallback_and_legacy_policy(self):
  self.assertEqual(timeout_seconds(self.policy,{}, {'review_id':'r'}),150)
  self.assertEqual(timeout_seconds({'stalled_unsent_after_seconds':60},{'kind':'correction'}),60)
 def test_unknown_fallback_also_waits_distribution_deadline(self):
  from browser.shared_page_repair import stalled_page_fallback
  config={'web_cards':{'shared_window':{'health_repair':{**self.policy,'replace_unrecoverable_pages':True,'stalled_check_rounds':2}}}}
  h={'health':'unknown','evidence':{'snapshot':{'target_id':'t','inspection_complete':True,'streaming':False}},
     'bounded_recheck':{'first_seen':100,'rounds':2,'state':'still_protected','reads':1}}
  self.assertFalse(stalled_page_fallback(config,h,{'kind':'review'}, {'target_id':'t'},at=250))
  self.assertTrue(stalled_page_fallback(config,h,{'kind':'review'}, {'target_id':'t'},at=251))
