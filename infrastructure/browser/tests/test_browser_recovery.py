import json,tempfile,unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch
from types import SimpleNamespace
from browser.browser_recovery import check_health, main_chrome_pid
from browser.web_card_transport import formal_gpt_url

class BrowserRecovery(unittest.TestCase):
 def test_shared_registration_blocks_legacy_restart_even_if_configuration_is_changed(self):
  from browser.browser_recovery import maintain_pool
  (self.data/'shared-gpt-window.json').write_text('{}')
  with patch('browser.browser_recovery.targets') as query,patch('browser.browser_recovery.open_owned_pages') as reopen:
   self.assertEqual(check_health(self.config,force_restart=True)['state'],'owner_managed')
   self.assertEqual(maintain_pool(self.config)['state'],'owner_managed')
   query.assert_not_called();reopen.assert_not_called()
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.data=self.root/'data';self.data.mkdir()
  self.config={'catalog_path':str(self.data/'catalog.sqlite3'),'web_cards':{'enabled':True,'browser_recovery':{'enabled':True}}}
  self.patch=patch('browser.browser_recovery.ROOT',self.root);self.patch.start();self.addCleanup(self.patch.stop)
 def test_healthy_tabs_do_not_restart(self):
  with patch('browser.browser_recovery.targets',return_value=[{'id':'other','type':'page','url':'https://example.com/'}]),patch('browser.browser_recovery.open_owned_pages') as open_pages:
   self.assertEqual(check_health(self.config)['state'],'healthy');open_pages.assert_not_called()
 def test_empty_browser_reopens_once_and_respects_cooldown(self):
  with patch('browser.browser_recovery.targets',return_value=[]),patch('browser.browser_recovery.open_owned_pages',return_value=['new']) as open_pages:
   self.assertEqual(check_health(self.config)['state'],'recovered')
   self.assertEqual(check_health(self.config)['state'],'recovery_cooldown');self.assertEqual(open_pages.call_count,1)
 def test_user_pause_and_verification_never_restart(self):
  for name,value in [('web-card-control.json',{'paused_by_user':True}),('web-channel-control.json',{'chatgpt':{'manual_verification_required':True}})]:
   path=self.data/name;path.write_text(json.dumps(value))
   with patch('browser.browser_recovery.targets') as query:self.assertIn(check_health(self.config)['state'],('paused','manual_verification'));query.assert_not_called()
   path.unlink()
 def test_unknown_pages_are_preserved_during_restart(self):
  with patch('browser.browser_recovery.targets',return_value=[{'id':'user','type':'page','url':'https://example.com'}]),patch('browser.browser_recovery.main_chrome_pid') as pid:
   self.assertEqual(check_health(self.config,force_restart=True)['state'],'needs_inspection');pid.assert_not_called()
 def test_only_exact_dedicated_process_matches(self):
  profile=Path('/tmp/paper-profile');prefix='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome '
  text='12 '+prefix+'--user-data-dir=/tmp/paper-profile-other --remote-debugging-port=9222\n13 '+prefix+'--user-data-dir=/tmp/paper-profile --remote-debugging-port=9222\n'
  with patch('browser.browser_recovery.subprocess.run',return_value=SimpleNamespace(stdout=text)):
   self.assertEqual(main_chrome_pid(profile,9222),13)
 def test_temporary_conversations_not_accepted(self):
  for url in ['https://chatgpt.com/','https://chatgpt.com/c/local-chatgpt%3Aabc','https://other.com/c/abc']:self.assertFalse(formal_gpt_url(url))
  self.assertTrue(formal_gpt_url('https://chatgpt.com/c/6ac67d52-01d4-83e8-8462-afb7fa9d325b'))
 def test_owned_restart_restores_urls_without_any_resubmit(self):
  live=[{'id':'mine','type':'page','url':'https://chatgpt.com/c/saved'}]
  (self.data/'gpt-window-pool.json').write_text(json.dumps({'windows':{'mine':{'state':'busy'}}}))
  with patch('browser.browser_recovery.targets',return_value=live),patch('browser.browser_recovery.main_chrome_pid',return_value=77),patch('browser.browser_recovery.os.kill',side_effect=[None,ProcessLookupError()]) as kill,patch('browser.browser_recovery.subprocess.run') as start,patch('browser.browser_recovery.open_owned_pages',return_value=['restored']) as restore:
   self.assertEqual(check_health(self.config,force_restart=True)['state'],'recovered')
   restore.assert_called_once_with(self.config,['https://chatgpt.com/c/saved'],use_bootstrap=True)
   self.assertEqual(kill.call_count,2);self.assertIn('--remote-debugging-port=9222',start.call_args.args[0])
 def test_recovery_limit_prevents_restart_storm(self):
  import time
  (self.data/'browser-recovery.json').write_text(json.dumps({'recoveries':[time.time(),time.time()]}))
  with patch('browser.browser_recovery.targets',return_value=[]),patch('browser.browser_recovery.open_owned_pages') as reopen:
   self.assertEqual(check_health(self.config,force_restart=True)['state'],'recovery_limit');reopen.assert_not_called()
 def test_ten_slots_ignore_stale_entries_and_include_other_pages_in_limit(self):
  from browser.browser_recovery import pool_capacity
  mine=[{'id':str(i),'type':'page'} for i in range(2)]
  self.assertEqual(pool_capacity(mine,{'0','1','stale'},10),8)
  others=[{'id':'other-'+str(i),'type':'page'} for i in range(17)]
  self.assertEqual(pool_capacity(mine+others,{'0','1'},10),1)
  self.assertEqual(pool_capacity([{'id':str(i),'type':'page'} for i in range(11)],set(map(str,range(11))),10),0)
 def test_ten_slot_maintenance_respects_user_pause(self):
  from browser.browser_recovery import maintain_pool
  self.config['web_cards']['target_pool_pages']=10
  (self.data/'web-card-control.json').write_text(json.dumps({'paused_by_user':True}))
  with patch('browser.browser_recovery.targets') as query:
   self.assertEqual(maintain_pool(self.config)['state'],'paused');query.assert_not_called()

class QuarantinedCapacity(unittest.TestCase):
 def test_preserved_unknown_pages_do_not_take_working_slots(self):
  from browser.browser_recovery import quarantined_slots, pool_capacity
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   (root/'gpt-window-pool.json').write_text(json.dumps({'windows':{'held':{'state':'needs_inspection'},'active':{'state':'busy'},'gone':{'state':'needs_inspection'}}}))
   live=[{'id':i,'type':'page'} for i in ('held','active','user')]
   held=quarantined_slots(root,live)
   self.assertEqual(held,1)
   self.assertEqual(pool_capacity(live,{'held','active'},2+held),1)
   self.assertEqual(pool_capacity(live,{'held','active'},2+held,limit=3),0)
   self.assertEqual(json.loads((root/'gpt-window-pool.json').read_text())['windows']['held']['state'],'needs_inspection')
