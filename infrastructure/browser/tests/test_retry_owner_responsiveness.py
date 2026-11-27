import hashlib,json,tempfile,unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch,Mock
from cards import web_card_retry as retry
from cards.tests import test_web_card_retry as fixtures

class RetryOwnerResponsiveness(unittest.TestCase):
    def test_streaming_hash_yields_and_still_hashes_every_byte(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'input';content=b'x'*(5*1024*1024)+b'ending';path.write_bytes(content)
            check=Mock();clock=iter(range(20))
            with patch('cards.web_card_retry.time.monotonic',side_effect=lambda:next(clock)):
                actual=retry.cooperative_digest(path,check)
            self.assertEqual(actual,hashlib.sha256(content).hexdigest());self.assertGreaterEqual(check.call_count,3)

    def test_change_during_yield_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'input';path.write_bytes(b'original')
            with self.assertRaisesRegex(ValueError,'读取期间变化'):
                retry.cooperative_digest(path,lambda:path.write_bytes(b'changed'))

    def test_frozen_inputs_detect_change_after_responsive_hash(self):
        fixture=fixtures.RetryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        original=(fixture.folder/'visual.pdf').read_bytes()
        (fixture.folder/'visual.pdf').write_bytes(original+b'changed')
        with self.assertRaisesRegex(ValueError,'冻结输入已变化'):
            retry.frozen_inputs(fixture.folder,fixture.packet,fixture.catalog.get(fixture.pid),checkpoint=Mock())

    def test_budget_rotates_blocked_jobs_without_requeue_or_new_retry(self):
        fixture=fixtures.RetryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        jobs=[{'paper_id':str(i),'state':'failed'} for i in range(3)]
        order=[]
        for _ in range(4):
            clock=iter([0,10,10]);check=Mock()
            with patch('cards.web_card_queue.jobs',return_value=jobs):
                report=retry.run_once(fixture.config,router=fixture.router,checkpoint=check,monotonic=lambda:next(clock))
            self.assertEqual(report['inspected'],1);self.assertEqual(report['requeued'],[])
            self.assertEqual(report['published'],[]);self.assertEqual(check.call_count,1)
            order.append(report['blocked'][0]['paper_id'])
        self.assertEqual(order,['2','1','0','2']);self.assertEqual(fixture.state(),'failed')
        self.assertFalse((fixture.folder/'retry.json').exists())

    def test_seed_retry_precedes_persisted_ordinary_cursor(self):
        fixture=fixtures.RetryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        jobs=[{'paper_id':fixture.pid,'state':'failed'},{'paper_id':'ordinary','state':'failed'}]
        with fixture.catalog.connect() as db:
            db.execute("INSERT INTO manual_seed_roots VALUES(?,'seed.pdf','hash',1)",(fixture.pid,))
        (fixture.catalog.path.parent/'web-card-retry-scan.json').write_text(json.dumps({'next_paper_id':'ordinary'}))
        clock=iter([0,10,10])
        with patch('cards.web_card_queue.jobs',return_value=jobs):
            report=retry.run_once(fixture.config,router=fixture.router,monotonic=lambda:next(clock))
        self.assertEqual(report['blocked'][0]['paper_id'],fixture.pid)
        self.assertEqual(report['requeued'],[])
        self.assertEqual(fixture.state(),'failed')

    def test_invalid_budget_never_enables_new_work(self):
        fixture=fixtures.RetryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        for budget in [True,0,-1,float('inf'),11]:
            fixture.config['web_cards']['retry']['inspection_budget_seconds']=budget
            with self.assertRaises(ValueError):retry.run_once(fixture.config)
        self.assertEqual(fixture.state(),'failed')

class PageEligibilityFailure(unittest.TestCase):
    def test_live_reuse_rejection_invalidates_readiness_without_changing_ownership(self):
        from browser.shared_pool_store import failed_request
        from browser.shared_browser_window import WindowIsolationError
        original={'state':'ready_blank','active_paper_id':'old','raw_path':'original','raw_sha256':'saved','slot':4}
        entry={'state':'busy','active_paper_id':'new'}
        failed_request(entry,original,page_touched=False,error=WindowIsolationError('复用页有草稿'))
        self.assertEqual(entry['state'],'needs_inspection');self.assertEqual(entry['active_paper_id'],'old')
        self.assertEqual(entry['raw_path'],'original');self.assertEqual(entry['raw_sha256'],'saved')
        self.assertEqual(entry['slot'],4)

    def test_unrelated_local_failure_keeps_untouched_page_ready(self):
        from browser.shared_pool_store import failed_request
        original={'state':'ready_blank','slot':4};entry={'state':'busy'}
        failed_request(entry,original,page_touched=False,error=ValueError('input changed'))
        self.assertEqual(entry,original)
