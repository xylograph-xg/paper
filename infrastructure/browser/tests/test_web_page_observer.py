import asyncio,json,os,tempfile,time,unittest
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace
from browser.web_page_observer import PageObserver, INTERVAL, response_identity

class ObserverScheduleTests(unittest.IsolatedAsyncioTestCase):
 async def test_network_evidence_is_owned_upload_errors_only_and_removes_signed_urls(self):
  from unittest.mock import Mock
  with tempfile.TemporaryDirectory() as d:
   o=PageObserver(d,SimpleNamespace(_loop=asyncio.get_running_loop()))
   page=Mock();other=Mock();o.pages={'own':page,'other':other};o.window_targets={'own'}
   request=SimpleNamespace(url='https://files.oaiusercontent.com/files/secret?sig=private-token',method='PUT',resource_type='fetch',failure='net::ERR_CONNECTION_RESET')
   o._network_event('other',other,request)
   o._network_event('own',page,request,200)
   self.assertFalse(getattr(o,'_network_events',[]))
   o._network_event('own',page,request,403)
   o._network_event('own',page,request)
   self.assertEqual(len(o._network_events),2)
   self.assertNotIn('private-token',json.dumps(o._network_events));self.assertNotIn('/secret',json.dumps(o._network_events))
   self.assertEqual(o._network_events[-1]['failure'],'net::ERR_CONNECTION_RESET')
 async def test_network_hooks_follow_original_registered_pages_without_browser_calls(self):
  from unittest.mock import Mock
  with tempfile.TemporaryDirectory() as d:
   o=PageObserver(d,SimpleNamespace(_loop=asyncio.get_running_loop()));page=Mock()
   o.pages={'own':page};o.window_targets={'own'};o._update_network_pages()
   self.assertEqual(page.on.call_count,4)
   self.assertEqual({call.args[0] for call in page.on.call_args_list},{'request','response','requestfailed','requestfinished'})
   o.pages={};o._update_network_pages();self.assertEqual(page.remove_listener.call_count,4)
   self.assertFalse(o._network_pages)
 async def test_successful_transfer_receipts_keep_original_attempt_without_settling_or_cooldown(self):
  from unittest.mock import Mock
  from browser import upload_trace
  with tempfile.TemporaryDirectory() as d:
   upload_trace.configure(Path(d));self.addCleanup(upload_trace.reset)
   o=PageObserver(d,SimpleNamespace(_loop=asyncio.get_running_loop()));page=Mock()
   o.pages={'own':page};o.window_targets={'own'};o.on_upload_network_failure=Mock()
   req=SimpleNamespace(_guid='original-request',url='https://files.oaiusercontent.com/files/x?sig=private',method='PUT',resource_type='fetch',failure=None)
   first=upload_trace.begin(target_id='own');o._network_event('own',page,req,phase='request')
   upload_trace.finish(first['upload_attempt_id'],result='failed',failure_kind='settle_timeout')
   second=upload_trace.begin(target_id='own');ring=list(o._network_events);o.on_upload_network_failure.reset_mock()
   o._network_event('own',page,req,201,phase='response');o._network_event('own',page,req,phase='requestfinished')
   lines=[json.loads(x) for x in (Path(d)/upload_trace.EVENTS_FILE).read_text().splitlines()]
   proof=[x for x in lines if x.get('kind')=='network'][-2:]
   self.assertEqual([x['phase'] for x in proof],['response','requestfinished'])
   self.assertEqual(proof[0]['status'],201)
   self.assertTrue(all(x['upload_attempt_id']==first['upload_attempt_id'] for x in proof))
   self.assertEqual(upload_trace.active('own'),second['upload_attempt_id'])
   self.assertEqual(o._network_events,ring);o.on_upload_network_failure.assert_not_called()
   self.assertNotIn('private',json.dumps(proof))
 async def test_late_upload_response_keeps_the_attempt_bound_when_it_started(self):
  """Attribution follows the request, never the target's newest task."""
  from unittest.mock import Mock
  from browser import upload_trace
  with tempfile.TemporaryDirectory() as d:
   upload_trace.configure(Path(d));self.addCleanup(upload_trace.reset)
   o=PageObserver(d,SimpleNamespace(_loop=asyncio.get_running_loop()));page=Mock()
   o.pages={'own':page};o.window_targets={'own'}
   def request(key):return SimpleNamespace(_guid=key,url='https://files.oaiusercontent.com/files/secret?sig=private',
     method='PUT',resource_type='fetch',failure=None)
   first=upload_trace.begin(target_id='own',zip_path='/tmp/one.zip')
   o._network_event('own',page,request('guid-1'),phase='request')
   second=upload_trace.begin(target_id='own',zip_path='/tmp/two.zip')
   self.assertEqual(upload_trace.active('own'),second['upload_attempt_id'])
   o._network_event('own',page,request('guid-1'),404)
   o._network_event('own',page,request('guid-2'),phase='request')
   o._network_event('own',page,request('guid-2'),404)
   bound=[json.loads(line) for line in (Path(d)/upload_trace.EVENTS_FILE).read_text().splitlines()]
   network=[line for line in bound if line['kind']=='network']
   self.assertEqual([line['upload_attempt_id'] for line in network],
                    [first['upload_attempt_id'],first['upload_attempt_id'],
                     second['upload_attempt_id'],second['upload_attempt_id']])
   self.assertEqual(network[-1]['status'],404);self.assertTrue(network[-1]['attributed'])
   self.assertNotIn('private',json.dumps(network))
   unbound=SimpleNamespace(_guid='guid-9',url='https://files.oaiusercontent.com/files/x?sig=private',
                            method='PUT',resource_type='fetch',failure='net::ERR_HTTP2_PROTOCOL_ERROR')
   o._network_event('own',page,unbound)
   last=o._network_events[-1]
   self.assertIsNone(last['upload_attempt_id']);self.assertFalse(last['attributed'])
   self.assertEqual(o.network_report()['owner_pid'],os.getpid())
 async def test_a_request_without_an_active_attempt_is_kept_as_unattributed(self):
  """An owner restart empties the live attempt table; the request still counts."""
  from unittest.mock import Mock
  from browser import upload_trace
  with tempfile.TemporaryDirectory() as d:
   upload_trace.configure(Path(d));self.addCleanup(upload_trace.reset)
   o=PageObserver(d,SimpleNamespace(_loop=asyncio.get_running_loop()));page=Mock()
   o.pages={'own':page};o.window_targets={'own'}
   request=SimpleNamespace(_guid='guid-orphan',url='https://files.oaiusercontent.com/files/x?sig=private',
     method='PUT',resource_type='fetch',failure=None)
   o._network_event('own',page,request,phase='request')
   lines=[json.loads(line) for line in (Path(d)/upload_trace.EVENTS_FILE).read_text().splitlines()]
   network=[line for line in lines if line['kind']=='network']
   self.assertEqual(len(network),1)
   self.assertIsNone(network[0]['upload_attempt_id']);self.assertFalse(network[0]['attributed'])
   self.assertEqual(upload_trace.lookup_request('guid-orphan'),None)
   report=o.network_report()
   self.assertEqual(len(report['errors']),1)
   self.assertEqual(report['attribution_counters']['request_unbound'],1)
   self.assertNotIn('private',json.dumps(network))
 async def test_a_request_without_a_stable_identity_is_counted_not_dropped_silently(self):
  from unittest.mock import Mock
  from browser import upload_trace
  with tempfile.TemporaryDirectory() as d:
   upload_trace.configure(Path(d));self.addCleanup(upload_trace.reset)
   o=PageObserver(d,SimpleNamespace(_loop=asyncio.get_running_loop()));page=Mock()
   o.pages={'own':page};o.window_targets={'own'}
   attempt=upload_trace.begin(target_id='own',zip_path='/tmp/one.zip')
   for _ in range(3):
    o._network_event('own',page,SimpleNamespace(url='https://files.oaiusercontent.com/files/x?sig=private',
      method='PUT',resource_type='fetch',failure=None),phase='request')
   self.assertEqual(upload_trace.active('own'),attempt['upload_attempt_id'])
   self.assertEqual([json.loads(line)['kind'] for line in
     (Path(d)/upload_trace.EVENTS_FILE).read_text().splitlines()],['upload_started'])
   report=o.network_report()
   self.assertEqual(report['attribution_counters']['request_without_key'],3)
   self.assertEqual(report['errors'],[])
 async def test_receipt_scan_does_not_block_the_resident_driver_clock(self):
  import threading
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   o=PageObserver(d,SimpleNamespace(_loop=asyncio.get_running_loop()))
   o.pages={'owned':SimpleNamespace(url='https://example.test/')}
   async def inspect(tid,*args):return {'target_id':tid,'state':'idle'}
   o.inspect=inspect
   entered=threading.Event();release=threading.Event()
   def slow_index(root):
    entered.set();release.wait(timeout=2);return {},{}
   with patch('browser.attempt_history.index_attempts',side_effect=slow_index):
    task=asyncio.create_task(o.check())
    try:
     deadline=time.monotonic()+1
     while not entered.is_set() and time.monotonic()<deadline:await asyncio.sleep(.005)
     self.assertTrue(entered.is_set());self.assertFalse(task.done())
     # An in-flight scan cannot prevent the loop from serving its next timer.
     tick=asyncio.Event();asyncio.get_running_loop().call_later(.02,tick.set)
     await asyncio.wait_for(tick.wait(),.2)
    finally:release.set();await task
 async def test_all_pages_checked_on_one_clock_during_other_work(self):
  with tempfile.TemporaryDirectory() as d:
   o=PageObserver(d,SimpleNamespace(_loop=asyncio.get_running_loop()));o.interval=.03
   o.pages={'a':SimpleNamespace(url='a'),'b':SimpleNamespace(url='b')};seen=[]
   async def inspect(tid,*_):seen.append(tid);await asyncio.sleep(.005);return {'target_id':tid}
   o.inspect=inspect;o.start()
   await asyncio.sleep(.12);o.stop();await asyncio.sleep(0)
   self.assertGreaterEqual(seen.count('a'),3);self.assertEqual(seen.count('a'),seen.count('b'))
   report=json.loads((Path(d)/'web-page-observer.json').read_text());self.assertEqual(report['page_count'],2);self.assertEqual(INTERVAL,10)

