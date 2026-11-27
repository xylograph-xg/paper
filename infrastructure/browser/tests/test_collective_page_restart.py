import unittest,tempfile,json,hashlib
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from browser.collective_page_restart import active, eligible, episode_targets
class Collective(unittest.TestCase):
 def test_live_upload_is_protected_even_after_original_client_timeout(self):
  from browser.shared_page_health import classify
  s={'target_id':'t','inspection_complete':True,'streaming':False,'uploading':True,
     'url':'https://chatgpt.com/','draft':'','attachments':1,'attachment_names':['original.zip']}
  r={'state':'not_sent','send_click_started':False,'finished':1,'target_id':'t'}
  h=classify(s,{'state':'needs_inspection'},r)
  self.assertEqual(h['health'],'uploading');self.assertFalse(h['replace_allowed'])
  self.assertTrue(h['evidence']['snapshot']['uploading'])
  self.assertFalse(eligible({'health':'dirty','evidence':{'snapshot':s}},{},r,[]))
 def test_retained_old_page_does_not_starve_new_mass_failures(self):
  policy={'collective_restart_enabled':True,'collective_min_pages':5}
  report={'checked_at':100,'counts':{'dirty':5},'pages':{t:{'health':'dirty'} for t in ['a','b','c','d','e','foreign']}}
  registered={'old','a','b','c','d','e'}
  self.assertEqual(episode_targets(policy,report,['old','retired'],registered,110),registered)
  self.assertEqual(episode_targets(policy,report,['old','retired'],registered,200),{'old'})
 def test_threshold_and_freshness(self):
  p={'collective_restart_enabled':True,'collective_min_pages':5}
  self.assertTrue(active(p,{'checked_at':100,'counts':{'dirty':5}},110))
  self.assertFalse(active(p,{'checked_at':100,'counts':{'dirty':4}},110))
  self.assertFalse(active(p,{'checked_at':0,'counts':{'dirty':20}},110))
 def test_only_bound_terminated_unsent_not_new_draft(self):
  with tempfile.TemporaryDirectory() as f:
   p=Path(f);text='原任务第一段\n材料正文';(p/'prompt-actual.txt').write_text(text);(p/'bundle.zip').write_bytes(b'original')
   r={'state':'not_sent','send_click_started':False,'finished':1,'target_id':'t','error':'附件上传失败','_ledger_path':str(p/'attempt.json'),'actual_prompt_sha256':hashlib.sha256(text.encode()).hexdigest(),'upload_bundle':{'zip_path':str(p/'bundle.zip'),'zip_sha256':hashlib.sha256(b'original').hexdigest()}}
   s={'target_id':'t','inspection_complete':True,'streaming':False,'url':'https://chatgpt.com/','draft':'原任务第一段','attachments':1,'attachment_names':['bundle.zip']};h={'health':'dirty','evidence':{'snapshot':s}}
   with patch('browser.collective_page_restart._uncollected_history',return_value=[]):
    self.assertTrue(eligible(h,{},r,[]))
    for change in [{'send_click_started':True},{'send_click_started':None},{'state':'submitted'}]:self.assertFalse(eligible(h,{},dict(r,**change),[]))
    for change in [{'draft':'用户新草稿'},{'quota':True},{'login':True},{'streaming':True},
                   {'attachment_names':['other.zip']},{'attachments':0,'attachment_names':['other.zip']},
                   {'draft':'你是独立论文阅读卡片评审。样本类型：另一份原任务'}]:
     self.assertFalse(eligible({'health':'dirty','evidence':{'snapshot':dict(s,**change)}},{},r,[]))
   with patch('browser.collective_page_restart._uncollected_history',return_value=['unknown']):self.assertFalse(eligible(h,{},r,[]))
 def test_missing_latest_prompt_does_not_strand_pipeline_failure(self):
  s={'target_id':'t','inspection_complete':True,'streaming':False,'url':'https://chatgpt.com/','draft':'你是独立论文阅读卡片评审。样本类型：mixed。旧任务','attachments':0}
  r={'state':'not_sent','send_click_started':False,'target_id':'t','_ledger_path':'/missing/attempt.json'}
  with patch('browser.collective_page_restart._uncollected_history',return_value=[]):
   self.assertTrue(eligible({'health':'dirty','evidence':{'snapshot':s}},{},r,[]))
   self.assertFalse(eligible({'health':'dirty','evidence':{'snapshot':s}},{},{**r,'send_click_started':None},[]))
 def test_never_used_slot_requires_initialization_evidence(self):
  s={'target_id':'t','inspection_complete':True,'streaming':False,'url':'https://chatgpt.com/','draft':'你是独立论文阅读卡片评审。样本类型：mixed。恢复草稿','attachments':0}
  with patch('browser.collective_page_restart._uncollected_history',return_value=[]):
   self.assertFalse(eligible({'health':'dirty','evidence':{'snapshot':s}},{'never_submitted':True},None,[]))
   self.assertTrue(eligible({'health':'dirty','evidence':{'snapshot':s}},{'never_submitted':True,'startup_request_id':'acknowledged'},None,[]))

 def test_unused_nonce_replacement_is_recoverable_after_restored_draft(self):
  s={'target_id':'t','inspection_complete':True,'streaming':False,'url':'https://chatgpt.com/','draft':'你是独立论文阅读卡片评审。样本类型：mixed。旧草稿','attachments':0}
  with patch('browser.collective_page_restart._uncollected_history',return_value=[]):
   self.assertTrue(eligible({'health':'dirty','evidence':{'snapshot':s}},{'never_submitted':True,'origin':'shared_page_health_repair','repair_id':'owner-nonce-registration'},None,[]))
   self.assertFalse(eligible({'health':'dirty','evidence':{'snapshot':s}},{'never_submitted':True,'repair_id':'unbound'},None,[]))

 def test_one_minute_unsent_timeout_and_changed_evidence(self):
  from browser.collective_page_restart import timed_unsent_restart
  s={'target_id':'t','inspection_complete':True,'streaming':False,'url':'https://chatgpt.com/','draft':'\n','attachments':0}
  h={'health':'dirty','evidence':{'snapshot':s,'fingerprint':'same'}}
  r={'state':'not_sent','send_click_started':False,'target_id':'t','finished':100,'_ledger_sha256':'ledger'}
  p={'stalled_unsent_after_seconds':60}
  with patch('browser.collective_page_restart._uncollected_history',return_value=[]):
   self.assertFalse(timed_unsent_restart(p,h,{},r,[],None,160))
   self.assertTrue(timed_unsent_restart(p,h,{},r,[],None,161))
   fresh={'health':'dirty','evidence':{'snapshot':s,'fingerprint':'changed'}}
   self.assertFalse(timed_unsent_restart(p,fresh,{},r,[],h,200))
   self.assertFalse(timed_unsent_restart(p,h,{},dict(r,state='submitted'),[],None,300))

 def test_numbered_attachment_alias_requires_exact_original_hash(self):
  with tempfile.TemporaryDirectory() as f:
   p=Path(f);(p/'bundle.zip').write_bytes(b'original')
   r={'state':'not_sent','send_click_started':False,'target_id':'t','_ledger_path':str(p/'attempt.json'),'upload_bundle':{'zip_path':str(p/'bundle.zip'),'zip_sha256':hashlib.sha256(b'original').hexdigest()}}
   s={'target_id':'t','inspection_complete':True,'streaming':False,'url':'https://chatgpt.com/','draft':'\n','attachments':1,'attachment_names':['bundle(1).zip']}
   h={'health':'dirty','evidence':{'snapshot':s}}
   with patch('browser.collective_page_restart._uncollected_history',return_value=[]):
    self.assertTrue(eligible(h,{},r,[]))
    (p/'bundle.zip').write_bytes(b'changed')
    self.assertFalse(eligible(h,{},r,[]))

