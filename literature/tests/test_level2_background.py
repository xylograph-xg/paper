"""Full-library L2 admission, separate heads, incremental scheduling and pause."""
import json
import os
import signal
import time
from unittest.mock import patch

import unittest
from . import test_automatic as fixtures
from literature import background as runtime
from literature.background_level2 import (Worker, level2_status, level2_start,
    level2_control, level2_release, predict_record, EVIDENCE_BUDGET)
from core.api import literature_catalog__source_records as source_records


class Level2BackgroundTests(unittest.TestCase):
    def setUp(self):
        fixtures.AutomaticTests.setUp(self)
        self.catalog.upsert({'doi':'10.1000/automatic',
            'title':'Reverse intersystem crossing in TADF emitters for organic light-emitting diodes'})
    def test_background_independent_heads_frozen_input_and_incremental(self):
        before=self.catalog.path.read_bytes()
        first=runtime.Worker({'catalog_path':str(self.catalog.path)}, 'first')
        first.cycle()
        l1=self.library.store.automatic_results(scope='level1')
        worker=Worker(first.config, 'second')
        self.assertTrue(worker.cycle()); self.assertFalse(worker.cycle())
        self.assertEqual(before, self.catalog.path.read_bytes())
        self.assertEqual(l1, self.library.store.automatic_results(scope='level1'))
        self.assertEqual(self.library.store.automatic_results(), [])
        l2=self.library.store.automatic_results(scope='level2')[0]
        self.assertEqual(l2['level1'], []); self.assertTrue(l2['level2'])
        self.assertFalse(l2['scientific_verified'])
        doc=self.library.store.automatic_input(self.pid, scope='level2')
        self.assertEqual(doc['coverage']['budget_chars'], EVIDENCE_BUDGET)
        self.assertEqual(doc['source_provenance']['kind'], 'frozen_source_context')
        detail=self.library.detail(self.pid)
        self.assertTrue(any(a.get('level')==1 for a in detail['annotations']))
        self.assertTrue(any(a.get('level')==2 for a in detail['annotations']))

    def test_missing_si_protected_and_changed_original_are_not_success(self):
        config={'catalog_path':str(self.catalog.path)}
        missing=self.catalog.upsert({'title':'No original', 'doi':'10.1000/missing'})
        self.source.write_bytes(b'changed original')
        worker=Worker(config,'test'); worker.cycle(); worker.cycle()
        self.assertEqual(worker.state['completed'],0)
        self.assertEqual(worker.state['awaiting_original'],1)
        self.assertEqual(worker.state['source_mismatch'],1)
        with worker.store.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM level2_checks WHERE paper_id=?',(missing,)).fetchone()[0],'awaiting_original')
        self.assertFalse(worker.store.automatic_results(scope='level2')[0]['level2'])

    def test_pause_readonly_status_and_scope_isolation(self):
        config={'catalog_path':str(self.catalog.path)}
        missing={'catalog_path':str(self.root/'none'/'catalog.db')}
        self.assertFalse(level2_status(missing)['registered'])
        self.assertFalse((self.root/'none').exists())
        runtime.level1_control(config,True)
        level2_control(config,True)
        self.assertFalse(Worker(config,'test').cycle())
        with self.assertRaises(ValueError):level2_start(config)
        level2_release(config)
        runtime.atomic(runtime.paths(config,'level2')['service'],{'pid':os.getpid(),'state':'waiting','updated':time.time()})
        with patch('literature.background.subprocess.Popen',side_effect=AssertionError('duplicate')):
            level2_start(config)
        self.assertTrue(runtime.level1_status(config)['paused_by_user'])
        self.assertFalse(level2_status(config)['paused_by_user'])

    def test_si_only_and_identity_protection_remain_distinct(self):
        raw=json.dumps({'source_text':[{'source_page':1,'text':
            'S1\nSupporting Information\nMethods\nWe measured reverse intersystem crossing.'}]}).encode()
        import hashlib
        (self.folder/'source-context.json').write_bytes(raw)
        self.packet['input_hashes']['source-context.json']=hashlib.sha256(raw).hexdigest()
        (self.folder/'packet.json').write_text(json.dumps(self.packet))
        worker=Worker({'catalog_path':str(self.catalog.path)},'test')
        worker.cycle(); self.assertFalse(worker.cycle())
        self.assertEqual(worker.state['supplementary_only'],1)
        self.assertEqual(worker.state['completed'],0)
        with self.catalog.connect() as db:
            db.execute("UPDATE papers SET metadata=json_set(metadata,'$.identity_review_required',1) WHERE id=?",(self.pid,))
        self.assertTrue(worker.cycle()); self.assertFalse(worker.cycle())
        self.assertEqual(worker.state['protected'],1)
        self.assertFalse(worker.store.automatic_results(scope='level2')[0]['level2'])

    def test_source_change_during_prediction_and_failure_backoff(self):
        config={'catalog_path':str(self.catalog.path)}
        worker=Worker(config,'test')
        original=predict_record
        def change(record, generation):
            value=original(record,generation)
            self.source.write_bytes(b'changed during prediction')
            return value
        with patch('literature.background_level2.predict_record',side_effect=change):worker.cycle()
        self.assertEqual(worker.store.automatic_results(scope='level2'),[])
        self.assertFalse(worker.cycle())
        with worker.store.connect(True) as db: db.execute('DELETE FROM level2_checks')
        with patch('literature.background_level2.predict_record',side_effect=ValueError('parser failure')):worker.cycle()
        self.assertIn(self.pid,worker.failures)
        self.assertFalse(worker.cycle())

    def test_fallback_for_noncurated_original_and_l2_storage_rejects_l1(self):
        record=source_records(self.catalog.path,[self.pid])[0]; record['materials']=[]
        from types import SimpleNamespace
        with patch('read.api.parser__parse_pdf',return_value=SimpleNamespace(page_texts=[self.pages[0]['text']])):
            doc,result=predict_record(record,'frozen-generation')
        self.assertEqual(doc['source_provenance']['kind'],'local_pdf_text')
        self.assertTrue(result['level2'])
        result['level1']=[{'level':1}]
        with self.assertRaises(ValueError):self.library.store.save_automatic_run(doc,result,scope='level2')

    def test_failed_input_retry_budget_survives_restart_and_changed_material_reopens(self):
        config={'catalog_path':str(self.catalog.path)}
        worker=Worker(config,'test')
        with patch('literature.background_level2.predict_record',side_effect=ValueError('parser failure')) as predict:
            for _ in range(3):
                self.assertTrue(worker.cycle())
                with worker.store.connect(True) as db: db.execute('UPDATE level2_checks SET retry_at=0')
            self.assertFalse(worker.cycle())
            self.assertEqual(predict.call_count,3)
            restarted=Worker(config,'restart')
            self.assertFalse(restarted.cycle())
            self.assertEqual(restarted.state['failed'],1)
            self.assertEqual(restarted.state['queued'],0)
            self.assertEqual(restarted.state['retry_exhausted'],1)
            self.assertEqual(restarted.failures[self.pid]['attempts'],3)
            # A newly frozen, verified source context is a different recovery input.
            raw=json.dumps({'source_text':self.pages,'new_material':True}).encode()
            (self.folder/'source-context.json').write_bytes(raw)
            import hashlib
            self.packet['input_hashes']['source-context.json']=hashlib.sha256(raw).hexdigest()
            (self.folder/'packet.json').write_text(json.dumps(self.packet))
        self.assertTrue(restarted.cycle())
        self.assertFalse(restarted.cycle())
        self.assertNotIn(self.pid,restarted.failures)
        self.assertEqual(len(self.library.store.automatic_results(scope='level2')),1)

    def test_legacy_exhausted_failure_preserves_attempts_reason_and_check(self):
        config={'catalog_path':str(self.catalog.path)}; worker=Worker(config,'test')
        worker.failures[self.pid]={'attempts':33,'retry_at':0,'error':'code=5: exception stack overflow!'}
        from core.api import literature_catalog__metadata_rows as metadata_rows
        worker.check(next(r for r in metadata_rows(self.catalog.path) if r['id']==self.pid),'failed','original parser error')
        with worker.store.connect() as db: before=dict(db.execute('SELECT * FROM level2_checks').fetchone())
        worker.emit()
        with patch('literature.background_level2.predict_record',side_effect=AssertionError('blind retry')):
            self.assertFalse(worker.cycle())
            self.assertFalse(Worker(config,'restart').cycle())
        with worker.store.connect() as db: self.assertEqual(before,dict(db.execute('SELECT * FROM level2_checks').fetchone()))
        self.assertEqual(worker.failures[self.pid]['attempts'],33)
        self.assertEqual(worker.failures[self.pid]['error'],'code=5: exception stack overflow!')

    def test_sidecar_constructor_rejects_primary_catalog_before_any_write(self):
        from literature.store import Store
        before=self.catalog.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'Catalog'): Store(self.catalog.path)
        self.assertEqual(before,self.catalog.path.read_bytes())

    def test_failure_recovery_identity_tracks_original_material_and_parser(self):
        from literature.background_level2 import recovery_input
        record=source_records(self.catalog.path,[self.pid])[0]
        key=recovery_input(record,'generation')
        self.assertEqual(key,recovery_input(record,'generation'))
        self.source.write_bytes(b'changed original bytes')
        self.assertNotEqual(key,recovery_input(record,'generation'))
        self.source.write_bytes(b'%PDF synthetic source bound by content hash')
        self.assertEqual(key,recovery_input(record,'generation'))
        parser=self.root/'parser.py'; parser.write_text('parser revision 1')
        with patch('inspect.getsourcefile',return_value=str(parser)):
            first=recovery_input(record,'generation')
            parser.write_text('parser revision 2')
            self.assertNotEqual(first,recovery_input(record,'generation'))

    def test_real_spawn_pause_resume_without_l1_control(self):
        config={'catalog_path':str(self.catalog.path)}; child=None
        runtime.level1_control(config,True); level2_release(config)
        def wait(predicate):
            end=time.time()+12
            while time.time()<end:
                state=level2_status(config)
                if predicate(state):return state
                time.sleep(.05)
            self.fail('L2 worker did not reach expected state')
        try:
            level2_start(config); state=wait(lambda s:s.get('completed')==1)
            child=state['pid']; self.assertEqual(level2_start(config)['pid'],child)
            self.assertEqual(state['parallel'],8)
            self.assertTrue(runtime.level1_status(config)['paused_by_user'])
            level2_control(config,True)
            self.catalog.upsert({'title':'New metadata-only paper','doi':'10.1000/new-missing'})
            time.sleep(.15)
            self.assertTrue(level2_status(config)['paused_by_user'])
            level2_start(config); wait(lambda s:s.get('awaiting_original')==1)
        finally:
            if child:
                os.kill(child,signal.SIGTERM); wait(lambda s:s.get('state')=='stopped')

    def test_start_pins_validated_parser_runtime_even_from_web_environment(self):
        config={'catalog_path':str(self.catalog.path)}
        release=level2_release(config)
        try:
            with patch('literature.background.sys.executable','/unvalidated/web/python'), patch('literature.background.subprocess.Popen') as launch:
                launch.return_value.poll.return_value=None
                level2_start(config)
                self.assertEqual(launch.call_args.args[0][0],release['python_executable'])
                self.assertIn('literature.background_level2',launch.call_args.args[0])
        finally:
            nonce=runtime.read(runtime.paths(config,'level2')['service']).get('nonce')
            runtime._CHILDREN.pop(nonce,None)