class ObserverReadTests(unittest.IsolatedAsyncioTestCase):
 async def test_status_is_published_before_receipt_deadline_without_claiming_saved_or_identity(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);o=PageObserver(root,SimpleNamespace(_loop=asyncio.get_running_loop()))
   o.pages={str(i):SimpleNamespace(url='https://chatgpt.com/c/'+str(i)) for i in range(20)}
   ledger={'state':'submitted','_ledger_path':str(root/'attempt.json')}
   entered=asyncio.Event();release=asyncio.Event()
   async def inspect(tid,page,urls,ledgers,collect=True):
    if collect:
     o._inflight[tid]['inspection_stage']='receipt_identity';entered.set();await release.wait()
    return {'target_id':tid,'state':'complete','checked_at':time.time(),'streaming':False,'complete':True,'answers':1}
   o.inspect=inspect
   with patch('browser.attempt_history.index_attempts',return_value=({}, {'0':ledger})),patch('browser.web_page_observer.PAGE_CHECK_TIMEOUT',.15):
    task=asyncio.create_task(o.check())
    try:
     await asyncio.wait_for(entered.wait(),1)
     early=json.loads((root/'web-page-observer.json').read_text())
     self.assertEqual(len(early['pages']),20);self.assertFalse(task.done())
     self.assertTrue(all(p['state']=='complete' for p in early['pages']))
     await task
    finally:release.set();await task
   report=json.loads((root/'web-page-observer.json').read_text());page=report['pages'][0]
   self.assertEqual(page['state'],'complete');self.assertEqual(page['receipt_state'],'inspection_error')
   self.assertEqual(page['receipt_failed_stage'],'receipt_identity')
   self.assertNotIn('activity_verified',page);self.assertNotIn('saved',page)
   journal=[json.loads(s) for s in (root/'web-page-observer-errors.jsonl').read_text().splitlines()]
   self.assertEqual(len(journal),1);self.assertEqual(journal[0]['diagnostic_kind'],'receipt_collection')
   self.assertNotEqual(journal[0]['check_id'],page['check_id'])
   self.assertEqual(journal[0]['check_id'],page['receipt_check_id'])
   self.assertEqual(report['receipt_inspection_errors'],1);self.assertFalse(o._inflight)

 async def test_real_identity_proof_survives_collection_error_with_its_own_time(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);o=PageObserver(root,SimpleNamespace(_loop=asyncio.get_running_loop()))
   o.pages={'own':SimpleNamespace(url='https://chatgpt.com/c/own')}
   ledger={'state':'submitted','_ledger_path':str(root/'attempt.json')};identity_at=time.time()
   async def inspect(tid,page,urls,ledgers,collect=True):
    if collect:
     o._inflight[tid].update(activity_verified=True,kind='cards',identity_checked_at=identity_at,
                            inspection_stage='answer_stability')
     raise TimeoutError('private body must not enter journal')
    return {'target_id':tid,'state':'complete','streaming':False,'complete':True,'answers':1}
   o.inspect=inspect
   with patch('browser.attempt_history.index_attempts',return_value=({}, {'own':ledger})):await o.check()
   page=json.loads((root/'web-page-observer.json').read_text())['pages'][0]
   self.assertTrue(page['activity_verified']);self.assertEqual(page['identity_checked_at'],identity_at)
   self.assertEqual(page['state'],'complete');self.assertNotIn('saved',page)
   self.assertEqual(page['receipt_failed_stage'],'answer_stability')
   self.assertNotIn('private body',(root/'web-page-observer-errors.jsonl').read_text())

 async def test_status_reads_use_one_round_trip_without_locator_count_fanout(self):
  from unittest.mock import Mock,AsyncMock
  with tempfile.TemporaryDirectory() as d:
   o=PageObserver(d,SimpleNamespace(_loop=asyncio.get_running_loop()))
   page=Mock();page.url='https://chatgpt.com/'
   page.evaluate=AsyncMock(return_value={'login':False,'streaming':False,'complete':False,'answers':0,
       'send_button_present':True,'send_button_disabled':True,'upload_indicator_visible':False})
   result=await o.inspect('own',page,[page.url],{})
   self.assertEqual(result['state'],'idle');self.assertTrue(result['send_button_disabled'])
   self.assertFalse(result['upload_indicator_visible']);page.evaluate.assert_awaited_once()
   page.locator.return_value.count.assert_not_called()

 async def test_saved_nonstreaming_reply_skips_deep_identity_without_granting_reuse(self):
  from unittest.mock import Mock,AsyncMock
  from web_gpt.core import ANSWER
  with tempfile.TemporaryDirectory() as d:
   o=PageObserver(d,SimpleNamespace(_loop=asyncio.get_running_loop()))
   page=Mock(url='https://chatgpt.com/c/original')
   page.evaluate=AsyncMock(return_value={'login':False,'streaming':False,'complete':True,'answers':1})
   result=await o.inspect('own',page,[page.url],{'own':(Path(d)/'attempt.json',{'state':'response_saved'})})
   self.assertEqual(result['collection_state'],'already_saved');self.assertEqual(result['state'],'complete')
   self.assertNotIn('activity_verified',result);self.assertNotIn('saved',result)
   page.locator.assert_called_once_with(ANSWER)

 async def test_one_slow_page_preserves_partial_evidence_and_does_not_timeout_other_pages(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   o=PageObserver(d,SimpleNamespace(_loop=asyncio.get_running_loop()))
   o.pages={str(i):SimpleNamespace(url='https://chatgpt.com/') for i in range(20)}
   async def inspect(tid,*args):
    if tid=='0':
     o._inflight[tid].update(inspection_stage='receipt_identity',last_observed_state='complete')
     await asyncio.sleep(1)
    return {'target_id':tid,'state':'idle'}
   o.inspect=inspect
   with patch('browser.web_page_observer.PAGE_CHECK_TIMEOUT',.04):await o.check()
   report=json.loads((Path(d)/'web-page-observer.json').read_text());pages={p['target_id']:p for p in report['pages']}
   self.assertEqual(sum(p['state']=='idle' for p in pages.values()),19)
   failed=pages['0'];self.assertEqual(failed['state'],'inspection_error')
   self.assertEqual(failed['failed_stage'],'receipt_identity');self.assertEqual(failed['error_type'],'TimeoutError')
   self.assertTrue(failed['checked_at']);self.assertGreater(failed['check_finished_at'],failed['check_started_at'])
   self.assertEqual(len({p['check_id'] for p in pages.values()}),20)
   journal=[json.loads(s) for s in (Path(d)/'web-page-observer-errors.jsonl').read_text().splitlines()]
   self.assertEqual(len(journal),1);self.assertEqual(journal[0]['check_id'],failed['check_id'])
   self.assertNotIn('url',journal[0]);self.assertFalse(o._inflight)

class IdentityTests(unittest.TestCase):
 def test_review_standard_contract_header_does_not_create_a_second_task(self):
  import hashlib
  contract=json.loads((Path(__file__).resolve().parents[2]/'config/card_review_standard.json').read_text())['contract']
  for rid in ('a'*24, 'b'*24+'-auto-1792616961'):
   expected='本次核验材料标识 card-review-'+rid+'。\n'+contract
   url='https://chatgpt.com/c/original-review'
   attempt={'review_id':rid,'target_id':'own','conversation_url':url,
            'actual_prompt_sha256':hashlib.sha256(expected.encode()).hexdigest()}
   self.assertTrue(response_identity(attempt,expected,expected,url,[url],'own'))
   self.assertFalse(response_identity(attempt,expected,expected,url,[url,url],'own'))
   self.assertFalse(response_identity(attempt,expected,expected,url,[url],'other'))

 def test_review_contract_header_cannot_hide_duplicate_or_foreign_task(self):
  from browser.web_page_observer import _review_identity
  rid='a'*24+'-auto-1792616961'
  expected='材料标识 card-review-'+rid+'。\n制卡与核验共用同一合同（card-review-standard-v3）：\n规则。'
  for additional in ('card-review-'+rid,'card-review-'+'b'*24,
                     'card-review-standard-v3','card-review-standard-v4'):
   self.assertFalse(_review_identity(expected+'\n'+additional,rid))
  self.assertFalse(_review_identity(expected,'a'*24))

 def test_only_known_qualified_contract_header_is_not_a_task_marker(self):
  from browser.web_page_observer import _review_markers
  self.assertEqual(_review_markers('制卡与核验共用同一合同（card-review-standard-v3）：'),[])
  self.assertEqual(_review_markers('其他合同（card-review-standard-v3）：'),['standard-v3'])
  self.assertEqual(_review_markers('制卡与核验共用同一合同（card-review-standard-v4）：'),['standard-v4'])
  self.assertEqual(_review_markers('card-review-standard-v3'),['standard-v3'])

 def test_review_auto_successor_uses_full_unique_marker(self):
  import hashlib
  rid='a'*24+'-auto-1792616961';expected='Independent card-review-'+rid+'; bound input';url='https://chatgpt.com/c/review'
  a={'review_id':rid,'target_id':'own','actual_prompt_sha256':hashlib.sha256(expected.encode()).hexdigest()}
  self.assertTrue(response_identity(a,expected,expected,url,[url],'own'))
  for user in (expected+' card-review-'+rid, expected+' card-review-'+'b'*24):
   self.assertFalse(response_identity(a,expected,user,url,[url],'own'))
  a['review_id']='a'*24
  self.assertFalse(response_identity(a,expected,expected,url,[url],'own'))

 def test_duplicate_url_or_changed_prompt_never_accepts_answer(self):
  import hashlib
  expected='web-card-12345678-1234-1234-1234-123456789abc-test input';url='https://chatgpt.com/c/own'
  a={'target_id':'own','actual_prompt_sha256':hashlib.sha256(expected.encode()).hexdigest()}
  self.assertTrue(response_identity(a,expected,expected,url,[url],'own'))
  self.assertFalse(response_identity(a,expected,expected,url,[url,url],'own'))
  self.assertFalse(response_identity(a,expected,'other input',url,[url],'own'))

class BlankReplyTests(unittest.IsolatedAsyncioTestCase):
 async def test_complete_original_review_with_standard_header_is_saved_without_resend(self):
  import hashlib
  from unittest.mock import AsyncMock,Mock,patch
  from browser.web_card_pool import USER
  from web_gpt.core import ANSWER
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);path=root/'attempt.json';rid='c'*24+'-auto-1792616961'
   prompt='材料标识 card-review-'+rid+'。\n制卡与核验共用同一合同（card-review-standard-v3）：\n通用规则。'
   url='https://chatgpt.com/c/original-review';raw='{"synthetic":"complete review receipt"}'
   a={'state':'submitted','review_id':rid,'target_id':'own','created':1,
      'conversation_url':url,'actual_prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
   path.write_text(json.dumps(a));(root/'prompt-actual.txt').write_text(prompt)
   users=Mock();users.count=AsyncMock(return_value=1);users.first.evaluate=AsyncMock(return_value=[prompt,prompt])
   answers=Mock();answers.last.evaluate=AsyncMock(return_value=[raw,raw]);answers.last.get_attribute=AsyncMock(return_value='false')
   page=Mock();page.url=url;page.evaluate=AsyncMock(return_value={'login':False,'streaming':False,'complete':True,'answers':1})
   page.locator.side_effect=lambda selector:{USER:users,ANSWER:answers}[selector]
   o=PageObserver(root,SimpleNamespace(_loop=asyncio.get_running_loop()));o.pages={'own':page}
   with patch('browser.web_page_observer.asyncio.sleep',new=AsyncMock()):
    result=await o.inspect('own',page,[url],{'own':(path,a)})
   self.assertTrue(result.get('saved'));self.assertEqual((root/'response-raw.txt').read_text(),raw)
   final=json.loads(path.read_text());self.assertEqual(final['state'],'response_saved')
   for key in ('target_id','created','conversation_url','actual_prompt_sha256','review_id'):
    self.assertEqual(final[key],a[key])
   page.goto.assert_not_called();page.click.assert_not_called();page.fill.assert_not_called()

 async def test_generation_resuming_during_stability_replaces_the_completed_status(self):
  import hashlib
  from unittest.mock import AsyncMock,Mock
  from browser.web_card_pool import USER
  from web_gpt.core import ANSWER
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);path=root/'attempt.json';prompt='web-card-12345678-1234-1234-1234-123456789abc-test input'
   url='https://chatgpt.com/c/own'
   ledger={'state':'submitted','target_id':'own','actual_prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
   path.write_text(json.dumps(ledger));(root/'prompt-actual.txt').write_text(prompt)
   users=Mock();users.count=AsyncMock(return_value=1);users.first.evaluate=AsyncMock(return_value=[prompt,prompt])
   answers=Mock();answers.last.evaluate=AsyncMock(return_value=['{"ok":true}','rendered'])
   page=Mock();page.url=url
   page.evaluate=AsyncMock(side_effect=[{'login':False,'streaming':False,'complete':True,'answers':1},
                                      {'login':False,'streaming':True,'complete':False,'answers':1}])
   page.locator.side_effect=lambda selector:{USER:users,ANSWER:answers}[selector]
   o=PageObserver(root,SimpleNamespace(_loop=asyncio.get_running_loop()))
   result=await o.inspect('own',page,[url],{'own':(path,ledger)})
   self.assertEqual(result['state'],'generating');self.assertTrue(result['streaming']);self.assertFalse(result['complete'])
   self.assertNotIn('saved',result);self.assertFalse((root/'response-raw.txt').exists())
   self.assertEqual(json.loads(path.read_text()),ledger)

 async def test_final_receipt_cas_preserves_newer_owner_write_after_dom_await(self):
  import hashlib
  from unittest.mock import AsyncMock,Mock
  from contextlib import nullcontext
  from browser.web_card_pool import USER
  from web_gpt.core import ANSWER,STOP_BUTTON
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);path=root/'attempt.json';prompt='web-card-12345678-1234-1234-1234-123456789abc-test input';url='https://chatgpt.com/c/own'
   a={'state':'submitted','target_id':'own','created':1,'actual_prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
   path.write_text(json.dumps(a));(root/'prompt-actual.txt').write_text(prompt)
   empty=Mock();empty.count=AsyncMock(return_value=0)
   users=Mock();users.count=AsyncMock(return_value=1);users.first.evaluate=AsyncMock(return_value=[prompt,prompt[:15]+'显示更多'])
   turns=Mock();turns.count=AsyncMock(return_value=1);turns.last.get_attribute=AsyncMock(return_value='complete')
   answers=Mock();answers.count=AsyncMock(return_value=1);answers.last.evaluate=AsyncMock(return_value=['{"complete":true}','rendered'])
   newer={**a,'state':'response_saved','raw_sha256':'owner-verified','publish_checked':True}
   async def changed_receipt(*args):path.write_text(json.dumps(newer));return 'false'
   answers.last.get_attribute=AsyncMock(side_effect=changed_receipt)
   page=Mock();page.url=url;page.evaluate=AsyncMock(return_value={'login':False,'streaming':False,'complete':True,'answers':1});page.locator.side_effect=lambda selector:{USER:users,ANSWER:answers,STOP_BUTTON:empty,'[data-talvt-turn-state]':turns}.get(selector,empty)
   o=PageObserver(root,SimpleNamespace(_loop=asyncio.get_running_loop()));o.pages={'own':page}
   from unittest.mock import patch
   with patch('web_gpt.submission.submission_lock',return_value=nullcontext()):
    result=await o.inspect('own',page,[url],{'own':(path,a)})
   self.assertNotIn('saved',result)
   self.assertEqual(json.loads(path.read_text()),newer)
   self.assertFalse((root/'response-raw.txt').exists())

 async def test_empty_completed_element_is_not_saved_or_reclassified(self):
  import hashlib
  from unittest.mock import AsyncMock,Mock
  from browser.web_card_pool import USER
  from web_gpt.core import ANSWER,STOP_BUTTON
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);path=root/'attempt.json';prompt='web-card-12345678-1234-1234-1234-123456789abc-test input';url='https://chatgpt.com/c/own'
   a={'state':'submitted','target_id':'own','created':1,'actual_prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
   path.write_text(json.dumps(a));before=path.read_bytes();(root/'prompt-actual.txt').write_text(prompt)
   empty=Mock();empty.count=AsyncMock(return_value=0)
   users=Mock();users.count=AsyncMock(return_value=1);users.first.evaluate=AsyncMock(return_value=[prompt,prompt])
   turns=Mock();turns.count=AsyncMock(return_value=1);turns.last.get_attribute=AsyncMock(return_value='complete')
   answers=Mock();answers.count=AsyncMock(return_value=1);answers.last.evaluate=AsyncMock(return_value=[' \n',' \n'])
   page=Mock();page.url=url;page.evaluate=AsyncMock(return_value={'login':False,'streaming':False,'complete':True,'answers':1});page.locator.side_effect=lambda selector:{USER:users,ANSWER:answers,STOP_BUTTON:empty,'[data-talvt-turn-state]':turns}.get(selector,empty)
   o=PageObserver(root,SimpleNamespace(_loop=asyncio.get_running_loop()))
   result=await o.inspect('own',page,[url],{'own':(path,a)})
   self.assertEqual(result['state'],'empty_response');self.assertNotIn('saved',result)
   self.assertEqual(path.read_bytes(),before);self.assertFalse((root/'response-raw.txt').exists())


class WindowPositionTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  from unittest.mock import AsyncMock,Mock
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)
  self.observer=PageObserver(self.root,SimpleNamespace(_loop=asyncio.get_running_loop()))
  self.session=Mock();self.session.send=AsyncMock();self.session.detach=AsyncMock()
  self.browser_impl=Mock();self.browser_impl.new_browser_cdp_session=AsyncMock(return_value=self.session)
  self.browser=SimpleNamespace(_impl_obj=self.browser_impl)
  self.pages={tid:SimpleNamespace(_impl_obj=SimpleNamespace(url='https://chatgpt.com/c/'+tid)) for tid in ('one','two')}
  async def inspect(tid,*_):
   return {'target_id':tid,'checked_at':time.time(),'state':'generating','activity_verified':True,'kind':'cards','streaming':True}
  self.observer.inspect=inspect

 def report(self):
  return json.loads((self.root/'web-page-observer.json').read_text())

 async def test_registered_window_queries_are_parallel_on_existing_async_browser(self):
  running=0;maximum=0;dom_started=asyncio.Event();queries_started=asyncio.Event();count=0
  async def position(method,params):
   nonlocal running,maximum,count
   self.assertEqual(method,'Browser.getWindowForTarget')
   running+=1;maximum=max(maximum,running);count+=1
   if count==2:queries_started.set()
   await dom_started.wait();await queries_started.wait();await asyncio.sleep(.001)
   running-=1
   return {'windowId':10 if params['targetId']=='one' else 20}
  self.session.send.side_effect=position
  original=self.observer.inspect
  async def inspect(tid,*args):
   dom_started.set();await queries_started.wait();return await original(tid,*args)
  self.observer.inspect=inspect
  self.observer.update(self.pages,shared_browser=self.browser,registered_targets={'one','two'})
  before=time.time();await self.observer.check();report=self.report()
  self.assertEqual(maximum,2)
  self.assertEqual(report['window_schema_version'],1);self.assertEqual(report['window_target_count'],2)
  results={p['target_id']:p for p in report['pages']}
  self.assertEqual(results['one']['window_id'],10);self.assertEqual(results['two']['window_id'],20)
  for result in results.values():
   self.assertTrue(result['window_observed']);self.assertGreaterEqual(result['window_checked_at'],before)
   self.assertTrue(result['activity_verified']);self.assertEqual(result['state'],'generating')
  self.browser_impl.new_browser_cdp_session.assert_awaited_once()
  self.session.detach.assert_awaited_once()
  self.browser_impl.connect_over_cdp.assert_not_called()
  self.browser_impl.new_page.assert_not_called()
  self.browser_impl.close.assert_not_called()

 async def test_failed_position_only_marks_that_target_and_keeps_activity(self):
  async def position(method,params):
   if params['targetId']=='one':raise RuntimeError('target disappeared')
   return {'windowId':30}
  self.session.send.side_effect=position
  self.observer.update(self.pages,shared_browser=self.browser,registered_targets={'one','two'})
  await self.observer.check();results={p['target_id']:p for p in self.report()['pages']}
  bad=results['one'];good=results['two']
  self.assertFalse(bad['window_observed']);self.assertIn('target disappeared',bad['window_error'])
  self.assertNotIn('window_id',bad);self.assertTrue(bad['activity_verified'])
  self.assertEqual(bad['state'],'generating');self.assertTrue(good['window_observed']);self.assertEqual(good['window_id'],30)
  self.session.detach.assert_awaited_once()

 async def test_no_dom_page_still_receives_exact_registered_target_lookup(self):
  self.session.send.return_value={'windowId':42}
  self.observer.update({'one':self.pages['one']},shared_browser=self.browser,registered_targets={'one','missing'})
  await self.observer.check();report=self.report();results={p['target_id']:p for p in report['pages']}
  self.assertEqual({call.args[1]['targetId'] for call in self.session.send.await_args_list},{'one','missing'})
  self.assertEqual(results['missing']['state'],'not_observed');self.assertEqual(results['missing']['window_id'],42)
  self.assertNotIn('activity_verified',results['missing']);self.assertEqual(report['page_count'],1)

 async def test_nonshared_does_not_create_cdp_session_or_query_other_targets(self):
  self.observer.update(self.pages,registered_targets={'one','two','foreign'})
  await self.observer.check();report=self.report()
  self.browser_impl.new_browser_cdp_session.assert_not_called();self.session.send.assert_not_called()
  self.assertNotIn('window_schema_version',report)
  self.assertTrue(all('window_id' not in result for result in report['pages']))

 async def test_session_failure_preserves_activity_without_assuming_registered_window(self):
  self.browser_impl.new_browser_cdp_session.side_effect=RuntimeError('session unavailable')
  self.observer.update(self.pages,shared_browser=self.browser,registered_targets={'one','two'})
  await self.observer.check();report=self.report()
  self.assertIn('session unavailable',report['window_errors'][0])
  for result in report['pages']:
   self.assertFalse(result['window_observed']);self.assertNotIn('window_id',result)
   self.assertTrue(result['activity_verified']);self.assertEqual(result['state'],'generating')
  self.session.detach.assert_not_called()

 async def test_invalid_window_id_is_not_replaced_with_guess_or_previous_position(self):
  self.observer.update(self.pages,shared_browser=self.browser,registered_targets={'one','two'})
  self.session.send.return_value={'windowId':99}
  await self.observer.check()
  for value in (True,-1,'99',None):
   with self.subTest(window_id=value):
    self.session.send.return_value={'windowId':value};await self.observer.check()
    for result in self.report()['pages']:
     self.assertFalse(result['window_observed']);self.assertNotIn('window_id',result)

class NetworkHandoffEvidence(unittest.IsolatedAsyncioTestCase):
 async def test_old_owner_network_failures_survive_projection_restart(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);old={'owner_pid':123,'updated':100,'errors':[{'target_id':'original','at':90,
       'method':'PUT','host':'sdmntprwestus.oaiusercontent.com','failure':'net::ERR_HTTP2_PROTOCOL_ERROR'}]}
   (root/'web-upload-network.json').write_text(json.dumps(old))
   observer=PageObserver(root,SimpleNamespace(_loop=asyncio.get_running_loop()))
   report=observer.network_report()
   self.assertEqual(report['errors'][0]['at'],90);self.assertTrue(report['errors'][0]['historical'])
   self.assertEqual(report['errors'][0]['observed_owner_pid'],123)
   archives=list((root/'web-upload-network-history').iterdir());self.assertEqual(len(archives),1)
   self.assertEqual(json.loads(archives[0].read_text()),old)
