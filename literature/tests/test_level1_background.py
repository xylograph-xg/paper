"""Metadata-only production loop, isolated sidecar heads and pause ownership."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.api import catalog__Catalog as Catalog, literature_catalog__metadata_rows as metadata_rows
from literature.api import Library
from literature.background import (Worker, document, predict, generation_fingerprint,
    level1_status, level1_control, level1_start, level1_release, paths, atomic, locked)
from literature.classifier import classify, metadata_fingerprint


class Level1BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.catalog=Catalog(self.root/'catalog.sqlite3')
        self.pid=self.catalog.upsert({'title':'Blue thermally activated delayed fluorescence emitters',
            'doi':'10.1000/l1','abstract':'Here we report blue TADF emitters for organic light-emitting diodes.'})
        self.config={'catalog_path':str(self.catalog.path)}
        self.worker=Worker(self.config,'test'); self.library=Library(self.catalog.path)

    def test_only_title_abstract_no_fulltext_and_catalog_read_only(self):
        before=self.catalog.path.read_bytes()
        with patch('literature.inputs.load_documents',side_effect=AssertionError('PDF forbidden')):
            self.assertTrue(self.worker.cycle())
        self.assertEqual(before,self.catalog.path.read_bytes())
        run=self.library.store.automatic_results(scope='level1')[0]
        self.assertEqual(run['level2'],[]); self.assertEqual(run['level2_state'],'not_requested')
        self.assertFalse(run['scientific_verified']); self.assertTrue(run['level1'])
        with self.library.store.connect() as db:
            doc=json.loads(db.execute('SELECT document FROM automatic_inputs').fetchone()[0])
        self.assertEqual(doc['chunks'],[]); self.assertIsNone(doc['source_fingerprint'])
        self.assertNotIn('keywords',doc)
        for label in run['level1']:
            self.assertTrue(all(e['scope'] in ('title','abstract') for e in label['evidence']))

    def test_incremental_empty_results_and_source_changes_do_not_retag(self):
        self.catalog.upsert({'title':'Unspecified study','doi':'10.1000/empty'})
        self.worker.cycle(); self.assertFalse(self.worker.cycle())
        self.assertEqual(self.worker.state['undetermined'],1)
        self.catalog.update(self.pid,asset_hash='updated-pdf',asset_path='missing.pdf',acquisition='available')
        self.assertFalse(self.worker.cycle())
        with self.catalog.connect() as db:
            db.execute("UPDATE papers SET metadata=json_set(metadata,'$.abstract',?) WHERE id=?",('Here we report phosphorescent emitters.',self.pid))
        self.assertTrue(self.worker.cycle())
        self.assertFalse(self.worker.cycle())
        with self.library.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM automatic_runs').fetchone()[0],3)

    def test_new_metadata_and_rechecked_metadata_race(self):
        original=metadata_rows
        calls=0
        def changing(path):
            nonlocal calls
            calls+=1
            if calls==2:
                with self.catalog.connect() as db:
                    db.execute("UPDATE papers SET metadata=json_set(metadata,'$.abstract',?) WHERE id=?",('Metadata changed while classifying.',self.pid))
            return original(path)
        with patch('literature.background.metadata_rows',side_effect=changing): self.worker.cycle()
        self.assertEqual(self.library.store.automatic_results(scope='level1'),[])
        self.assertTrue(self.worker.cycle())
        self.catalog.upsert({'title':'Phosphorescent organic emitters','doi':'10.1000/new'})
        self.assertTrue(self.worker.cycle()); self.assertFalse(self.worker.cycle())
        self.assertEqual(self.worker.state['completed'],2)

    def test_level2_head_and_old_inputs_preserved_and_visible(self):
        row=metadata_rows(self.catalog.path)[0]
        doc={'paper_id':self.pid,'title':row['title'],'abstract':row['metadata']['abstract'],
             'metadata_fingerprint':metadata_fingerprint(row),'source_fingerprint':row['source_fingerprint'],
             'chunks':[{'id':'body','text':'We investigate reverse intersystem crossing. We performed cyclic voltammetry measurements.',
                        'scope':'fulltext','section':'results','page':2}]}
        old=self.library.store.save_automatic_run(doc,classify(doc)); before=self.library.store.automatic_input(self.pid)
        self.assertTrue(old['level2'])
        self.worker.cycle()
        self.assertEqual(self.library.store.automatic_results()[0]['run_id'],old['run_id'])
        self.assertEqual(self.library.store.automatic_input(self.pid),before)
        detail=self.library.detail(self.pid)
        self.assertTrue(any(a.get('level')==2 for a in detail['annotations']))
        first_id=detail['automatic_labeling']['level1_run_id']
        self.assertNotEqual(first_id,old['run_id'])
        for annotation in detail['annotations']:
            if annotation.get('level')==2:
                self.assertEqual(annotation['run_id'],old['run_id'])
                self.assertTrue(all(e['input_fingerprint']==old['input_fingerprint'] and e['generator_version']==old['rule_version'] for e in annotation['evidence']))
        self.catalog.update(self.pid,asset_hash='new-pdf')
        detail=self.library.detail(self.pid)
        self.assertTrue(any(a.get('level')==1 for a in detail['annotations']))
        self.assertFalse(any(a.get('level')==2 for a in detail['annotations']))

    def test_historical_manual_rejection_not_overwritten(self):
        self.worker.cycle(); label=self.library.store.automatic_results(scope='level1')[0]['level1'][0]
        with self.library.store.connect(True) as db:
            db.execute('INSERT INTO decisions VALUES(?,?,?,?,?)',(self.pid,label['tag_id'],'rejected','manual',1))
        self.assertFalse(any(a['tag_id']==label['tag_id'] and a['actor']=='automatic' for a in self.library.detail(self.pid)['annotations']))
        self.assertFalse(self.worker.cycle())

    def test_pause_and_read_only_status_and_singleton_start(self):
        missing={'catalog_path':str(self.root/'missing'/'catalog.sqlite3')}
        self.assertFalse(level1_status(missing)['registered']); self.assertFalse((self.root/'missing').exists())
        level1_control(self.config,True); self.assertFalse(self.worker.cycle())
        self.assertEqual(self.library.store.automatic_results(scope='level1'),[])
        with self.assertRaises(ValueError): level1_start(self.config)
        level1_release(self.config)
        atomic(paths(self.config)['service'],{'pid':os.getpid(),'state':'waiting','updated':0})
        with patch('literature.background.subprocess.Popen',side_effect=AssertionError('duplicate spawn')):
            level1_start(self.config)
        self.assertFalse(level1_status(self.config)['paused_by_user'])
        level1_control(self.config,True)
        self.assertTrue(level1_status(self.config)['paused_by_user'])
        with locked(paths(self.config)['owner']):
            with self.assertRaises(BlockingIOError):
                with locked(paths(self.config)['owner'],blocking=False): pass

    def test_failure_backoff_and_rule_revision(self):
        with patch('literature.background.predict',side_effect=ValueError('bad input')):
            self.worker.cycle()
        self.assertIn(self.pid,self.worker.failures)
        with patch('literature.background.predict',side_effect=AssertionError('backoff')):
            self.assertFalse(self.worker.cycle())
        self.worker.failures[self.pid]['retry_at']=0; self.worker.cycle()
        self.assertFalse(self.worker.cycle())
        self.worker.generation='new-validated-rules'; self.assertTrue(self.worker.cycle())
        self.assertFalse(self.worker.cycle())

    def test_real_isolated_worker_start_once_and_pause_resume(self):
        import signal
        import time
        level1_release(self.config)
        child_pid=None
        def wait_for(predicate):
            until=time.time()+8
            while time.time()<until:
                value=level1_status(self.config)
                if predicate(value): return value
                time.sleep(.05)
            self.fail('isolated worker did not reach expected state')
        try:
            level1_start(self.config)
            first=wait_for(lambda s:s.get('completed')==1)
            child_pid=first['pid']; self.assertNotEqual(child_pid,os.getpid())
            self.assertEqual(level1_start(self.config)['pid'],child_pid)
            level1_control(self.config,True)
            self.assertTrue(level1_status(self.config)['paused_by_user'])
            self.catalog.upsert({'title':'Organic phosphorescent emitters','doi':'10.1000/new'})
            time.sleep(.15)
            self.assertEqual(len(self.library.store.automatic_results(scope='level1')),1)
            level1_start(self.config)
            resumed=wait_for(lambda s:s.get('completed')==2)
            self.assertEqual(resumed['pid'],child_pid)
        finally:
            if child_pid:
                os.kill(child_pid,signal.SIGTERM)
                wait_for(lambda s:s.get('state')=='stopped')

    def test_level1_storage_rejects_fulltext_or_fine_results(self):
        doc=document(metadata_rows(self.catalog.path)[0],generation_fingerprint()); result=predict(doc)
        doc['chunks']=[{'text':'private fulltext'}]
        with self.assertRaises(ValueError): self.library.store.save_automatic_run(doc,result,scope='level1')


if __name__=='__main__': unittest.main()