class FailedNativeUpload(unittest.TestCase):
 def setUp(self):
  from browser.collective_page_restart import failed_upload_restart
  self.check=failed_upload_restart
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  text='原上传提示\n完整材料';(self.root/'prompt-actual.txt').write_text(text)
  (self.root/'source.pdf').write_bytes(b'source');(self.root/'bundle.zip').write_bytes(b'zip')
  self.record={'state':'not_sent','send_click_started':False,'owner_pid':123,'created':10,'finished':40,
   'target_id':'t','_ledger_path':str(self.root/'attempt.json'),'_ledger_sha256':'ledger',
   'inputs':{'source.pdf':hashlib.sha256(b'source').hexdigest()},'actual_prompt_sha256':hashlib.sha256(text.encode()).hexdigest(),
   'upload_bundle':{'zip_path':str(self.root/'bundle.zip'),'zip_sha256':hashlib.sha256(b'zip').hexdigest()}}
  self.snapshot={'target_id':'t','inspection_complete':True,'streaming':False,'uploading':True,
   'url':'https://chatgpt.com/','draft':text,'attachments':1,'attachment_names':['bundle.zip']}
  self.policy={'failed_upload_recovery_enabled':True,'stalled_after_seconds_by_lane':{'cards':60}}
  self.errors=[{'target_id':'t','at':30,'method':'PUT','failure':'net::ERR_HTTP2_PROTOCOL_ERROR'}]
  self.entry={'state':'needs_inspection'}
 def health(self,**changes):
  return {'health':'uploading','evidence':{'snapshot':dict(self.snapshot,**changes),'fingerprint':'page'}}
 def test_two_real_rounds_and_unchanged_upload_observation(self):
  h=self.health();self.assertFalse(self.check(self.policy,h,self.entry,self.record,[],self.errors,None,110))
  too_soon=self.health();self.assertFalse(self.check(self.policy,too_soon,self.entry,self.record,[],self.errors,h,139))
  after=self.health();self.assertTrue(self.check(self.policy,after,self.entry,self.record,[],self.errors,too_soon,140))
  self.assertTrue(after['evidence']['snapshot']['uploading']);self.assertTrue(after['failed_upload_network_proof'])
  changed=self.health();changed['evidence']['fingerprint']='changed'
  self.assertFalse(self.check(self.policy,changed,self.entry,self.record,[],self.errors,after,200))
 def test_sent_unknown_new_draft_active_or_changed_material_stays_protected(self):
  from browser.collective_page_restart import failed_upload_eligible as safe
  for change in [{'state':'submitted'},{'state':'needs_inspection'},{'send_click_started':None},
                 {'send_click_started':True},{'finished':None},{'owner_pid':None},{'inputs':{}}]:
   with self.subTest(record=change):self.assertFalse(safe(self.policy,self.health(),self.entry,dict(self.record,**change),[],self.errors,200))
  for change in [{'draft':'用户新草稿'},{'streaming':True},{'login':True},{'quota':True},
                 {'verification':True},{'user_texts':['already sent']},{'attachment_names':['other.zip']}]:
   with self.subTest(page=change):self.assertFalse(safe(self.policy,self.health(**change),self.entry,self.record,[],self.errors,200))
  self.assertFalse(safe(self.policy,self.health(),{'state':'uploading'},self.record,[],self.errors,200))
  (self.root/'source.pdf').write_bytes(b'changed')
  self.assertFalse(safe(self.policy,self.health(),self.entry,self.record,[],self.errors,200))
 def test_requires_explicit_switch_elapsed_deadline_and_matching_terminal_put(self):
  from browser.collective_page_restart import failed_upload_eligible as safe
  self.assertFalse(safe({},self.health(),self.entry,self.record,[],self.errors,200))
  self.assertFalse(safe(self.policy,self.health(),self.entry,self.record,[],self.errors,100))
  for events in [[],[dict(self.errors[0],target_id='foreign')],[dict(self.errors[0],at=9)],
                 [dict(self.errors[0],method='POST')],[dict(self.errors[0],failure=None,status=201)]]:
   self.assertFalse(safe(self.policy,self.health(),self.entry,self.record,[],events,200))
 def test_ended_legacy_upload_receipt_is_independent_of_lost_network_ring(self):
  from browser.collective_page_restart import failed_upload_eligible as safe
  record=dict(self.record,error='附件上传失败')
  health=self.health()
  self.assertTrue(safe(self.policy,health,self.entry,record,[],[],200))
  self.assertEqual(health['failed_upload_network_proof'],[])
  self.assertTrue(health['failed_upload_receipt_proof']['ended_upload'])
  self.assertFalse(safe(self.policy,self.health(),self.entry,dict(record,send_click_started=True),[],[],200))
