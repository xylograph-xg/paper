"""Only a verified original job may hand off; callbacks never touch browser pages."""
import json
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from maintenance import owner_supervision as q
REAL_MANAGED = q._managed


class OwnerSupervision(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name).resolve()
        self.config={'catalog_path':str(self.root/'catalog.db'),'automatic_issue_handling':{'enabled':True,'owner_supervision':{'enabled':True}}}
        self.current={'browser/helper.py':'b'*64}
        self.evidence={'status':'ok','import_root':'/fixture/chatgpt_playwright','sdk_version':'1.63.0',
                       'files':{'dependency:web_gpt.core':'/fixture/chatgpt_playwright/web_gpt/core.py'},
                       'errors':[]}
        self.owner={'alive':True,'pid':123,'token':'original-owner-token','updated':1000,'stage':'idle',
                    'code_version':{'module_sha256':{'browser/helper.py':'a'*64},'external_dependencies':dict(self.evidence)}}
        self.managed={'pid':123,'plist_sha256':'p'*64}
        self.code=self.enterContext(patch.object(q,'_code',return_value=self.current))
        self.evidence_patch=self.enterContext(patch.object(q,'_release_evidence',return_value=dict(self.evidence)))
        self.process=self.enterContext(patch.object(q,'_owner',side_effect=lambda c:dict(self.owner)))
        self.job=self.enterContext(patch.object(q,'_managed',side_effect=lambda c:dict(self.managed)))
        self.allowed=self.enterContext(patch.object(q,'_permitted',return_value=True))
        self.idle=self.enterContext(patch.object(q,'_submission_idle',return_value=True))
        self.kill=self.enterContext(patch.object(q.os,'kill'))
        self.start=self.enterContext(patch.object(q,'_kickstart'))
        self.alive=self.enterContext(patch.object(q,'alive',return_value=True))
        q.publish_validated(self.config,self.current,{'tests_passed':True,'interfaces_passed':True,'links_passed':True,
                                                      'test_count':10,'external_dependencies':dict(self.evidence)})
    def write_observer(self,updated,owner_pid=123):
        (self.root/'web-page-observer.json').write_text(json.dumps({'updated':updated,'owner_pid':owner_pid}))
    def test_validated_update_signals_original_then_waits_for_exit_and_starts_only_same_job(self):
        result=q.tick(self.config,at=1000);self.assertEqual(result['state'],'graceful_handoff_requested')
        self.kill.assert_called_once_with(123,signal.SIGTERM);self.start.assert_not_called()
        self.assertNotIn('original-owner-token',(self.root/'owner-supervision.json').read_text())
        self.assertEqual(q.tick(self.config,at=1060)['state'],'waiting_old_owner_exit');self.start.assert_not_called()
        self.alive.return_value=False;self.managed['pid']=None;self.owner['alive']=False
        self.assertEqual(q.tick(self.config,at=1120)['state'],'original_entry_restarted');self.start.assert_called_once()
        self.assertEqual(q.tick(self.config,at=1180)['state'],'waiting_original_entry_receipt');self.start.assert_called_once()
        self.managed['pid']=456;self.owner.update(pid=456,alive=True,code_version={'module_sha256':self.current})
        self.assertEqual(q.tick(self.config,at=1240)['state'],'new_owner_confirmed')
    def test_unvalidated_changed_source_and_incomplete_evidence_cannot_stop_or_start(self):
        self.code.return_value={'browser/helper.py':'c'*64}
        self.assertEqual(q.tick(self.config,at=1000)['state'],'waiting_validated_release')
        self.kill.assert_not_called();self.start.assert_not_called()
        with self.assertRaises(ValueError):q.publish_validated(self.config,self.current,{'tests_passed':True})
    def test_external_kernel_drift_alone_invalidates_the_validated_release(self):
        drifted=dict(self.current);drifted['dependency:web_gpt.core']='c'*64
        self.code.return_value=drifted
        self.assertEqual(q.tick(self.config,at=1000)['state'],'waiting_validated_release')
        self.kill.assert_not_called();self.start.assert_not_called()
    def test_incomplete_external_dependency_evidence_cannot_be_published(self):
        incomplete={'status':'incomplete','import_root':None,'sdk_version':None,'files':{},
                    'errors':['外部登记不可读']}
        self.evidence_patch.return_value=incomplete
        with self.assertRaises(ValueError):
            q.publish_validated(self.config,self.current,{'tests_passed':True,'interfaces_passed':True,
                'links_passed':True,'test_count':10,'external_dependencies':incomplete})
    def test_upload_or_model_lock_defers_update_without_touching_pages(self):
        self.idle.return_value=False
        self.assertEqual(q.tick(self.config,at=1000)['state'],'waiting_submission_boundary')
        self.kill.assert_not_called();self.start.assert_not_called()

    def test_continuous_lock_after_five_minute_validated_update_only_requests_graceful_exit(self):
        path=self.root/'validated-owner-release.json';release=json.loads(path.read_text())
        release['validated_at']=1000;path.write_text(json.dumps(release));self.idle.return_value=False
        self.assertEqual(q.tick(self.config,at=1299)['state'],'waiting_submission_boundary')
        self.kill.assert_not_called()
        self.assertEqual(q.tick(self.config,at=1300)['state'],'graceful_handoff_requested')
        self.kill.assert_called_once_with(123,signal.SIGTERM);self.start.assert_not_called()
        self.assertEqual(q.tick(self.config,at=1360)['state'],'waiting_old_owner_exit')
        self.start.assert_not_called()
    def test_fresh_observation_prevents_false_stall_and_two_distinct_stale_checks_are_required(self):
        self.owner['code_version']['module_sha256']=self.current;self.owner['updated']=0
        self.write_observer(990)
        self.assertEqual(q.tick(self.config,at=1000)['state'],'healthy')
        self.write_observer(0)
        self.assertEqual(q.tick(self.config,at=1000)['state'],'confirming_stale_owner')
        self.assertEqual(q.tick(self.config,at=1001)['state'],'confirming_stale_owner');self.kill.assert_not_called()
        self.assertEqual(q.tick(self.config,at=1060)['state'],'graceful_handoff_requested')
    def test_pause_during_handoff_never_restarts_or_changes_queue_controls(self):
        control=self.root/'web-card-control.json';control.write_bytes(b'{"paused_by_user":true}')
        q.tick(self.config,at=1000);self.allowed.return_value=False;self.alive.return_value=False;self.managed['pid']=None
        self.assertEqual(q.tick(self.config,at=1060)['state'],'respect_pause');self.start.assert_not_called()
        self.assertEqual(control.read_bytes(),b'{"paused_by_user":true}')
    def test_changed_pid_token_or_job_identity_cannot_signal_a_replacement_process(self):
        self.process.side_effect=[self.owner,{**self.owner,'token':'different'}]
        self.assertEqual(q.tick(self.config,at=1000)['state'],'identity_or_pause_changed');self.kill.assert_not_called()
    def test_existing_job_or_unregistered_agent_never_creates_a_peer(self):
        self.managed['pid']=999
        self.assertEqual(q.tick(self.config,at=1000)['state'],'owner_not_confirmed');self.kill.assert_not_called()
        self.job.side_effect=ValueError('original job unregistered')
        self.assertEqual(q.tick(self.config,at=1060)['state'],'preserved_error');self.start.assert_not_called()
    def test_cooldown_bounds_maintenance_requests(self):
        (self.root/'owner-supervision.json').write_text(json.dumps({'requests':[900,990]}))
        self.assertEqual(q.tick(self.config,at=1000)['state'],'cooldown');self.kill.assert_not_called()
    def test_global_or_supervision_disable_is_respected(self):
        self.config['automatic_issue_handling']['enabled']=False
        self.assertEqual(q.tick(self.config,at=1000)['state'],'disabled');self.kill.assert_not_called()
    def test_managed_entry_requires_exact_existing_module_config_and_working_directory(self):
        import plistlib
        from types import SimpleNamespace
        self.job.side_effect=None
        # Bypass the fixture's patch only for this pure metadata validation.
        patcher=patch.object(q.Path,'home',return_value=self.root)
        folder=self.root/'Library/LaunchAgents';folder.mkdir(parents=True)
        self.config.update(web_cards={'python':str(self.root/'python')},_config_path=str(self.root/'config.json'))
        spec={'Label':q.LABEL,'WorkingDirectory':str(q.ROOT),'ProgramArguments':[str(self.root/'python'),'-u','-m','cards.web_card_service','run','--config',str(self.root/'config.json')]}
        target=folder/(q.LABEL+'.plist');target.write_bytes(plistlib.dumps(spec))
        # The actual metadata function is saved before fixture mocking below.
        with patcher,patch.object(q.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='pid = 123')):
            self.assertEqual(REAL_MANAGED(self.config)['pid'],123)
            spec.pop('WorkingDirectory');target.write_bytes(plistlib.dumps(spec))
            with self.assertRaises(ValueError):REAL_MANAGED(self.config)
            spec['WorkingDirectory']=str(q.ROOT);spec['ProgramArguments'][3]='other_service';target.write_bytes(plistlib.dumps(spec))
            with self.assertRaises(ValueError):REAL_MANAGED(self.config)
