import unittest,hashlib
from unittest.mock import patch
from browser.authorized_unsent_restore import validate
class AuthorizedRestore(unittest.TestCase):
 def setUp(self):
  self.item={'failed_owner_pid':43520,'target_id':'t','ledger_sha256':'ledger','prompt_sha256':'prompt','draft_sha256':hashlib.sha256('draft'.encode()).hexdigest()}
  self.record={'state':'not_sent','send_click_started':False,'owner_pid':43520,'target_id':'t','_ledger_sha256':'ledger','actual_prompt_sha256':'prompt'}
  self.snapshot={'inspection_complete':True,'streaming':False,'user_texts':[],'answer_texts':[],'url':'https://chatgpt.com/','draft':'draft'}
 def test_exact_identity_bound_unsent_allowed(self):
  with patch('browser.authorized_unsent_restore._uncollected_history',return_value=[]):validate(self.item,self.record,self.snapshot,[])
 def test_protect_changed_or_unknown_receipts(self):
  with patch('browser.authorized_unsent_restore._uncollected_history',return_value=[]):
   for change in [{'send_click_started':True},{'send_click_started':None},{'state':'submitted'},{'owner_pid':1},{'target_id':'other'},{'_ledger_sha256':'changed'}]:
    with self.subTest(change=change),self.assertRaises(ValueError):validate(self.item,{**self.record,**change},self.snapshot,[])
  with patch('browser.authorized_unsent_restore._uncollected_history',return_value=['old']),self.assertRaises(ValueError):validate(self.item,self.record,self.snapshot,[])
 def test_protect_new_draft_or_activity_or_account(self):
  with patch('browser.authorized_unsent_restore._uncollected_history',return_value=[]):
   for change in [{'draft':'new'},{'streaming':True},{'user_texts':['message']},{'answer_texts':['answer']},{'login':True},{'verification':True},{'quota':True},{'inspection_complete':False}]:
    with self.subTest(change=change),self.assertRaises(ValueError):validate(self.item,self.record,{**self.snapshot,**change},[])
